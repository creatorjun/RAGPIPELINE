# src/rag/embedder.py
from typing import List


class BgeEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self._model_name = model_name
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from FlagEmbedding import BGEM3FlagModel
        self._model = BGEM3FlagModel(self._model_name, use_fp16=True)

    def embed(self, texts: List[str], batch_size: int = 12) -> List[List[float]]:
        self._ensure_loaded()
        output = self._model.encode(
            texts,
            batch_size=batch_size,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return output["dense_vecs"].tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.embed([text])[0]
