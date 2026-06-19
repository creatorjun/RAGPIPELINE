# src/pipeline_io.py
"""
I/O 책임만 담당하는 독립 모듈.

PipelineOrchestrator God-class 를 분석하여 다음의 SRP 단위로 정리한다.
  - pipeline_io.py   ← 파일시스템 I/O (init_dirs, save_output, log)
  - pipeline_runner.py ← 단일 문서 실행 로직
  - pipeline.py      ← 오토케스트레이션 (일괄 실행 럨너)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from src.config import AppConfig


class PipelineIO:
    """디렉토리 초기화, 로그 쓰기, 출력 파일 저장을 채임진다."""

    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._log_path: Optional[Path] = None
        self._log_lock = Lock()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_dirs(self) -> None:
        """config 에 정의된 입력/출력/로그 디렉토리를 생성한다."""
        for domain in self._cfg.domains:
            Path(self._cfg.pipeline.output_dir, domain.output_folder).mkdir(
                parents=True, exist_ok=True
            )
        Path(self._cfg.pipeline.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self._cfg.pipeline.input_dir).mkdir(parents=True, exist_ok=True)

    def open_log(self) -> Path:
        """JSONL 로그 파일을 열고 경로를 반환한다."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = Path(self._cfg.pipeline.log_dir) / f"pipeline_run_{ts}.jsonl"
        return self._log_path

    @property
    def log_path(self) -> Optional[Path]:
        return self._log_path

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def write_log(self, entry: dict) -> None:
        """JSONL 로그에 한 줄을 thread-safe 하게 기록한다."""
        if self._log_path is None:
            return
        with self._log_lock:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def save_output(self, refined_text: str, source_file: str, domains: list[str]) -> list[str]:
        """지정된 도메인별 출력 폴더에 정제 문서를 저장하고 저장 경로 목록을 반환한다."""
        saved: list[str] = []
        for domain in domains:
            folder = self._cfg.get_output_folder(domain)
            if folder is None:
                continue
            out_dir = Path(self._cfg.pipeline.output_dir) / folder
            stem = Path(source_file).stem + ".md"
            out_path = out_dir / stem
            out_path.write_text(refined_text, encoding="utf-8")
            saved.append(str(out_path))
        return saved
