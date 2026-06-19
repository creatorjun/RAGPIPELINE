#!/usr/bin/env python3
# run.py
"""
Phase 1\u00b72 \uc815\uc81c \ud30c\uc774\ud504\ub77c\uc778 \uc9c4\uc785\uc810.

\uc2e4\ud589 \ud750\ub984:
    1. config.yaml \ub85c\ub4dc
    2. server.managed=True \uc774\uba74 ModelServer \uc790\ub3d9 \uae30\ub3d9
    3. PipelineOrchestrator.run()
    4. \uc815\uc0c1/\uc608\uc678 \uc885\ub8cc \uc2dc ModelServer.stop()
"""
import argparse
import sys

from src.config import AppConfig
from src.model_server import ModelServer, ModelServerError
from src.pipeline import PipelineOrchestrator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG Pipeline \uc815\uc81c \uc2e4\ud589",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="\uc124\uc815 \ud30c\uc77c \uacbd\ub85c")
    parser.add_argument("--no-resume", action="store_true", help="Resume \ubb34\uc2dc \ud6c4 \uc804\uccb4 \uc7ac\ucc98\ub9ac")
    parser.add_argument("--dry-run", action="store_true", help="LLM \ud638\ucd9c \uc5c6\uc774 \ub300\uc0c1 \ubaa9\ub85d\ub9cc \ucd9c\ub825")
    parser.add_argument(
        "--backend",
        choices=["mlx_lm", "mlx_vllm"],
        default=None,
        help="\uc11c\ubc84 \ubc31\uc5d4\ub4dc \uc6b0\uc120 (config.yaml server.backend \ub300\ube44 CLI \uc6b0\uc120)",
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="\uc11c\ubc84 \uc790\ub3d9 \uae30\ub3d9 \uc2a4\ud0b5 (\uc678\ubd80\uc5d0\uc11c \uc774\ubbf8 \uc2e4\ud589 \uc911\uc778 \uc11c\ubc84 \uc0ac\uc6a9)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = AppConfig.from_yaml(args.config)

    # CLI \uc778\uc218\ub85c server \uc124\uc815 \ub36e\uc5b4\uc4f0\uae30
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
            # \uc11c\ubc84 base_url \uc744 \uc2e4\uc81c \uac00\ub3d9 \uc8fc\uc18c\ub85c \ub36e
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
        print("\n[INFO] \uc0ac\uc6a9\uc790 \uc911\ub2e8 (Ctrl+C)", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
