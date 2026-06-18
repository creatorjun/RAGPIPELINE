# src/refiner.py
from datetime import date
from typing import List, Optional
import re

from src.llm_client import LLMClient
from src.models import Document, DocumentChunk

_EXTRACT_SYSTEM = """You are a technical document editor. Extract only the relevant sections as instructed."""

_EXTRACT_USER_TEMPLATE = """From the document below, extract ONLY the sections related to the [{domains}] domain(s).

Rules:
1. Extract the header (H1~H3) and content of relevant sections verbatim.
2. Remove sections that are not related.
3. If no relevant sections exist, output only the word: NONE
4. Preserve Markdown formatting.
5. Output pure Markdown — do NOT wrap the output in code fences (```markdown, ```yaml, etc.).

[Document]
{content}"""

_REFINE_SYSTEM = """You are an expert technical editor who converts internal technical documents into Markdown optimized for RAG (Retrieval-Augmented Generation) search systems.

Output format rules:
1. The very first block MUST be a YAML front-matter block that starts with "---" and ends with "---".
2. Do NOT wrap the entire output in code fences (```markdown, ```yaml, etc.).
3. Output ONLY pure Markdown text.

Absolute prohibitions:
1. Do NOT add any content, numbers, dates, or version info that does not exist in the source document.
2. Do NOT modify code blocks, commands, or formulas from the source.
3. Do NOT change or omit factual relationships from the source.
4. Do NOT insert dates or numbers found inside [web ref ...] tags into the body text.
5. [web ref ...] tags are for citation only — never use their dates or numbers in the body.

Internal glossary:
- RCA: Root Cause Analysis
- SRE: Site Reliability Engineering
- MTTR: Mean Time To Recovery
- PROD: Production Environment"""

_REFINE_USER_TEMPLATE = """Convert the source document below into a RAG-optimized Markdown document.

YAML front-matter fields (ALL required):
- title: clear descriptive title (string)
- domain: {domains_yaml}
- doc_type: one of runbook | architecture | troubleshooting | policy | procedure | reference
- keywords: MUST include all of the following original keywords, then add more as needed: {required_keywords}
- summary: 1-2 sentence summary (string)
- source_file: {source_file}
- refined_at: {today}

Structure conversion rules:
1. Use exactly one H1 heading.
2. Reorganize content under independent H2 sections.
3. Remove citation/reference expressions.
4. Convert passive voice to active voice.
5. Make implicit knowledge explicit.
6. Remove duplicates.
7. Write out acronyms in full on first use.
8. Remove [web ref ...] tags from the body; do NOT add their dates or numbers to the body.

[Source Document]
{content}"""

_REFINE_PREFIX = "---\n"

_CODEFENCE_PATTERN = re.compile(
    r'^```[^\n]*\n(.*?)```\s*$',
    re.DOTALL,
)
_THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)
_KEYWORDS_FIELD_PATTERN = re.compile(
    r'(?m)^keywords:\s*\n((?:[ \t]*-[^\n]*\n)+)',
)


def _parse_llm_output(raw: str) -> str:
    cleaned = _THINK_PATTERN.sub('', raw).strip()

    m = _CODEFENCE_PATTERN.match(cleaned)
    if m:
        cleaned = m.group(1).strip()

    fm_pos = cleaned.find('---')
    if fm_pos > 0:
        cleaned = cleaned[fm_pos:]

    return cleaned


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

    def refine_chunk(
        self,
        chunk: DocumentChunk,
        domains: List[str],
        source_file: str,
        required_keywords: Optional[List[str]] = None,
    ) -> str:
        today = date.today().isoformat()
        domains_yaml = "[\n" + "".join(f"    - {d}\n" for d in domains) + "  ]"
        kw_hint = ", ".join(required_keywords) if required_keywords else "extract from source"
        user_prompt = _REFINE_USER_TEMPLATE.format(
            domains_yaml=domains_yaml,
            source_file=source_file,
            today=today,
            content=chunk.content,
            required_keywords=kw_hint,
        )
        raw = self._llm.generate(_REFINE_SYSTEM, user_prompt, prefix=_REFINE_PREFIX)
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
                cleaned_lines: List[str] = []
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
                    cleaned_lines.append(line)
                body_parts.append("\n".join(cleaned_lines))
            merged = head + "\n\n" + "\n\n".join(body_parts)

        if self._augmenter is not None:
            merged = self._augmenter.augment(merged, doc.source_file)

        return merged
