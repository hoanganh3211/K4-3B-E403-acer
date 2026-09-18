"""Promptfoo provider for the frozen production-code evaluation."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.harness import EVAL, read_json, score_case, utc_now, verify_frozen, write_new


def admission_case(case):
    from services.admission_policy import AdmissionPolicyService
    from services.content_policy import ContentPolicyError, validate_lesson_content
    from services.moderation_service import GeminiModerationEvaluator

    calls = []
    evaluator = GeminiModerationEvaluator()

    def recorded(system, payload):
        record = {"started_at": utc_now(), "system": system, "input": payload,
                  "provider": "google", "task": "admission", "usage": None}
        calls.append(record)
        started = time.perf_counter()
        try:
            value = evaluator(system, payload)
            record["output"] = value
            return value
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["elapsed_seconds"] = time.perf_counter() - started

    lesson = case["input"]["lesson"]
    stage, decision, category, metadata = "local", None, None, None
    try:
        validate_lesson_content(lesson)
        stage = "semantic"
        verdict = AdmissionPolicyService(recorded).require(lesson)
        decision, metadata = verdict.decision, verdict.to_dict()
    except ContentPolicyError as exc:
        category = exc.category
        decision = {"needs_clarification": "clarify", "admission_unavailable": "unavailable"}.get(category, "block")
    expected = case["expected"]["decision"]
    observed = {"checks": {"decision_matches": decision == expected,
                            "no_unsafe_allow": expected == "allow" or decision != "allow"},
                "details": {"decision": decision, "category": category, "stage": stage,
                            "metadata": metadata, "expected_decision": expected},
                "evidence_level": "live_model" if calls else "local_guard",
                "provider_call_count": len(calls), "raw_calls": calls}
    if decision == "unavailable":
        observed["error"] = {"type": "AdmissionUnavailable", "message": "Classification did not complete; this case is failed, not silently excluded."}
    return observed


def call_api(prompt, options, context):
    verify_frozen()
    run_value = os.environ.get("SCRIPTSCOUT_EVAL_RUN_DIR")
    if not run_value:
        raise RuntimeError("Use eval/run.py run so raw results have a unique destination.")
    run_dir = Path(run_value).resolve()
    if run_dir.parent != (EVAL / "runs").resolve():
        raise RuntimeError("Evaluation output must stay inside eval/runs.")
    case_id = context["vars"]["case_id"]
    cases = read_json(EVAL / "golden_set.json")["cases"]
    case = next(row for row in cases if row["id"] == case_id)
    destination = run_dir / "cases" / f"{case_id}.json"
    if destination.exists():
        # Duplicate orchestration cannot rerun a model or replace the first result.
        raise RuntimeError("Duplicate case invocation; original raw result preserved.")
    started = utc_now()
    clock = time.perf_counter()
    try:
        if case["runner"] == "admission":
            observed = admission_case(case)
        else:
            from eval.scenarios import run_case
            observed = run_case(case, mode="live")
    except Exception as exc:
        observed = {"checks": {}, "details": {}, "evidence_level": "error",
                    "provider_call_count": 0, "raw_calls": [],
                    "error": {"type": type(exc).__name__, "message": "Case execution failed; no retry or replacement result."}}
    result = score_case(case, observed)
    result.update(started_at=started, finished_at=utc_now(), elapsed_seconds=time.perf_counter() - clock)
    write_new(destination, result)
    compact = {key: value for key, value in result.items() if key != "observed"}
    compact["checks"] = observed.get("checks", {})
    compact["evidence_level"] = observed.get("evidence_level")
    compact["error"] = observed.get("error")
    return {"output": json.dumps(compact, ensure_ascii=False)}
