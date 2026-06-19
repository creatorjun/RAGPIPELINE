# src/model_server.py
"""
LLM 서버 자동 기동 / 헬스체크 / 종료 모듈.

지원 백엔드::

    mlx_lm   — Apple Silicon 전용. python -m mlx_lm.server
    mlx_vllm — Apple Silicon 전용. python -m mlx_vllm.entrypoints.openai.api_server
    vllm     — x64 (CUDA / ROCm). python -m vllm.entrypoints.openai.api_server

사용 방식::

    from src.model_server import ModelServer

    server = ModelServer.from_config(cfg)   # config.yaml 에서 직접 생성
    with server:                            # __enter__ 에 기동, __exit__ 에 종료
        orchestrator.run()

또는 수동으로::

    server.start()
    server.wait_ready(timeout=120)
    ...
    server.stop()

노트:
    세 백엔드 모두 OpenAI-compatible 엔드포인트를 제공하므로
    LLMClient 는 변경 없이 그대로 사용할 수 있다.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Optional

import requests

from src.config import AppConfig, ServerConfig


# ---------------------------------------------------------------------------
# Helper
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
    """서버 기동 / 헬스체크 실패 시 발생한다."""


class ModelServer:
    """mlx_lm / mlx_vllm / vllm 서버를 하위 프로세스로 기동한다.

    Args:
        model_path:            HuggingFace repo ID 또는 로컬 디렉터리
        host:                  리스닝 호스트 (기본 0.0.0.0)
        port:                  리스닝 포트 (기본 8000)
        backend:               ``"mlx_lm"``, ``"mlx_vllm"``, 또는 ``"vllm"``
        max_tokens:            서버 수준 max_tokens 특성
        trust_remote_code:     원격 코드 실행 허용 여부
        extra_args:            관리자가 추가할 CLI 인수 목록
        startup_timeout:       서버 준비 대기 시간 (초, 기본 180)
        managed:               False 이면 start()/stop() 로직을 모두 스킵 —
                               외부에서 서버를 이미 런치한 중일 때 사용
        dtype:                 vllm 전용 dtype (auto / float16 / bfloat16)
        gpu_memory_utilization: vllm 전용 GPU 메모리 점유율 (0.1~1.0)
        tensor_parallel_size:  vllm 전용 텐서 병렬 수
        max_model_len:         vllm 전용 최대 컨텍스트 길이 (None → 자동)
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
        # vllm-specific
        dtype: str = "auto",
        gpu_memory_utilization: float = 0.90,
        tensor_parallel_size: int = 1,
        max_model_len: Optional[int] = None,
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
        # vllm
        self._dtype = dtype
        self._gpu_memory_utilization = gpu_memory_utilization
        self._tensor_parallel_size = tensor_parallel_size
        self._max_model_len = max_model_len

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: AppConfig) -> "ModelServer":
        """AppConfig.server 섹션에서 ModelServer 를 생성한다."""
        sc: ServerConfig = cfg.server
        return cls(
            model_path=cfg.resolved_model_path(),
            host=sc.host,
            port=sc.port,
            backend=sc.backend,
            max_tokens=cfg.model.max_tokens,
            trust_remote_code=sc.trust_remote_code,
            extra_args=sc.extra_args,
            startup_timeout=sc.startup_timeout,
            managed=sc.managed,
            dtype=sc.dtype,
            gpu_memory_utilization=sc.gpu_memory_utilization,
            tensor_parallel_size=sc.tensor_parallel_size,
            max_model_len=sc.max_model_len,
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
        """하위 프로세스로 서버를 런치한다.

        Raises:
            ModelServerError: 이미 포트가 점유된 경우 또는 실행파일 없음.
        """
        bind_host = "127.0.0.1" if self._host == "0.0.0.0" else self._host
        if _is_port_bound(bind_host, self._port):
            raise ModelServerError(
                f"[ModelServer] 포트 {self._port} 이미 사용 중. "
                "외부 서버를 이용하려면 config.server.managed = false 로 설정하세요."
            )

        cmd = self._build_command()
        print(f"[ModelServer] 기동: {' '.join(cmd)}")

        env = os.environ.copy()
        env.setdefault("TOKENIZERS_PARALLELISM", "false")

        self._proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True,
        )

    def wait_ready(self, timeout: Optional[int] = None) -> None:
        """서버가 /health 엔드포인트에 200 OK 를 반환할 때까지 대기한다.

        Raises:
            ModelServerError: timeout 내 준비가 완료되지 않으면.
        """
        limit = timeout if timeout is not None else self._startup_timeout
        url = _health_url(
            "127.0.0.1" if self._host == "0.0.0.0" else self._host,
            self._port,
        )
        print(f"[ModelServer] 준비 대기 ({url}, 제한={limit}s) ...", flush=True)
        deadline = time.monotonic() + limit

        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise ModelServerError(
                    f"[ModelServer] 프로세스 조기 종료 (exit={self._proc.returncode}). "
                    "모델 경로나 서버 설정을 확인하세요."
                )
            try:
                r = requests.get(url, timeout=2)
                if r.status_code == 200:
                    print("[ModelServer] 서버 준비 완료.", flush=True)
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(2)

        self.stop()
        raise ModelServerError(
            f"[ModelServer] {limit}초 내 서버 준비 실패. "
            "GPU 메모리 또는 모델 로드 실패일 수 있습니다."
        )

    def stop(self) -> None:
        """하위 프로세스에 SIGTERM 을 보내고, 10초 후에도 살아있으면 SIGKILL 로 강제 종료한다."""
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            self._proc = None
            return
        print("[ModelServer] 종료 중...", flush=True)
        try:
            self._proc.send_signal(signal.SIGTERM)
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[ModelServer] SIGTERM 응답 없음 — SIGKILL 실행", flush=True)
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None
        print("[ModelServer] 종료 완료.", flush=True)

    @property
    def base_url(self) -> str:
        """LLMClient 에 주입할 OpenAI-compatible base URL."""
        host = "127.0.0.1" if self._host == "0.0.0.0" else self._host
        return f"http://{host}:{self._port}/v1"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_command(self) -> list[str]:
        """backend 설정에 따라 CLI 명령어를 조립한다."""
        python = sys.executable
        if self._backend == "mlx_vllm":
            return self._build_mlx_vllm_cmd(python)
        elif self._backend == "vllm":
            return self._build_vllm_cmd(python)
        else:  # mlx_lm (default)
            return self._build_mlx_lm_cmd(python)

    def _build_mlx_lm_cmd(self, python: str) -> list[str]:
        """mlx_lm.server CLI (Apple Silicon 전용)

        Example::

            python -m mlx_lm.server \\
                --model mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit \\
                --host 0.0.0.0 --port 8000 --max-tokens 4096
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
        """mlx_vllm API 서버 CLI (Apple Silicon 전용)

        Example::

            python -m mlx_vllm.entrypoints.openai.api_server \\
                --model mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit \\
                --host 0.0.0.0 --port 8000 --max-model-len 8192
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

    def _build_vllm_cmd(self, python: str) -> list[str]:
        """표준 vLLM API 서버 CLI (x64 CUDA / ROCm 전용)

        Example::

            python -m vllm.entrypoints.openai.api_server \\
                --model Qwen/Qwen2.5-7B-Instruct \\
                --host 0.0.0.0 --port 8000 \\
                --dtype auto \\
                --gpu-memory-utilization 0.90 \\
                --tensor-parallel-size 1 \\
                --max-model-len 8192
        """
        cmd = [
            python, "-m", "vllm.entrypoints.openai.api_server",
            "--model", self._model_path,
            "--host", self._host,
            "--port", str(self._port),
            "--dtype", self._dtype,
            "--gpu-memory-utilization", str(self._gpu_memory_utilization),
            "--tensor-parallel-size", str(self._tensor_parallel_size),
        ]
        if self._max_model_len is not None:
            cmd += ["--max-model-len", str(self._max_model_len)]
        if self._trust_remote_code:
            cmd.append("--trust-remote-code")
        cmd.extend(self._extra_args)
        return cmd

    def _check_already_running(self) -> None:
        """managed=False 시 이미 서버가 떠 있는지 확인한다."""
        alive = _is_port_bound(
            "127.0.0.1" if self._host == "0.0.0.0" else self._host,
            self._port,
        )
        if not alive:
            raise ModelServerError(
                f"[ModelServer] managed=false 인데 {self._host}:{self._port} 에 서버가 없습니다. "
                "외부에서 mlx_lm / mlx_vllm / vllm 서버를 먼저 시작하세요."
            )
        print(f"[ModelServer] managed=false — 외부 서버 사용 ({self._host}:{self._port})", flush=True)
