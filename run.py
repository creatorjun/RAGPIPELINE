#!/usr/bin/env python3
# run.py
"""
Phase 1·2 정제 파이프라인 진입점.

플랫폼 자동 감지::

    macOS (Apple Silicon) → mlx-community/gemma-4-26b-a4b-it-4bit + mlx_lm
    x64  (Linux / Windows) → google/gemma-4-E2B-it-assistant       + vllm

백엔드 선택 기준::

    mlx_lm   — 텍스트 전용 Gemma-4 모델 (gemma-4-*-it-*bit)
    mlx_vllm — 비전+텍스트 겸용 VLM (mlx-vlm 패키지 필요)
    vllm     — x64 CUDA / ROCm 환경

실행 흐름:
    1. config.yaml 로드
    2. 플랫폼 감지 → 모델 / 백엔드 자동 설정
    3. server.managed=True 이면 ModelServer 자동 기동
    4. PipelineOrchestrator.run()
    5. 정상/예외 종료 시 ModelServer.stop()

CLI 예시::

    # 자동 감지 (플랫폼에 따라 모델·백엔드 선택)
    python run.py

    # 테스트 모드 — 경량 모델(E2B) + config.yaml 백엔드, 포트 8001
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
    """현재 프로세스가 macOS(애플 실리콘 포함) 위에서 동작 중이면 True."""
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
    # --test 모드에서 사용할 경량 모델
    test_model_path: str


MACOS_PRESET = PlatformPreset(
    model_path="mlx-community/gemma-4-26b-a4b-it-4bit",
    # Gemma-4 는 텍스트 전용 모델 → mlx_lm 사용
    # mlx_vllm(mlx-vlm) 은 VLM(비전+텍스트) 전용이라 가중치 구조 불일치 발생
    backend="mlx_lm",
    description="macOS (Apple Silicon)",
    test_model_path="mlx-community/gemma-4-e2b-it-4bit",
)

X64_PRESET = PlatformPreset(
    model_path="google/gemma-4-E2B-it-assistant",
    backend="vllm",
    description="x64 (Linux/Windows CUDA)",
    test_model_path="google/gemma-4-E2B-it-assistant",
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

    모델은 PlatformPreset.test_model_path 에서 자동 선택되므로
    이 클래스에는 포트 관련 고정값만 담는다.
    백엔드는 config.yaml 값을 우선하여 추후 --backend CLI로 치환 가능하다.
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
            f"\ud14c\uc2a4\ud2b8 \ubaa8\ub4dc: \uacbd\ub7c9 E2B \ubaa8\ub378\uc744 \ud3ec\ud2b8 {TEST_PRESET.port} "
            "\uc73c\ub85c \uae30\ub3d9 (\ubc31\uc5d4\ub4dc\ub294 config.yaml \ub610\ub294 --backend \uc73c\ub85c \uc9c0\uc815)"
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
        help="서버 백엔드 치환 (config.yaml / 자동 감지보다 우선)",
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
    """config.yaml에 model_path / backend가 없으면 플랫폼 프리셋을 기본값으로 적용.

    config.yaml에 명시된 설정은 고정되지 않는다.
    """
    if not cfg.server.model_path:
        cfg.server.model_path = preset.model_path
        cfg.model.model_name = preset.model_path
    # config.yaml backend가 플랫폼 프리셋과 다른 경우는 config.yaml을 존중한다


def _apply_test_preset(cfg: AppConfig, preset: TestPreset, platform_preset: PlatformPreset) -> None:
    """--test 모드: 경량 E2B 모델 + 포트만 고정, 백엔드는 config.yaml 값 유지.

    백엔드 우선순위:
        1. --backend CLI 인수 (이후 main()에서 덮어쓸)
        2. config.yaml 에 명시된 backend (cfg.server.backend)
        3. PlatformPreset.backend
    """
    test_model = platform_preset.test_model_path
    cfg.server.model_path = test_model
    cfg.model.model_name = test_model
    # 백엔드는 config.yaml이 명시된 경우 그대로 유지; 미설정이면 플랫폼 프리셋 사용
    if not cfg.server.backend:
        cfg.server.backend = platform_preset.backend
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

    # 2) 테스트 모드 적용 — 백엔드는 config.yaml을 유지
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
