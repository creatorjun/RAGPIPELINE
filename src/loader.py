# src/loader.py
import re
from pathlib import Path
from typing import List

from src.models import Document, DocumentChunk

_CHARS_PER_TOKEN = 4


def _load_text(path: Path) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _split_by_h2(text: str) -> List[str]:
    parts = re.split(r"(?m)^(?=## )", text)
    return [p for p in parts if p.strip()]


def _build_chunks(
    sections: List[str],
    source_file: str,
    max_chars: int,
    overlap_chars: int,
) -> List[DocumentChunk]:
    chunks: List[str] = []
    current = ""

    for section in sections:
        if len(current) + len(section) <= max_chars:
            current += ("\n\n" if current else "") + section
        else:
            if current:
                chunks.append(current)
            current = section

    if current:
        chunks.append(current)

    if not chunks:
        return [DocumentChunk(
            source_file=source_file,
            content="",
            chunk_index=0,
            total_chunks=1,
        )]

    result: List[DocumentChunk] = []
    total = len(chunks)
    for i, content in enumerate(chunks):
        if i > 0 and overlap_chars > 0:
            tail = chunks[i - 1][-overlap_chars:]
            content = tail + "\n\n" + content
        result.append(DocumentChunk(
            source_file=source_file,
            content=content,
            chunk_index=i,
            total_chunks=total,
        ))
    return result


def load_document(path: Path, max_chunk_tokens: int = 8000, overlap_tokens: int = 200) -> Document:
    text = _load_text(path)
    max_chars = max_chunk_tokens * _CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN
    sections = _split_by_h2(text)
    chunks = _build_chunks(sections, path.name, max_chars, overlap_chars)
    return Document(source_file=path.name, content=text, chunks=chunks)


def load_all_documents(input_dir: str, max_chunk_tokens: int = 8000, overlap_tokens: int = 200) -> List[Document]:
    base = Path(input_dir)
    docs: List[Document] = []
    for md_path in sorted(base.rglob("*.md")):
        docs.append(load_document(md_path, max_chunk_tokens, overlap_tokens))
    return docs
