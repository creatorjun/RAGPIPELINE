# src/rag/vector_store.py
from pathlib import Path
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from src.rag.models import RagChunk

_VECTOR_DIM = 1024


class QdrantStore:
    def __init__(self, path: str, collection_name: str):
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=path)
        self._collection = collection_name

    def _ensure_collection(self) -> None:
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=_VECTOR_DIM, distance=Distance.COSINE),
            )

    def upsert(self, chunks: List[RagChunk], vectors: List[List[float]]) -> None:
        self._ensure_collection()
        points = [
            PointStruct(
                id=idx,
                vector=vec,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "source_file": chunk.source_file,
                    "domain": chunk.domain,
                    "section_title": chunk.section_title,
                    "content": chunk.content,
                    "doc_type": chunk.doc_type,
                    "keywords": chunk.keywords,
                    "summary": chunk.summary,
                },
            )
            for idx, (chunk, vec) in enumerate(zip(chunks, vectors))
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        domain_filter: Optional[List[str]] = None,
    ) -> List[tuple]:
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        query_filter = None
        if domain_filter:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="domain",
                        match=MatchAny(any=domain_filter),
                    )
                ]
            )
        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        return [(r.payload, r.score) for r in results]

    def count(self) -> int:
        return self._client.count(collection_name=self._collection).count
