# tools/log_analyzer.py
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import List


def _load_entries(log_dir: str) -> List[dict]:
    entries: List[dict] = []
    base = Path(log_dir)
    if not base.exists():
        return entries
    for log_file in sorted(base.glob("pipeline_run_*.jsonl")):
        with open(log_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entries.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    continue
    return entries


def _latest_per_file(entries: List[dict]) -> List[dict]:
    latest: dict = {}
    for e in entries:
        src = e.get("source_file", "")
        if src not in latest or e.get("timestamp", "") > latest[src].get("timestamp", ""):
            latest[src] = e
    return list(latest.values())


def cmd_status(log_dir: str) -> None:
    entries = _latest_per_file(_load_entries(log_dir))
    if not entries:
        print("[INFO] 로그 없음")
        return
    status_cnt = Counter(e.get("status") for e in entries)
    print("\n  상태별 문서 수")
    print("  " + "-" * 30)
    for status, cnt in status_cnt.most_common():
        print(f"  {status:<15}: {cnt}건")
    print(f"  {'TOTAL':<15}: {len(entries)}건")
    print()


def cmd_domains(log_dir: str) -> None:
    entries = _latest_per_file(_load_entries(log_dir))
    domain_cnt: Counter = Counter()
    for e in entries:
        for d in e.get("domain", []):
            domain_cnt[d] += 1
    print("\n  도메인별 처리 건수")
    print("  " + "-" * 30)
    for d, c in domain_cnt.most_common():
        print(f"  {d:<15}: {c}건")
    print()


def cmd_failures(log_dir: str) -> None:
    entries = _latest_per_file(_load_entries(log_dir))
    failed = [e for e in entries if e.get("status") == "fail"]
    if not failed:
        print("[INFO] 실패 문서 없음")
        return
    print(f"\n  실패 문서 {len(failed)}건")
    print("  " + "-" * 50)
    for e in failed:
        print(f"  ❌ {e['source_file']}")
        print(f"     원인: {e.get('error', 'N/A')}")
    print()


def cmd_tokens(log_dir: str) -> None:
    entries = _latest_per_file(_load_entries(log_dir))
    t_in = sum(e.get("tokens_in", 0) for e in entries)
    t_out = sum(e.get("tokens_out", 0) for e in entries)
    durations = [e.get("duration_sec", 0.0) for e in entries if e.get("status") == "success"]
    avg_dur = sum(durations) / len(durations) if durations else 0.0
    total_dur = sum(e.get("duration_sec", 0.0) for e in entries)
    m, s = divmod(int(total_dur), 60)
    h, m = divmod(m, 60)
    total_dur_str = f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")
    print("\n  토큰 사용량 및 소요 시간")
    print("  " + "-" * 30)
    print(f"  입력 토큰 합계  : {t_in:,}")
    print(f"  출력 토큰 합계  : {t_out:,}")
    print(f"  성공 평균 시간 : {avg_dur:.1f}초/건")
    print(f"  전체 소요 시간 : {total_dur_str}")
    print()


def cmd_retention(log_dir: str) -> None:
    entries = _latest_per_file(_load_entries(log_dir))
    success = [e for e in entries if e.get("status") == "success"]
    if not success:
        print("[INFO] 성공 레코드 없음")
        return
    rates = [e.get("keyword_retention_rate", 0.0) for e in success]
    avg = sum(rates) / len(rates)
    below = [e for e in success if e.get("keyword_retention_rate", 1.0) < 0.7]
    print("\n  키워드 보존율 통계")
    print("  " + "-" * 30)
    print(f"  평균 보존율   : {avg:.2%}")
    print(f"  70% 미달 문서 : {len(below)}건")
    if below:
        print("  [\uc800품질 목록]")
        for e in sorted(below, key=lambda x: x.get("keyword_retention_rate", 0)):
            print(f"    • {e['source_file']}  {e.get('keyword_retention_rate', 0):.2%}")
    print()


def cmd_report(log_dir: str) -> None:
    cmd_status(log_dir)
    cmd_domains(log_dir)
    cmd_tokens(log_dir)
    cmd_retention(log_dir)
    cmd_failures(log_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 파이프라인 로그 분석 도구")
    parser.add_argument("--log-dir", default="./logs", help="로그 폴더 경로")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status",    help="상태별 문서 수 출력")
    sub.add_parser("domains",   help="도메인별 처리 건수")
    sub.add_parser("failures",  help="실패 문서 목록 및 원인")
    sub.add_parser("tokens",    help="토큰 사용량 및 시간 통계")
    sub.add_parser("retention", help="키워드 보존율 통계")
    sub.add_parser("report",    help="전체 요약 리포트")

    args = parser.parse_args()
    dispatch = {
        "status":    cmd_status,
        "domains":   cmd_domains,
        "failures":  cmd_failures,
        "tokens":    cmd_tokens,
        "retention": cmd_retention,
        "report":    cmd_report,
    }
    dispatch[args.cmd](args.log_dir)


if __name__ == "__main__":
    main()
