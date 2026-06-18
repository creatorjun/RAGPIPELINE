# src/domain_filter.py
import json
import re
from typing import List

from src.llm_client import LLMClient
from src.models import Document, FilterResult

_SYSTEM_PROMPT = """당신은 사내 기술 문서 분류 전문가입니다.
반드시 JSON 형식으로만 출력하세요. 다른 텍스트는 절대 출력하지 마세요."""

_USER_TEMPLATE = """아래 문서가 다음 3개 도메인 중 어디에 해당하는지 판별하세요.

[도메인 정의]
- build: 솔루션/시스템/인프라의 구축, 설치, 설계, 배포, 환경 구성
- maintenance: 운영 중인 시스템의 유지보수, 모니터링, 백업, 성능 튜닝, 정기점검
- incident: 장애 발생, 에러 대응, 복구, 롤백, 원인 분석(RCA), 인시던트 관리

[출력 형식 — JSON만 출력]
{{"domain": ["build"|"maintenance"|"incident"], "confidence": 0.0~1.0, "is_partial": true|false}}

- domain 배열에는 해당 도메인만 포함
- 해당 없으면 빈 배열 []
- is_partial: 문서 일부 섹션만 관련 있으면 true

[문서 내용]
{preview}

출력 예시:
{{"domain": ["build", "incident"], "confidence": 0.94, "is_partial": false}}"""

_PREVIEW_CHARS = 3000
_VALID_DOMAINS = {"build", "maintenance", "incident"}


def _extract_json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"JSON 파싱 실패: {raw!r}")


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
