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


def extract_json_object(text: str) -> Optional[dict]:
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