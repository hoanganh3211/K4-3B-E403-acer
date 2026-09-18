"""Mandatory semantic admission through the API and direct pipeline boundaries.

The real decision validator/cache receives mocked classifications. No model,
search provider, scraper, or user database is contacted by these tests.
"""

import copy
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

import api_server as api
from services.admission_policy import AdmissionPolicyService
from services.content_policy import ContentPolicyError, validate_lesson_content
from services.llm_service import LLMService
from services.pipeline_service import PipelineService
from services.scraper_service import ScraperService
from services.search_service import SearchService
from services.session_store import SessionStore, now_iso

try:
    from tests import test_api as fixtures
except ImportError:
    import test_api as fixtures


ALLOW = {"decision": "allow", "subject": "general_education", "intent": "educational", "field": "lesson"}
BLOCK = {"decision": "block", "subject": "wrongdoing", "intent": "facilitative", "field": "topic"}
UNLISTED_TOPICS = (
    "Cách đưa phong bì để được ưu tiên trái quy định",
    "Dạy cách xóa vật chứng trước khi cơ quan điều tra đến",
    "Mua bán động vật hoang dã bị cấm để thu lợi",
)


class SemanticAdmissionAPITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="scriptscout-semantic-api-")
        self.addCleanup(directory.cleanup)
        self.store = SessionStore(Path(directory.name) / "sessions.sqlite3")
        self.executor = fixtures.ControlledExecutor()
        self.evaluator = Mock(return_value=copy.deepcopy(ALLOW))
        self.service = AdmissionPolicyService(self.evaluator)
        self.instances = []
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(api, "store", self.store))
        stack.enter_context(patch.object(api, "executor", self.executor))
        stack.enter_context(patch.object(api, "configuration", return_value={
            "llm_provider": "google", "model": "test-model", "llm_configured": True, "search_configured": True,
        }))
        self.put = stack.enter_context(patch.object(self.store, "put", wraps=self.store.put))
        self.update = stack.enter_context(patch.object(self.store, "update", wraps=self.store.update))
        self.admission = stack.enter_context(patch.object(api, "require_research_admission", side_effect=self.require))

        def factory(progress):
            pipeline = fixtures.FakePipeline(progress)
            self.instances.append(pipeline)
            return pipeline

        self.pipeline_factory = stack.enter_context(patch.object(api, "PipelineService", side_effect=factory))
        self.search = stack.enter_context(patch.object(
            SearchService, "search_multiple", side_effect=AssertionError("Research search must not run")))
        self.model = stack.enter_context(patch.object(
            LLMService, "generate_json", side_effect=AssertionError("Research model must not run")))
        self.fetch = stack.enter_context(patch.object(
            ScraperService, "fetch_url", side_effect=AssertionError("Document fetch must not run")))
        self.gemini = stack.enter_context(patch("google.genai.Client", side_effect=AssertionError("No live Gemini in tests")))
        self.client = stack.enter_context(TestClient(api.app))

    def require(self, payload):
        validate_lesson_content(payload)
        return self.service.require(payload)

    def seed(self, *, topic=UNLISTED_TOPICS[0]):
        request = {**copy.deepcopy(fixtures.LESSON), "topic": topic}
        validate_lesson_content(request)  # This fixture genuinely passes the local keyword check.
        dossier = fixtures.dossier_fixture()
        dossier["sources"].append(fixtures.source_fixture(
            "src_unread", is_accessible=False, claims=[], status="unreachable"))
        session = {"session_id": "ss_semantic", "req": request, "dossier": dossier,
                   "script": fixtures.script_fixture(), "active_source_ids": ["src_ok"],
                   "status": "script_ready", "progress": [], "created_at": now_iso(),
                   "raw_sources": [{"source_id": "src_ok", "raw_markdown": "Original evidence"}]}
        self.store.put(session)
        self.put.reset_mock()
        self.update.reset_mock()
        return session

    def assert_no_research_or_queue(self):
        self.assertEqual(self.executor.pending, [])
        self.pipeline_factory.assert_not_called()
        self.search.assert_not_called()
        self.model.assert_not_called()
        self.fetch.assert_not_called()
        self.gemini.assert_not_called()

    def assert_rejection(self, response, status=422, code="content_not_allowed"):
        self.assertEqual(response.status_code, status)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], code)
        self.assertTrue(detail["message"])
        self.assertNotIn("secret-provider-payload", detail["message"])

    def test_unlisted_unsafe_topics_require_semantic_block_before_save_or_queue(self):
        self.evaluator.return_value = BLOCK
        for topic in UNLISTED_TOPICS:
            with self.subTest(topic=topic):
                request = {**fixtures.LESSON, "topic": topic}
                validate_lesson_content(request)
                response = self.client.post("/api/pipeline/start", json=request)
                self.assert_rejection(response)
                self.assertEqual(self.store.list(), [])
                self.put.assert_not_called()
                self.update.assert_not_called()
                self.assert_no_research_or_queue()
        self.assertEqual(self.evaluator.call_count, len(UNLISTED_TOPICS))

    def test_allow_is_obtained_before_creation_and_worker_reuses_validated_cache(self):
        def evaluate(_system, lesson):
            self.assertEqual(self.store.list(), [])
            self.assertEqual(self.executor.pending, [])
            self.pipeline_factory.assert_not_called()
            self.assertEqual(lesson, {key: fixtures.LESSON[key] for key in (
                "topic", "target_audience", "objectives", "teaching_style")})
            return ALLOW

        self.evaluator.side_effect = evaluate
        response = self.client.post("/api/pipeline/start", json=fixtures.LESSON)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.executor.pending), 1)
        self.put.assert_called_once()
        self.pipeline_factory.assert_not_called()
        self.executor.run_next()
        self.assertEqual(self.admission.call_count, 2)
        self.evaluator.assert_called_once()
        self.pipeline_factory.assert_called_once()
        self.assertEqual(self.store.get(response.json()["session_id"])["status"], "awaiting_review")
        self.gemini.assert_not_called()

    def test_clarification_unavailable_and_malformed_decisions_fail_closed(self):
        cases = [
            ({**ALLOW, "decision": "clarify", "subject": "unclear", "intent": "unclear"}, None,
             422, "content_needs_clarification"),
            (None, TimeoutError("secret-provider-payload"), 503, "content_review_unavailable"),
            ({"decision": "allow"}, None, 503, "content_review_unavailable"),
            ({**ALLOW, "extra_explanation": "secret-provider-payload"}, None, 503, "content_review_unavailable"),
        ]
        for verdict, error, status, code in cases:
            with self.subTest(status=status, verdict=verdict):
                self.service = AdmissionPolicyService(self.evaluator)
                self.evaluator.side_effect = error
                self.evaluator.return_value = verdict
                response = self.client.post("/api/pipeline/start", json=fixtures.LESSON)
                self.assert_rejection(response, status, code)
                self.assertEqual(self.store.list(), [])
                self.put.assert_not_called()
                self.update.assert_not_called()
                self.assert_no_research_or_queue()

    def test_wrongdoing_legal_analysis_without_prevention_cannot_use_model_allow(self):
        self.evaluator.return_value = {**ALLOW, "subject": "wrongdoing", "intent": "legal_analysis"}
        request = {**fixtures.LESSON, "topic": "Phân tích pháp luật về bảo tồn động vật hoang dã"}
        validate_lesson_content(request)
        self.assert_rejection(self.client.post("/api/pipeline/start", json=request), 422, "content_needs_clarification")
        self.put.assert_not_called()
        self.assert_no_research_or_queue()

    def test_mixed_or_promotional_intent_cannot_use_model_allow(self):
        for intent in ("mixed", "promotional", "facilitative"):
            with self.subTest(intent=intent):
                self.service = AdmissionPolicyService(self.evaluator)
                self.evaluator.return_value = {**ALLOW, "subject": "wrongdoing", "intent": intent}
                response = self.client.post("/api/pipeline/start", json={**fixtures.LESSON, "topic": UNLISTED_TOPICS[0]})
                self.assert_rejection(response)
                self.put.assert_not_called()
                self.assert_no_research_or_queue()

    def test_semantic_preventive_decision_allows_protective_lesson(self):
        self.evaluator.return_value = {**ALLOW, "subject": "wrongdoing", "intent": "preventive"}
        request = {**fixtures.LESSON, "topic": "Nhận diện và phòng chống mua bán động vật hoang dã"}
        response = self.client.post("/api/pipeline/start", json=request)
        self.assertEqual(response.status_code, 202)
        self.evaluator.assert_called_once()
        self.assertEqual(len(self.executor.pending), 1)
        self.pipeline_factory.assert_not_called()

    def test_every_legacy_paid_route_requires_semantic_admission_before_mutation(self):
        before = self.seed()
        self.evaluator.return_value = BLOCK
        requests = [
            ("/api/pipeline/review", {"approved_source_ids": ["src_ok"]}),
            ("/api/pipeline/patch", {"remove_source_ids": ["src_ok"]}),
            ("/api/pipeline/sources", {"url": "https://example.org/new-paper"}),
            ("/api/pipeline/sources/retry", {"source_id": "src_unread"}),
        ]
        for path, body in requests:
            with self.subTest(path=path):
                calls_before = self.admission.call_count
                response = self.client.post(path, json={"session_id": "ss_semantic", **body})
                self.assert_rejection(response)
                self.assertEqual(self.admission.call_count, calls_before + 1)
                self.assertEqual(self.store.get("ss_semantic"), before)
                self.put.assert_not_called()
                self.update.assert_not_called()
                self.assert_no_research_or_queue()
        response = self.client.post("/api/pipeline/sources/upload", data={"session_id": "ss_semantic"},
                                    files={"file": ("research.pdf", b"%PDF-1.7\nfixture", "application/pdf")})
        self.assert_rejection(response)
        self.assertEqual(self.store.get("ss_semantic"), before)
        self.put.assert_not_called()
        self.update.assert_not_called()
        self.assert_no_research_or_queue()
        self.evaluator.assert_called_once()  # Repeated decisions use the exact-input cache.

    def test_upload_semantic_denial_happens_before_reading_document_bytes(self):
        self.seed()
        self.evaluator.return_value = BLOCK
        file_object = Mock()
        file_object.read.side_effect = AssertionError("PDF bytes must not be read before admission")
        with self.assertRaises(HTTPException) as raised:
            api.upload_source("ss_semantic", UploadFile(filename="research.pdf", file=file_object))
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["code"], "content_not_allowed")
        file_object.read.assert_not_called()
        file_object.close.assert_called_once()
        self.assert_no_research_or_queue()

    def test_worker_rechecks_changed_full_lesson_before_pipeline_construction(self):
        for field in ("topic", "target_audience", "objectives", "teaching_style"):
            with self.subTest(field=field):
                self.service = AdmissionPolicyService(self.evaluator)
                self.evaluator.reset_mock()
                self.evaluator.side_effect = [ALLOW, BLOCK]
                before = self.seed(topic=fixtures.LESSON["topic"])
                self.assertEqual(self.require(before["req"]).decision, "allow")
                changed = copy.deepcopy(before)
                changed["req"][field] = [UNLISTED_TOPICS[1]] if field == "objectives" else UNLISTED_TOPICS[1]
                changed["status"] = "researching"
                validate_lesson_content(changed["req"])
                self.store.update(changed)
                api.run_operation("ss_semantic", "research", None)
                after = self.store.get("ss_semantic")
                self.assertEqual(after["status"], "failed")
                self.assertEqual(after["script"], before["script"])
                self.assertEqual(after["dossier"], before["dossier"])
                self.assertEqual(self.evaluator.call_count, 2)
                self.assert_no_research_or_queue()

    def test_legacy_sessions_can_be_read_exported_and_deleted_without_semantic_review(self):
        self.seed()
        self.evaluator.side_effect = AssertionError("Read/delete must not request semantic review")
        for path in ("/api/sessions", "/api/sessions/ss_semantic", "/api/sessions/ss_semantic/export",
                     "/api/sessions/ss_semantic/sources/src_ok"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.delete("/api/sessions/ss_semantic").status_code, 200)
        self.assertIsNone(self.store.get("ss_semantic"))
        self.evaluator.assert_not_called()
        self.admission.assert_not_called()
        self.assert_no_research_or_queue()

    def test_direct_pipeline_entry_points_require_semantic_approval_before_work(self):
        session = self.seed()
        before = copy.deepcopy(session)
        self.evaluator.return_value = BLOCK
        llm, search, scraper = Mock(), Mock(), Mock()
        pipeline = PipelineService(llm=llm, search=search, scraper=scraper, admission=self.require)
        operations = {
            "research": lambda: pipeline.research(session["req"]),
            "review": lambda: pipeline.review(session, ["src_ok"]),
            "patch": lambda: pipeline.patch(session, ["src_ok"]),
            "add_source": lambda: pipeline.add_source(session, "https://example.org/paper"),
            "retry_source": lambda: pipeline.retry_source(session, "src_unread"),
            "add_pdf": lambda: pipeline.add_pdf(session, "research.pdf", b"%PDF-1.7\nfixture"),
        }
        with patch.object(ScraperService, "_extract_pdf", side_effect=AssertionError("No PDF parsing before admission")) as parser:
            for name, invoke in operations.items():
                with self.subTest(operation=name):
                    with self.assertRaises(ContentPolicyError):
                        invoke()
                    self.assertEqual(llm.mock_calls, [])
                    self.assertEqual(search.mock_calls, [])
                    self.assertEqual(scraper.mock_calls, [])
                    self.assertEqual(session, before)
            parser.assert_not_called()
        self.evaluator.assert_called_once()


if __name__ == "__main__":
    unittest.main()
