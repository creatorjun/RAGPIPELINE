# src/resume.py
import json
from pathlib import Path
from typing import List, Set


def load_processed_files(log_dir: str) -> Set[str]:
    """JSONL 로그에서 success/skip 완료된 파일명 세트를 반환한다."""
    processed: Set[str] = set()
    log_base = Path(log_dir)
    if not log_base.exists():
        return processed

    for log_file in sorted(log_base.glob("pipeline_run_*.jsonl")):
        with open(log_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if entry.get("status") in ("success", "skip"):
                    processed.add(entry["source_file"])
    return processed


class ResumeTracker:
    """Resume 지원 클래스.

    이전 실행에서 success/skip 로 기록된 파일은
    filter_pending() 에서 사듕되어 중복 처리를 방지한다.

    Args:
        log_dir: JSONL 로그 디렉토리
        enabled: False 이면 filter_pending 이 입력을 그대로 반환 (전체 재처리)
    """

    def __init__(self, log_dir: str, enabled: bool = True) -> None:
        self._log_dir = log_dir
        self._enabled = enabled
        self._done: Set[str] = set()
        if enabled:
            self._done = load_processed_files(log_dir)
            if self._done:
                print(f"[Resume] 이전 완료 파일 {len(self._done)}개 제외")

    def filter_pending(self, files: List[Path]) -> List[Path]:
        """어음이 완료되지 않은 파일만 반환한다."""
        if not self._enabled:
            return files
        return [f for f in files if f.name not in self._done]

    def mark_done(self, path: Path) -> None:
        """처리 완료된 파일을 내부 집합에 추가한다 (메모리 전용)."""
        self._done.add(path.name)
