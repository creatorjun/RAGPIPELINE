# src/validator.py
import re
from typing import List

from src.llm_utils import strip_llm_noise
from src.models import ValidationResult

_H2_PATTERN = re.compile(r"(?m)^## ")
_FRONTMATTER_CLOSE_PATTERN = re.compile(r"(?m)^---\s*$")
_REQUIRED_FIELDS = [
    "title:", "domain:", "doc_type:",
    "keywords:", "summary:", "source_file:", "refined_at:",
]


def strip_thinking(text: str) -> str:
    """하위 호환성 유지를 위한 alias — 내부는 llm_utils.strip_llm_noise 를 사용한다."""
    return strip_llm_noise(text)


def _extract_body(text: str) -> str:
    """YAML front-matter 를 제거하고 본문만 반환한다.

    BUG FIX: text.find('---', 3) 은 front-matter 내부의 '---' 값과 충돌할 수 있다.
    대신 줄 단위로 두 번째 독립적인 '---' 행을 찾는다.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return stripped

    # 첫 번째 '---' 이후부터 다음 '---' 단독 행 검색
    after_open = stripped[3:]  # '---' 바로 뒤 문자열
    m = _FRONTMATTER_CLOSE_PATTERN.search(after_open)
    if m is None:
        return stripped
    return after_open[m.end():]


class StructureValidator:
    """
    YAML front-matter 구조와 필수 필드 존재 여부만 검사한다.
    내용(content) 품질 판단은 JudgeLLM 이 전담한다.
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

        body = _extract_body(text)
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
