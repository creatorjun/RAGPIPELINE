# src/llm_logger.py
"""
LLM 요청/응답 전체를 기록하는 전용 로거.

파일 구조 (logs/ 디렉토리)
::

    logs/
    ├── pipeline_run_20260619_101500.jsonl   ← 파이프라인 요약 로깅
    └── llm_20260619_101500.log               ← LLM 전체 대화 로깅 (이 모듈)

llm_*.log 포맷 (1 호출 = 3 블록)::

    ===== [2026-06-19 10:15:32 UTC] CALL #1  stage=refine  file=doc.md =====
    --- SYSTEM ---
    <system prompt 전체>
    --- USER ---
    <user prompt 전체>
    --- ASSISTANT ---
    <LLM 응답 전체>
    (tokens: prompt=1234  completion=567  total=1801  finish=stop)
    ======================================================================
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_SEPARATOR_WIDTH = 72


class LLMLogger:
    """LLM 호출당 요청과 응답을 llm_*.log 에 전체 기록하는 로거.

    사용 방식::

        logger = LLMLogger(log_dir="./logs")
        logger.open(run_ts="20260619_101500")

        # LLMClient._call() 내부에서 호출
        logger.record(
            stage="refine",
            source_file="doc.md",
            system_prompt="...",
            user_prompt="...",
            response="...",
            prompt_tokens=1234,
            completion_tokens=567,
            finish_reason="stop",
        )
    """

    def __init__(self, log_dir: str | Path = "./logs", enabled: bool = True):
        self._log_dir = Path(log_dir)
        self._enabled = enabled
        self._logger: Optional[logging.Logger] = None
        self._lock = threading.Lock()
        self._call_counter = 0
        self._log_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self, run_ts: Optional[str] = None) -> Path:
        """log 파일을 열고 Path 를 반환한다.

        Args:
            run_ts: pipeline_run_{ts}.jsonl 과 동일한 타임스탬프 문자열.
                    None 이면 현재 시간으로 자동 생성.
        """
        if not self._enabled:
            return Path("/dev/null")

        self._log_dir.mkdir(parents=True, exist_ok=True)
        ts = run_ts or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._log_path = self._log_dir / f"llm_{ts}.log"

        logger_name = f"llm_trace.{ts}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False  # 자동으로 root logger 로 스핀되지 않게

        handler = logging.FileHandler(self._log_path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

        return self._log_path

    def close(self) -> None:
        """log 파일 핸들러를 닫는다."""
        if self._logger is None:
            return
        for h in list(self._logger.handlers):
            h.flush()
            h.close()
            self._logger.removeHandler(h)
        self._logger = None

    @property
    def log_path(self) -> Optional[Path]:
        return self._log_path

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        stage: str = "",
        source_file: str = "",
        system_prompt: str,
        user_prompt: str,
        response: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        finish_reason: str = "",
    ) -> None:
        """LLM 1회 호출 전체를 log 에 기록한다 (thread-safe)."""
        if not self._enabled or self._logger is None:
            return

        with self._lock:
            self._call_counter += 1
            n = self._call_counter

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        total = prompt_tokens + completion_tokens
        sep = "=" * _SEPARATOR_WIDTH
        dash = "-" * _SEPARATOR_WIDTH

        lines = [
            "",
            sep,
            f"[{ts}] CALL #{n}  stage={stage or '?'}  file={source_file or '?'}",
            sep,
            "--- SYSTEM ---",
            system_prompt,
            "--- USER ---",
            user_prompt,
            "--- ASSISTANT ---",
            response,
            f"(tokens: prompt={prompt_tokens}  completion={completion_tokens}  "
            f"total={total}  finish={finish_reason})",
            sep,
        ]
        with self._lock:
            self._logger.debug("\n".join(lines))

    # ------------------------------------------------------------------
    # Context manager (optional)
    # ------------------------------------------------------------------

    def __enter__(self) -> "LLMLogger":
        return self

    def __exit__(self, *_) -> None:
        self.close()
