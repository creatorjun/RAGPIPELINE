# src/model_server.py
"""
mlx_lm.server 자동 기동 / 헬스첬 / 종료 모듈.

사용 방식::

    from src.model_server import ModelServer

    server = ModelServer.from_config(cfg)   # config.yaml 에서 직접 생성
    with server:                            # __enter__ 에 기동, __exit__ 에 종료
        orchestrator.run()

또는 수동으로::

    server.start()   # subprocess 런치
    server.wait_ready(timeout=120)  # HTTP /health 응답 대기
    ...              # 파이프라인 실행
    server.stop()    # 종료 (SIGTERM → SIGKILL fallback)

노트:
    mlx-vllm 또는 mlx_lm.server 중 설정된 ``backend`` 에 따라
    합수(compatible) OpenAI 엔드포인트를 제공하므로
    LLMClient 는 변경 없이 그대로 사용할 수 있다.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Optional

import requests

from src.config import AppConfig, ServerConfig


# ---------------------------------------------------------------------------
# Helper — 서버 주소 맨드리
# ---------------------------------------------------------------------------

def _health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def _is_port_bound(host: str, port: int) -> bool:
    """TCP 소켓 연결로 포트 점유 여부를 확인한다."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# ModelServer
# ---------------------------------------------------------------------------


class ModelServerError(RuntimeError):
    """\uc11c\ubc84 \uae30\ub3d9 / \ud5ec\uc2a4\uccac \uc2e4\ud328 \uc2dc \ubc1c\uc0dd\ud55c\ub2e4."""


class ModelServer:
    """mlx_lm.server \ub610\ub294 mlx-vllm \uc11c\ubc84\ub97c \ud558\uc704 \ud504\ub85c\uc138\uc2a4\ub85c \uae30\ub3d9\ud55c\ub2e4.

    Args:
        model_path:   HuggingFace repo ID \ub610\ub294 \ub85c\ucef9 \ub514\ub809\ud130\ub9ac
        host:         \ub9ac\uc2a4\ub2dd \ud638\uc2a4\ud2b8 (\uae30\ubcf8 0.0.0.0)
        port:         \ub9ac\uc2a4\ub2dd \ud3ec\ud2b8 (\uae30\ubcf8 8000)
        backend:      ``"mlx_lm"`` \ub610\ub294 ``"mlx_vllm"``
        max_tokens:   \uc11c\ubc84 \uc218\uc900 max_tokens \ud2b9\uc131
        trust_remote_code: \uc6d0\uaca9 \ucf54\ub4dc \uc2e4\ud589 \ud5c8\uc6a9 \uc5ec\ubd80
        extra_args:   \uad00\ub9ac\uc790\uac00 \ucd94\uac00\ud560 CLI \uc778\uc218 \ubaa9\ub85d
        startup_timeout: \uc11c\ubc84 \uc900\ube44 \ub300\uae30 \uc2dc\uac04 (\ucd08, \uae30\ubcf8 180)
        managed:      False \uc774\uba74 start()/stop() \ub85c\uc9c1\uc744 \ubaa8\ub450 \uc2a4\ud0b5 —
                      \uc678\ubd80\uc5d0\uc11c \uc11c\ubc84\ub97c \uc774\ubbf8 \ub7f0\uce58\ud55c \uc911\uc77c \ub54c \uc0ac\uc6a9
    """

    def __init__(
        self,
        model_path: str,
        host: str = "0.0.0.0",
        port: int = 8000,
        backend: str = "mlx_lm",
        max_tokens: int = 4096,
        trust_remote_code: bool = False,
        extra_args: Optional[list[str]] = None,
        startup_timeout: int = 180,
        managed: bool = True,
    ):
        self._model_path = model_path
        self._host = host
        self._port = port
        self._backend = backend
        self._max_tokens = max_tokens
        self._trust_remote_code = trust_remote_code
        self._extra_args = extra_args or []
        self._startup_timeout = startup_timeout
        self._managed = managed
        self._proc: Optional[subprocess.Popen] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: AppConfig) -> "ModelServer":
        """AppConfig.server \uc139\uc158\uc5d0\uc11c ModelServer \ub97c \uc0dd\uc131\ud55c\ub2e4."""
        sc: ServerConfig = cfg.server
        return cls(
            model_path=sc.model_path,
            host=sc.host,
            port=sc.port,
            backend=sc.backend,
            max_tokens=cfg.model.max_tokens,
            trust_remote_code=sc.trust_remote_code,
            extra_args=sc.extra_args,
            startup_timeout=sc.startup_timeout,
            managed=sc.managed,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ModelServer":
        if self._managed:
            self.start()
            self.wait_ready()
        else:
            self._check_already_running()
        return self

    def __exit__(self, *_) -> None:
        if self._managed:
            self.stop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """\ud558\uc704 \ud504\ub85c\uc138\uc2a4\ub85c \uc11c\ubc84\ub97c \ub7f0\uce58\ud55c\ub2e4.

        Raises:
            ModelServerError: \uc774\ubbf8 \ud3ec\ud2b8\uac00 \uc810\uc720\ub41c \uacbd\uc6b0 \ub610\ub294 \uc2e4\ud589\ud30c\uc77c \uc5c6\uc74c.
        """
        if _is_port_bound(self._host if self._host != "0.0.0.0" else "127.0.0.1", self._port):
            raise ModelServerError(
                f"[ModelServer] \ud3ec\ud2b8 {self._port} \uc774\ubbf8 \uc0ac\uc6a9 \uc911. "
                "\uc678\ubd80 \uc11c\ubc84\ub97c \uc774\uc6a9\ud558\ub824\uba74 config.server.managed = false \ub85c \uc124\uc815\ud558\uc138\uc694."
            )

        cmd = self._build_command()
        print(f"[ModelServer] \uae30\ub3d9: {' '.join(cmd)}")

        log_env = os.environ.copy()
        # MLX \uad00\ub828 \ud658\uacbd\ubcc0\uc218 — \ud398\uc774\uc9c0 \ud3c4
        log_env.setdefault("TOKENIZERS_PARALLELISM", "false")

        self._proc = subprocess.Popen(
            cmd,
            env=log_env,
            stdout=sys.stdout,   # \uba54\uc778 \ud504\ub85c\uc138\uc2a4\uc640 stdout \uacf5\uc720
            stderr=sys.stderr,
            text=True,
        )

    def wait_ready(self, timeout: Optional[int] = None) -> None:
        """\uc11c\ubc84\uac00 /health \uc5d4\ub4dc\ud3ec\uc778\ud2b8\uc5d0 200 OK \ub97c \ubc18\ud658\ud560 \ub54c\uae4c\uc9c0 \ub300\uae30\ud55c\ub2e4.

        Raises:
            ModelServerError: timeout \ub0b4 \uc900\ube44\uac00 \uc644\ub8cc\ub418\uc9c0 \uc54a\uc73c\uba74.
        """
        limit = timeout if timeout is not None else self._startup_timeout
        url = _health_url(
            "127.0.0.1" if self._host == "0.0.0.0" else self._host,
            self._port,
        )
        print(f"[ModelServer] \uc900\ube44 \ub300\uae30 ({url}, \uc81c\ud55c={limit}s) ...", flush=True)
        deadline = time.monotonic() + limit

        while time.monotonic() < deadline:
            # \ud504\ub85c\uc138\uc2a4\uac00 \uc870\uae30 \uc885\ub8cc\ub41c \uacbd\uc6b0 \ube60\ub974\uac8c \uc2e4\ud328
            if self._proc is not None and self._proc.poll() is not None:
                raise ModelServerError(
                    f"[ModelServer] \ud504\ub85c\uc138\uc2a4 \uc870\uae30 \uc885\ub8cc (exit={self._proc.returncode}). "
                    "\ubaa8\ub378 \uacbd\ub85c\ub098 \uc11c\ubc84 \uc124\uc815\uc744 \ud655\uc778\ud558\uc138\uc694."
                )
            try:
                r = requests.get(url, timeout=2)
                if r.status_code == 200:
                    print("[ModelServer] \uc11c\ubc84 \uc900\ube44 \uc644\ub8cc.", flush=True)
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(2)

        self.stop()  # \uc2e4\ud328 \uc2dc \uc815\ub9ac
        raise ModelServerError(
            f"[ModelServer] {limit}\ucd08 \ub0b4 \uc11c\ubc84 \uc900\ube44 \uc2e4\ud328. "
            "GPU \uba54\ubaa8\ub9ac \ub610\ub294 \ubaa8\ub378 \ub85c\ub4dc \uc2e4\ud328\uc77c \uc218 \uc788\uc2b5\ub2c8\ub2e4."
        )

    def stop(self) -> None:
        """\ud558\uc704 \ud504\ub85c\uc138\uc2a4\uc5d0 SIGTERM \uc744 \ubcf4\ub0b4\uace0, 10\ucd08 \ud6c4\uc5d0\ub3c4 \uc0b4\uc544\uc788\uc73c\uba74 SIGKILL \ub85c \uac15\uc81c \uc885\ub8cc\ud55c\ub2e4."""
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            self._proc = None
            return
        print("[ModelServer] \uc885\ub8cc \uc911...", flush=True)
        try:
            self._proc.send_signal(signal.SIGTERM)
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[ModelServer] SIGTERM \uc751\ub2f5 \uc5c6\uc74c \u2014 SIGKILL \uc2e4\ud589", flush=True)
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None
        print("[ModelServer] \uc885\ub8cc \uc644\ub8cc.", flush=True)

    @property
    def base_url(self) -> str:
        """LLMClient \uc5d0 \uc8fc\uc785\ud560 OpenAI-compatible base URL."""
        host = "127.0.0.1" if self._host == "0.0.0.0" else self._host
        return f"http://{host}:{self._port}/v1"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_command(self) -> list[str]:
        """backend \uc124\uc815\uc5d0 \ub530\ub77c CLI \uba85\ub839\uc5b4\ub97c \uc870\ub9bd\ud55c\ub2e4."""
        python = sys.executable

        if self._backend == "mlx_vllm":
            return self._build_mlx_vllm_cmd(python)
        else:  # mlx_lm (default)
            return self._build_mlx_lm_cmd(python)

    def _build_mlx_lm_cmd(self, python: str) -> list[str]:
        """mlx_lm.server CLI

        Example::

            python -m mlx_lm.server \\
                --model mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit \\
                --host 0.0.0.0 --port 8000 \\
                --max-tokens 4096
        """
        cmd = [
            python, "-m", "mlx_lm.server",
            "--model", self._model_path,
            "--host", self._host,
            "--port", str(self._port),
            "--max-tokens", str(self._max_tokens),
        ]
        if self._trust_remote_code:
            cmd.append("--trust-remote-code")
        cmd.extend(self._extra_args)
        return cmd

    def _build_mlx_vllm_cmd(self, python: str) -> list[str]:
        """mlx_vllm \uc2dc vllm.entrypoints.openai.api_server \ubbf8\ub7ec\ub9c1 CLI

        Example::

            python -m mlx_vllm.entrypoints.openai.api_server \\
                --model mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit \\
                --host 0.0.0.0 --port 8000 \\
                --max-model-len 8192
        """
        cmd = [
            python, "-m", "mlx_vllm.entrypoints.openai.api_server",
            "--model", self._model_path,
            "--host", self._host,
            "--port", str(self._port),
            "--max-model-len", str(self._max_tokens * 2),
        ]
        if self._trust_remote_code:
            cmd.append("--trust-remote-code")
        cmd.extend(self._extra_args)
        return cmd

    def _check_already_running(self) -> None:
        """managed=False \uc2dc \uc774\ubbf8 \uc11c\ubc84\uac00 \ub728 \uc788\ub294\uc9c0 \ud655\uc778\ud55c\ub2e4."""
        alive = _is_port_bound(
            "127.0.0.1" if self._host == "0.0.0.0" else self._host,
            self._port,
        )
        if not alive:
            raise ModelServerError(
                f"[ModelServer] managed=false \uc778\ub370 {self._host}:{self._port} \uc5d0 \uc11c\ubc84\uac00 \uc5c6\uc2b5\ub2c8\ub2e4. "
                "\uc678\ubd80\uc5d0\uc11c mlx_lm.server \ub610\ub294 mlx_vllm \uc11c\ubc84\ub97c \uba3c\uc800 \uc2dc\uc791\ud558\uc138\uc694."
            )
        print(f"[ModelServer] managed=false \u2014 \uc678\ubd80 \uc11c\ubc84 \uc0ac\uc6a9 ({self._host}:{self._port})", flush=True)
