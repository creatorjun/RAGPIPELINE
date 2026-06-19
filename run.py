#!/usr/bin/env python3
# run.py
"""
Phase 1·2 정제 파이프라인 진입점.

플랫폼 자동 감지::

    macOS (Apple Silicon) → mlx-community/gemma-4-26b-a4b-it-4bit + mlx_lm
    x64  (Linux / Windows) → google/gemma-4-E2B-it-assistant       + vllm

실행 흐름:
    1. config.yaml 로드
    2. 플랫폼 감지 → 모델 / 백엔드 자동 설정
    3. server.managed=True 이면 ModelServer 자동 기동
    4. PipelineOrchestrator.run()
    5. 정상/예외 종료 시 ModelServer.stop()

CLI 예시::

    # 자동 감지 (플랫폼에 따라 모델·백엔드 선택)
    python run.py

    # 테스트 모드 — 경량 모델(E2B) + 플랫폼 적합 백엔드, 포트 8001
    python run.py --test

    # 백엔드 치환 (CLI 우선)
    python run.py --backend vllm

    # dry-run
    python run.py --dry-run
"""
from __future__ import annotations

import argparse
import platform
import sys
from dataclasses import dataclass
from typing import Optional

from src.config import AppConfig
from src.model_server import ModelServer, ModelServerError
from src.pipeline import PipelineOrchestrator


# ---------------------------------------------------------------------------
# 플랫폼 감지
# ---------------------------------------------------------------------------

def _is_macos() -> bool:
    """현재 프로세스가 macOS(애플 실리콘 포함) 위에서 돹작 중이면 True."""
    return platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# 모델 프리셋
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlatformPreset:
    """Apple Silicon / x64 관계없이 공유되는 모델 선택 프리셋."""
    model_path: str
    backend: str
    description: str


MACOS_PRESET = PlatformPreset(
    model_path="mlx-community/gemma-4-26b-a4b-it-4bit",
    backend="mlx_lm",
    description="macOS (Apple Silicon)",
)

X64_PRESET = PlatformPreset(
    model_path="google/gemma-4-E2B-it-assistant",
    backend="vllm",
    description="x64 (Linux/Windows CUDA)",
)


def _platform_preset() -> PlatformPreset:
    """현재 OS에 따라 적합한 프리셋을 반환한다."""
    return MACOS_PRESET if _is_macos() else X64_PRESET


# ---------------------------------------------------------------------------
# 테스트 모드 프리셋
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestPreset:
    """--test 플래그 적용 시 사용할 고정 값.

    모델 / 백엔드는 플랫폼 감지에서 자동 선택되므로
    이 클래스에는 사이즈 / 포트 관련 고정값만 담는다.
    """
    port: int = 8001
    max_tokens: int = 2048
    startup_timeout: int = 120
    llm_log_enabled: bool = True  # 테스트는 LLM 로깅 항상 활성


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
            f"\ud14c\uc2a4\ud2b8 \ubaa8\ub4dc: E2B \ubaa8\ub378\uc744 \ud3ec\ud2b8 {TEST_PRESET.port} "
            "\uc73c\ub85c \uae30\ub3d9 (\ud50c\ub7ab\ud3fc\uc5d0 \ub530\ub77c \ubc31\uc5d4\ub4dc \uc790\ub3d9 \uc120\ud0dd)"
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
        choices=["mlx_lm", "mlx_vllm", "vllm"],
        default=None,
        help="서버 백엔드 치환 (자동 감지보다 우선)",
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="서버 자동 기동 스킵 (외부에서 이미 실행 중인 서버 사용)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Override 헬퍼
# ---------------------------------------------------------------------------

def _apply_platform_preset(cfg: AppConfig, preset: PlatformPreset) -> None:
    """플랫폼에 적합한 모델·백엔드를 cfg 에 적용한다.

    config.yaml 에 model_path / backend 설정이 없으면
    플랫폼 프리셋을 기본값으로 이용한다.
    config.yaml 에 명시된 경우는 config가 우선된다.
    """
    if not cfg.server.model_path:
        cfg.server.model_path = preset.model_path
        cfg.model.model_name = preset.model_path
    if cfg.server.backend == "mlx_lm" and preset.backend != "mlx_lm":
        # 기본값(mlx_lm)인 채로 사용자가 명시하지 않은 경우만 스와프
        cfg.server.backend = preset.backend


def _apply_test_preset(cfg: AppConfig, preset: TestPreset, platform_preset: PlatformPreset) -> None:
    """테스트 프리셋 값을 cfg 에 적용한다.

    모델 / 백엔드는 플랫폼 프리셋에서 가져오며,
    테스트 포트·토큰 수 제한만 고정으로 스와프한다.
    """
    # 테스트는 플랫폼에 상관없이 E2B 사용
    # (사이즈가 작아서 빠르게 동작 확인하는 용도)
    cfg.server.model_path = "google/gemma-4-E2B-it-assistant"
    cfg.model.model_name = "google/gemma-4-E2B-it-assistant"
    cfg.server.backend = platform_preset.backend  # 백엔드는 플랫폼에 적합하게
    cfg.server.port = preset.port
    cfg.server.managed = True
    cfg.server.startup_timeout = preset.startup_timeout
    cfg.model.max_tokens = preset.max_tokens
    cfg.logging.llm_log_enabled = preset.llm_log_enabled


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()
    cfg = AppConfig.from_yaml(args.config)
    platform_preset = _platform_preset()

    print(
        f"[run] 플랫폼: {platform_preset.description}  "
        f"(model={platform_preset.model_path}, backend={platform_preset.backend})"
    )

    # 1) 플랫폼 기본값 적용 (config.yaml 명시 설정이 없으면)
    _apply_platform_preset(cfg, platform_preset)

    # 2) 테스트 모드 적용 (플랫폼 감지보다 우선)
    if args.test:
        _apply_test_preset(cfg, TEST_PRESET, platform_preset)
        print(
            f"[run] 테스트 모드: model={cfg.server.model_path}  "
            f"backend={cfg.server.backend}  port={cfg.server.port}"
        )

    # 3) CLI 추가 override (가장 우선)
    if args.no_server:
        cfg.server.managed = False
    if args.backend:
        cfg.server.backend = args.backend

    server = ModelServer.from_config(cfg)

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
