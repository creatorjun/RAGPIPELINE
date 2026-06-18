# src/rag/indexer.py
from pathlib import Path
from typing import List

from src.config import AppConfig
from src.rag.bm25_index import Bm25Index
from src.rag.chunker import load_all_chunks
from src.rag.embedder import BgeEmbedder
from src.rag.models import RagChunk
from src.rag.vector_store import QdrantStore

_EMBED_BATCH = 12


class RagIndexer:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._embedder = BgeEmbedder(config.rag.embedding_model)
        self._vector_store = QdrantStore(
            path=config.rag.qdrant_path,
            collection_name=config.rag.collection_name,
        )
        self._bm25 = Bm25Index()

    def run(self) -> None:
        print("[INFO] to_be 청크 로드 중...")
        chunks: List[RagChunk] = load_all_chunks(self._cfg.pipeline.output_dir)
        if not chunks:
            print("[WARN] 쫐크가 없습니다. Phase 2가 완료되었는지 확인하세요.")
            return

        print(f"[INFO] {len(chunks)}개 쫐크 로드 완료")

        print("[INFO] 임베딩 생성 중 (bge-m3)...")
        texts = [c.content for c in chunks]
        vectors: List[List[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH):
            batch = texts[i: i + _EMBED_BATCH]
            vectors.extend(self._embedder.embed(batch))
            done = min(i + _EMBED_BATCH, len(texts))
            print(f"\r  {done}/{len(texts)} 청크 임베딩 완료", end="", flush=True)
        print()

        print("[INFO] Qdrant 저장 중...")
        self._vector_store.upsert(chunks, vectors)
        print(f"[INFO] Qdrant 저장 완료 — 총 {self._vector_store.count()}건")

        print("[INFO] BM25 인덱스 빌드 중...")
        self._bm25.build(chunks)
        self._bm25.save(self._cfg.rag.bm25_index_path)
        print(f"[INFO] BM25 인덱스 저장 완료 — {self._cfg.rag.bm25_index_path}")

        print("[INFO] 인덱싱 완료")
