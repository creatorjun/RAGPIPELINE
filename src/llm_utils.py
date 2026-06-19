# src/llm_utils.py
from __future__ import annotations

import json
import re
from typing import Optional

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_GENERIC_TAG_PATTERN = re.compile(r"<\|[^>]+>", re.DOTALL)
_CODEFENCE_PATTERN = re.compile(r"^```[^\n]*\n(.*?)```\s*$", re.DOTALL)
_WEB_REF_TAG_PATTERN = re.compile(
    r"\[(?:\uc6f9 \ucc38\uc870|web ref)[^\]]*\]", re.IGNORECASE
)
_BARE_THINKING_PATTERNS = [
    re.compile(r"^Expert technical editor\..*?(?=^---)", re.DOTALL | re.MULTILINE),
    re.compile(r"^\*\s+\*.*?(?=^---)", re.DOTALL | re.MULTILINE),
    re.compile(r"^(?:Let me|I will|I'll|First,|Step \d|Now,|Okay,|Sure,|Here is|The document).*?(?=^---)", re.DOTALL | re.MULTILINE),
]


def strip_llm_noise(text: str) -> str:
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


def strip_bare_thinking(text: str) -> str:
    for pattern in _BARE_THINKING_PATTERNS:
        m = pattern.search(text)
        if m and m.start() == 0:
            text = text[m.end():]
            break
    return text.strip()


def strip_web_ref_tags(text: str) -> str:
    return _WEB_REF_TAG_PATTERN.sub("", text)


def _try_parse_json(text: str, start: int, end: int) -> Optional[dict]:
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def extract_json_object(text: str) -> Optional[dict]:
    """텍스트에서 첫 번째 완전한 JSON 객체를 추출한다."""
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
                return _try_parse_json(text, start, i)
    return None


def extract_last_json_object(text: str) -> Optional[dict]:
    """텍스트에서 마지막 완전한 JSON 객체를 추출한다.

    Gemma4 reasoning 모드에서 모델이 프롬프트 내 JSON 스키마를 복창(echo)한 뒤
    실제 응답 JSON을 뒤에 붙이는 패턴에 대응하기 위해 마지막 객체를 선택한다.
    """
    last_result: Optional[dict] = None
    search_from = 0
    while True:
        start = text.find("{", search_from)
        if start == -1:
            break
        depth = 0
        end = -1
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            break
        parsed = _try_parse_json(text, start, end)
        if parsed is not None:
            last_result = parsed
        search_from = end + 1
    return last_result
