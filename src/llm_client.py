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
        self._base_url = base_url
        self._api_key = api_key
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        prefix: str | None,
        temperature: float,
        top_p: float,
        max_tokens: int,
        client: OpenAI,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if prefix:
            messages.append({"role": "assistant", "content": prefix})

        response = client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
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

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        prefix: str | None = None,
    ) -> str:
        """일반 생성 호출 — 인스턴스 기본 파라미터 사용."""
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prefix=prefix,
            temperature=self._temperature,
            top_p=self._top_p,
            max_tokens=self._max_tokens,
            client=self._client,
        )

    def generate_isolated(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """
        완전히 격리된 컨텍스트에서 단발성 호출을 수행한다.
        - 새 OpenAI 클라이언트 인스턴스를 생성해 세션 상태를 공유하지 않는다.
        - temperature 를 호출자가 명시적으로 지정한다 (Judge: 0.0 고정).
        - 기존 generate() 호출의 대화 히스토리와 완전히 분리된다.
        """
        isolated_client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prefix=None,
            temperature=temperature,
            top_p=self._top_p,
            max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
            client=isolated_client,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def max_tokens(self) -> int:
        return self._max_tokens
