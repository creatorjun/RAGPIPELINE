# src/rag/bm25_index.py
import pickle
import re
from pathlib import Path
from typing import List, Tuple

from rank_bm25 import BM25Okapi

from src.rag.models import RagChunk

_TOKEN_RE = re.compile(r"[\w\uAC00-\uD7A3]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


class Bm25Index:
    def __init__(self):
        self._bm25: BM25Okapi = None
        self._chunks: List[RagChunk] = []

    def build(self, chunks: List[RagChunk]) -> None:
        self._chunks = chunks
        corpus = [_tokenize(c.content) for c in chunks]
        self._bm25 = BM25Okapi(corpus)

    def search(self, query: str, top_k: int = 10) -> List[Tuple[RagChunk, float]]:
        if self._bm25 is None:
            return []
        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [(self._chunks[i], float(scores[i])) for i in top_indices]

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"bm25": self._bm25, "chunks": self._chunks}, f)

    def load(self, path: str) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._bm25 = data["bm25"]
        self._chunks = data["chunks"]
