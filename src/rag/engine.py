# src/rag/engine.py
from pathlib import Path
from typing import List, Optional

from src.config import AppConfig
from src.llm_client import LLMClient
from src.rag.answer_generator import AnswerGenerator
from src.rag.bm25_index import Bm25Index
from src.rag.embedder import BgeEmbedder
from src.rag.models import RagAnswer
from src.rag.retriever import HybridRetriever
from src.rag.vector_store import QdrantStore


class RagEngine:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._embedder = BgeEmbedder(config.rag.embedding_model)
        self._vector_store = QdrantStore(
            path=config.rag.qdrant_path,
            collection_name=config.rag.collection_name,
        )
        self._bm25 = Bm25Index()
        bm25_path = config.rag.bm25_index_path
        if Path(bm25_path).exists():
            self._bm25.load(bm25_path)
        else:
            print(f"[WARN] BM25 인덱스 없음: {bm25_path} — embed.py 먼저 실행 필요")

        self._retriever = HybridRetriever(
            embedder=self._embedder,
            vector_store=self._vector_store,
            bm25_index=self._bm25,
            top_k_dense=config.rag.top_k_dense,
            top_k_bm25=config.rag.top_k_bm25,
            top_k_rerank=config.rag.top_k_rerank,
            rrf_k=config.rag.rrf_k,
            reranker_model=config.rag.reranker_model,
        )
        self._llm = LLMClient(
            base_url=config.model.base_url,
            api_key=config.model.api_key,
            model_name=config.model.model_name,
            max_tokens=config.rag.answer_max_tokens,
            temperature=config.model.temperature,
            top_p=config.model.top_p,
        )
        self._generator = AnswerGenerator(self._llm)

    def query(
        self,
        question: str,
        domain_filter: Optional[List[str]] = None,
    ) -> RagAnswer:
        results = self._retriever.retrieve(question, domain_filter=domain_filter)
        return self._generator.generate(question, results)
