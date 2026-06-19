# src/llm_client.py
from __future__ import annotations

from typing import Optional

from openai import OpenAI

from src.ports import LLMClientPort
from src.llm_logger import LLMLogger


class LLMEmptyResponseError(RuntimeError):
    pass


class LLMClient(LLMClientPort):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        llm_logger: Optional[LLMLogger] = None,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._isolated_client = OpenAI(base_url=base_url, api_key=api_key)
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._top_p = top_p
        # LLMLogger 가 None 이면 no-op 인스턴스로 대체
        self._logger: LLMLogger = llm_logger or LLMLogger(enabled=False)

    # ------------------------------------------------------------------
    # 주 호출 로직
    # ------------------------------------------------------------------

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        prefix: str | None,
        temperature: float,
        top_p: float,
        max_tokens: int,
        client: OpenAI,
        stage: str = "",
        source_file: str = "",
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
        finish_reason = choice.finish_reason or ""
        message = choice.message
        content = (message.content or "").strip()
        if not content:
            reasoning = getattr(message, "reasoning_content", None) or ""
            content = reasoning.strip()
        if not content:
            # 빈 응답도 로깅
            self._logger.record(
                stage=stage,
                source_file=source_file,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response="<EMPTY RESPONSE>",
                prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
                completion_tokens=getattr(response.usage, "completion_tokens", 0),
                finish_reason=finish_reason,
            )
            raise LLMEmptyResponseError(
                f"LLM 빈 응답 (finish_reason={finish_reason})"
            )

        final = (prefix + content) if prefix else content

        # 정상 응답 로깅
        self._logger.record(
            stage=stage,
            source_file=source_file,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=final,
            prompt_tokens=getattr(response.usage, "prompt_tokens", 0),
            completion_tokens=getattr(response.usage, "completion_tokens", 0),
            finish_reason=finish_reason,
        )
        return final

    # ------------------------------------------------------------------
    # Port 구현
    # ------------------------------------------------------------------

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        prefix: str | None = None,
        stage: str = "",
        source_file: str = "",
    ) -> str:
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prefix=prefix,
            temperature=self._temperature,
            top_p=self._top_p,
            max_tokens=self._max_tokens,
            client=self._client,
            stage=stage,
            source_file=source_file,
        )

    def generate_isolated(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stage: str = "",
        source_file: str = "",
    ) -> str:
        return self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prefix=None,
            temperature=temperature,
            top_p=self._top_p,
            max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
            client=self._isolated_client,
            stage=stage,
            source_file=source_file,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def max_tokens(self) -> int:
        return self._max_tokens
