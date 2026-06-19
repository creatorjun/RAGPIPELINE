# src/pipeline.py
"""
오토케스튤레이션 (일괄 실행 럨너).

SRP 역할: 처리 대상 문서 목록을 결정하고, concurrency 맨니저로
         DocumentRunner 에 위임한다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Set

from src.config import AppConfig
from src.domain_filter import DomainFilter
from src.judge import JudgeLLM
from src.llm_client import LLMClient
from src.loader import load_all_documents
from src.pipeline_io import PipelineIO
from src.pipeline_runner import DocumentRunner
from src.progress import ProgressReporter
from src.refiner import Refiner
from src.resume import load_processed_files
from src.search_augmenter import SearchAugmenter
from src.validator import StructureValidator
from src.web_search import SearXNGClient


class PipelineOrchestrator:
    """오토케스트레이션.

    의존성 연결 + 실행 제어만 담당하고
    세부 로직은 DocumentRunner / PipelineIO 에 위임한다.
    """

    def __init__(self, config: AppConfig):
        self._cfg = config

        # --- infrastructure ----------------------------------------
        llm = LLMClient(
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
            llm=llm,
            searxng=searxng,
            enabled=config.search.enabled,
        )

        # --- domain services ---------------------------------------
        domain_filter = DomainFilter(
            llm=llm,
            valid_domains=config.get_domain_names(),
        )
        refiner = Refiner(llm, augmenter=augmenter)
        structure_validator = StructureValidator(
            min_doc_length=config.pipeline.min_doc_length,
            min_sections=config.pipeline.min_sections,
        )
        judge: Optional[JudgeLLM] = (
            JudgeLLM(llm, max_tokens=config.judge.max_tokens)
            if config.judge.enabled
            else None
        )

        # --- I/O + runner ------------------------------------------
        self._io = PipelineIO(config)
        self._runner = DocumentRunner(
            cfg=config,
            io=self._io,
            domain_filter=domain_filter,
            refiner=refiner,
            structure_validator=structure_validator,
            judge=judge,
            on_judge_error=config.judge.on_error,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, resume: Optional[bool] = None, dry_run: bool = False) -> None:
        self._io.init_dirs()
        log_path = self._io.open_log()
        print(f"[INFO] 로그 파일: {log_path}")
        if self._cfg.search.enabled:
            print(f"[INFO] 웹 검색 보강 활성화 ({self._cfg.search.base_url})")
        if self._cfg.judge.enabled:
            print(
                f"[INFO] Judge LLM 활성화 "
                f"(model={self._cfg.model.model_name}, "
                f"on_error={self._cfg.judge.on_error})"
            )

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
            print(f"[DRY-RUN] 실제 실행 없이 종료 \u2014 처리 대상 {len(docs_to_process)}건")
            for doc in docs_to_process:
                print(f"  - {doc.source_file}")
            return

        concurrency = max(1, self._cfg.pipeline.concurrency)
        reporter = ProgressReporter(total=len(docs_to_process))
        counts: dict[str, int] = {"success": 0, "fail": 0, "skip": 0}

        if concurrency == 1:
            for doc in docs_to_process:
                result = self._runner.run(doc)
                counts[result] = counts.get(result, 0) + 1
                reporter.update(result)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(self._runner.run, doc): doc for doc in docs_to_process}
                for future in as_completed(futures):
                    result = future.result()
                    counts[result] = counts.get(result, 0) + 1
                    reporter.update(result)

        reporter.close()
        print(f"\n[DONE] 성공={counts['success']} / 실패={counts['fail']} / 스킵={counts['skip']}")
        print(f"[INFO] 로그: {log_path}")
