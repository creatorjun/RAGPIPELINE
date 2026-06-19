# src/ports.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.web_search import SearchResult


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


class WebSearchClientPort(ABC):
    @abstractmethod
    def search(self, query: str, language: str = "ko-KR") -> List[SearchResult]: ...

    @abstractmethod
    def format_for_prompt(self, results: List[SearchResult]) -> str: ...
