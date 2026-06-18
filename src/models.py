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
    chunks: List[DocumentChunk] = field(default_factory=list)


@dataclass
class FilterResult:
    domains: List[str]
    confidence: float
    is_partial: bool


@dataclass
class ValidationResult:
    is_valid: bool
    keyword_retention_rate: float
    errors: List[str] = field(default_factory=list)
