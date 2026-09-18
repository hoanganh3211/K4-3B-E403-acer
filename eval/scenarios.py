"""Frozen, controlled-retrieval evaluation scenarios for production ScriptScout.

Live runs use Gemini for the production read/cross-check/write/revise methods.
The web is replaced by explicit synthetic HTTP fixtures; neither search nor a
user session database is used. Contract runners are separately labelled mocks.
This file never runs a scenario merely by being imported.
"""

from __future__ import annotations

import ast
import copy
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
import html
import importlib
import io
import json
from pathlib import Path
import re
import socket
import time
import unittest
from unittest.mock import patch

import httpx

from config import settings
from models.llm_outputs import OUTPUT_SCHEMAS
from models.script import Scene, ScriptLine, SourceReference, VideoScript
from services.citation_checker import CitationChecker
from services.content_policy import validate_lesson_content
from services.llm_service import LLMService
from services.pipeline_service import PipelineService, eligible_source
import services.pipeline_service as pipeline_module
from services.scraper_service import ScraperService


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = Path(__file__).resolve().parent / "fixtures"
AS_OF_DATE = "2026-09-18"
DEFAULT_LESSON = {
    "topic": "Đọc hiểu tài liệu giáo dục có dẫn chứng",
    "target_audience": "Giảng viên và sinh viên kiểm tra phần mềm",
    "objectives": ["Giải thích luận điểm chính và giới hạn của tài liệu"],
    "duration_minutes": 1,
    "teaching_style": "Giải thích rõ ràng bằng tiếng Việt, giữ nguyên phạm vi bằng chứng.",
    "source_languages": ["en"], "max_sources": 3,
}


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(AS_OF_DATE)


class NoSearch:
    def generate_queries(self, *args, **kwargs):
        raise AssertionError("Evaluation fixtures must not invoke a query planner")

    def search_multiple(self, *args, **kwargs):
        raise AssertionError("Evaluation fixtures must not invoke live web search")


class AuditedLLM:
    """Lazy production JSON adapter with one wire attempt per logical request."""

    def __init__(self, mode):
        self.mode = mode
        self.calls = []
        self._service = None
        self._client = None

    @property
    def usage(self):
        return list(self._service.usage) if self._service is not None else []

    def generate_json(self, system, payload):
        if self.mode != "live":
            raise RuntimeError("This scenario requires live mode; no model answer was simulated")
        output_cap = 8192 if payload.get("task") == "write_script" else 4096
        call = {"system": system, "payload": copy.deepcopy(payload), "task": payload.get("task"),
                "provider": "google", "model": settings.google_model, "response": None, "usage": [],
                "provider_call_attempted": False,
                "token_usage": {"input_tokens": None, "output_tokens": None},
                "request_config": {"max_output_tokens": output_cap, "timeout_seconds": 60, "attempts": 1}}
        self.calls.append(call)
        started = time.perf_counter()
        usage_before = len(self.usage)
        try:
            if self._service is None:
                from google import genai
                from google.genai import types
                config = settings.model_copy(update={"llm_provider": "google", "max_tokens": output_cap,
                                                     "llm_timeout_seconds": 60})
                self._client = genai.Client(
                    api_key=config.google_api_key, vertexai=False,
                    http_options=types.HttpOptions(timeout=60_000,
                        retry_options=types.HttpRetryOptions(attempts=1)),
                )
                self._service = LLMService(provider="google", config=config, client=self._client)
            self._service.max_tokens = output_cap
            call["provider_call_attempted"] = True
            response = self._service.generate_json(system, payload)
            call["response"] = copy.deepcopy(response)
            call["usage"] = copy.deepcopy(self._service.usage[usage_before:])
            try:
                OUTPUT_SCHEMAS[payload["task"]].model_validate(response)
                call["application_schema_valid"] = True
            except (KeyError, TypeError, ValueError) as exc:
                call["application_schema_valid"] = False
                call["schema_error_type"] = type(exc).__name__
            return response
        except Exception as exc:
            # SDK exceptions can include keys/URLs; never log their raw message.
            call["error"] = {"type": type(exc).__name__, "message": "generation_failed"}
            call["error_type"] = type(exc).__name__
            if self._service is not None:
                call["usage"] = copy.deepcopy(self._service.usage[usage_before:])
            raise
        finally:
            for key in ("input_tokens", "output_tokens"):
                values = [record.get(key) for record in call["usage"] if isinstance(record.get(key), (int, float))]
                call["token_usage"][key] = sum(values) if values else None
            call["duration_seconds"] = round(time.perf_counter() - started, 4)

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None


def _read_fixture(name):
    return json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))


def _lesson(*overrides):
    lesson = copy.deepcopy(DEFAULT_LESSON)
    for values in overrides:
        lesson.update(copy.deepcopy(values or {}))
    return lesson


def _normalized(value):
    return " ".join(str(value).split())


def _vi(value):
    # A narrow language-presence proxy, not a fluency or translation-quality judge.
    return bool(re.search(r"[ăĂđĐơƠưƯạ-ỹ]", value)) and len(value.split()) >= 4


def _patterns_present(text, patterns):
    return bool(patterns) and all(re.search(pattern, text, re.I) is not None for pattern in patterns)


def _html_document(document):
    metadata = [f'<meta charset="utf-8"><title>{html.escape(document["title"])}</title>']
    for name, value in (("author", document.get("author")), ("date", document.get("published_date"))):
        if value:
            metadata.append(f'<meta name="{name}" content="{html.escape(value, quote=True)}">')
    return (f'<html lang="{document["language"]}"><head>{"".join(metadata)}</head>'
            f'<body>{document["body_html"]}</body></html>').encode("utf-8")


@contextmanager
def _fixture_scraper(documents):
    requests = []
    lookup = {document["url"]: document for document in documents}

    def respond(request):
        url = str(request.url.copy_with(host=request.headers["host"]))
        if url not in lookup:
            raise AssertionError("Attempted retrieval outside the frozen fixture map")
        requests.append(url)
        document = lookup[url]
        return httpx.Response(document.get("status", 200), content=_html_document(document),
                              headers={"content-type": "text/html; charset=utf-8"})

    scraper = ScraperService(transport=httpx.MockTransport(respond), scholarly_search=lambda _doi: [])
    dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
    # Only retrieval is inside this guard; Gemini calls occur after it is left.
    with patch("socket.getaddrinfo", return_value=dns), patch(
        "socket.socket.connect", side_effect=AssertionError("Fixture retrieval attempted a real socket")
    ):
        yield scraper, requests


def _fetch_document(document, source_id):
    with _fixture_scraper([document]) as (scraper, requests):
        raw = scraper.fetch_url(document["url"])
    raw.source_id = source_id
    raw.fetched_at = datetime(2026, 9, 18, tzinfo=timezone.utc)
    return raw.model_dump(mode="json"), list(requests), scraper


def _pipeline(llm, scraper=None):
    # Isolate the research/writing stage; mandatory admission has separate live
    # cases. These frozen educational fixtures are pre-admitted, not auto-passed
    # as a claimed test of moderation.
    return PipelineService(llm=llm, search=NoSearch(), scraper=scraper or ScraperService(),
                           admission=validate_lesson_content)


def _completed(llm):
    return bool(llm.calls) and all(call.get("response") is not None and not call.get("error")
                                  and call.get("application_schema_valid") is True for call in llm.calls)


def _source_case(case, llm):
    fixture_name = case["input"]["fixture"]
    document = _read_fixture("source_documents.json")["documents"][fixture_name]
    raw, requested, scraper = _fetch_document(document, "src_" + fixture_name)
    lesson = _lesson(document.get("lesson"), case["input"].get("lesson"))
    item = _pipeline(llm, scraper).evaluate_source(raw, lesson)
    claims = item.get("claims", [])
    text = "\n".join([item.get("summary_vi", "")] + [
        str(claim.get(key, "")) for claim in claims for key in ("claim_text", "snippet_translation_vi")])
    expected = case["expected"]
    forbidden = expected.get("forbidden_text", [])
    forbidden = [forbidden] if isinstance(forbidden, str) else forbidden
    public_evidence = json.dumps({"summary": item.get("summary_vi"), "claims": claims}, ensure_ascii=False)
    model_payloads = json.dumps([call["payload"] for call in llm.calls], ensure_ascii=False)
    checks = {
        "model_completed": _completed(llm),
        "accessible": bool(item["is_accessible"]),
        "inaccessible": not item["is_accessible"] and bool(item.get("error_message")),
        "quarantined": bool(item["has_prompt_injection"]) and item["status"] == "rejected" and not eligible_source(item),
        "no_claims": not claims,
        "no_model_call": not llm.calls,
        "claims_present": bool(claims),
        "quotes_grounded": bool(claims) and all(
            claim.get("is_verified") and _normalized(claim["snippet_quote"]) in _normalized(raw["raw_markdown"])
            for claim in claims),
        "vietnamese_summary": _vi(item.get("summary_vi", "")),
        "vietnamese_translations": bool(claims) and all(_vi(claim.get("snippet_translation_vi", "")) for claim in claims),
        "language_matches_fixture": item.get("language") == document["language"],
        "author_matches_fixture": item.get("author") == document.get("author"),
        "date_matches_fixture": item.get("published_date") == document.get("published_date"),
        "stale_warning": bool(item.get("is_outdated")) and any("3 năm" in warning for warning in item.get("warnings", [])),
        "no_snippet_evidence": bool(document.get("search_snippet")) and not claims
            and not raw["raw_markdown"] and not eligible_source(item),
        "forbidden_text_absent": bool(forbidden) and all(
            marker not in public_evidence and marker not in model_payloads for marker in forbidden),
        "required_facts_present": _patterns_present(text, expected.get("required_fact_patterns", [])),
    }
    return checks, {"fixture": fixture_name, "raw_source": raw, "source": item, "retrieval_requests": requested,
                    "lesson": lesson, "language_check": "Vietnamese character/word presence only; not a fluency judgment",
                    "fact_check": "Predeclared regex coverage proxy; not an independent semantic judgment"}, (
                        "live_model_controlled_retrieval" if llm.calls else "production_guard_controlled_retrieval")


def _structured_session(fixture_name):
    fixture = _read_fixture("structured_scenarios.json")["scenarios"][fixture_name]
    sources, raws, requests = [], [], []
    checker = CitationChecker()
    for index, entry in enumerate(fixture["sources"], 1):
        document = {**entry, "author": "Controlled evaluation author", "published_date": "2026-09-01",
                    "status": 200, "body_html": f'<article><p>{html.escape(entry["quote"])}</p>'
                    '<p>This is a synthetic controlled teaching fixture, not a report of real research findings.</p></article>'}
        raw, retrieved, _scraper = _fetch_document(document, entry["source_id"])
        requests.extend(retrieved)
        checked = checker.verify_single(entry["quote"], raw["raw_markdown"])
        if not checked.is_verified:
            raise ValueError("Preverified fixture quote did not match the retrieved document")
        claim = {"claim_id": entry["source_id"] + "_c1", "source_id": entry["source_id"],
                 "claim_text": entry["claim_vi"], "snippet_quote": entry["quote"],
                 "snippet_translation_vi": entry["claim_vi"], "source_context": raw["raw_markdown"],
                 "is_statistical": entry["statistical"], "is_verified": True,
                 "verification_score": checked.score, "verification_note": "Controlled fixture quote matched.",
                 "independently_verified": False, "corroborating_claim_ids": []}
        sources.append({"source_id": entry["source_id"], "url": entry["url"], "title": entry["title"],
                        "language": entry["language"], "status": "approved", "is_accessible": True,
                        "has_prompt_injection": False, "trust_score": 70, "claims": [claim],
                        "summary_vi": entry["claim_vi"], "published_date": "2026-09-01"})
        raws.append(raw)
    lesson = _lesson(fixture.get("lesson"), {"topic": fixture["topic"]})
    session = {"req": lesson, "dossier": {"topic": fixture["topic"], "sources": sources, "warnings": [],
                "conflicts": [], "total_urls_scanned": len(sources), "output_language": "vi"},
               "raw_sources": raws, "active_source_ids": [source["source_id"] for source in sources], "usage": []}
    if fixture.get("seed_lines"):
        source_map = {source["source_id"]: source for source in sources}
        lines = []
        for seed in fixture["seed_lines"]:
            refs = []
            for sid in seed["source_ids"]:
                source = source_map[sid]
                claim = source["claims"][0]
                refs.append(SourceReference(source_id=sid, claim_id=claim["claim_id"], url=source["url"],
                    snippet_quote=claim["snippet_quote"], snippet_translation_vi=claim["snippet_translation_vi"],
                    source_context=claim["source_context"], is_verified=True, verification_score=100))
            lines.append(ScriptLine(line_id=seed["line_id"], text=seed["text"], kind=seed["kind"],
                                    source_refs=refs, has_factual_content=bool(refs)))
        script = VideoScript(script_id="script_fixture", topic=lesson["topic"], target_audience=lesson["target_audience"],
            objectives=lesson["objectives"], target_duration_minutes=1, teaching_style=lesson["teaching_style"],
            generated_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
            scenes=[Scene(scene_id="scene_fixture", scene_number=1, scene_label="Khái niệm", lines=lines)])
        PipelineService.finalize_script(script)
        session["script"] = script.model_dump(mode="json")
    return fixture, session, requests


def _conflict_case(case, llm):
    fixture, session, requests = _structured_session(case["input"]["fixture"])
    dossier = session["dossier"]
    scope_fields = ("claim_text", "snippet_quote", "source_context")
    original_scope = {claim["claim_id"]: {key: claim[key] for key in scope_fields}
                      for source in dossier["sources"] for claim in source["claims"]}
    _pipeline(llm).cross_check(dossier)
    known = {claim["claim_id"] for source in dossier["sources"] for claim in source["claims"]}
    conflicts = dossier["conflicts"]
    pair = set(fixture["expected_source_pair"])
    statistical = [claim for source in dossier["sources"] for claim in source["claims"] if claim["is_statistical"]]
    final_scope = {claim["claim_id"]: {key: claim[key] for key in scope_fields}
                   for source in dossier["sources"] for claim in source["claims"]}
    sent_claims = {claim["claim_id"]: claim for call in llm.calls if call["task"] == "cross_check"
                   for claim in call["payload"].get("claims", [])}
    scope_preserved = bool(original_scope) and final_scope == original_scope and all(
        claim_id in sent_claims and sent_claims[claim_id].get("source_context") == scope["source_context"]
        and scope["snippet_quote"] in sent_claims[claim_id]["source_context"]
        and sent_claims[claim_id].get("claim_text") == scope["claim_text"][:240]
        for claim_id, scope in original_scope.items())
    checks = {
        "model_completed": _completed(llm),
        "conflict_detected": _completed(llm) and any(set(conflict["source_ids"]) == pair for conflict in conflicts),
        "no_false_conflict": _completed(llm) and not conflicts,
        "conflict_scope_preserved": _completed(llm) and scope_preserved,
        "statistical_unverified": bool(statistical) and all(not claim.get("independently_verified") for claim in statistical),
        "only_known_claim_ids": _completed(llm) and all(
            set(conflict["claim_ids"]) <= known and len(conflict["source_ids"]) >= 2 for conflict in conflicts),
    }
    return checks, {"fixture": case["input"]["fixture"], "dossier": dossier, "retrieval_requests": requests,
                    "scope_check": "Original claims, quotes and full cohort/year/denominator context retained in dossier and model input; no_false_conflict separately checks the live model decision",
                    "seed_evidence": "Synthetic manually checked claims; source evaluation intentionally isolated"}, "live_model_preverified_fixture"


def _lines(script):
    return [line for scene in script["scenes"] for line in scene["lines"]]


def _grounded(line, raw_map, allowed_ids):
    refs = line.get("source_refs", [])
    return bool(refs) and not line.get("is_unverified") and not line.get("hallucination_detected") and all(
        ref["source_id"] in allowed_ids and ref.get("is_verified")
        and _normalized(ref.get("snippet_quote", ""))
        and _normalized(ref["snippet_quote"]) in _normalized(raw_map.get(ref["source_id"], "")) for ref in refs)


def _patch_case(case, llm):
    _fixture, session, requests = _structured_session(case["input"]["fixture"])
    session["req"].update(case["input"].get("lesson", {}))
    before = copy.deepcopy(session)
    removed = case["input"]["remove_source_ids"]
    expected_affected = {line["line_id"] for line in _lines(before["script"])
                         if any(ref["source_id"] in removed for ref in line["source_refs"])}
    result = _pipeline(llm).patch(session, removed)
    after = {line["line_id"]: line for line in _lines(result["script"])}
    old = {line["line_id"]: line for line in _lines(before["script"])}
    allowed = set(before["active_source_ids"]) - set(removed)
    raw_map = {raw["source_id"]: raw["raw_markdown"] for raw in session["raw_sources"]}
    affected_lines = [after[line_id] for line_id in expected_affected if line_id in after]
    checks = {
        "model_completed": _completed(llm),
        "affected_exact": bool(expected_affected) and set(result["affected_line_ids"]) == expected_affected,
        "untouched_identical": all(old[line_id] == after.get(line_id) for line_id in old if line_id not in expected_affected),
        "line_ids_preserved": set(old) == set(after),
        "removed_refs_absent": all(ref["source_id"] not in removed for line in after.values() for ref in line["source_refs"]),
        "script_input_unchanged": session == before,
        "replacements_grounded": bool(affected_lines) and all(_grounded(line, raw_map, allowed) for line in affected_lines),
        "no_patch_generation_when_empty": not allowed and all(call["task"] != "patch_script" for call in llm.calls),
        "unverified_placeholder": bool(affected_lines) and not allowed and all(
            line["text"] == "[Cần giảng viên bổ sung bằng chứng cho ý này.]"
            and line["is_unverified"] and not line["source_refs"] for line in affected_lines),
        "vietnamese_narration": _vi(" ".join(line["text"] for line in after.values())),
    }
    return checks, {"fixture": case["input"]["fixture"], "before": before["script"], "result": result,
                    "expected_affected_line_ids": sorted(expected_affected), "retrieval_requests": requests,
                    "seed_evidence": "Synthetic manually checked claims; moderation and retrieval quality isolated"}, (
                        "live_model_preverified_fixture" if llm.calls else "production_guard_preverified_fixture")


def _teaching_case(case, llm):
    _fixture, session, requests = _structured_session(case["input"]["fixture"])
    session.pop("script", None)
    session["req"].update(case["input"].get("lesson", {}))
    approved = case["input"].get("approved_source_ids", session["active_source_ids"])
    result = _pipeline(llm).review(session, approved)
    lines = _lines(result["script"])
    narration = "\n".join(line["text"] for line in lines)
    raw_map = {raw["source_id"]: raw["raw_markdown"] for raw in session["raw_sources"]}
    factual = [line for line in lines if line.get("has_factual_content") or line["source_refs"]]
    writer_calls = [call for call in llm.calls if call["task"] == "write_script"]
    checks = {
        "model_completed": _completed(llm),
        "teaching_style_forwarded": bool(writer_calls) and all(
            call["payload"]["lesson"]["teaching_style"] == session["req"]["teaching_style"] for call in writer_calls),
        "teaching_style_applied": _patterns_present(narration, case["expected"].get("style_patterns", [])),
        "grounded_factual_lines": bool(factual) and all(_grounded(line, raw_map, set(approved)) for line in factual),
        "vietnamese_narration": _vi(narration),
        "only_approved_refs": bool(factual) and all(ref["source_id"] in approved for line in lines for ref in line["source_refs"]),
    }
    return checks, {"fixture": case["input"]["fixture"], "lesson": session["req"], "result": result,
                    "retrieval_requests": requests, "style_check": "Predeclared literal/regex proxy, not oral naturalness evaluation",
                    "seed_evidence": "Synthetic manually checked claims; admission tested separately"}, "live_model_preverified_fixture"


def _contract_case(case):
    test_name = case["input"]["test"]
    if not re.fullmatch(r"tests\.test_[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.test_[A-Za-z0-9_]+", test_name):
        raise ValueError("Contract case must name one explicit local unittest method")
    module_name, class_name, method_name = test_name.rsplit(".", 2)
    module = importlib.import_module(module_name)
    test = getattr(module, class_name)(method_name)
    suite = unittest.TestSuite([test])
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output), patch(
        "socket.socket.connect", side_effect=AssertionError("Contract evaluation must not access a real network")
    ):
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    passed = result.testsRun == 1 and result.wasSuccessful() and not result.skipped
    return {"contract_passed": passed}, {"test": test_name, "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "raw_test_output": output.getvalue(),
        "limitation": "Existing mocked regression test; measures software contracts, not model judgment or live provider quality"}, "mocked_contract"


CHECK_NAMES = {
    "admission": {"decision_matches", "no_unsafe_allow"},
    "source": {"model_completed", "accessible", "inaccessible", "quarantined", "no_claims", "no_model_call",
               "claims_present", "quotes_grounded", "vietnamese_summary", "vietnamese_translations",
               "language_matches_fixture", "author_matches_fixture", "date_matches_fixture", "stale_warning",
               "no_snippet_evidence", "forbidden_text_absent", "required_facts_present"},
    "conflict": {"model_completed", "conflict_detected", "no_false_conflict", "conflict_scope_preserved",
                 "statistical_unverified", "only_known_claim_ids"},
    "patch": {"model_completed", "affected_exact", "untouched_identical", "line_ids_preserved", "removed_refs_absent",
              "script_input_unchanged", "replacements_grounded", "no_patch_generation_when_empty",
              "unverified_placeholder", "vietnamese_narration"},
    "teaching_style": {"model_completed", "teaching_style_forwarded", "teaching_style_applied",
                       "grounded_factual_lines", "vietnamese_narration", "only_approved_refs"},
    "contract": {"contract_passed"},
}


def validate_cases(cases):
    """Validate frozen selectors/data statically; never run tests, retrieval or models."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("Expected a nonempty list of cases")
    documents = _read_fixture("source_documents.json")
    structured = _read_fixture("structured_scenarios.json")
    if documents.get("as_of_date") != AS_OF_DATE or structured.get("as_of_date") != AS_OF_DATE:
        raise ValueError("Fixture reference dates differ from the evaluation clock")
    seen = set()
    for case in cases:
        case_id = case["id"]
        if not case_id or case_id in seen:
            raise ValueError("Duplicate or empty case ID")
        seen.add(case_id)
        runner, data, expected = case["runner"], case["input"], case["expected"]
        names = expected["checks"]
        if runner not in CHECK_NAMES or not isinstance(names, list) or not names:
            raise ValueError(f"{case_id}: invalid runner/checks")
        if len(set(names)) != len(names) or set(names) - CHECK_NAMES[runner]:
            raise ValueError(f"{case_id}: unknown or duplicate check names")
        for check, field in (("required_facts_present", "required_fact_patterns"),
                             ("teaching_style_applied", "style_patterns")):
            if check in names:
                patterns = expected.get(field)
                if not isinstance(patterns, list) or not patterns:
                    raise ValueError(f"{case_id}: missing {field}")
                for pattern in patterns:
                    re.compile(pattern, re.I)
        if "forbidden_text_absent" in names and not expected.get("forbidden_text"):
            raise ValueError(f"{case_id}: missing forbidden markers")
        if runner == "admission":
            if not isinstance(data.get("lesson"), dict) or not data["lesson"].get("topic"):
                raise ValueError(f"{case_id}: missing admission lesson")
            if expected.get("decision") not in {"allow", "block", "clarify"}:
                raise ValueError(f"{case_id}: invalid admission decision")
        elif runner == "source":
            document = documents["documents"][data["fixture"]]
            for field in ("url", "title", "language", "body_html"):
                if not isinstance(document.get(field), str) or not document[field]:
                    raise ValueError(f"{case_id}: missing source field {field}")
        elif runner in {"conflict", "patch", "teaching_style"}:
            fixture = structured["scenarios"][data["fixture"]]
            ids = {source["source_id"] for source in fixture["sources"]}
            if len(ids) != len(fixture["sources"]) or not ids:
                raise ValueError(f"{case_id}: invalid structured source IDs")
            for source in fixture["sources"]:
                for field in ("url", "title", "language", "quote", "claim_vi"):
                    if not isinstance(source.get(field), str) or not source[field]:
                        raise ValueError(f"{case_id}: missing structured source field {field}")
            if runner == "conflict" and (len(fixture["expected_source_pair"]) < 2
                                         or not set(fixture["expected_source_pair"]) <= ids):
                raise ValueError(f"{case_id}: invalid expected source pair")
            if runner == "patch" and (not fixture.get("seed_lines") or not data.get("remove_source_ids")
                                      or not set(data["remove_source_ids"]) <= ids):
                raise ValueError(f"{case_id}: invalid patch seed/removal IDs")
            if runner == "teaching_style" and not data.get("lesson", {}).get("teaching_style"):
                raise ValueError(f"{case_id}: missing requested teaching style")
        elif runner == "contract":
            selector = data["test"]
            if not re.fullmatch(r"tests\.test_[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.test_[A-Za-z0-9_]+", selector):
                raise ValueError(f"{case_id}: invalid contract selector")
            module_name, class_name, method_name = selector.rsplit(".", 2)
            module_path = ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
            tree = ast.parse(module_path.read_text(encoding="utf-8-sig"))
            classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
            if len(classes) != 1 or not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                           and node.name == method_name for node in classes[0].body):
                raise ValueError(f"{case_id}: contract method does not exist")
    return {"case_count": len(cases), "fixture_date": AS_OF_DATE, "execution": "static_only"}


def run_case(case, mode="live"):
    """Run one frozen case, retaining calls and failures for the root scorer.

    ``expected.checks`` controls scoring; missing checks are explicitly false.
    Admission cases are owned by the root provider, not silently simulated here.
    ``offline`` runs only contracts/early retrieval guards; a needed model call
    becomes a failed observation, never a fabricated answer.
    """
    if mode not in {"live", "offline"}:
        raise ValueError("mode must be live or offline")
    required = case["expected"]["checks"]
    if not isinstance(required, list) or not required or any(not isinstance(name, str) for name in required):
        raise ValueError("Each case must declare nonempty expected check names")
    llm = AuditedLLM(mode)
    checks, details, level = {}, {}, "evaluation_error"
    error = None
    try:
        runner = case["runner"]
        with patch.object(pipeline_module, "date", FixedDate):
            if runner == "source":
                checks, details, level = _source_case(case, llm)
            elif runner == "conflict":
                checks, details, level = _conflict_case(case, llm)
            elif runner == "patch":
                checks, details, level = _patch_case(case, llm)
            elif runner == "teaching_style":
                checks, details, level = _teaching_case(case, llm)
            elif runner == "contract":
                checks, details, level = _contract_case(case)
            else:
                raise ValueError("Runner is not supported by eval.scenarios; admission belongs to the root provider")
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": "scenario_execution_failed"}
        details["error"] = error
        checks = {name: False for name in required}
    finally:
        try:
            llm.close()
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": "provider_cleanup_failed"}
            details["error"] = error
            checks = {name: False for name in required}
    missing = [name for name in required if name not in checks]
    if missing and not error:
        error = {"type": "MissingExpectedCheck", "message": "scenario_did_not_produce_required_checks"}
        details["error"] = error
    if not error and any(call.get("error") for call in llm.calls):
        error = {"type": "ModelCallFailed", "message": "production_returned_after_model_failure"}
        details["error"] = error
    if not error and any(call.get("application_schema_valid") is False for call in llm.calls):
        error = {"type": "ModelSchemaInvalid", "message": "model_output_failed_application_schema"}
        details["error"] = error
    details.update({"as_of_date": AS_OF_DATE, "missing_expected_checks": missing,
                    "execution_mode": mode, "live_web_search": False,
                    "provider_request_definition": "Logical Gemini SDK generate_content calls; retry attempts configured to one"})
    result = {"checks": {name: bool(checks.get(name, False)) for name in required}, "details": details,
              "evidence_level": level,
              "provider_call_count": sum(bool(call.get("provider_call_attempted")) for call in llm.calls),
              "raw_calls": llm.calls}
    if error:
        result["error"] = error
        result["error_type"] = error["type"]
    return result
