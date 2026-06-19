# src/pipeline_runner.py
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

    def run(self, doc: Document) -> str:
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

    def _execute(self, doc: Document, log: dict, start: datetime) -> str:
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

        working_doc = self._maybe_extract(doc, filter_result, log)

        result, refined_text = self._run_refine_loop(doc, working_doc, filter_result, log, start)
        if result != "success":
            return result

        log["tokens_out"] = _token_count(refined_text) if refined_text else 0
        saved = self._io.save_output(refined_text, doc.source_file, filter_result.domains)
        log.update(output_files=saved, status="success", stage="done")
        log["duration_sec"] = (datetime.now(tz=timezone.utc) - start).total_seconds()
        self._io.write_log(log)
        return "success"

    def _run_refine_loop(
        self,
        doc: Document,
        working_doc: Document,
        filter_result: FilterResult,
        log: dict,
        start: datetime,
    ) -> tuple[str, str]:
        refined_text = ""
        last_verdict: Optional[JudgeVerdict] = None
        max_retries = self._cfg.pipeline.max_retries
        structure_failed = False

        for attempt in range(max_retries + 1):
            retry_hint: Optional[str] = (
                last_verdict.retry_hint
                if last_verdict and last_verdict.retry_hint != "none"
                else None
            )

            log["stage"] = "refine"
            try:
                refined_text = self._refiner.refine_document(
                    working_doc,
                    filter_result.domains,
                    retry_hint=retry_hint,
                    structure_failed=structure_failed,
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
                return "fail", ""

            if not refined_text.strip():
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 refine \uacb0\uacfc \ube48 \ubb38\uc790\uc5f4")
                    structure_failed = True
                    continue
                log.update(
                    status="fail",
                    error="refine \uacb0\uacfc \ube48 \ubb38\uc790\uc5f4",
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail", ""

            clean_text = strip_thinking(refined_text)

            log["stage"] = "structure_validate"
            struct_result = self._validator.validate(clean_text)
            if not struct_result.is_valid:
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 \uad6c\uc870 \uc624\ub958: {struct_result.errors}")
                    structure_failed = True
                    continue
                log.update(
                    status="fail",
                    error=str(struct_result.errors),
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail", ""

            structure_failed = False

            if self._judge is not None:
                judge_result, last_verdict = self._run_judge(
                    doc, clean_text, log, start, attempt, max_retries, last_verdict
                )
                if judge_result == "retry":
                    continue
                if judge_result == "fail":
                    return "fail", ""

            log["retry_count"] = attempt
            refined_text = clean_text
            break

        return "success", refined_text

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
                print("[JUDGE] on_judge_error=skip \u2014 \ud310\uc815 \uac74\ub108\ub700.")
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
            print(f"\n[WARN] {doc.source_file} \u2014 \uc784\uc2dc \ud30c\uc77c \ub85c\ub4dc \uc2e4\ud328, \uc6d0\ubcf8\uc73c\ub85c \ud3f4\ubc31: {exc}")
            return doc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
