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
    """LLM \uc11c\ubc84 \uc790\ub3d9 \uae30\ub3d9 \uc124\uc815.

    Attributes:
        managed:          True \uc774\uba74 run.py \uc2e4\ud589 \uc2dc \uc11c\ubc84\ub97c \uc790\ub3d9 \uae30\ub3d9/\uc885\ub8cc.
                          False \uc774\uba74 \uc678\ubd80\uc5d0\uc11c \uc774\ubbf8 \ub5a0 \uc788\ub294 \uc11c\ubc84\ub97c \uac00\uc815\ud569\ub2c8\ub2e4.
        model_path:       HuggingFace repo ID \ub610\ub294 \ub85c\ucef9 \ub514\ub809\ud130\ub9ac.
                          \uc9c0\uc815\ud558\uc9c0 \uc54a\uc73c\uba74 model.model_name \uc744 \uc0ac\uc6a9\ud569\ub2c8\ub2e4.
        host:             \ub9ac\uc2a4\ub2dd \ud638\uc2a4\ud2b8 (\uae30\ubcf8 0.0.0.0)
        port:             \ub9ac\uc2a4\ub2dd \ud3ec\ud2b8 (\uae30\ubcf8 8000)
        backend:          ``mlx_lm`` (\uae30\ubcf8) \ub610\ub294 ``mlx_vllm``
        trust_remote_code: \uc6d0\uaca9 \ucf54\ub4dc \uc2e4\ud589 \ud5c8\uc6a9
        extra_args:       \uc11c\ubc84 CLI \uc5d0 \ucd94\uac00\ud560 \uc778\uc218 \ubaa9\ub85d
        startup_timeout:  \uc900\ube44 \ub300\uae30 \uc81c\ud55c (\ucd08, \uae30\ubcf8 180)
    """
    managed: bool = True
    model_path: Optional[str] = None          # None \u2192 model.model_name \uc0ac\uc6a9
    host: str = "0.0.0.0"
    port: int = 8000
    backend: Literal["mlx_lm", "mlx_vllm"] = "mlx_lm"
    trust_remote_code: bool = False
    extra_args: List[str] = Field(default_factory=list)
    startup_timeout: int = 180


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
    """Judge LLM \ub3d9\uc791 \uc124\uc815.

    Attributes:
        enabled:           Judge \ud65c\uc131\ud654 \uc5ec\ubd80.
        max_tokens:        Judge \uc751\ub2f5 \ucd5c\ub300 \ud1a0\ud070 \uc218.
        on_error:          JudgeError \ubc1c\uc0dd \uc2dc \uc815\ucc45.
                           ``"fail"`` (default) \u2014 \ud310\uc815 \uc2e4\ud328\ub97c \ubb38\uc11c \uc2e4\ud328\ub85c \ucc98\ub9ac.
                           ``"skip"``           \u2014 \ud310\uc815 \uc2e4\ud328\ub97c \ubb34\uc2dc\ud558\uace0 \uc131\uacf5\uc73c\ub85c \uc9c4\ud589.
        judge_input_chars: Judge \uc5d0 \uc804\ub2ec\ud558\ub294 \uc6d0\ubcf8/\uc815\uc81c \ubb38\uc11c \ucd5c\ub300 \ubb38\uc790 \uc218.
    """
    enabled: bool = True
    max_tokens: int = 1024
    on_error: Literal["skip", "fail"] = "fail"
    judge_input_chars: int = Field(
        default=6000,
        ge=1000,
        description="Judge \uc5d0 \uc804\ub2ec\ud560 \uc6d0\ubcf8/\uc815\uc81c \ubb38\uc11c\uc758 \ucd5c\ub300 \ubb38\uc790 \uc218 (\uae30\ubcf8 6000)",
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
    server: ServerConfig = Field(default_factory=ServerConfig)
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
        """server.model_path \uac00 \uc5c6\uc73c\uba74 model.model_name \uc744 \ubc18\ud658\ud55c\ub2e4."""
        return self.server.model_path or self.model.model_name

    def resolved_base_url(self) -> str:
        """LLMClient \uc5d0 \uc8fc\uc785\ud560 base_url.

        server.managed=True \uc774\uba74 127.0.0.1:{server.port}/v1 \uc744 \uc0ac\uc6a9\ud558\uace0
        managed=False \uc774\uba74 model.base_url \uc744 \uadf8\ub300\ub85c \uc0ac\uc6a9\ud55c\ub2e4.
        """
        if self.server.managed:
            host = "127.0.0.1" if self.server.host == "0.0.0.0" else self.server.host
            return f"http://{host}:{self.server.port}/v1"
        return self.model.base_url
