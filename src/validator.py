# src/validator.py
import re
from typing import List

from src.models import ValidationResult

_NUM_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
_VER_PATTERN = re.compile(r"v?\d+\.\d+(?:\.\d+)?")
_CODE_PATTERN = re.compile(r"`[^`]{2,30}`")
_H2_PATTERN = re.compile(r"(?m)^## ")
_HALLUC_NUM_PATTERN = re.compile(r"\b\d{4,}\b")
_WEB_REF_PATTERN = re.compile(r"\[웹 참조[^\]]*\]")


def _normalize(text: str) -> str:
    return _WEB_REF_PATTERN.sub("", text)


def _extract_keywords(text: str) -> set:
    normalized = _normalize(text)
    keywords: set = set()
    keywords.update(_NUM_PATTERN.findall(normalized))
    keywords.update(_VER_PATTERN.findall(normalized))
    keywords.update(m.group() for m in _CODE_PATTERN.finditer(normalized))
    return keywords


def _has_frontmatter(text: str) -> bool:
    return text.lstrip().startswith("---")


def _check_required_fields(text: str) -> List[str]:
    missing: List[str] = []
    required = ["title:", "domain:", "doc_type:", "keywords:", "summary:", "source_file:", "refined_at:"]
    for field in required:
        if field not in text:
            missing.append(field.rstrip(":"))
    return missing


class Validator:
    def __init__(
        self,
        keyword_retention_threshold: float = 0.7,
        min_doc_length: int = 200,
        min_sections: int = 1,
    ):
        self._threshold = keyword_retention_threshold
        self._min_length = min_doc_length
        self._min_sections = min_sections

    def validate(self, original_text: str, refined_text: str) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not _has_frontmatter(refined_text):
            errors.append("YAML front-matter 없음")

        missing_fields = _check_required_fields(refined_text)
        if missing_fields:
            errors.append(f"필수 필드 누락: {missing_fields}")

        body_start = refined_text.find("---", 3)
        body = refined_text[body_start + 3:] if body_start != -1 else refined_text
        if len(body.strip()) < self._min_length:
            errors.append(f"본문 길이 부족: {len(body.strip())}자 (최소 {self._min_length}자)")

        h2_count = len(_H2_PATTERN.findall(refined_text))
        if h2_count < self._min_sections:
            errors.append(f"H2 섹션 부족: {h2_count}개 (최소 {self._min_sections}개)")

        original_keywords = _extract_keywords(original_text)
        refined_normalized = _normalize(refined_text)
        retained = sum(1 for kw in original_keywords if kw in refined_normalized)
        rate = retained / len(original_keywords) if original_keywords else 1.0

        if rate < self._threshold:
            errors.append(f"키워드 보존율 미달: {rate:.2%} (기준 {self._threshold:.0%})")

        orig_nums = set(_HALLUC_NUM_PATTERN.findall(_normalize(original_text)))
        refined_nums = set(_HALLUC_NUM_PATTERN.findall(refined_normalized))
        halluc_candidates = refined_nums - orig_nums
        if halluc_candidates:
            warnings.append(f"[경고] 원문에 없는 숫자 출현 (환각 의심): {halluc_candidates}")

        all_messages = errors + warnings
        return ValidationResult(
            is_valid=len(errors) == 0,
            keyword_retention_rate=rate,
            errors=all_messages,
        )

    def validate_strict(self, original_text: str, refined_text: str) -> ValidationResult:
        result = self.validate(original_text, refined_text)
        blocking = [e for e in result.errors if "경고" not in e]
        return ValidationResult(
            is_valid=len(blocking) == 0,
            keyword_retention_rate=result.keyword_retention_rate,
            errors=result.errors,
        )
