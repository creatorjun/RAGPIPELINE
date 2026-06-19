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
    """Judge LLM 동작 설정.

    Attributes:
        enabled:        Judge 활성화 여부.
        max_tokens:     Judge 응답 최대 토큰 수.
        on_error:       JudgeError 발생 시 정책.
                        ``"fail"`` (default) — 판정 실패를 문서 실패로 처리.
                        ``"skip"``           — 판정 실패를 무시하고 성공으로 진행.
        judge_input_chars: Judge 에 전달하는 원본/정제 문서 최대 문자 수.
                           BUG-C FIX: 하드코딩 6000 → 설정값으로 외부화.
    """
    enabled: bool = True
    max_tokens: int = 1024
    on_error: Literal["skip", "fail"] = "fail"
    judge_input_chars: int = Field(
        default=6000,
        ge=1000,
        description="Judge 에 전달할 원본/정제 문서의 최대 문자 수 (기본 6000)",
    )


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
