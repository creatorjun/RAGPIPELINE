#!/usr/bin/env python3
# run.py
from __future__ import annotations

import argparse
import sys

import requests

from src.config import AppConfig
from src.pipeline import PipelineOrchestrator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG Pipeline 정제 실행",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("--no-resume", action="store_true", help="Resume 무시 후 전체 재처리")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 대상 목록만 출력")
    return parser.parse_args()


def _check_server(base_url: str, api_key: str) -> None:
    health_url = base_url.rstrip("/").replace("/v1", "") + "/health"
    try:
        r = requests.get(health_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        if r.status_code == 200:
            print(f"[run] LLM 서버 연결 확인: {health_url}")
            return
        print(f"[run] WARNING: /health 응답 {r.status_code} — 계속 진행합니다.")
    except requests.exceptions.ConnectionError:
        print(
            f"\n[FATAL] LLM 서버에 연결할 수 없습니다: {health_url}\n"
            "  서버가 실행 중인지 확인하세요.\n"
            "  예) vllm serve <model> --host 0.0.0.0 --port 8000 --api-key sk-no-key-required",
            file=sys.stderr,
        )
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"[run] WARNING: /health 응답 타임아웃 — 계속 진행합니다.")


def main() -> int:
    args = _parse_args()
    cfg = AppConfig.from_yaml(args.config)

    base_url = cfg.model.base_url
    api_key = cfg.model.api_key

    print(f"[run] LLM 엔드포인트: {base_url}")
    print(f"[run] 모델: {cfg.model.model_name}")

    _check_server(base_url, api_key)

    try:
        orchestrator = PipelineOrchestrator(cfg)
        orchestrator.run(
            resume=not args.no_resume,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("\n[INFO] 사용자 중단 (Ctrl+C)", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
