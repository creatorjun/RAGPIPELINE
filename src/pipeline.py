# src/pipeline.py
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.config import AppConfig
from src.domain_filter import DomainFilter
from src.llm_client import LLMClient
from src.loader import load_all_documents
from src.models import Document
from src.refiner import Refiner
from src.validator import Validator


class PipelineOrchestrator:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._llm = LLMClient(
            model_path=config.model.path,
            max_tokens=config.model.max_tokens,
            temperature=config.model.temperature,
            top_p=config.model.top_p,
            repetition_penalty=config.model.repetition_penalty,
        )
        self._filter = DomainFilter(self._llm)
        self._refiner = Refiner(self._llm)
        self._validator = Validator(
            keyword_retention_threshold=config.pipeline.keyword_retention_threshold,
            min_doc_length=config.pipeline.min_doc_length,
            min_sections=config.pipeline.min_sections,
        )
        self._log_path: Optional[Path] = None

    def _init_dirs(self) -> None:
        for domain in self._cfg.domains:
            Path(self._cfg.pipeline.output_dir, domain.output_folder).mkdir(parents=True, exist_ok=True)
        Path(self._cfg.pipeline.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self._cfg.pipeline.input_dir).mkdir(parents=True, exist_ok=True)

    def _open_log(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = Path(self._cfg.pipeline.log_dir) / f"pipeline_run_{ts}.jsonl"

    def _write_log(self, entry: dict) -> None:
        if self._log_path is None:
            return
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _save_output(self, refined_text: str, source_file: str, domains: List[str]) -> List[str]:
        saved: List[str] = []
        for domain in domains:
            folder = self._cfg.get_output_folder(domain)
            if folder is None:
                continue
            out_dir = Path(self._cfg.pipeline.output_dir) / folder
            out_path = out_dir / source_file
            out_path.write_text(refined_text, encoding="utf-8")
            saved.append(str(out_path))
        return saved

    def _process_document(self, doc: Document) -> None:
        start = datetime.now(tz=timezone.utc)
        log_entry: dict = {
            "timestamp": start.isoformat(),
            "source_file": doc.source_file,
            "stage": "start",
            "status": "processing",
            "domain": [],
            "output_files": [],
            "retry_count": 0,
            "keyword_retention_rate": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "duration_sec": 0.0,
            "error": None,
        }
        self._write_log(log_entry)

        try:
            filter_result = self._filter.classify(doc)
            log_entry["stage"] = "domain_filter"
            log_entry["domain"] = filter_result.domains

            if not filter_result.domains:
                log_entry["status"] = "skip"
                log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
                self._write_log(log_entry)
                print(f"[SKIP] {doc.source_file} — 관련 도메인 없음")
                return

            if filter_result.confidence < 0.7:
                print(f"[WARN] {doc.source_file} — 분류 신뢰도 낮음: {filter_result.confidence:.2f}")

            working_doc = doc
            if filter_result.is_partial:
                log_entry["stage"] = "extract"
                extracted = self._refiner.extract_domain_sections(doc, filter_result.domains)
                if not extracted:
                    log_entry["status"] = "skip"
                    log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
                    self._write_log(log_entry)
                    print(f"[SKIP] {doc.source_file} — PARTIAL 추출 후 관련 내용 없음")
                    return
                from src.loader import load_document
                import tempfile, os
                with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
                    tmp.write(extracted)
                    tmp_path = tmp.name
                try:
                    working_doc = load_document(
                        Path(tmp_path),
                        self._cfg.pipeline.max_chunk_tokens,
                        self._cfg.pipeline.overlap_tokens,
                    )
                    working_doc.source_file = doc.source_file
                finally:
                    os.unlink(tmp_path)

            refined_text = ""
            retry = 0
            max_retries = self._cfg.pipeline.max_retries

            while retry <= max_retries:
                log_entry["stage"] = "refine"
                refined_text = self._refiner.refine_document(working_doc, filter_result.domains)

                log_entry["stage"] = "validate"
                validation = self._validator.validate_strict(doc.content, refined_text)

                if validation.is_valid:
                    break

                retry += 1
                log_entry["retry_count"] = retry
                print(f"[RETRY {retry}/{max_retries}] {doc.source_file} — {validation.errors}")

            log_entry["keyword_retention_rate"] = validation.keyword_retention_rate

            if not validation.is_valid:
                log_entry["status"] = "fail"
                log_entry["error"] = str(validation.errors)
                log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
                self._write_log(log_entry)
                print(f"[FAIL] {doc.source_file} — {validation.errors}")
                return

            saved = self._save_output(refined_text, doc.source_file, filter_result.domains)
            log_entry["output_files"] = saved
            log_entry["status"] = "success"
            log_entry["stage"] = "done"
            log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
            self._write_log(log_entry)
            print(f"[OK] {doc.source_file} → {saved}")

        except Exception as exc:
            log_entry["status"] = "fail"
            log_entry["error"] = repr(exc)
            log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
            self._write_log(log_entry)
            print(f"[ERROR] {doc.source_file} — {exc}")

    def run(self) -> None:
        self._init_dirs()
        self._open_log()
        print(f"[INFO] 로그 파일: {self._log_path}")

        docs = load_all_documents(
            self._cfg.pipeline.input_dir,
            self._cfg.pipeline.max_chunk_tokens,
            self._cfg.pipeline.overlap_tokens,
        )
        print(f"[INFO] 문서 {len(docs)}건 로드 완료")

        for doc in docs:
            self._process_document(doc)

        print("[INFO] 파이프라인 완료")
