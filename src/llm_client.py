# src/llm_client.py
from __future__ import annotations

from typing import Optional


class LLMClient:
    def __init__(self, model_path: str, max_tokens: int, temperature: float, top_p: float, repetition_penalty: float):
        self._model_path = model_path
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._repetition_penalty = repetition_penalty
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from mlx_lm import load
            self._model, self._tokenizer = load(self._model_path)
        except Exception as exc:
            raise RuntimeError(f"모델 로드 실패: {self._model_path} — {exc}") from exc

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self._ensure_loaded()
        from mlx_lm import generate

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        response = generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=self._max_tokens,
            temp=self._temperature,
            top_p=self._top_p,
            repetition_penalty=self._repetition_penalty,
        )
        return response.strip()
