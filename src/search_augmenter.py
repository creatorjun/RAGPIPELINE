# src/search_augmenter.py
from __future__ import annotations

import json
import re
from typing import List

from src.ports import LLMClientPort
from src.web_search import WebSearchClientPort

_JUDGE_SYSTEM = """당신은 기술 문서 업데이트 필요성을 판단하는 전문가입니다.
주어진 문서를 분석하여 실제 인터넷 검색이 필요한 쿼리만 JSON으로 출력하세요.

입력:
- JSON만, 다른 텍스트 없이 출력
- 형식: {"needs_search": true | false, "queries": ["query1", "query2"]}

[검색이 필요한 경우]
- 특정 버전, 날짜, 릴리스 정보가 없거나 누락된 경우
- 보안 취약점, CVE, 패치 정보가 없는 경우
- 권장 설정값이나 모범 사례가 없는 경우

[검색이 필요 없는 경우]
- 문서가 충분히 완결하다고 판단되는 경우
- 내부 프로세스, 정책만 다루는 경우
- 이미 충분한 수치와 스펙이 포함된 경우"""

_JUDGE_USER_TEMPLATE = """[문서 내용]
{content}

위 문서에 대해 인터넷 검색이 필요한지 판단하고 JSON으로만 출력하세요."""

_AUGMENT_SYSTEM = """당신은 기술 문서 편집자입니다.
웹 검색 결과를 참고하여 기존 정제 문서를 보강하거나 수정하세요.

[규칙]
1. 웹 검색 결과에서 실제로 유용한 정보만 반영하세요.
2. 검색 결과는 참고 자료일 뿐 \u2014 확인되지 않은 정보를 사실첫럼 기술하지 마세요.
3. 기존 문서의 YAML front-matter 구조는 반드시 유지하세요.
4. 검색 결과가 문서와 무관하면 원문 그대로 반환하세요.
5. Output ONLY the document. Do not include preamble, explanation, or thinking text.
6. Do NOT include any [web ref ...] or [\uc6f9 \ucc38\uc870 ...] annotation tags in the final output."""

_AUGMENT_USER_TEMPLATE = """[기존 정제 문서]
{refined}

{search_context}

위 검색 결과를 참고하여 문서를 검토하고, 유용한 정보가 있으면 반영하세요. 없으면 원문 그대로 반환하세요.
Output ONLY the document starting with ---"""

_THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)
_GENERIC_TAG_PATTERN = re.compile(r'<\|[^>]+>', re.DOTALL)
_CODEFENCE_PATTERN = re.compile(r'^```[^\n]*\n(.*?)```\s*$', re.DOTALL)
_WEB_REF_TAG_PATTERN = re.compile(r'\[(?:\uc6f9 \ucc38\uc870|web ref)[^\]]*\]', re.IGNORECASE)


def _clean_augment_output(raw: str, fallback: str) -> str:
    cleaned = _THINK_PATTERN.sub('', raw)
    cleaned = _GENERIC_TAG_PATTERN.sub('', cleaned)

    lines = cleaned.splitlines()
    trimmed: list[str] = []
    found = False
    for line in lines:
        if not found and line.strip() in ('', 'thought', 'model', 'user'):
            continue
        found = True
        trimmed.append(line)
    cleaned = '\n'.join(trimmed).strip()

    m = _CODEFENCE_PATTERN.match(cleaned)
    if m:
        cleaned = m.group(1).strip()

    idx = cleaned.find('---')
    if idx == -1:
        return fallback
    candidate = cleaned[idx:]
    if candidate.startswith('---\n') or candidate.startswith('---\r\n'):
        result = candidate.strip()
    else:
        next_idx = cleaned.find('---', idx + 3)
        if next_idx != -1:
            candidate2 = cleaned[next_idx:]
            if candidate2.startswith('---\n') or candidate2.startswith('---\r\n'):
                result = candidate2.strip()
            else:
                return fallback
        else:
            return fallback

    result = _WEB_REF_TAG_PATTERN.sub('', result)
    return result


def _extract_json_object(text: str) -> dict | None:
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
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class SearchAugmenter:
    def __init__(self, llm: LLMClientPort, searxng: WebSearchClientPort, enabled: bool = True):
        self._llm = llm
        self._searxng = searxng
        self._enabled = enabled

    def _parse_judge(self, response: str) -> tuple[bool, list[str]]:
        think_cleaned = _THINK_PATTERN.sub('', response)
        data = _extract_json_object(think_cleaned)
        if data is None:
            return False, []
        return bool(data.get('needs_search', False)), data.get('queries', [])

    def augment(self, refined_text: str, source_file: str) -> str:
        if not self._enabled:
            return refined_text

        judge_prompt = _JUDGE_USER_TEMPLATE.format(content=refined_text[:3000])
        try:
            judge_response = self._llm.generate(_JUDGE_SYSTEM, judge_prompt)
        except Exception as exc:
            print(f"[SEARCH WARN] judge 실패 ({source_file}): {exc}")
            return refined_text

        needs_search, queries = self._parse_judge(judge_response)

        if not needs_search or not queries:
            return refined_text

        all_results = []
        for query in queries[:3]:
            try:
                results = self._searxng.search(query)
                all_results.extend(results)
                print(f"\n[SEARCH] {source_file} \u2014 '{query}' ({len(results)}건)")
            except Exception as exc:
                print(f"\n[SEARCH WARN] {query} 실패: {exc}")

        if not all_results:
            return refined_text

        search_context = self._searxng.format_for_prompt(all_results)
        user_prompt = _AUGMENT_USER_TEMPLATE.format(
            refined=refined_text,
            search_context=search_context,
        )
        try:
            raw = self._llm.generate(_AUGMENT_SYSTEM, user_prompt)
        except Exception as exc:
            print(f"[SEARCH WARN] augment LLM 실패 ({source_file}): {exc}")
            return refined_text

        return _clean_augment_output(raw, fallback=refined_text)
