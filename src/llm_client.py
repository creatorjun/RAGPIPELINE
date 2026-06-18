# src/llm_client.py
from __future__ import annotations

from openai import OpenAI


class LLMEmptyResponseError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ):
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        prefix: str | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if prefix:
            messages.append({"role": "assistant", "content": prefix})

        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            top_p=self._top_p,
        )
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        message = choice.message

        content = (message.content or "").strip()

        if not content:
            reasoning = getattr(message, "reasoning_content", None) or ""
            content = reasoning.strip()

        if not content:
            raise LLMEmptyResponseError(
                f"LLM 빈 응답 (finish_reason={finish_reason})"
            )

        return (prefix + content) if prefix else content

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def max_tokens(self) -> int:
        return self._max_tokens
