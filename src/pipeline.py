# src/pipeline.py
"""
Phase 1·2 오케스트레이터.

PipelineOrchestrator 는 다음을 조합한다:
  - PipelineIO      (디렉토리 파일 출력 / JSONL 로깅)
  - LLMLogger       (LLM 요청·응답 전체 로깅)
  - LLMClient       (OpenAI-compatible 서버 접속)
  - DocumentRunner  (단일 문서 처리)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

from src.config import AppConfig
from src.domain_filter import DomainFilter
from src.judge import JudgeLLM
from src.llm_client import LLMClient
from src.llm_logger import LLMLogger
from src.loader import DocumentLoader
from src.pipeline_io import PipelineIO
from src.pipeline_runner import DocumentRunner
from src.progress import ProgressTracker
from src.refiner import Refiner
from src.resume import ResumeTracker
from src.search_augmenter import SearchAugmenter
from src.validator import StructureValidator
from src.web_search import SearXNGClient


class PipelineOrchestrator:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._io = PipelineIO(cfg)

    def run(self, resume: bool = True, dry_run: bool = False) -> None:
        cfg = self._cfg
        io = self._io

        io.init_dirs()

        run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        log_path = io.open_log(run_ts=run_ts)
        print(f"[Pipeline] 로그: {log_path}")

        llm_logger = LLMLogger(
            log_dir=cfg.pipeline.log_dir,
            enabled=cfg.logging.llm_log_enabled,
        )
        llm_log_path = llm_logger.open(run_ts=run_ts)
        print(f"[Pipeline] LLM 로그: {llm_log_path}")

        llm = LLMClient(
            base_url=cfg.model.base_url,
            api_key=cfg.model.api_key,
            model_name=cfg.model.model_name,
            max_tokens=cfg.model.max_tokens,
            temperature=cfg.model.temperature,
            top_p=cfg.model.top_p,
            llm_logger=llm_logger,
        )

        domain_filter = DomainFilter(
            llm=llm,
            valid_domains=cfg.get_domain_names(),
        )
        refiner = Refiner(llm=llm)
        structure_validator = StructureValidator()

        # JudgeLLM 시그니처: (llm, max_tokens, judge_input_chars)
        # enabled / on_error 는 JudgeLLM 에 없음 — enabled 여부는 pipeline 에서 관리
        judge: JudgeLLM | None = None
        if cfg.judge.enabled:
            judge = JudgeLLM(
                llm=llm,
                max_tokens=cfg.judge.max_tokens,
                judge_input_chars=cfg.judge.judge_input_chars,
            )

        searxng: SearXNGClient | None = None
        if cfg.search.enabled:
            searxng = SearXNGClient(
                base_url=cfg.search.base_url,
                timeout=cfg.search.timeout,
                max_results=cfg.search.max_results,
            )
        search_augmenter = SearchAugmenter(llm=llm, searxng=searxng)
        _ = search_augmenter  # DocumentRunner 에 직접 전달하지 않음 (현재 미구현)

        loader = DocumentLoader(
            input_dir=cfg.pipeline.input_dir,
            max_chunk_tokens=cfg.pipeline.max_chunk_tokens,
            overlap_tokens=cfg.pipeline.overlap_tokens,
        )
        resume_tracker = ResumeTracker(
            log_dir=cfg.pipeline.log_dir,
            enabled=resume,
        )

        runner = DocumentRunner(
            cfg=cfg,
            io=io,
            domain_filter=domain_filter,
            refiner=refiner,
            structure_validator=structure_validator,
            judge=judge,
            on_judge_error=cfg.judge.on_error,
        )

        files: List[Path] = loader.load_all()
        if resume:
            files = resume_tracker.filter_pending(files)

        total = len(files)
        print(f"[Pipeline] 대상 {total}개" + (" [dry-run]" if dry_run else ""))

        progress = ProgressTracker(total) if total > 0 else None

        try:
            for fp in files:
                if dry_run:
                    print(f"  [dry-run] {fp.name}")
                    continue
                doc = loader.load(fp)
                status = runner.run(doc)
                resume_tracker.mark_done(fp)
                if progress:
                    progress.update(status)
        finally:
            llm_logger.close()

        if progress:
            progress.print_summary()
        elif dry_run:
            print("[Pipeline] dry-run 완료")
