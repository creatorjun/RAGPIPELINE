# src/progress.py
import sys
from datetime import datetime, timezone
from typing import Optional


class ProgressReporter:
    def __init__(self, total: int):
        self._total = total
        self._done = 0
        self._success = 0
        self._skip = 0
        self._fail = 0
        self._start = datetime.now(tz=timezone.utc)

    def _elapsed(self) -> float:
        return (datetime.now(tz=timezone.utc) - self._start).total_seconds()

    def _eta(self) -> Optional[str]:
        if self._done == 0:
            return None
        avg = self._elapsed() / self._done
        remaining = avg * (self._total - self._done)
        m, s = divmod(int(remaining), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def update(self, status: str) -> None:
        self._done += 1
        if status == "success":
            self._success += 1
        elif status == "skip":
            self._skip += 1
        else:
            self._fail += 1

        pct = self._done / self._total * 100
        eta = self._eta()
        eta_str = f" ETA {eta}" if eta else ""
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        line = (
            f"\r[{bar}] {pct:5.1f}%  "
            f"{self._done}/{self._total}  "
            f✔️{self._success} ⏭️{self._skip} ❌{self._fail}"
            f"{eta_str}   "
        )
        sys.stdout.write(line)
        sys.stdout.flush()
        if self._done == self._total:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def print_summary(self) -> None:
        elapsed = self._elapsed()
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        elapsed_str = f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")
        avg = elapsed / self._done if self._done else 0.0

        print("\n" + "=" * 52)
        print("  실행 완료 요약")
        print("=" * 52)
        print(f"  전체 문서  : {self._total}건")
        print(f"  성공        : {self._success}건")
        print(f"  스킵        : {self._skip}건")
        print(f"  실패        : {self._fail}건")
        print(f"  소요 시간  : {elapsed_str}")
        print(f"  평균 처리  : {avg:.1f}초/건")
        print("=" * 52)
