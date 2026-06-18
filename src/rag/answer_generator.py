# src/rag/answer_generator.py
from typing import List

from src.llm_client import LLMClient
from src.rag.models import RagAnswer, SearchResult

_SYSTEM_PROMPT = """당신은 사내 기술 문서를 기반으로 질문에 답변하는 AI 어시스턴트입니다.

[규칙]
1. 반드시 제공된 문서 내용만 근거로 답변하세요.
2. 문서에 없는 내용을 추측하거나 리한하지 마세요.
3. 참조한 문서의 제목을 [출처] 형식으로 명시하세요.
4. 정보가 부족하면 직접 안내하세요."""

_USER_TEMPLATE = """아래 문서들을 참조하여 질문에 답변하세요.

[참조 문서]
{context}

[질문]
{question}"""


def _build_context(results: List[SearchResult]) -> str:
    parts = []
    for r in results:
        header = f"[{r.rank + 1}] {r.chunk.section_title} ('{r.chunk.source_file}')"
        parts.append(f"{header}\n{r.chunk.content}")
    return "\n\n---\n\n".join(parts)


class AnswerGenerator:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def generate(self, question: str, results: List[SearchResult]) -> RagAnswer:
        if not results:
            return RagAnswer(
                question=question,
                answer="관련 문서를 찾지 못했습니다.",
                sources=[],
            )
        context = _build_context(results)
        user_prompt = _USER_TEMPLATE.format(context=context, question=question)
        answer = self._llm.generate(_SYSTEM_PROMPT, user_prompt)
        return RagAnswer(question=question, answer=answer, sources=results)
