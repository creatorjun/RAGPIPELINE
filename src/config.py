# src/config.py
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    path: str
    max_tokens: int = 4096
    temperature: float = 0.1
    top_p: float = 0.9
    repetition_penalty: float = 1.1


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


class DomainConfig(BaseModel):
    name: str
    output_folder: str
    keywords: List[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    model: ModelConfig
    pipeline: PipelineConfig
    domains: List[DomainConfig]
    glossary_path: str = "./glossary.yaml"

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
