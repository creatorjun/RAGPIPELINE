# src/domain_filter.py
import json
import re
from typing import List, Optional, Tuple

from src.llm_client import LLMClient
from src.models import Document, FilterResult

_SYSTEM_PROMPT = """You are an internal technical document classifier.
Output ONLY a valid JSON object. No other text."""

_USER_TEMPLATE = """Classify the document below into one or more of the following 3 domains.

[Domain definitions]
- build: construction, installation, deployment, design, infrastructure setup, environment configuration
- maintenance: operations, monitoring, backup, tuning, optimization, routine checks
- incident: failures, errors, recovery, rollback, RCA, incident response

[Output format]
{{
  "domains": ["<domain1>", "<domain2>"],
  "confidence": <0.0-1.0>,
  "is_partial": <true|false>
}}

Rules:
- domains: list of matching domains (can be multiple). If none match, return [].
- confidence: your overall classification confidence.
- is_partial: true if the document contains sections from multiple domains and should be split.

[Document]
{content}"""


def _extract_json_object(text: str) -> Optional[dict]:
    """JSON 객체를 중첩 brace를 고려해 안전하게 추출한다."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None


def _parse_filter_response(response: str) -> Tuple[List[str], float, bool]:
    think_cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
    data = _extract_json_object(think_cleaned)
    if data is None:
        return [], 0.0, False

    raw_domains = data.get('domains', [])
    if isinstance(raw_domains, str):
        raw_domains = [raw_domains]
    valid = {'build', 'maintenance', 'incident'}
    domains = [d for d in raw_domains if d in valid]

    confidence = float(data.get('confidence', 1.0))
    is_partial = bool(data.get('is_partial', False))
    return domains, confidence, is_partial


class DomainFilter:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def classify(self, doc: Document) -> FilterResult:
        preview = doc.content[:4000]
        user_prompt = _USER_TEMPLATE.format(content=preview)
        try:
            raw = self._llm.generate(_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            print(f"[WARN] DomainFilter LLM 호출 실패 ({doc.source_file}): {exc}")
            return FilterResult(domains=[], confidence=0.0, is_partial=False)

        domains, confidence, is_partial = _parse_filter_response(raw)
        return FilterResult(domains=domains, confidence=confidence, is_partial=is_partial)
