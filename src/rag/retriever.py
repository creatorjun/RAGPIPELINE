# src/rag/retriever.py
from typing import Dict, List, Optional, Tuple

from src.rag.bm25_index import Bm25Index
from src.rag.embedder import BgeEmbedder
from src.rag.models import RagChunk, SearchResult
from src.rag.vector_store import QdrantStore


def _rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank + 1)


def _reciprocal_rank_fusion(
    dense_results: List[Tuple[dict, float]],
    bm25_results: List[Tuple[RagChunk, float]],
    rrf_k: int,
) -> List[Tuple[str, float, Optional[dict], Optional[RagChunk]]]:
    scores: Dict[str, float] = {}
    dense_map: Dict[str, dict] = {}
    bm25_map: Dict[str, RagChunk] = {}

    for rank, (payload, _) in enumerate(dense_results):
        cid = payload["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + _rrf_score(rank, rrf_k)
        dense_map[cid] = payload

    for rank, (chunk, _) in enumerate(bm25_results):
        cid = chunk.chunk_id
        scores[cid] = scores.get(cid, 0.0) + _rrf_score(rank, rrf_k)
        bm25_map[cid] = chunk

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        (cid, score, dense_map.get(cid), bm25_map.get(cid))
        for cid, score in ranked
    ]


def _payload_to_chunk(payload: dict) -> RagChunk:
    from src.rag.models import RagChunk
    return RagChunk(
        chunk_id=payload["chunk_id"],
        source_file=payload["source_file"],
        domain=payload.get("domain", []),
        section_title=payload.get("section_title", ""),
        content=payload.get("content", ""),
        doc_type=payload.get("doc_type", ""),
        keywords=payload.get("keywords", []),
        summary=payload.get("summary", ""),
    )


class HybridRetriever:
    def __init__(
        self,
        embedder: BgeEmbedder,
        vector_store: QdrantStore,
        bm25_index: Bm25Index,
        top_k_dense: int = 10,
        top_k_bm25: int = 10,
        top_k_rerank: int = 5,
        rrf_k: int = 60,
        reranker_model: str = "BAAI/bge-reranker-v2-m3",
    ):
        self._embedder = embedder
        self._vector_store = vector_store
        self._bm25 = bm25_index
        self._top_k_dense = top_k_dense
        self._top_k_bm25 = top_k_bm25
        self._top_k_rerank = top_k_rerank
        self._rrf_k = rrf_k
        self._reranker_model = reranker_model
        self._reranker = None

    def _ensure_reranker(self) -> None:
        if self._reranker is not None:
            return
        from FlagEmbedding import FlagReranker
        self._reranker = FlagReranker(self._reranker_model, use_fp16=True)

    def retrieve(
        self,
        query: str,
        domain_filter: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        query_vec = self._embedder.embed_query(query)

        dense_results = self._vector_store.search(
            query_vector=query_vec,
            top_k=self._top_k_dense,
            domain_filter=domain_filter,
        )
        bm25_results = self._bm25.search(query, top_k=self._top_k_bm25)

        if domain_filter:
            bm25_results = [
                (c, s) for c, s in bm25_results
                if any(d in domain_filter for d in c.domain)
            ]

        fused = _reciprocal_rank_fusion(dense_results, bm25_results, self._rrf_k)

        candidate_chunks: List[RagChunk] = []
        for cid, _, payload, bm25_chunk in fused:
            if payload:
                candidate_chunks.append(_payload_to_chunk(payload))
            elif bm25_chunk:
                candidate_chunks.append(bm25_chunk)

        if not candidate_chunks:
            return []

        self._ensure_reranker()
        pairs = [[query, c.content] for c in candidate_chunks]
        rerank_scores = self._reranker.compute_score(pairs, normalize=True)

        if isinstance(rerank_scores, float):
            rerank_scores = [rerank_scores]

        scored = sorted(
            zip(candidate_chunks, rerank_scores),
            key=lambda x: x[1],
            reverse=True,
        )[: self._top_k_rerank]

        return [
            SearchResult(chunk=chunk, score=float(score), rank=rank)
            for rank, (chunk, score) in enumerate(scored)
        ]
