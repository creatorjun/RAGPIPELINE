# src/pipeline.py
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import List, Optional, Set

from src.config import AppConfig
from src.domain_filter import DomainFilter
from src.llm_client import LLMClient
from src.loader import load_all_documents, load_document
from src.models import Document
from src.progress import ProgressReporter
from src.refiner import Refiner
from src.resume import load_processed_files
from src.search_augmenter import SearchAugmenter
from src.validator import Validator
from src.web_search import SearXNGClient


class PipelineOrchestrator:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._llm = LLMClient(
            base_url=config.model.base_url,
            api_key=config.model.api_key,
            model_name=config.model.model_name,
            max_tokens=config.model.max_tokens,
            temperature=config.model.temperature,
            top_p=config.model.top_p,
        )
        searxng = SearXNGClient(
            base_url=config.search.base_url,
            timeout=config.search.timeout,
            max_results=config.search.max_results,
        )
        augmenter = SearchAugmenter(
            llm=self._llm,
            searxng=searxng,
            enabled=config.search.enabled,
        )
        self._filter = DomainFilter(self._llm)
        self._refiner = Refiner(self._llm, augmenter=augmenter)
        self._validator = Validator(
            keyword_retention_threshold=config.pipeline.keyword_retention_threshold,
            min_doc_length=config.pipeline.min_doc_length,
            min_sections=config.pipeline.min_sections,
        )
        self._log_path: Optional[Path] = None
        self._log_lock = Lock()

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
        with self._log_lock:
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

    def _process_document(self, doc: Document) -> str:
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
                return "skip"

            if filter_result.confidence < 0.7:
                print(f"\n[WARN] {doc.source_file} — 분류 신뢰도 낮음: {filter_result.confidence:.2f}")

            working_doc = doc
            if filter_result.is_partial:
                log_entry["stage"] = "extract"
                extracted = self._refiner.extract_domain_sections(doc, filter_result.domains)
                if not extracted:
                    print(f"\n[WARN] {doc.source_file} — 섹션 추출 결과 없음, 원본으로 폴백")
                else:
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".md", delete=False, encoding="utf-8"
                    ) as tmp:
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
            validation = None
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

            log_entry["keyword_retention_rate"] = validation.keyword_retention_rate if validation else 0.0

            if not validation or not validation.is_valid:
                log_entry["status"] = "fail"
                log_entry["error"] = str(validation.errors if validation else "unknown")
                log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
                self._write_log(log_entry)
                return "fail"

            saved = self._save_output(refined_text, doc.source_file, filter_result.domains)
            log_entry["output_files"] = saved
            log_entry["status"] = "success"
            log_entry["stage"] = "done"
            log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
            self._write_log(log_entry)
            return "success"

        except Exception as exc:
            log_entry["status"] = "fail"
            log_entry["error"] = repr(exc)
            log_entry["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
            self._write_log(log_entry)
            print(f"\n[ERROR] {doc.source_file} — {exc}")
            return "fail"

    def run(self, resume: Optional[bool] = None, dry_run: bool = False) -> None:
        self._init_dirs()
        self._open_log()
        print(f"[INFO] 로그 파일: {self._log_path}")
        if self._cfg.search.enabled:
            print(f"[INFO] 웹 검색 보강 활성화 ({self._cfg.search.base_url})")

        all_docs = load_all_documents(
            self._cfg.pipeline.input_dir,
            self._cfg.pipeline.max_chunk_tokens,
            self._cfg.pipeline.overlap_tokens,
        )
        print(f"[INFO] 입력 문서 {len(all_docs)}건 발견")

        use_resume = resume if resume is not None else self._cfg.pipeline.resume
        docs_to_process = all_docs

        if use_resume:
            processed: Set[str] = load_processed_files(self._cfg.pipeline.log_dir)
            skipped_names = {d.source_file for d in all_docs} & processed
            docs_to_process = [d for d in all_docs if d.source_file not in processed]
            if skipped_names:
                print(f"[RESUME] 이미 완료된 문서 {len(skipped_names)}건 스킵")

        if dry_run:
            print(f"[DRY-RUN] 실제 실행 없이 종료 — 처리 대상 {len(docs_to_process)}건")
            for doc in docs_to_process:
                print(f"  • {doc.source_file}")
            return

        if not docs_to_process:
            print("[INFO] 처리할 문서가 없습니다.")
            return

        print(f"[INFO] 처리 대상: {len(docs_to_process)}건")
        concurrency = max(1, self._cfg.pipeline.concurrency)
        reporter = ProgressReporter(len(docs_to_process))

        if concurrency == 1:
            for doc in docs_to_process:
                status = self._process_document(doc)
                reporter.update(status)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(self._process_document, doc): doc for doc in docs_to_process}
                for future in as_completed(futures):
                    status = future.result()
                    reporter.update(status)

        reporter.print_summary()
        self._print_domain_summary()

    def _print_domain_summary(self) -> None:
        output_base = Path(self._cfg.pipeline.output_dir)
        print("\n  도메인별 출력 문서 수")
        print("  " + "-" * 30)
        for domain in self._cfg.domains:
            folder = output_base / domain.output_folder
            count = len(list(folder.glob("*.md"))) if folder.exists() else 0
            print(f"  {domain.name:<15}: {count}건")
        print()
