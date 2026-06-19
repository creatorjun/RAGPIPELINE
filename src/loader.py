# src/loader.py
import re
from pathlib import Path
from typing import List

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))

except ImportError:
    def _count_tokens(text: str) -> int:
        korean = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
        ascii_like = len(text) - korean
        return korean + ascii_like // 4

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".rst"}

from src.models import Document, DocumentChunk


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
    max_tokens: int,
    overlap_tokens: int,
) -> List[DocumentChunk]:
    chunks: List[str] = []
    current = ""
    current_tokens = 0

    for section in sections:
        section_tokens = _count_tokens(section)
        if current_tokens + section_tokens <= max_tokens:
            current += ("\n\n" if current else "") + section
            current_tokens += section_tokens
        else:
            if current:
                chunks.append(current)
            current = section
            current_tokens = section_tokens

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
        if i > 0 and overlap_tokens > 0:
            prev_tokens = _count_tokens(chunks[i - 1])
            if prev_tokens > overlap_tokens:
                tail_chars = len(chunks[i - 1]) * overlap_tokens // prev_tokens
                tail = chunks[i - 1][-tail_chars:]
            else:
                tail = chunks[i - 1]
            content = tail + "\n\n" + content
        result.append(DocumentChunk(
            source_file=source_file,
            content=content,
            chunk_index=i,
            total_chunks=total,
        ))
    return result


def load_document(path: Path, max_chunk_tokens: int = 8000, overlap_tokens: int = 200) -> Document:
    """단일 파일을 로드해 Document 로 변환한다."""
    text = _load_text(path)
    sections = _split_by_h2(text)
    chunks = _build_chunks(sections, path.name, max_chunk_tokens, overlap_tokens)
    return Document(source_file=path.name, content=text, chunks=chunks)


def load_all_documents(input_dir: str, max_chunk_tokens: int = 8000, overlap_tokens: int = 200) -> List[Document]:
    """디렉토리 아래 모든 지원 파일을 재귀 로드한다."""
    base = Path(input_dir)
    docs: List[Document] = []
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS:
            docs.append(load_document(path, max_chunk_tokens, overlap_tokens))
    return docs


class DocumentLoader:
    """pipeline.py 가 사용하는 파일 로더 클래스.

    내부적으로 load_document() / load_all_documents() 함수를 위임한다.

    Args:
        input_dir:        입력 디렉토리 경로
        max_chunk_tokens: 청크 최대 토큰 수 (기본 8000)
        overlap_tokens:   청크 간 오버랩 토큰 수 (기본 200)
    """

    def __init__(
        self,
        input_dir: str,
        max_chunk_tokens: int = 8000,
        overlap_tokens: int = 200,
    ) -> None:
        self._input_dir = input_dir
        self._max_chunk_tokens = max_chunk_tokens
        self._overlap_tokens = overlap_tokens

    def load_all(self) -> List[Path]:
        """지원 확장자 파일 경로 목록을 반환한다 (정렬, 재귀)."""
        base = Path(self._input_dir)
        return [
            path
            for path in sorted(base.rglob("*"))
            if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS
        ]

    def load(self, path: Path) -> Document:
        """단일 Path 를 Document 로 변환한다."""
        return load_document(path, self._max_chunk_tokens, self._overlap_tokens)

    def load_all_documents(self) -> List[Document]:
        """모든 파일을 Document 리스트로 반환한다."""
        return load_all_documents(
            self._input_dir, self._max_chunk_tokens, self._overlap_tokens
        )
