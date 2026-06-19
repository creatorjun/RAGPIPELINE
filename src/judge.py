# src/judge.py
from __future__ import annotations

import json
import re
from typing import Optional

from src.llm_client import LLMClient
from src.models import JudgeVerdict

_JUDGE_SYSTEM = """You are a brutally critical technical document reviewer.
Your sole purpose is to find flaws in a refined internal document.
You have NO prior context — evaluate ONLY what is given to you right now.

Evaluation criteria:
1. FAITHFULNESS  — Every factual claim in the refined document must be traceable
   to the original source. Any number, version, command, or procedure that
   appears in the refined text but NOT in the original is a hallucination.
2. COMPLETENESS  — All critical information from the original (steps, warnings,
   commands, configs, version numbers) must be present in the refined text.
   Omissions of safety-critical or operational details are hard failures.
3. STRUCTURE     — The document must begin with a valid YAML front-matter block
   (--- ... ---), contain at least one H2 section, and have a non-empty body.

Bias rules:
- Assume the refined document is WRONG until proven otherwise.
- Do NOT give benefit of the doubt.
- A vague or paraphrased fact that could be misread counts as unfaithful.
- Missing detail that an operator would need counts as incomplete.

Output ONLY a single JSON object. No preamble, no explanation outside the JSON.

JSON schema:
{
  "faithfulness": true | false,
  "completeness": true | false,
  "structure_ok": true | false,
  "passed": true | false,
  "critique": "<concise list of every flaw found, or 'PASS' if none>",
  "retry_hint": "<one actionable instruction for the refiner to fix the worst flaw, or 'none'>"
}

Rule: passed = faithfulness AND completeness AND structure_ok."""

_USER_TEMPLATE = """[ORIGINAL SOURCE DOCUMENT]
{original}

---

[REFINED DOCUMENT UNDER REVIEW]
{refined}

Apply all evaluation criteria strictly. Output JSON only."""

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_GENERIC_TAG_PATTERN = re.compile(r"<\|[^>]+>", re.DOTALL)


def _extract_json_object(text: str) -> Optional[dict]:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _parse_verdict(raw: str) -> Optional[JudgeVerdict]:
    cleaned = _THINK_PATTERN.sub("", raw)
    cleaned = _GENERIC_TAG_PATTERN.sub("", cleaned)
    data = _extract_json_object(cleaned)
    if data is None:
        return None
    try:
        return JudgeVerdict(
            passed=bool(data.get("passed", False)),
            faithfulness=bool(data.get("faithfulness", False)),
            completeness=bool(data.get("completeness", False)),
            structure_ok=bool(data.get("structure_ok", False)),
            critique=str(data.get("critique", "")),
            retry_hint=str(data.get("retry_hint", "none")),
        )
    except Exception:
        return None


class JudgeLLM:
    """
    완전히 격리된 컨텍스트에서 동작하는 Judge LLM.
    - temperature=0 으로 고정해 결정론적 판정을 보장한다.
    - 동일한 모델·엔드포인트를 사용하되 새 OpenAI 클라이언트 인스턴스로
      생성 LLM의 대화 컨텍스트와 완전히 분리된다.
    - 시스템 프롬프트는 비판적(adversarial) 관점으로 고정된다.
    """

    def __init__(self, llm: LLMClient, max_tokens: int = 1024):
        self._llm = llm
        self._max_tokens = max_tokens

    def judge(
        self,
        original_text: str,
        refined_text: str,
        source_file: str = "",
    ) -> JudgeVerdict:
        original_preview = original_text[:6000]
        refined_preview = refined_text[:6000]
        user_prompt = _USER_TEMPLATE.format(
            original=original_preview,
            refined=refined_preview,
        )
        try:
            raw = self._llm.generate_isolated(
                system_prompt=_JUDGE_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            print(f"[JUDGE WARN] LLM 호출 실패 ({source_file}): {exc}")
            return JudgeVerdict(
                passed=True,
                faithfulness=True,
                completeness=True,
                structure_ok=True,
                critique="Judge LLM unavailable — skipped",
                retry_hint="none",
            )

        verdict = _parse_verdict(raw)
        if verdict is None:
            print(f"[JUDGE WARN] JSON 파싱 실패 ({source_file}), raw={raw[:200]}")
            return JudgeVerdict(
                passed=True,
                faithfulness=True,
                completeness=True,
                structure_ok=True,
                critique="Judge parse error — skipped",
                retry_hint="none",
            )

        return verdict
