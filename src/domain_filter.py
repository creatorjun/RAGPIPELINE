# src/domain_filter.py
import json
import re
from typing import List

from src.llm_client import LLMClient
from src.models import Document, FilterResult

_SYSTEM_PROMPT = """You are an internal technical document classifier.
Output ONLY a valid JSON object. No other text."""

_USER_TEMPLATE = """Classify the document below into one or more of the following 3 domains.

[Domain definitions]
- build: construction, installation, design, deployment, or configuration of solutions/systems/infrastructure
- maintenance: maintenance, monitoring, backup, performance tuning, or regular inspection of running systems
- incident: failures, error response, recovery, rollback, root cause analysis (RCA), or incident management

[Output format — JSON only]
{{"domain": ["build"|"maintenance"|"incident"], "confidence": 0.0-1.0, "is_partial": true|false}}

- domain array: include only matching domains
- If none match: empty array []
- is_partial: true if only some sections of the document are relevant

[Document]
{preview}

Example output:
{{"domain": ["build", "incident"], "confidence": 0.94, "is_partial": false}}"""

_PREVIEW_CHARS = 3000
_VALID_DOMAINS = {"build", "maintenance", "incident"}
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def _extract_json(raw: str) -> dict:
    cleaned = _THINK_PATTERN.sub("", raw).strip()

    fence_m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fence_m:
        cleaned = fence_m.group(1).strip()

    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", cleaned):
        try:
            obj, _ = decoder.raw_decode(cleaned, m.start())
            return obj
        except json.JSONDecodeError:
            continue

    raise ValueError(f"JSON parsing failed: {raw!r}")


class DomainFilter:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def classify(self, doc: Document) -> FilterResult:
        preview = doc.content[:_PREVIEW_CHARS]
        user_prompt = _USER_TEMPLATE.format(preview=preview)
        raw = self._llm.generate(_SYSTEM_PROMPT, user_prompt)
        parsed = _extract_json(raw)

        domains: List[str] = [
            d.lower() for d in parsed.get("domain", [])
            if d.lower() in _VALID_DOMAINS
        ]
        confidence = float(parsed.get("confidence", 0.0))
        is_partial = bool(parsed.get("is_partial", False))

        return FilterResult(domains=domains, confidence=confidence, is_partial=is_partial)
