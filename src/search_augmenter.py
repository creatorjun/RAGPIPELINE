# src/search_augmenter.py
from __future__ import annotations

import json
import re
from typing import List, Optional

from src.llm_client import LLMClient
from src.web_search import SearXNGClient

_JUDGE_SYSTEM = """당신은 기술 문서 업데이트 필요성을 판단하는 전문가입니다.
주어진 문서를 분석하여 실제 인터넷 검색이 필요한 쿼리만 JSON으로 출력하세요.

출력 형식 (JSON만, 다른 텍스트 없이):
{
  "needs_search": true | false,
  "queries": ["query1", "query2"]
}

[검색이 필요한 경우]
- 특정 버전, 날짜, 릴리즈 정보가 없거나 누락된 경우
- 보안 취약점, CVE, 패치 정보가 없는 경우
- 권장 설정값이나 모범 사례가 없는 경우
- 외부 툴, API, 서비스의 최신 상태를 확인해야 하는 경우

[검색이 필요 없는 경우]
- 문서가 충분히 완결하다고 판단되는 경우
- 내부 프로세스, 정책만 다루는 경우 (와부로 검색해도 무의미)
- 이미 충분한 수치와 스펙이 포함된 경우"""

_JUDGE_USER_TEMPLATE = """[\ubb38\uc11c \ub0b4\uc6a9]
{content}

\uc704 \ubb38\uc11c\uc5d0 \ub300\ud574 \uc778\ud130\ub137 \uac80\uc0c9\uc774 \ud544\uc694\ud55c\uc9c0 \ud310\ub2e8\ud558\uace0 JSON\uc73c\ub85c\ub9cc \ucd9c\ub825\ud558\uc138\uc694."""

_AUGMENT_SYSTEM = """당신은 기술 문서 편집자입니다.
웹 검색 결과를 참고하여 기존 정제 문서를 보강하거나 수정하세요.

[규칙]
1. 웹 검색 결과에서 실제로 유용한 정보만 반영하세요.
2. 검색 결과는 참고 자료일 뿐 — 확인되지 않은 정보를 사실처럼 기술하지 마세요.
3. 추가/수정된 내용에는 검색 날짜를 '[\uc6f9 \ucc38\uc870 YYYY-MM-DD]' 형식으로 주석 표시하세요.
4. 기존 문서의 YAML front-matter 구조는 유지하세요.
5. 검색 결과가 문서와 무관하면 원문 그대로 반환하세요."""

_AUGMENT_USER_TEMPLATE = """[\uae30\uc874 \uc815\uc81c \ubb38\uc11c]
{refined}

{search_context}

\uc704 \uac80\uc0c9 \uacb0\uacfc\ub97c \ucc38\uace0\ud558\uc5ec \ubb38\uc11c\ub97c \uac80\ud1a0\ud558\uace0, \uc720\uc6a9\ud55c \uc815\ubcf4\uac00 \uc788\uc73c\uba74 \ubc18\uc601\ud558\uc138\uc694. \uc5c6\uc73c\uba74 \uc6d0\ubb38 \uadf8\ub300\ub85c \ubc18\ud658\ud558\uc138\uc694."""


class SearchAugmenter:
    def __init__(self, llm: LLMClient, searxng: SearXNGClient, enabled: bool = True):
        self._llm = llm
        self._searxng = searxng
        self._enabled = enabled

    def _parse_judge(self, response: str) -> tuple[bool, List[str]]:
        try:
            match = re.search(r"\{.*?\}", response, re.DOTALL)
            if not match:
                return False, []
            data = json.loads(match.group())
            return bool(data.get("needs_search", False)), data.get("queries", [])
        except Exception:
            return False, []

    def augment(self, refined_text: str, source_file: str) -> str:
        if not self._enabled:
            return refined_text

        judge_prompt = _JUDGE_USER_TEMPLATE.format(content=refined_text[:3000])
        judge_response = self._llm.generate(_JUDGE_SYSTEM, judge_prompt)
        needs_search, queries = self._parse_judge(judge_response)

        if not needs_search or not queries:
            return refined_text

        all_results = []
        for query in queries[:3]:
            try:
                results = self._searxng.search(query)
                all_results.extend(results)
                print(f"\n[SEARCH] {source_file} \u2014 '{query}' ({len(results)}\uac74)")
            except Exception as exc:
                print(f"\n[SEARCH WARN] {query} \uc2e4\ud328: {exc}")

        if not all_results:
            return refined_text

        search_context = self._searxng.format_for_prompt(all_results)
        user_prompt = _AUGMENT_USER_TEMPLATE.format(
            refined=refined_text,
            search_context=search_context,
        )
        augmented = self._llm.generate(_AUGMENT_SYSTEM, user_prompt)
        return augmented if augmented.strip() else refined_text
