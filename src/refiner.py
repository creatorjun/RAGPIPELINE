# src/refiner.py
from datetime import date
from typing import List, Optional
import re

from src.llm_utils import strip_llm_noise
from src.models import Document, DocumentChunk
from src.ports import AugmenterPort, LLMClientPort

_EXTRACT_SYSTEM = """You are a technical document editor. Extract only the relevant sections as instructed."""

_EXTRACT_USER_TEMPLATE = """From the document below, extract ONLY the sections related to the [{domains}] domain(s).

Rules:
1. Extract the header (H1~H3) and content of relevant sections verbatim.
2. Remove sections that are not related.
3. If no relevant sections exist, output only the word: NONE
4. Preserve Markdown formatting.
5. Output pure Markdown - do NOT wrap the output in code fences.

[Document]
{content}"""

_REFINE_SYSTEM = """You are an expert technical editor converting internal documents into RAG-optimized Markdown.

Absolute prohibitions:
- Do NOT add content, numbers, dates, or versions not present in the source.
- Do NOT modify code blocks, commands, or formulas.
- Do NOT change or omit facts from the source.
- Do NOT use dates or numbers from [web ref ...] tags in the body text.

Internal glossary: RCA=Root Cause Analysis, SRE=Site Reliability Engineering, MTTR=Mean Time To Recovery, PROD=Production Environment"""

_REFINE_USER_TEMPLATE = """Convert the source document into a RAG-optimized Markdown document.

Required YAML front-matter fields:
  title: <descriptive title>
  domain: {domains_yaml}
  doc_type: <runbook|architecture|troubleshooting|policy|procedure|reference>
  keywords:
    - <keyword1>
    - <keyword2>  # MUST include: {required_keywords}
  summary: <1-2 sentence summary>
  source_file: {source_file}
  refined_at: {today}

Structure rules:
- One H1 heading only.
- Reorganize content under H2 sections (at least one H2 required).
- Remove citation expressions and [web ref ...] tags.
- Convert passive to active voice.
- Make implicit knowledge explicit.
- Remove duplicates.
- Write acronyms in full on first use.

Example of required output format:
---
title: Example Document Title
domain:
  - incident
doc_type: runbook
keywords:
  - keyword_a
  - keyword_b
summary: One or two sentence summary here.
source_file: example.md
refined_at: 2026-01-01
---

# Example Document Title

## Section One

Body text here.

## Section Two

More body text.
---END EXAMPLE---

Now convert the following source document. Output ONLY the converted document starting with ---. Do not include any preamble, explanation, or thinking text before the --- line.

{retry_instruction}[Source Document]
{content}"""

_CODEFENCE_PATTERN = re.compile(
    r'^```[^\n]*\n(.*?)```\s*$',
    re.DOTALL,
)
_KEYWORDS_FIELD_PATTERN = re.compile(
    r'(?m)^keywords:\s*\n((?:[ \t]*-[^\n]*\n)+)',
)
_FRONTMATTER_PATTERN = re.compile(r'^---\s*\n.*?\n---\s*\n', re.DOTALL)
_H1_PATTERN = re.compile(r'(?m)^# .+$')


def _strip_thinking_preamble(text: str) -> str:
    idx = text.find('---')
    if idx == -1:
        return text
    candidate = text[idx:]
    if candidate.startswith('---\n') or candidate.startswith('---\r\n'):
        return candidate
    next_idx = text.find('---', idx + 3)
    if next_idx != -1:
        candidate2 = text[next_idx:]
        if candidate2.startswith('---\n') or candidate2.startswith('---\r\n'):
            return candidate2
    return candidate


def _parse_llm_output(raw: str) -> str:
    """노이즈 제거를 llm_utils.strip_llm_noise 로 위임하고
    front-matter preamble 제거만 이 함수가 담당한다."""
    cleaned = strip_llm_noise(raw)
    cleaned = _strip_thinking_preamble(cleaned)
    return cleaned.strip()


def _extract_frontmatter_block(text: str) -> str:
    m = _FRONTMATTER_PATTERN.match(text.lstrip())
    return m.group(0) if m else ""


def _strip_frontmatter(text: str) -> str:
    stripped = text.lstrip()
    m = _FRONTMATTER_PATTERN.match(stripped)
    if m:
        return stripped[m.end():]
    return stripped


def _strip_first_h1(text: str) -> str:
    m = _H1_PATTERN.search(text)
    if m:
        return text[:m.start()] + text[m.end():].lstrip('\n')
    return text


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
    def __init__(self, llm: LLMClientPort, augmenter: Optional[AugmenterPort] = None):
        # DESIGN-B FIX: augmenter 타입을 AugmenterPort Protocol 로 명시
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

    def refine_chunk(
        self,
        chunk: DocumentChunk,
        domains: List[str],
        source_file: str,
        required_keywords: Optional[List[str]] = None,
        retry_hint: Optional[str] = None,
    ) -> str:
        today = date.today().isoformat()
        domains_yaml = "[\n" + "".join(f"    - {d}\n" for d in domains) + "  ]"
        kw_hint = ", ".join(required_keywords) if required_keywords else "extract from source"
        retry_instruction = (
            f"[PREVIOUS ATTEMPT FAILED \u2014 JUDGE FEEDBACK]\n{retry_hint}\n\nFix the above issue strictly.\n\n"
            if retry_hint
            else ""
        )
        user_prompt = _REFINE_USER_TEMPLATE.format(
            domains_yaml=domains_yaml,
            source_file=source_file,
            today=today,
            content=chunk.content,
            required_keywords=kw_hint,
            retry_instruction=retry_instruction,
        )
        raw = self._llm.generate(_REFINE_SYSTEM, user_prompt)
        result = _parse_llm_output(raw)
        if required_keywords:
            result = _ensure_keywords_present(result, required_keywords)
        return result

    def refine_document(
        self,
        doc: Document,
        domains: List[str],
        retry_hint: Optional[str] = None,
    ) -> str:
        required_keywords = _extract_original_keywords(doc)
        refined_chunks: List[str] = []
        for chunk in doc.chunks:
            refined = self.refine_chunk(
                chunk,
                domains,
                doc.source_file,
                required_keywords,
                retry_hint=retry_hint,
            )
            refined_chunks.append(refined)

        if not refined_chunks:
            return ""

        if len(refined_chunks) == 1:
            merged = refined_chunks[0]
        else:
            head = refined_chunks[0]
            frontmatter = _extract_frontmatter_block(head)
            head_body = _strip_frontmatter(head)
            body_parts: List[str] = [head_body.strip()]
            for subsequent in refined_chunks[1:]:
                body_only = _strip_frontmatter(subsequent)
                body_only = _strip_first_h1(body_only)
                body_parts.append(body_only.strip())
            merged = frontmatter + "\n".join(body_parts)

        if self._augmenter is not None:
            merged = self._augmenter.augment(merged, doc.source_file)

        return merged
