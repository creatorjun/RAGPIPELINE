# src/rag/chunker.py
import re
import uuid
from pathlib import Path
from typing import List, Optional

import yaml

from src.rag.models import RagChunk

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_H2_SPLIT_RE = re.compile(r"(?m)^(?=## )")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    body = text[m.end():]
    return meta, body


def _extract_section_title(section_text: str) -> str:
    for line in section_text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            return line[3:].strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "(no title)"


def chunk_document(path: Path) -> List[RagChunk]:
    for enc in ("utf-8", "cp949"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    meta, body = _parse_frontmatter(text)
    source_file = meta.get("source_file", path.name)
    domains = meta.get("domain", [])
    doc_type = meta.get("doc_type", "")
    keywords = meta.get("keywords", [])
    summary = meta.get("summary", "")

    sections = [s for s in _H2_SPLIT_RE.split(body) if s.strip()]
    if not sections:
        sections = [body]

    chunks: List[RagChunk] = []
    for section in sections:
        title = _extract_section_title(section)
        chunk_id = str(uuid.uuid4())
        chunks.append(RagChunk(
            chunk_id=chunk_id,
            source_file=source_file,
            domain=domains if isinstance(domains, list) else [domains],
            section_title=title,
            content=section.strip(),
            doc_type=doc_type,
            keywords=keywords if isinstance(keywords, list) else [],
            summary=summary,
        ))
    return chunks


def load_all_chunks(output_dir: str) -> List[RagChunk]:
    base = Path(output_dir)
    chunks: List[RagChunk] = []
    for md_path in sorted(base.rglob("*.md")):
        chunks.extend(chunk_document(md_path))
    return chunks
