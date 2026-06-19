# src/validator.py
import re
from typing import List

from src.models import ValidationResult

_THINK_TAG_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_GENERIC_TAG_PATTERN = re.compile(r"<\|[^>]+>", re.DOTALL)
_H2_PATTERN = re.compile(r"(?m)^## ")
_FRONTMATTER_OPEN = re.compile(r"^---\s*\n", re.MULTILINE)
_REQUIRED_FIELDS = [
    "title:", "domain:", "doc_type:",
    "keywords:", "summary:", "source_file:", "refined_at:",
]


def strip_thinking(text: str) -> str:
    cleaned = _THINK_TAG_PATTERN.sub("", text)
    cleaned = _GENERIC_TAG_PATTERN.sub("", cleaned)
    lines = cleaned.splitlines()
    result: List[str] = []
    found = False
    for line in lines:
        if not found and line.strip() in ("", "thought", "model", "user"):
            continue
        found = True
        result.append(line)
    return "\n".join(result).strip()


class StructureValidator:
    """
    YAML front-matter 구조와 필수 필드 존재 여부만 검사한다.
    내용(content) 품질 판단은 JudgeLLM이 전담한다.
    """

    def __init__(self, min_doc_length: int = 200, min_sections: int = 1):
        self._min_length = min_doc_length
        self._min_sections = min_sections

    def validate(self, refined_text: str) -> ValidationResult:
        errors: List[str] = []
        text = strip_thinking(refined_text)

        if not text.lstrip().startswith("---"):
            errors.append("YAML front-matter 없음")

        missing = [f.rstrip(":") for f in _REQUIRED_FIELDS if f not in text]
        if missing:
            errors.append(f"필수 필드 누락: {missing}")

        body_start = text.find("---", 3)
        body = text[body_start + 3:] if body_start != -1 else text
        if len(body.strip()) < self._min_length:
            errors.append(f"본문 길이 부족: {len(body.strip())}자 (최소 {self._min_length}자)")

        h2_count = len(_H2_PATTERN.findall(text))
        if h2_count < self._min_sections:
            errors.append(f"H2 섹션 부족: {h2_count}개 (최소 {self._min_sections}개)")

        return ValidationResult(
            is_valid=len(errors) == 0,
            keyword_retention_rate=1.0,
            errors=errors,
        )


Validator = StructureValidator
