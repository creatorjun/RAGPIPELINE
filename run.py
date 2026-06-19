#!/usr/bin/env python3
# run.py
from __future__ import annotations

import argparse
import platform
import sys
from dataclasses import dataclass
from typing import Optional

from src.config import AppConfig
from src.model_server import ModelServer, ModelServerError
from src.pipeline import PipelineOrchestrator


def _is_macos() -> bool:
    return platform.system() == "Darwin"


@dataclass(frozen=True)
class PlatformPreset:
    model_path: str
    backend: str
    description: str
    test_model_path: str


MACOS_PRESET = PlatformPreset(
    model_path="mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit",
    backend="vllm_mlx",
    description="macOS (Apple Silicon)",
    test_model_path="mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit",
)

X64_PRESET = PlatformPreset(
    model_path="google/gemma-4-E2B-it-assistant",
    backend="vllm",
    description="x64 (Linux/Windows CUDA)",
    test_model_path="google/gemma-4-E2B-it-assistant",
)


def _platform_preset() -> PlatformPreset:
    return MACOS_PRESET if _is_macos() else X64_PRESET


@dataclass(frozen=True)
class TestPreset:
    port: int = 8001
    max_tokens: int = 2048
    startup_timeout: int = 300
    llm_log_enabled: bool = True


TEST_PRESET = TestPreset()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG Pipeline 정제 실행",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            f"\ud14c\uc2a4\ud2b8 \ubaa8\ub4dc: \ud3ec\ud2b8 {TEST_PRESET.port} "
            "\uc73c\ub85c \uae30\ub3d9 (\ubc31\uc5d4\ub4dc\ub294 config.yaml \ub610\ub294 --backend \uc73c\ub85c \uc9c0\uc815)"
        ),
    )
    parser.add_argument("--no-resume", action="store_true", help="Resume 무시 후 전체 재처리")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 대상 목록만 출력")
    parser.add_argument(
        "--backend",
        choices=["mlx_lm", "mlx_vllm", "vllm_mlx", "vllm"],
        default=None,
        help="서버 백엔드 치환 (config.yaml / 자동 감지보다 우선)",
    )
    parser.add_argument("--no-server", action="store_true", help="서버 자동 기동 스킵")
    return parser.parse_args()


def _apply_platform_preset(cfg: AppConfig, preset: PlatformPreset) -> None:
    if not cfg.server.model_path:
        cfg.server.model_path = preset.model_path
        cfg.model.model_name = preset.model_path


def _apply_test_preset(cfg: AppConfig, preset: TestPreset, platform_preset: PlatformPreset) -> None:
    test_model = platform_preset.test_model_path
    cfg.server.model_path = test_model
    cfg.model.model_name = test_model
    if not cfg.server.backend:
        cfg.server.backend = platform_preset.backend
    cfg.server.port = preset.port
    cfg.server.managed = True
    cfg.server.startup_timeout = preset.startup_timeout
    cfg.model.max_tokens = preset.max_tokens
    cfg.logging.llm_log_enabled = preset.llm_log_enabled


def main() -> int:
    args = _parse_args()
    cfg = AppConfig.from_yaml(args.config)
    platform_preset = _platform_preset()

    print(
        f"[run] 플랫폼: {platform_preset.description}  "
        f"(model={platform_preset.model_path}, backend={platform_preset.backend})"
    )

    _apply_platform_preset(cfg, platform_preset)

    if args.test:
        _apply_test_preset(cfg, TEST_PRESET, platform_preset)
        print(
            f"[run] 테스트 모드: model={cfg.server.model_path}  "
            f"backend={cfg.server.backend}  port={cfg.server.port}"
        )

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
