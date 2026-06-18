# src/refiner.py
from datetime import date
from typing import List, Optional
import re

from src.llm_client import LLMClient
from src.models import Document, DocumentChunk

_EXTRACT_SYSTEM = """당신은 기술 문서 편집자입니다. 지시에 따라 관련 섹션만 추출하세요."""

_EXTRACT_USER_TEMPLATE = """아래 문서에서 [{domains}] 도메인에 관련된 섹션만 추출하세요.

[추출 규칙]
1. 관련 섹션의 헤더(H1~H3)와 내용을 원문 그대로 추출
2. 관련 없는 섹션은 제거
3. 추출된 섹션이 없으면 "NONE"만 출력
4. 마크다운 형식 유지
5. 코드펜스(```markdown, ```yaml 등)로 감싸지 말고 순수 마크다운으로 출력

[원본 문서]
{content}"""

_REFINE_SYSTEM = """당신은 사내 기술 문서를 RAG 검색 시스템에 최적화된 Markdown으로 변환하는 전문 기술 편집자입니다.

[출력 형식 규칙]
1. 반드시 "---" 로 시작하는 YAML front-matter를 첫 번째 블록으로 출력
2. 코드펜스(```markdown, ```yaml 등)로 전체 출력을 감싸지 마세요
3. 순수 Markdown 텍스트로만 출력

[절대 금지 사항]
1. 원문에 없는 내용, 수치, 날짜, 버전 정보를 절대 추가하지 마세요
2. 원문의 코드 블록, 명령어, 수식을 변경하지 마세요
3. 원문의 사실 관계를 변경하거나 누락시키지 마세요
4. 웹 검색 참조 정보([웹 참조 ...])에 포함된 날짜, 연도, 버전 숫자를 본문에 삽입하지 마세요
5. [웹 참조 ...] 태그는 출처 표기 전용입니다. 해당 태그의 날짜 숫자를 본문에 사용하지 마세요

[사내 용어집]
- RCA: Root Cause Analysis (근본 원인 분석)
- SRE: Site Reliability Engineering
- MTTR: Mean Time To Recovery (평균 복구 시간)
- PROD: 운영 환경 (Production Environment)"""

_REFINE_USER_TEMPLATE = """다음 원본 문서를 RAG 최적화 Markdown으로 변환하세요.

[YAML front-matter 작성 규칙]
- title: 명확한 제목 (문자열)
- domain: {domains_yaml}
- doc_type: runbook|architecture|troubleshooting|policy|procedure|reference 중 택1
- keywords: 아래 원본 키워드를 반드시 모두 포함한 뒤 추가 가능 → {required_keywords}
- summary: 2문장 이내 (문자열)
- source_file: {source_file}
- refined_at: {today}

[구조 변환 규칙]
1. H1은 1개만 사용
2. H2는 독립 주제로 재구성
3. 참조 표현 제거
4. 수동태를 능동태로 변환
5. 암묵지를 명시적 문장으로 변환
6. 중복 제거
7. 약어 최초 등장 시 풀네임 병기
8. [웹 참조 ...] 태그는 본문에서 제거하되, 해당 태그에서 파생된 날짜·숫자를 본문에 추가하지 말 것

[원본 문서]
{content}

출력은 반드시 "---" 로 시작하며, 코드펜스로 감싸지 말것"""

_CODEFENCE_PATTERN = re.compile(
    r'^```[^\n]*\n(.*?)```\s*$',
    re.DOTALL,
)
_KEYWORDS_FIELD_PATTERN = re.compile(
    r'(?m)^keywords:\s*\n((?:[ \t]*-[^\n]*\n)+)',
)


def _parse_llm_output(raw: str) -> str:
    stripped = raw.strip()
    m = _CODEFENCE_PATTERN.match(stripped)
    if m:
        return m.group(1).strip()
    return stripped


def _extract_original_keywords(doc: Document) -> List[str]:
    fm_match = re.search(r'^---\n(.*?)\n---', doc.content, re.DOTALL)
    if not fm_match:
        return []
    fm_block = fm_match.group(1)
    kw_match = re.search(r'(?m)^keywords:\s*\n((?:[ \t]*-[^\n]*\n?)+)', fm_block)
    if not kw_match:
        return []
    lines = kw_match.group(1).splitlines()
    keywords = []
    for line in lines:
        kw = line.strip().lstrip('- ').strip()
        if kw:
            keywords.append(kw)
    return keywords


def _ensure_keywords_present(refined: str, required_keywords: List[str]) -> str:
    if not required_keywords:
        return refined
    m = _KEYWORDS_FIELD_PATTERN.search(refined)
    if not m:
        return refined
    existing_block = m.group(1)
    existing = [l.strip().lstrip('- ').strip() for l in existing_block.splitlines() if l.strip()]
    missing = [kw for kw in required_keywords if kw not in existing]
    if not missing:
        return refined
    extra_lines = ''.join(f'  - {kw}\n' for kw in missing)
    new_block = existing_block + extra_lines
    return refined[:m.start(1)] + new_block + refined[m.end(1):]


class Refiner:
    def __init__(self, llm: LLMClient, augmenter=None):
        self._llm = llm
        self._augmenter = augmenter

    def extract_domain_sections(self, doc: Document, domains: List[str]) -> str:
        domains_str = ", ".join(d.upper() for d in domains)
        user_prompt = _EXTRACT_USER_TEMPLATE.format(
            domains=domains_str,
            content=doc.content,
        )
        raw = self._llm.generate(_EXTRACT_SYSTEM, user_prompt)
        result = _parse_llm_output(raw)
        if result.upper() == "NONE":
            return ""
        return result

    def refine_chunk(self, chunk: DocumentChunk, domains: List[str], source_file: str, required_keywords: Optional[List[str]] = None) -> str:
        today = date.today().isoformat()
        domains_yaml = "[\n" + "".join(f"    - {d}\n" for d in domains) + "  ]"
        kw_hint = ", ".join(required_keywords) if required_keywords else "원본 문서에서 추출"
        user_prompt = _REFINE_USER_TEMPLATE.format(
            domains_yaml=domains_yaml,
            source_file=source_file,
            today=today,
            content=chunk.content,
            required_keywords=kw_hint,
        )
        raw = self._llm.generate(_REFINE_SYSTEM, user_prompt)
        result = _parse_llm_output(raw)
        if required_keywords:
            result = _ensure_keywords_present(result, required_keywords)
        return result

    def refine_document(self, doc: Document, domains: List[str]) -> str:
        required_keywords = _extract_original_keywords(doc)
        refined_chunks: List[str] = []
        for chunk in doc.chunks:
            refined = self.refine_chunk(chunk, domains, doc.source_file, required_keywords)
            refined_chunks.append(refined)

        if not refined_chunks:
            return ""

        if len(refined_chunks) == 1:
            merged = refined_chunks[0]
        else:
            head = refined_chunks[0]
            body_parts: List[str] = []
            for subsequent in refined_chunks[1:]:
                lines = subsequent.splitlines()
                skip = False
                cleaned: List[str] = []
                fence_count = 0
                for line in lines:
                    if line.strip() == "---":
                        fence_count += 1
                        if fence_count <= 2:
                            skip = True
                            continue
                        else:
                            skip = False
                            continue
                    if skip:
                        continue
                    cleaned.append(line)
                body_parts.append("\n".join(cleaned))
            merged = head + "\n\n" + "\n\n".join(body_parts)

        if self._augmenter is not None:
            merged = self._augmenter.augment(merged, doc.source_file)

        return merged
