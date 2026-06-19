# src/judge.py
from __future__ import annotations

from typing import Optional

from src.llm_utils import extract_last_json_object, strip_llm_noise
from src.models import JudgeVerdict
from src.ports import LLMClientPort


class JudgeError(RuntimeError):
    pass


_JUDGE_SYSTEM = """You are a brutally critical technical document reviewer.
Your sole purpose is to find flaws in a refined internal document.
You have NO prior context \u2014 evaluate ONLY what is given to you right now.

Evaluation criteria:
1. FAITHFULNESS  \u2014 Every factual claim in the refined document must be traceable
   to the original source. Any number, version, command, or procedure that
   appears in the refined text but NOT in the original is a hallucination.
2. COMPLETENESS  \u2014 All critical information from the original (steps, warnings,
   commands, configs, version numbers) must be present in the refined text.
   Omissions of safety-critical or operational details are hard failures.
3. STRUCTURE     \u2014 The document must begin with a valid YAML front-matter block
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


def _parse_verdict(raw: str) -> Optional[JudgeVerdict]:
    cleaned = strip_llm_noise(raw)
    data = extract_last_json_object(cleaned)
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
    def __init__(self, llm: LLMClientPort, max_tokens: int = 1024, judge_input_chars: int = 6000):
        self._llm = llm
        self._max_tokens = max_tokens
        self._judge_input_chars = judge_input_chars

    def judge(
        self,
        original_text: str,
        refined_text: str,
        source_file: str = "",
    ) -> JudgeVerdict:
        limit = self._judge_input_chars
        user_prompt = _USER_TEMPLATE.format(
            original=original_text[:limit],
            refined=refined_text[:limit],
        )
        try:
            raw = self._llm.generate_isolated(
                system_prompt=_JUDGE_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise JudgeError(f"Judge LLM \ud638\ucd9c \uc2e4\ud328 ({source_file}): {exc}") from exc

        verdict = _parse_verdict(raw)
        if verdict is None:
            raise JudgeError(
                f"Judge JSON \ud30c\uc2f1 \uc2e4\ud328 ({source_file}), raw={raw[:200]!r}"
            )
        return verdict
