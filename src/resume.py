# src/resume.py
import json
from pathlib import Path
from typing import Set


def load_processed_files(log_dir: str) -> Set[str]:
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
