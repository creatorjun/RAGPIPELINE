# src/model_server.py
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


def _is_port_bound(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


class ModelServerError(RuntimeError):
    pass


class ModelServer:
    def __init__(
        self,
        model_path: str,
        host: str = "0.0.0.0",
        port: int = 8000,
        backend: str = "vllm_mlx",
        max_tokens: int = 4096,
        trust_remote_code: bool = False,
        extra_args: Optional[list[str]] = None,
        startup_timeout: int = 300,
        managed: bool = True,
        api_key: str = "sk-no-key-required",
        reasoning_parser: Optional[str] = None,
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
        self._api_key = api_key
        self._reasoning_parser = reasoning_parser
        self._proc: Optional[subprocess.Popen] = None
        self._dtype = dtype
        self._gpu_memory_utilization = gpu_memory_utilization
        self._tensor_parallel_size = tensor_parallel_size
        self._max_model_len = max_model_len

    @classmethod
    def from_config(cls, cfg: AppConfig) -> "ModelServer":
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
            api_key=sc.api_key,
            reasoning_parser=sc.reasoning_parser,
            dtype=sc.dtype,
            gpu_memory_utilization=sc.gpu_memory_utilization,
            tensor_parallel_size=sc.tensor_parallel_size,
            max_model_len=sc.max_model_len,
        )

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

    def start(self) -> None:
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
        limit = timeout if timeout is not None else self._startup_timeout
        check_host = "127.0.0.1" if self._host == "0.0.0.0" else self._host
        health_url = f"http://{check_host}:{self._port}/health"

        print(f"[ModelServer] 준비 대기 ({health_url}, 제한={limit}s) ...", flush=True)
        deadline = time.monotonic() + limit

        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise ModelServerError(
                    f"[ModelServer] 프로세스 조기 종료 (exit={self._proc.returncode}). "
                    "모델 경로나 서버 설정을 확인하세요."
                )
            try:
                r = requests.get(health_url, timeout=2)
                if r.status_code == 200:
                    print("[ModelServer] 서버 준비 완료.", flush=True)
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(2)

        self.stop()
        raise ModelServerError(
            f"[ModelServer] {limit}초 내 서버 준비 실패. "
            "모델 로드 실패 또는 메모리 부족일 수 있습니다."
        )

    def stop(self) -> None:
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
        host = "127.0.0.1" if self._host == "0.0.0.0" else self._host
        return f"http://{host}:{self._port}/v1"

    def _build_command(self) -> list[str]:
        if self._backend == "vllm_mlx":
            return self._build_vllm_mlx_cmd()
        elif self._backend == "mlx_vllm":
            return self._build_mlx_vlm_cmd(sys.executable)
        elif self._backend == "vllm":
            return self._build_vllm_cmd(sys.executable)
        else:
            return self._build_mlx_lm_cmd(sys.executable)

    def _build_vllm_mlx_cmd(self) -> list[str]:
        vllm_mlx = shutil.which("vllm-mlx") or "vllm-mlx"
        cmd = [
            vllm_mlx, "serve",
            self._model_path,
            "--host", self._host,
            "--port", str(self._port),
            "--api-key", self._api_key,
        ]
        if self._reasoning_parser:
            cmd += ["--reasoning-parser", self._reasoning_parser]
        cmd.extend(self._extra_args)
        return cmd

    def _build_mlx_lm_cmd(self, python: str) -> list[str]:
        cmd = [
            python, "-m", "mlx_lm", "server",
            "--model", self._model_path,
            "--host", self._host,
            "--port", str(self._port),
            "--max-tokens", str(self._max_tokens),
        ]
        if self._trust_remote_code:
            cmd.append("--trust-remote-code")
        cmd.extend(self._extra_args)
        return cmd

    def _build_mlx_vlm_cmd(self, python: str) -> list[str]:
        cmd = [
            python, "-m", "mlx_vlm.server",
            "--model", self._model_path,
            "--host", self._host,
            "--port", str(self._port),
        ]
        cmd.extend(self._extra_args)
        return cmd

    def _build_vllm_cmd(self, python: str) -> list[str]:
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
        alive = _is_port_bound(
            "127.0.0.1" if self._host == "0.0.0.0" else self._host,
            self._port,
        )
        if not alive:
            raise ModelServerError(
                f"[ModelServer] managed=false 인데 {self._host}:{self._port} 에 서버가 없습니다. "
                "외부에서 서버를 먼저 시작하세요."
            )
        print(f"[ModelServer] managed=false — 외부 서버 사용 ({self._host}:{self._port})", flush=True)
