# src/rag/models.py
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RagChunk:
    chunk_id: str
    source_file: str
    domain: List[str]
    section_title: str
    content: str
    doc_type: str = ""
    keywords: List[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class SearchResult:
    chunk: RagChunk
    score: float
    rank: int


@dataclass
class RagAnswer:
    question: str
    answer: str
    sources: List[SearchResult]
