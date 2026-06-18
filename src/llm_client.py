# src/llm_client.py
from __future__ import annotations

from openai import OpenAI


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

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            top_p=self._top_p,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
