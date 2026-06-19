# src/ports.py
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClientPort(ABC):
    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        prefix: str | None = None,
    ) -> str: ...

    @abstractmethod
    def generate_isolated(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def max_tokens(self) -> int: ...
