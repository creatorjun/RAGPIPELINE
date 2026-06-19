# src/config.py
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    base_url: str = "http://0.0.0.0:8000/v1"
    api_key: str = "sk-no-key-required"
    model_name: str = "mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit"
    max_tokens: int = 4096
    temperature: float = 0.1
    top_p: float = 0.9


class ServerConfig(BaseModel):
    managed: bool = True
    model_path: Optional[str] = None
    host: str = "0.0.0.0"
    port: int = 8000
    backend: Literal["mlx_lm", "mlx_vllm", "vllm_mlx", "vllm"] = "vllm_mlx"
    trust_remote_code: bool = False
    extra_args: List[str] = Field(default_factory=list)
    startup_timeout: int = 300
    api_key: str = "sk-no-key-required"
    reasoning_parser: Optional[str] = None
    dtype: str = "auto"
    gpu_memory_utilization: float = Field(default=0.90, ge=0.1, le=1.0)
    tensor_parallel_size: int = Field(default=1, ge=1)
    max_model_len: Optional[int] = None


class LoggingConfig(BaseModel):
    llm_log_enabled: bool = True


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


class JudgeConfig(BaseModel):
    enabled: bool = True
    max_tokens: int = 1024
    on_error: Literal["skip", "fail"] = "fail"
    judge_input_chars: int = Field(default=6000, ge=1000)


class DomainConfig(BaseModel):
    name: str
    output_folder: str
    keywords: List[str] = Field(default_factory=list)


class SearchConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:8080"
    timeout: int = 10
    max_results: int = 5


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
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    pipeline: PipelineConfig
    domains: List[DomainConfig]
    glossary_path: str = "./glossary.yaml"
    search: SearchConfig = Field(default_factory=SearchConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)

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

    def resolved_model_path(self) -> str:
        return self.server.model_path or self.model.model_name

    def resolved_base_url(self) -> str:
        if self.server.managed:
            host = "127.0.0.1" if self.server.host == "0.0.0.0" else self.server.host
            return f"http://{host}:{self.server.port}/v1"
        return self.model.base_url
