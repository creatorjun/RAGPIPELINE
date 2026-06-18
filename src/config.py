# src/config.py
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    base_url: str = "http://0.0.0.0:8000/v1"
    api_key: str = "sk-no-key-required"
    model_name: str = "mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit"
    max_tokens: int = 4096
    temperature: float = 0.1
    top_p: float = 0.9


class PipelineConfig(BaseModel):
    input_dir: str = "./as_is"
    output_dir: str = "./to_be"
    log_dir: str = "./logs"
    max_chunk_tokens: int = 8000
    overlap_tokens: int = 200
    max_retries: int = 2
    keyword_retention_threshold: float = 0.7
    min_sections: int = 1
    min_doc_length: int = 200
    resume: bool = True
    concurrency: int = 1


class DomainConfig(BaseModel):
    name: str
    output_folder: str
    keywords: List[str] = Field(default_factory=list)


class RagConfig(BaseModel):
    embedding_model: str = "BAAI/bge-m3"
    qdrant_path: str = "./qdrant_db"
    collection_name: str = "rag_docs"
    chunk_size_h2: bool = True
    top_k_dense: int = 10
    top_k_bm25: int = 10
    top_k_rerank: int = 5
    rrf_k: int = 60
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    answer_max_tokens: int = 2048
    bm25_index_path: str = "./qdrant_db/bm25_index.pkl"


class AppConfig(BaseModel):
    model: ModelConfig
    pipeline: PipelineConfig
    domains: List[DomainConfig]
    glossary_path: str = "./glossary.yaml"
    rag: RagConfig = Field(default_factory=RagConfig)

    @classmethod
    def from_yaml(cls, path: str = "config.yaml") -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(**raw)

    def get_domain_names(self) -> List[str]:
        return [d.name for d in self.domains]

    def get_output_folder(self, domain_name: str) -> Optional[str]:
        for d in self.domains:
            if d.name == domain_name:
                return d.output_folder
        return None
