#!/usr/bin/env python3
# run.py
"""
Phase 1·2 정제 파이프라인 진입점.

실행 흐름:
    1. config.yaml 로드
    2. server.managed=True 이면 ModelServer 자동 기동
    3. PipelineOrchestrator.run()
    4. 정상/예외 종료 시 ModelServer.stop()

CLI 예시::

    # 프로덤션 실행 (config.yaml 설정 권한)
    python run.py

    # 테스트 실행 — gemma-4-E2B mlx_vllm, 포트 8001 자동 적용
    python run.py --test

    # dry-run: LLM 호출 없이 대상 목록만 확인
    python run.py --test --dry-run
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional

from src.config import AppConfig
from src.model_server import ModelServer, ModelServerError
from src.pipeline import PipelineOrchestrator


# ---------------------------------------------------------------------------
# 테스트 모드 프리셋
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestPreset:
    """--test 플래그 적용 시 사용할 고정 값."""
    model_path: str = "google/gemma-4-E2B-it"
    backend: str = "mlx_vllm"
    port: int = 8001
    max_tokens: int = 2048
    startup_timeout: int = 120
    # 테스트에서는 LLM 응답 로깅을 항상 활성화
    llm_log_enabled: bool = True


TEST_PRESET = TestPreset()


# ---------------------------------------------------------------------------
# CLI 파서
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG Pipeline 정제 실행",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="설정 파일 경로",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            f"테스트 모드: {TEST_PRESET.model_path} 모델을 "
            f"{TEST_PRESET.backend} 백엔드, 포트 {TEST_PRESET.port} 으로 기동"
        ),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Resume 무시 후 전체 재처리",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LLM 호출 없이 대상 목록만 출력",
    )
    parser.add_argument(
        "--backend",
        choices=["mlx_lm", "mlx_vllm"],
        default=None,
        help="서버 백엔드 우선 (config.yaml server.backend 대비 CLI 우선)",
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="서버 자동 기동 스킵 (외부에서 이미 실행 중인 서버 사용)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 테스트 모드 override 헬퍼
# ---------------------------------------------------------------------------

def _apply_test_preset(cfg: AppConfig, preset: TestPreset) -> None:
    """테스트 프리셋 값을 cfg 에 사이드이폭트로 적용한다.

    config.yaml 은 건드리지 않으므로, 테스트를
    실행한 다음 원래 구성으로 돌아오고 싶으면
    그냥 python run.py (기본모드)를 실행하면 된다.
    """
    cfg.server.model_path = preset.model_path
    cfg.server.backend = preset.backend
    cfg.server.port = preset.port
    cfg.server.managed = True          # 테스트는 항상 자동 기동
    cfg.server.startup_timeout = preset.startup_timeout
    cfg.model.model_name = preset.model_path
    cfg.model.max_tokens = preset.max_tokens
    cfg.logging.llm_log_enabled = preset.llm_log_enabled


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()
    cfg = AppConfig.from_yaml(args.config)

    # 1) 테스트 모드 우선 적용
    if args.test:
        _apply_test_preset(cfg, TEST_PRESET)
        print(
            f"[run] 테스트 모드: 모델={TEST_PRESET.model_path}  "
            f"backend={TEST_PRESET.backend}  port={TEST_PRESET.port}"
        )

    # 2) 추가 CLI override (테스트 모드보다 나중에 적용되므로 우선순위 높음)
    if args.no_server:
        cfg.server.managed = False
    if args.backend:
        cfg.server.backend = args.backend

    server = ModelServer(
        model_path=cfg.resolved_model_path(),
        host=cfg.server.host,
        port=cfg.server.port,
        backend=cfg.server.backend,
        max_tokens=cfg.model.max_tokens,
        trust_remote_code=cfg.server.trust_remote_code,
        extra_args=cfg.server.extra_args,
        startup_timeout=cfg.server.startup_timeout,
        managed=cfg.server.managed,
    )

    try:
        with server:
            cfg.model.base_url = server.base_url
            orchestrator = PipelineOrchestrator(cfg)
            orchestrator.run(
                resume=not args.no_resume,
                dry_run=args.dry_run,
            )
    except ModelServerError as e:
        print(f"\n[FATAL] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[INFO] 사용자 중단 (Ctrl+C)", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
