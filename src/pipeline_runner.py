# src/pipeline_runner.py
"""
\ub2e8\uc77c \ubb38\uc11c \uc2e4\ud589 \ub85c\uc9c1.

PipelineOrchestrator.run() \uc5d0 \ub4e4\uc5b4\uc788\ub358 _process_document() \uc2e4\uc2b8\uc744
\ub3c5\ub9bd\uc801\uc73c\ub85c \ud14c\uc2a4\ud2b8 \uac00\ub2a5\ud55c \ud074\ub798\uc2a4\ub85c \ubd84\ub9ac\ud55c\ub2e4.

SRP \uc5ed\ud560: \ud558\ub098\uc758 Document \ub97c \ubc1b\uc544 \uc815\uc81c \u2192 \ud310\uc815 \u2192 \uc800\uc7a5 \ud30c\uc774\ud504\ub77c\uc778\uc744 \uc2e4\ud589.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.config import AppConfig
from src.domain_filter import DomainFilter
from src.judge import JudgeError, JudgeLLM
from src.llm_client import LLMEmptyResponseError
from src.loader import load_document
from src.models import Document, FilterResult, JudgeVerdict
from src.pipeline_io import PipelineIO
from src.refiner import Refiner
from src.validator import StructureValidator, strip_thinking

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _token_count(text: str) -> int:
        return len(_ENC.encode(text))
except ImportError:
    def _token_count(text: str) -> int:
        korean = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
        return korean + (len(text) - korean) // 4


class DocumentRunner:
    """\ub2e8\uc77c ``Document`` \uc2e4\ud589\uc744 \ub2f4\ub2f9\ud55c\ub2e4.

    Args:
        cfg:                  \uc5f1\ud50c\ub9ac\ucf00\uc774\uc158 \uc124\uc815
        io:                   I/O \ud5ec\ud37c (dir init, log, save)
        domain_filter:        \ub3c4\uba54\uc778 \ubd84\ub958\uae30
        refiner:              \ubb38\uc11c \uc815\uc81c\uae30
        structure_validator:  YAML front-matter / \uc139\uc158 \uad6c\uc870 \uac80\uc99d\uae30
        judge:                LLM \ud310\uc815\uae30 (\uc120\ud0dd \uc0ac\ud56d)
        on_judge_error:       JudgeError \ubc1c\uc0dd \uc2dc \uc815\ucc45.
                              ``"skip"`` \u2192 \ud310\uc815 \uc2e4\ud328\ub97c \ubb34\uc2dc\ud558\uace0 \uc131\uacf5 \uc2dc\ud0b5
                              ``"fail"`` \u2192 \ud310\uc815 \uc2e4\ud328\ub97c \uc2e4\ud328\ub85c \uc2e4\ud589 (default)
    """

    def __init__(
        self,
        cfg: AppConfig,
        io: PipelineIO,
        domain_filter: DomainFilter,
        refiner: Refiner,
        structure_validator: StructureValidator,
        judge: Optional[JudgeLLM] = None,
        on_judge_error: str = "fail",
    ):
        self._cfg = cfg
        self._io = io
        self._filter = domain_filter
        self._refiner = refiner
        self._validator = structure_validator
        self._judge = judge
        if on_judge_error not in ("skip", "fail"):
            raise ValueError("on_judge_error must be 'skip' or 'fail'")
        self._on_judge_error = on_judge_error

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, doc: Document) -> str:
        """\ub2e8\uc77c \ubb38\uc11c\ub97c \uc2e4\ud589\ud558\uace0 ``"success"`` / ``"skip"`` / ``"fail"`` \uc911 \ud558\ub098\ub97c \ubc18\ud658\ud55c\ub2e4."""
        start = datetime.now(tz=timezone.utc)
        log_entry: dict = {
            "timestamp": start.isoformat(),
            "source_file": doc.source_file,
            "stage": "start",
            "status": "processing",
            "domain": [],
            "output_files": [],
            "retry_count": 0,
            "tokens_in": _token_count(doc.content),
            "tokens_out": 0,
            "duration_sec": 0.0,
            "error": None,
            "judge": None,
        }
        self._io.write_log(log_entry)

        try:
            return self._execute(doc, log_entry, start)
        except Exception as exc:
            log_entry.update(
                status="fail",
                error=repr(exc),
                duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
            )
            self._io.write_log(log_entry)
            print(f"\n[ERROR] {doc.source_file} \u2014 {exc}")
            return "fail"

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _execute(self, doc: Document, log: dict, start: datetime) -> str:
        # ---- domain filter ----------------------------------------
        log["stage"] = "domain_filter"
        filter_result = self._filter.classify(doc)
        log["domain"] = filter_result.domains

        if not filter_result.domains:
            log.update(
                status="skip",
                duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
            )
            self._io.write_log(log)
            return "skip"

        if filter_result.confidence < 0.7:
            print(f"\n[WARN] {doc.source_file} \u2014 \ubd84\ub958 \uc2e0\ub8b0\ub3c4 \ub099\uc74c: {filter_result.confidence:.2f}")

        # ---- partial-document extraction --------------------------
        working_doc = self._maybe_extract(doc, filter_result, log)

        # ---- refine \u2192 validate \u2192 judge loop ----------------------
        refined_text = ""
        # BUG FIX #1: last_verdict \ub294 JudgeVerdict | None \uc774\uc5b4\uc57c \ud558\uba70,
        #             _run_judge \uc5d0\uc11c \uac31\uc2e0\ud55c \ud6c4 \ub97c \ub2f4\uc544\ub450\uae30 \uc704\ud574
        #             \ud074\ub798\uc2a4 \ub808\ubca8 _last_judge_verdict \ub97c \uc4f0\uc9c0 \uc54a\uace0
        #             \uc9c0\uc5ed \ubcc0\uc218\ub85c \uad00\ub9ac\ud55c\ub2e4.
        last_verdict: Optional[JudgeVerdict] = None
        max_retries = self._cfg.pipeline.max_retries

        for attempt in range(max_retries + 1):
            retry_hint: Optional[str] = (
                last_verdict.retry_hint
                if last_verdict and last_verdict.retry_hint != "none"
                else None
            )

            # refine
            log["stage"] = "refine"
            try:
                refined_text = self._refiner.refine_document(
                    working_doc,
                    filter_result.domains,
                    retry_hint=retry_hint,
                )
            except LLMEmptyResponseError as exc:
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 LLM \ube48 \uc751\ub2f5")
                    continue
                log.update(
                    status="fail",
                    error=str(exc),
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail"

            if not refined_text.strip():
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 refine \uacb0\uacfc \ube48 \ubb38\uc790\uc5f4")
                    continue
                log.update(
                    status="fail",
                    error="refine \uacb0\uacfc \ube48 \ubb38\uc790\uc5f4",
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail"

            clean_text = strip_thinking(refined_text)

            # structure validate
            log["stage"] = "structure_validate"
            struct_result = self._validator.validate(clean_text)
            if not struct_result.is_valid:
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 \uad6c\uc870 \uc624\ub958: {struct_result.errors}")
                    continue
                log.update(
                    status="fail",
                    error=str(struct_result.errors),
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail"

            # judge
            if self._judge is not None:
                # BUG FIX #2: _run_judge \ubc18\ud658\uac12(str)\uc744 JudgeVerdict\uc5d0 \ud560\ub2f9\ud558\ub358
                #             \uc798\ubabb\ub41c \ucf54\ub4dc\ub97c \uc81c\uac70. verdict \ub294
                #             _run_judge \ub0b4\ubd80\uc5d0\uc11c self._last_verdict \ub97c \ud1b5\ud574 \uc804\ub2ec.
                judge_result, last_verdict = self._run_judge(
                    doc, clean_text, log, start, attempt, max_retries, last_verdict
                )
                if judge_result == "retry":
                    continue
                if judge_result == "fail":
                    return "fail"
                # "ok" \u2192 fall through

            log["retry_count"] = attempt
            refined_text = clean_text
            break

        # ---- save -------------------------------------------------
        log["tokens_out"] = _token_count(refined_text) if refined_text else 0
        saved = self._io.save_output(refined_text, doc.source_file, filter_result.domains)
        log.update(output_files=saved, status="success", stage="done")
        log["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
        self._io.write_log(log)
        return "success"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_judge(
        self,
        doc: Document,
        clean_text: str,
        log: dict,
        start: datetime,
        attempt: int,
        max_retries: int,
        last_verdict: Optional[JudgeVerdict],
    ) -> tuple[str, Optional[JudgeVerdict]]:
        """Judge \ub97c \uc2e4\ud589\ud558\uace0 (result_str, verdict) \ud29c\ud50c\uc744 \ubc18\ud658\ud55c\ub2e4.

        result_str \uc740 ``"ok"`` / ``"retry"`` / ``"fail"`` \uc911 \ud558\ub098.
        verdict \ub294 \uc131\uacf5 \uc2dc JudgeVerdict, \uc2e4\ud328/skip \uc2dc \uc774\uc804 verdict \uadf8\ub300\ub85c.

        JudgeError \uc2dc ``on_judge_error`` \uc815\ucc45\uc5d0 \ub530\ub77c:
          - ``"skip"`` \u2192 ``("ok", last_verdict)`` (\uc2e4\ud328 \ubb34\uc2dc)
          - ``"fail"`` \u2192 ``("fail", last_verdict)`` (\ubcf4\uc218\uc801 \ub514\ud3f4\ud2b8)
        """
        log["stage"] = "judge"
        assert self._judge is not None

        try:
            verdict = self._judge.judge(
                original_text=doc.content,
                refined_text=clean_text,
                source_file=doc.source_file,
            )
        except JudgeError as exc:
            print(f"[JUDGE ERROR] {doc.source_file}: {exc}")
            if self._on_judge_error == "skip":
                print("[JUDGE] on_judge_error=skip \u2014 \ud310\uc815 \uac74\ub108\ub6f0\ub2e4.")
                return "ok", last_verdict
            log.update(
                status="fail",
                error=f"JudgeError: {exc}",
                duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
            )
            self._io.write_log(log)
            return "fail", last_verdict

        log["judge"] = {
            "passed": verdict.passed,
            "faithfulness": verdict.faithfulness,
            "completeness": verdict.completeness,
            "structure_ok": verdict.structure_ok,
            "critique": verdict.critique,
            "retry_hint": verdict.retry_hint,
            "attempt": attempt,
        }
        self._io.write_log(log)

        if not verdict.passed:
            if attempt < max_retries:
                print(
                    f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file}\n"
                    f"  Judge critique: {verdict.critique}\n"
                    f"  Retry hint: {verdict.retry_hint}"
                )
                return "retry", verdict
            log.update(
                status="fail",
                error=f"Judge \ubd88\ud569\uaca9: {verdict.critique}",
                duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
            )
            self._io.write_log(log)
            return "fail", verdict

        return "ok", verdict

    def _maybe_extract(
        self,
        doc: Document,
        filter_result: FilterResult,
        log: dict,
    ) -> Document:
        """is_partial \uc2dc \ub3c4\uba54\uc778 \uad00\ub828 \uc139\uc158\ub9cc \ucd94\ucd9c\ud55c Document \ub97c \ubc18\ud658, \uc2e4\ud328 \uc2dc \uc6d0\ubcf8 \ubc18\ud658.

        BUG FIX #3: \uc784\uc2dc \ud30c\uc77c os.unlink \uc2e4\ud328 \uc2dc(Windows \ub4f1) \uc608\uc678\ub97c
                    \uc2a4\uc640\ub85c\uc9c0 \uc548\ud558\uace0 \uc6d0\ubcf8 doc \ub97c \ud3f4\ubc31\uc73c\ub85c \ubc18\ud658\ud55c\ub2e4.
        BUG FIX #4: load_document \uc2e4\ud328 \uc2dc\ub3c4 \uc624\ub958\uac00 \uc704\ub85c \uc804\ud30c\ub418\uc9c0 \uc54a\uac8c
                    except \ube14\ub85d\uc5d0\uc11c \uc6d0\ubcf8 doc \ud3f4\ubc31.
        """
        if not filter_result.is_partial:
            return doc

        log["stage"] = "extract"
        extracted = self._refiner.extract_domain_sections(doc, filter_result.domains)
        if not extracted:
            print(f"\n[WARN] {doc.source_file} \u2014 \uc139\uc158 \ucd94\ucd9c \uacb0\uacfc \uc5c6\uc74c, \uc6d0\ubcf8\uc73c\ub85c \ud3f4\ubc31")
            return doc

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(extracted)
                tmp_path = tmp.name
            working = load_document(
                Path(tmp_path),
                self._cfg.pipeline.max_chunk_tokens,
                self._cfg.pipeline.overlap_tokens,
            )
            working.source_file = doc.source_file
            return working
        except Exception as exc:
            # BUG FIX #4: load_document \uc2e4\ud328 \uc2dc \uc6d0\ubcf8\uc73c\ub85c \ud3f4\ubc31 (\uc624\ub958 \uc804\ud30c \uad6c\uc81c)
            print(f"\n[WARN] {doc.source_file} \u2014 \uc784\uc2dc \ud30c\uc77c \ub85c\ub4dc \uc2e4\ud328, \uc6d0\ubcf8\uc73c\ub85c \ud3f4\ubc31: {exc}")
            return doc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    # BUG FIX #3: Windows \ud30c\uc77c \uc7a0\uae08 \ub4f1 unlink \uc2e4\ud328 \ud5c8\uc6a9
                    pass
