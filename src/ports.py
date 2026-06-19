# src/ports.py
"""추상 Port 인터페이스 모음.

Domain 레이어가 인프라 구체 클래스에 직접 의존하지 않도록
모든 외부 의존성을 ABC 로 정의한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


class LLMClientPort(ABC):
    """LLM 클라이언트 추상 인터페이스."""

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


@runtime_checkable
class AugmenterPort(Protocol):
    """DESIGN-B FIX: SearchAugmenter 의 타입을 명시하는 Protocol.

    Protocol(structural subtyping) 을 사용하므로
    SearchAugmenter 가 이 인터페이스를 명시적으로 상속할 필요 없이
    augment(str, str) -> str 메서드만 있으면 자동으로 호환된다.
    """

    def augment(self, refined_text: str, source_file: str) -> str: ...
