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
        bar = "\u2588" * bar_filled + "\u2591" * (20 - bar_filled)
        line = (
            f"\r[{bar}] {pct:5.1f}%  "
            f"{self._done}/{self._total}  "
            f"\u2714\ufe0f{self._success} "
            f"\u23ed\ufe0f{self._skip} "
            f"\u274c{self._fail}"
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
        print("  \uc2e4\ud589 \uc644\ub8cc \uc694\uc57d")
        print("=" * 52)
        print(f"  \uc804\uccb4 \ubb38\uc11c  : {self._total}\uac74")
        print(f"  \uc131\uacf5        : {self._success}\uac74")
        print(f"  \uc2a4\ud0b5        : {self._skip}\uac74")
        print(f"  \uc2e4\ud328        : {self._fail}\uac74")
        print(f"  \uc18c\uc694 \uc2dc\uac04  : {elapsed_str}")
        print(f"  \ud3c9\uade0 \ucc98\ub9ac  : {avg:.1f}\ucd08/\uac74")
        print("=" * 52)
