# src/refiner.py
from datetime import date
from typing import List, Optional

from src.llm_client import LLMClient
from src.models import Document, DocumentChunk

_EXTRACT_SYSTEM = """당신은 기술 문서 편집자입니다. 지시에 따라 관련 섹션만 추출하세요."""

_EXTRACT_USER_TEMPLATE = """아래 문서에서 [{domains}] 도메인에 관련된 섹션만 추출하세요.

[추출 규칙]
1. 관련 섹션의 헤더(H1~H3)와 내용을 원문 그대로 추출
2. 관련 없는 섹션은 제거
3. 추출된 섹션이 없으면 "NONE"만 출력
4. 마크다운 형식 유지

[원본 문서]
{content}"""

_REFINE_SYSTEM = """당신은 사내 기술 문서를 RAG 검색 시스템에 최적화된 Markdown으로 변환하는 전문 기술 편집자입니다.

[절대 금지 사항]
1. 원문에 없는 내용, 수치, 날짜, 버전 정보를 절대 추가하지 마세요.
2. 원문의 코드 블록, 명령어, 수식을 변경하지 마세요.
3. 원문의 사실 관계를 변경하거나 누락시키지 마세요.

[사내 용어집]
- RCA: Root Cause Analysis (근본 원인 분석)
- SRE: Site Reliability Engineering
- MTTR: Mean Time To Recovery (평균 복구 시간)
- PROD: 운영 환경 (Production Environment)"""

_REFINE_USER_TEMPLATE = """다음 원본 문서를 RAG 최적화 Markdown으로 변환하세요.

[YAML front-matter 작성 규칙]
- title: 명확한 제목
- domain: 도메인 배열 {domains}
- doc_type: runbook|architecture|troubleshooting|policy|procedure|reference 중 택1
- keywords: 5~10개
- summary: 2문장 이내
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

[원본 문서]
{content}

출력은 반드시 "---" 로 시작"""


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
        result = self._llm.generate(_EXTRACT_SYSTEM, user_prompt)
        if result.strip().upper() == "NONE":
            return ""
        return result

    def refine_chunk(self, chunk: DocumentChunk, domains: List[str], source_file: str) -> str:
        today = date.today().isoformat()
        domains_str = str(domains)
        user_prompt = _REFINE_USER_TEMPLATE.format(
            domains=domains_str,
            source_file=source_file,
            today=today,
            content=chunk.content,
        )
        return self._llm.generate(_REFINE_SYSTEM, user_prompt)

    def refine_document(self, doc: Document, domains: List[str]) -> str:
        refined_chunks: List[str] = []
        for chunk in doc.chunks:
            refined = self.refine_chunk(chunk, domains, doc.source_file)
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
