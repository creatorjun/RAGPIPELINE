# src/llm_utils.py
"""
공통 LLM 출력 후처리 유틸리티.

judge.py / search_augmenter.py / domain_filter.py 에 중복 정의되어 있던
`_extract_json_object`, `_strip_llm_noise` 를 단일 모듈로 통합한다.
"""
from __future__ import annotations

import json
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Noise-stripping
# ---------------------------------------------------------------------------

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_GENERIC_TAG_PATTERN = re.compile(r"<\|[^>]+>", re.DOTALL)
_CODEFENCE_PATTERN = re.compile(r"^```[^\n]*\n(.*?)```\s*$", re.DOTALL)
_WEB_REF_TAG_PATTERN = re.compile(
    r"\[(?:\uc6f9 \ucc38\uc870|web ref)[^\]]*\]", re.IGNORECASE
)


def strip_llm_noise(text: str) -> str:
    """LLM 응답에서 <think>...</think>, <|...|>, 코드 펜스 등 노이즈를 제거한다."""
    cleaned = _THINK_PATTERN.sub("", text)
    cleaned = _GENERIC_TAG_PATTERN.sub("", cleaned)

    lines = cleaned.splitlines()
    trimmed: list[str] = []
    found = False
    for line in lines:
        if not found and line.strip() in ("", "thought", "model", "user"):
            continue
        found = True
        trimmed.append(line)
    cleaned = "\n".join(trimmed).strip()

    m = _CODEFENCE_PATTERN.match(cleaned)
    if m:
        cleaned = m.group(1).strip()

    return cleaned


def strip_web_ref_tags(text: str) -> str:
    """[웹 참조 ...] / [web ref ...] 어노테이션 태그를 제거한다."""
    return _WEB_REF_TAG_PATTERN.sub("", text)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def extract_json_object(text: str) -> Optional[dict]:
    """텍스트에서 첫 번째 완결된 JSON 오브젝트를 파싱해 반환한다.

    LLM 이 JSON 앞뒤로 불필요한 텍스트를 출력하는 경우에도 동작하도록
    중괄호 depth 카운팅으로 경계를 찾는다.
    파싱 실패 시 None 을 반환한다.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    return None
    return None
