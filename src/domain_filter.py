# src/domain_filter.py
from typing import List, Optional, Set, Tuple

from src.llm_utils import extract_json_object, strip_llm_noise
from src.models import Document, FilterResult
from src.ports import LLMClientPort

_SYSTEM_PROMPT = """You are an internal technical document classifier.
Output ONLY a valid JSON object. No other text."""

_USER_TEMPLATE = """Classify the document below into one or more of the following domains.

[Domain definitions]
{domain_definitions}

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


def _parse_filter_response(
    response: str,
    valid_domains: Set[str],
) -> Tuple[List[str], float, bool]:
    cleaned = strip_llm_noise(response)
    data = extract_json_object(cleaned)
    if data is None:
        return [], 0.0, False

    raw_domains = data.get("domains", [])
    if isinstance(raw_domains, str):
        raw_domains = [raw_domains]
    domains = [d for d in raw_domains if d in valid_domains]

    confidence = float(data.get("confidence", 1.0))
    is_partial = bool(data.get("is_partial", False))
    return domains, confidence, is_partial


class DomainFilter:
    def __init__(self, llm: LLMClientPort, valid_domains: List[str]):
        self._llm = llm
        self._valid_domains: Set[str] = set(valid_domains)
        self._domain_definitions = "\n".join(
            f"- {d}: document content related to the '{d}' domain"
            for d in valid_domains
        )

    def classify(self, doc: Document) -> FilterResult:
        preview = doc.content[:4000]
        user_prompt = _USER_TEMPLATE.format(
            domain_definitions=self._domain_definitions,
            content=preview,
        )
        try:
            raw = self._llm.generate(_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            print(f"[WARN] DomainFilter LLM \ud638\ucd9c \uc2e4\ud328 ({doc.source_file}): {exc}")
            return FilterResult(domains=[], confidence=0.0, is_partial=False)

        domains, confidence, is_partial = _parse_filter_response(raw, self._valid_domains)
        return FilterResult(domains=domains, confidence=confidence, is_partial=is_partial)
