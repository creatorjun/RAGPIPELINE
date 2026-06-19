# src/pipeline_runner.py
"""
단일 문서 실행 로직.

PipelineOrchestrator.run() 에 들어있던 _process_document() 실행을
독립적으로 테스트 가능한 클래스로 분리한다.

SRP 역할: 하나의 Document 를 받아 정제 → 판정 → 저장 파이프라인을 실행.
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
    """단일 ``Document`` 실행을 담당한다.

    Args:
        cfg:                  애플리케이션 설정
        io:                   I/O 헬퍼 (dir init, log, save)
        domain_filter:        도메인 분류기
        refiner:              문서 정제기
        structure_validator:  YAML front-matter / 섹션 구조 검증기
        judge:                LLM 판정기 (선택 사항)
        on_judge_error:       JudgeError 발생 시 정책.
                              ``"skip"`` → 판정 실패를 무시하고 성공 처리
                              ``"fail"`` → 판정 실패를 실패로 처리 (default)
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
        """단일 문서를 실행하고 ``"success"`` / ``"skip"`` / ``"fail"`` 중 하나를 반환한다."""
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
            print(f"\n[WARN] {doc.source_file} \u2014 분류 신뢰도 낮음: {filter_result.confidence:.2f}")

        # ---- partial-document extraction --------------------------
        working_doc = self._maybe_extract(doc, filter_result, log)

        # DESIGN-C FIX: refine → validate → judge 루프를 별도 메서드로 분리
        result, refined_text = self._run_refine_loop(doc, working_doc, filter_result, log, start)
        if result != "success":
            return result

        # ---- save -------------------------------------------------
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
        """refine → validate → judge 루프를 실행한다.

        Returns:
            (status, refined_text) 튜플.
            status 는 ``"success"`` / ``"fail"`` 중 하나.
        """
        refined_text = ""
        last_verdict: Optional[JudgeVerdict] = None
        max_retries = self._cfg.pipeline.max_retries

        for attempt in range(max_retries + 1):
            retry_hint: Optional[str] = (
                last_verdict.retry_hint
                if last_verdict and last_verdict.retry_hint != "none"
                else None
            )

            # -- refine ---------------------------------------------
            log["stage"] = "refine"
            try:
                refined_text = self._refiner.refine_document(
                    working_doc,
                    filter_result.domains,
                    retry_hint=retry_hint,
                )
            except LLMEmptyResponseError as exc:
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 LLM 빈 응답")
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
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 refine 결과 빈 문자열")
                    continue
                log.update(
                    status="fail",
                    error="refine 결과 빈 문자열",
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail", ""

            clean_text = strip_thinking(refined_text)

            # -- structure validate ---------------------------------
            log["stage"] = "structure_validate"
            struct_result = self._validator.validate(clean_text)
            if not struct_result.is_valid:
                if attempt < max_retries:
                    print(f"[RETRY {attempt + 1}/{max_retries}] {doc.source_file} \u2014 구조 오류: {struct_result.errors}")
                    continue
                log.update(
                    status="fail",
                    error=str(struct_result.errors),
                    duration_sec=(datetime.now(tz=timezone.utc) - start).total_seconds(),
                )
                self._io.write_log(log)
                return "fail", ""

            # -- judge ----------------------------------------------
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
        """Judge 를 실행하고 (result_str, verdict) 튜플을 반환한다.

        result_str 은 ``"ok"`` / ``"retry"`` / ``"fail"`` 중 하나.
        verdict 는 성공 시 JudgeVerdict, 실패/skip 시 이전 verdict 그대로.

        JudgeError 시 ``on_judge_error`` 정책에 따라:
          - ``"skip"`` → ``("ok", last_verdict)``
          - ``"fail"`` → ``("fail", last_verdict)``
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
                print("[JUDGE] on_judge_error=skip \u2014 판정 건너뜀.")
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
                error=f"Judge 불합격: {verdict.critique}",
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
        """is_partial 시 도메인 관련 섹션만 추출한 Document 를 반환, 실패 시 원본 반환."""
        if not filter_result.is_partial:
            return doc

        log["stage"] = "extract"
        extracted = self._refiner.extract_domain_sections(doc, filter_result.domains)
        if not extracted:
            print(f"\n[WARN] {doc.source_file} \u2014 섹션 추출 결과 없음, 원본으로 폴백")
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
            print(f"\n[WARN] {doc.source_file} \u2014 임시 파일 로드 실패, 원본으로 폴백: {exc}")
            return doc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
