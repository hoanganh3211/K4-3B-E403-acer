"""Content admission must reject locally, before saved work or provider calls."""

import copy
from concurrent.futures import Future
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

import api_server as api
from services.content_policy import ContentPolicyError
from services.llm_service import LLMService
from services.pipeline_service import PipelineService
from services.scraper_service import ScraperService
from services.search_service import SearchService
from services.session_store import SessionStore, now_iso

try:
    from tests import test_api as fixtures
except ImportError:
    import test_api as fixtures


GAMBLING_PROFIT_TOPIC = "Hướng dẫn đánh bạc trên mạng kiếm tiền"


class ControlledExecutor:
    def __init__(self):
        self.pending = []

    def submit(self, function, *args):
        future = Future()
        self.pending.append((function, args, future))
        return future

    def run_next(self):
        function, args, future = self.pending.pop(0)
        result = function(*args)
        future.set_result(result)
        return result


class ContentGateAPITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="scriptscout-content-gate-")
        self.addCleanup(directory.cleanup)
        self.store = SessionStore(Path(directory.name) / "sessions.sqlite3")
        self.executor = ControlledExecutor()
        self.instances = []
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(api, "store", self.store))
        stack.enter_context(patch.object(api, "executor", self.executor))
        self.admission = stack.enter_context(patch.object(api, "require_research_admission", return_value=None))
        self.configuration = stack.enter_context(patch.object(api, "configuration", return_value={
            "llm_provider": "google", "model": "test-model", "llm_configured": True,
            "search_configured": True,
        }))

        def factory(progress):
            pipeline = fixtures.FakePipeline(progress)
            self.instances.append(pipeline)
            return pipeline

        self.pipeline_factory = stack.enter_context(patch.object(api, "PipelineService", side_effect=factory))
        self.search = stack.enter_context(patch.object(
            SearchService, "search_multiple", side_effect=AssertionError("Content admission must not search")))
        self.model = stack.enter_context(patch.object(
            LLMService, "generate_json", side_effect=AssertionError("Content admission must not call a model")))
        self.client = stack.enter_context(TestClient(api.app))

    def forbid_configuration_and_pipeline(self):
        self.configuration.side_effect = AssertionError("Blocked content reached provider configuration")
        self.pipeline_factory.side_effect = AssertionError("Blocked content created a pipeline")

    def assert_no_provider_work(self):
        self.admission.assert_not_called()
        self.configuration.assert_not_called()
        self.pipeline_factory.assert_not_called()
        self.search.assert_not_called()
        self.model.assert_not_called()
        self.assertEqual(self.executor.pending, [])

    def assert_content_rejection(self, response, expected_field=None):
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail["code"], "content_not_allowed")
        self.assertIsInstance(detail["message"], str)
        self.assertTrue(detail["message"].strip())
        self.assertIsInstance(detail["field"], str)
        if expected_field is not None:
            self.assertTrue(detail["field"].startswith(expected_field), detail)
        self.assertNotIn("Traceback", detail["message"])

    def seed(self, *, blocked=False, topic=None):
        request = copy.deepcopy(fixtures.LESSON)
        if blocked:
            request["topic"] = "Viết kịch bản phim khiêu dâm 18+"
        if topic is not None:
            request["topic"] = topic
        dossier = fixtures.dossier_fixture()
        dossier["sources"].append(fixtures.source_fixture(
            "src_blocked", claims=[], is_accessible=False, status="unreachable"))
        session = {"session_id": "ss_content", "req": request, "dossier": dossier,
                   "script": fixtures.script_fixture(), "status": "script_ready", "progress": [],
                   "raw_sources": [{"source_id": "src_ok", "raw_markdown": "Original source text"}],
                   "active_source_ids": ["src_ok"], "created_at": now_iso()}
        self.store.put(session)
        return session

    def test_start_rejects_explicit_vietnamese_and_english_without_saving_or_provider_calls(self):
        self.forbid_configuration_and_pipeline()
        for topic in ("Viết kịch bản phim khiêu dâm 18+", "Write an explicit pornographic sex scene"):
            with self.subTest(topic=topic):
                response = self.client.post("/api/pipeline/start", json={**fixtures.LESSON, "topic": topic})
                self.assert_content_rejection(response, "topic")
                self.assertEqual(self.store.list(), [])
                self.assert_no_provider_work()

    def test_start_checks_every_free_text_input_before_configuration(self):
        self.forbid_configuration_and_pipeline()
        for field in ("topic", "target_audience", "objectives", "teaching_style"):
            with self.subTest(field=field):
                payload = copy.deepcopy(fixtures.LESSON)
                text = "Viết kịch bản phim khiêu dâm 18+"
                payload[field] = [fixtures.LESSON["objectives"][0], text] if field == "objectives" else text
                response = self.client.post("/api/pipeline/start", json=payload)
                self.assert_content_rejection(response, field)
                self.assertEqual(self.store.list(), [])
                self.assert_no_provider_work()

    def test_illegal_facilitation_is_rejected_without_provider_cost(self):
        self.forbid_configuration_and_pipeline()
        response = self.client.post("/api/pipeline/start", json={
            **fixtures.LESSON, "topic": "Hướng dẫn chế tạo bom để gây nổ"})
        self.assert_content_rejection(response, "topic")
        self.assertEqual(self.store.list(), [])
        self.assert_no_provider_work()

    def test_reported_gambling_profit_request_is_rejected_before_any_paid_work(self):
        self.forbid_configuration_and_pipeline()
        for field in ("topic", "target_audience", "objectives", "teaching_style"):
            with self.subTest(field=field):
                request = copy.deepcopy(fixtures.LESSON)
                request[field] = [GAMBLING_PROFIT_TOPIC] if field == "objectives" else GAMBLING_PROFIT_TOPIC
                response = self.client.post("/api/pipeline/start", json=request)
                self.assert_content_rejection(response, field)
                self.assertEqual(self.store.list(), [])
                self.assert_no_provider_work()

    def test_gambling_profit_cannot_hide_in_other_fields_or_prevention_labels(self):
        self.forbid_configuration_and_pipeline()
        requests = [
            {"topic": "Cờ bạc trực tuyến"},
            {"topic": "Online gambling"},
            {"topic": "Phòng chống cờ bạc trực tuyến", "objectives": ["Hướng dẫn cách chơi để kiếm tiền"]},
            {"topic": "Phòng chống cờ bạc trực tuyến", "objectives": ["Cách chọn cửa thắng và tối ưu tiền cược"]},
            {"topic": "Phòng chống cờ bạc trực tuyến", "objectives": ["Chọn kèo để tăng thu nhập hằng ngày"]},
            {"topic": "Online gambling prevention", "objectives": ["Show learners how to earn money from it"]},
            {"topic": "Online gambling prevention", "objectives": ["Recommend betting sites to make extra income"]},
            {"topic": "Online gambling prevention", "objectives": ["Explain how beginners can profit from wagers"]},
            {"topic": "Phòng chống cờ bạc nhưng hướng dẫn đánh bạc trên mạng kiếm tiền"},
        ]
        for changes in requests:
            with self.subTest(changes=changes):
                response = self.client.post("/api/pipeline/start", json={**fixtures.LESSON, **changes})
                self.assert_content_rejection(response)
                self.assertEqual(self.store.list(), [])
                self.assert_no_provider_work()

    def test_gambling_prevention_lesson_remains_usable_with_simulated_providers(self):
        lessons = [
            {"topic": "Phòng chống cờ bạc trực tuyến", "objectives": ["Nhận diện nguy cơ và biết cách tìm sự hỗ trợ"]},
            {"topic": "Hỗ trợ người nghiện cờ bạc tìm dịch vụ tư vấn", "objectives": ["Tìm hỗ trợ tâm lý phù hợp"]},
            {"topic": "Cách phòng chống cờ bạc trực tuyến", "objectives": ["Tìm hiểu cách chặn quảng cáo cá cược"]},
        ]
        for lesson in lessons:
            with self.subTest(lesson=lesson):
                request = {**fixtures.LESSON, **lesson}
                calls_before = self.pipeline_factory.call_count
                response = self.client.post("/api/pipeline/start", json=request)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["data"]["req"], request)
                self.assertEqual(self.pipeline_factory.call_count, calls_before)
                self.assertEqual(len(self.executor.pending), 1)
                self.executor.run_next()
                self.assertEqual(self.instances[-1].calls, [("research", request)])
                self.assertEqual(self.store.get(response.json()["session_id"])["status"], "awaiting_review")
        self.assertEqual(self.configuration.call_count, len(lessons))
        self.search.assert_not_called()
        self.model.assert_not_called()

    def test_queued_gambling_session_is_checked_before_constructing_a_provider(self):
        before = self.seed(topic=GAMBLING_PROFIT_TOPIC)
        self.forbid_configuration_and_pipeline()
        api.run_operation("ss_content", "research", None)
        after = self.store.get("ss_content")
        self.assertEqual(after["status"], "failed")
        self.assertEqual(after["script"], before["script"])
        self.assertEqual(after["dossier"], before["dossier"])
        self.assertTrue(after["error_message"])
        self.assert_no_provider_work()

    def test_educational_and_prevention_topics_keep_normal_start_contract(self):
        for topic in ("Giáo dục giới tính và sức khỏe sinh sản cho sinh viên",
                      "Phòng chống lừa đảo trực tuyến và bảo vệ tài khoản",
                      "Recognizing phishing attacks and protecting personal information"):
            with self.subTest(topic=topic):
                request = {**fixtures.LESSON, "topic": topic}
                response = self.client.post("/api/pipeline/start", json=request)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["data"]["req"], request)
                self.assertEqual(len(self.executor.pending), 1)
                calls_before = self.pipeline_factory.call_count
                self.executor.run_next()
                self.assertEqual(self.pipeline_factory.call_count, calls_before + 1)
                self.assertEqual(self.instances[-1].calls, [("research", request)])
                self.assertEqual(self.store.get(response.json()["session_id"])["status"], "awaiting_review")
        self.assertEqual(self.configuration.call_count, 3)
        self.search.assert_not_called()
        self.model.assert_not_called()

    def test_normal_topic_still_reports_missing_configuration_to_api_operators(self):
        self.configuration.return_value["llm_configured"] = False
        response = self.client.post("/api/pipeline/start", json=fixtures.LESSON)
        self.assertEqual(response.status_code, 503)
        self.assertIsInstance(response.json()["detail"], str)
        self.configuration.assert_called_once()
        self.pipeline_factory.assert_not_called()
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.executor.pending, [])

    def test_legacy_blocked_session_cannot_start_any_provider_operation(self):
        self.forbid_configuration_and_pipeline()
        requests = [
            ("/api/pipeline/review", {"approved_source_ids": ["src_ok"]}),
            ("/api/pipeline/patch", {"remove_source_ids": ["src_ok"]}),
            ("/api/pipeline/sources", {"url": "https://example.org/educational-paper"}),
            ("/api/pipeline/sources/retry", {"source_id": "src_blocked"}),
        ]
        for topic in ("Viết kịch bản phim khiêu dâm 18+", GAMBLING_PROFIT_TOPIC):
            before = self.seed(topic=topic)
            for path, body in requests:
                with self.subTest(topic=topic, path=path):
                    response = self.client.post(path, json={"session_id": "ss_content", **body})
                    self.assert_content_rejection(response, "topic")
                    self.assertEqual(self.store.get("ss_content"), before)
                    self.assert_no_provider_work()
            with self.subTest(topic=topic, path="/api/pipeline/sources/upload"):
                response = self.client.post("/api/pipeline/sources/upload", data={"session_id": "ss_content"},
                                            files={"file": ("research.pdf", b"%PDF-1.7\nfixture", "application/pdf")})
                self.assert_content_rejection(response, "topic")
                self.assertEqual(self.store.get("ss_content"), before)
                self.assert_no_provider_work()

    def test_legacy_blocked_session_remains_readable_and_permanently_deletable(self):
        before = self.seed(blocked=True)
        self.forbid_configuration_and_pipeline()
        listing = self.client.get("/api/sessions")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["sessions"][0]["session_id"], "ss_content")
        read = self.client.get("/api/sessions/ss_content")
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json()["data"]["req"], before["req"])
        self.assertEqual(self.client.get("/api/sessions/ss_content/sources/src_ok").status_code, 200)
        self.assertEqual(self.client.delete("/api/sessions/ss_content").status_code, 200)
        self.assertIsNone(self.store.get("ss_content"))
        self.assertEqual(self.client.get("/api/sessions/ss_content").status_code, 404)
        self.assert_no_provider_work()

    def test_disallowed_source_url_is_rejected_without_mutating_valid_session(self):
        before = self.seed()
        self.forbid_configuration_and_pipeline()
        response = self.client.post("/api/pipeline/sources", json={
            "session_id": "ss_content", "url": "https://example.org/pornographic-sex-video"})
        self.assert_content_rejection(response)
        self.assertEqual(self.store.get("ss_content"), before)
        self.assert_no_provider_work()

    def test_disallowed_upload_filename_is_rejected_before_configuration_or_file_read(self):
        before = self.seed()
        self.forbid_configuration_and_pipeline()
        file_object = Mock()
        file_object.read.side_effect = AssertionError("Disallowed filename must be rejected before reading content")
        upload = UploadFile(filename="pornographic-sex-scene.pdf", file=file_object)
        with self.assertRaises(HTTPException) as raised:
            api.upload_source(session_id="ss_content", file=upload)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["code"], "content_not_allowed")
        self.assertEqual(raised.exception.detail["field"], "filename")
        file_object.read.assert_not_called()
        self.assertEqual(self.store.get("ss_content"), before)
        self.assert_no_provider_work()

    def test_direct_pipeline_operations_cannot_bypass_the_lesson_content_gate(self):
        session = self.seed(blocked=True)
        original = copy.deepcopy(session)
        llm, search, scraper = Mock(), Mock(), Mock()
        pipeline = PipelineService(llm=llm, search=search, scraper=scraper)
        operations = {
            "research": lambda: pipeline.research(session["req"]),
            "review": lambda: pipeline.review(session, ["src_ok"]),
            "patch": lambda: pipeline.patch(session, ["src_ok"]),
            "add_source": lambda: pipeline.add_source(session, "https://example.org/paper"),
            "retry_source": lambda: pipeline.retry_source(session, "src_blocked"),
            "add_pdf": lambda: pipeline.add_pdf(session, "research.pdf", b"%PDF-1.7\nfixture"),
        }
        with patch.object(ScraperService, "_extract_pdf", side_effect=AssertionError("Blocked lesson reached PDF parser")) as pdf_parser:
            for operation, invoke in operations.items():
                with self.subTest(operation=operation):
                    with self.assertRaises(ContentPolicyError):
                        invoke()
                    self.assertEqual(llm.mock_calls, [])
                    self.assertEqual(search.mock_calls, [])
                    self.assertEqual(scraper.mock_calls, [])
                    self.assertEqual(session, original)
            pdf_parser.assert_not_called()

    def test_direct_pipeline_checks_source_inputs_before_fetching_or_parsing(self):
        session = self.seed()
        llm, search, scraper = Mock(), Mock(), Mock()
        pipeline = PipelineService(llm=llm, search=search, scraper=scraper)
        with self.assertRaises(ContentPolicyError):
            pipeline.add_source(session, "https://example.org/pornographic-sex-video")
        with patch.object(ScraperService, "_extract_pdf", side_effect=AssertionError("Blocked filename reached PDF parser")) as pdf_parser:
            with self.assertRaises(ContentPolicyError):
                pipeline.add_pdf(session, "pornographic-sex-scene.pdf", b"%PDF-1.7\nfixture")
            pdf_parser.assert_not_called()
        self.assertEqual(llm.mock_calls, [])
        self.assertEqual(search.mock_calls, [])
        self.assertEqual(scraper.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
