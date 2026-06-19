# src/models.py
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DocumentChunk:
    source_file: str
    content: str
    chunk_index: int
    total_chunks: int


@dataclass
class Document:
    source_file: str
    content: str
    chunks: List[DocumentChunk]


@dataclass
class FilterResult:
    domains: List[str]
    confidence: float
    is_partial: bool


@dataclass
class JudgeVerdict:
    passed: bool
    faithfulness: bool
    completeness: bool
    structure_ok: bool
    critique: str
    retry_hint: str


@dataclass
class ValidationResult:
    is_valid: bool
    keyword_retention_rate: float
    errors: List[str]
    missing_keywords: List[str] = field(default_factory=list)
    judge: Optional[JudgeVerdict] = None
