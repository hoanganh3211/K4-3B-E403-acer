"""API workflow contracts, using a temporary SQLite DB and controlled workers."""

import copy
from concurrent.futures import Future
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import api_server as api
from services.session_store import SessionStore, now_iso


LESSON = {
    "topic": "Self-attention trong Transformer", "target_audience": "Sinh viên học sâu",
    "objectives": ["Giải thích cơ chế liên kết các vị trí"], "duration_minutes": 3,
    "teaching_style": "Thầy đặt câu hỏi gợi mở, giải thích bằng ví dụ giả định.",
    "source_languages": ["vi", "en"], "max_sources": 4,
}


def source_fixture(source_id="src_ok", **changes):
    values = {
        "source_id": source_id, "url": f"https://example.org/{source_id}", "title": "Tài liệu gốc",
        "language": "en", "status": "pending", "is_accessible": True, "has_prompt_injection": False,
        "summary_vi": "Nguồn giải thích cơ chế liên kết vị trí trong chuỗi.", "trust_score": 65,
        "claims": [{"claim_id": f"{source_id}_c1", "source_id": source_id, "is_verified": True,
                    "claim_text": "Thông tin của các vị trí trong chuỗi được liên kết.",
                    "snippet_quote": "Self-attention relates different positions of a single sequence.",
                    "snippet_translation_vi": "Self-attention liên kết các vị trí trong cùng một chuỗi.",
                    "verification_note": "Khớp trích dẫn nguyên văn."}],
    }
    values.update(changes)
    return values


def dossier_fixture():
    return {"topic": LESSON["topic"], "sources": [source_fixture()], "total_urls_scanned": 1,
            "warnings": [], "conflicts": [], "output_language": "vi"}


def script_fixture():
    return {"script_id": "script_saved", "teaching_style": LESSON["teaching_style"],
            "estimated_duration_minutes": 3, "warnings": ["Giảng viên cần duyệt."],
            "dependency_graph": {"src_ok": ["line_saved"]},
            "scenes": [{"scene_number": 1, "scene_label": "Ý chính", "estimated_duration_seconds": 20,
                        "lines": [{"line_id": "line_saved", "text": "Lời đọc tiếng Việt đã lưu.",
                                   "source_refs": [{"source_id": "src_ok", "claim_id": "src_ok_c1"}],
                                   "is_unverified": False}]}]}


class ControlledExecutor:
    """Do not run workers until the test observes the HTTP acknowledgement."""
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


class FakePipeline:
    def __init__(self, progress):
        self.progress = progress
        self.llm = Mock()
        self.calls = []
        self.fail_on = None

    def _record(self, operation, payload):
        self.calls.append((operation, copy.deepcopy(payload)))
        self.progress(operation, "Đang xử lý bằng provider giả lập trong kiểm thử.")
        if self.fail_on == operation:
            raise RuntimeError("private provider payload must never be exposed")

    def research(self, request):
        self._record("research", request)
        return {"dossier": dossier_fixture(), "raw_sources": [{"source_id": "src_ok", "raw_markdown": "ORIGINAL RAW SOURCE TEXT"}],
                "active_source_ids": [], "usage": []}

    def review(self, session, approved):
        self._record("review", approved)
        return {"dossier": session["dossier"], "script": script_fixture(), "active_source_ids": approved, "usage": []}

    def patch(self, session, removed):
        self._record("patch", removed)
        return {"script": session["script"], "active_source_ids": [sid for sid in session["active_source_ids"] if sid not in removed]}

    def add_source(self, session, url):
        self._record("add", url)
        dossier = copy.deepcopy(session["dossier"])
        dossier["sources"].append(source_fixture("src_added", url=url))
        dossier["total_urls_scanned"] += 1
        return {"dossier": dossier, "raw_sources": session["raw_sources"] + [{"source_id": "src_added", "raw_markdown": "NEW RAW SOURCE"}]}


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="scriptscout-api-tests-")
        self.addCleanup(self.directory.cleanup)
        self.store = SessionStore(Path(self.directory.name) / "sessions.sqlite3")
        self.executor = ControlledExecutor()
        self.instances = []
        self.fail_operation = None
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(api, "store", self.store))
        self.stack.enter_context(patch.object(api, "executor", self.executor))
        self.admission = self.stack.enter_context(patch.object(api, "require_research_admission", return_value=None))
        self.config = self.stack.enter_context(patch.object(api, "configuration", return_value={
            "llm_provider": "openai", "model": "test-model", "llm_configured": True, "search_configured": True,
        }))

        def factory(progress):
            instance = FakePipeline(progress)
            instance.fail_on = self.fail_operation
            self.instances.append(instance)
            return instance

        self.stack.enter_context(patch.object(api, "PipelineService", side_effect=factory))
        self.client = self.stack.enter_context(TestClient(api.app))

    def seed(self, *, status="awaiting_review", with_script=False, sources=None):
        dossier = dossier_fixture()
        if sources is not None:
            dossier["sources"] = copy.deepcopy(sources)
        session = {"session_id": "ss_test", "req": copy.deepcopy(LESSON), "dossier": dossier,
                   "script": script_fixture() if with_script else None,
                   "raw_sources": [{"source_id": "src_ok", "raw_markdown": "ORIGINAL RAW SOURCE TEXT"}],
                   "active_source_ids": ["src_ok"] if with_script else [], "progress": [],
                   "created_at": now_iso(), "status": status}
        self.store.put(session)
        return session

    def test_start_returns_202_before_worker_and_status_survives_store_reopen(self):
        response = self.client.post("/api/pipeline/start", json=LESSON)
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        session_id = payload["session_id"]
        self.assertEqual(payload["status"], "researching")
        self.assertEqual(len(self.executor.pending), 1)
        self.assertFalse(self.instances)
        self.assertEqual(self.client.get(f"/api/sessions/{session_id}").json()["status"], "researching")
        self.executor.run_next()
        data = self.client.get(f"/api/sessions/{session_id}").json()
        self.assertEqual(data["status"], "awaiting_review")
        self.assertNotIn("raw_sources", data["data"])
        self.assertEqual([event["step"] for event in data["data"]["progress"]], ["queued", "research", "complete"])
        restored = SessionStore(self.store.path).get(session_id)
        self.assertEqual(restored["req"]["teaching_style"], LESSON["teaching_style"])
        self.assertEqual(restored["raw_sources"][0]["raw_markdown"], "ORIGINAL RAW SOURCE TEXT")
        self.instances[0].llm.close.assert_called_once()

    def test_missing_configuration_fails_before_creating_a_session(self):
        self.config.return_value["llm_configured"] = False
        response = self.client.post("/api/pipeline/start", json=LESSON)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.executor.pending, [])

    def test_active_session_rejects_parallel_review_patch_and_add(self):
        self.seed(status="writing", with_script=True)
        requests = [
            ("/api/pipeline/review", {"session_id": "ss_test", "approved_source_ids": ["src_ok"]}),
            ("/api/pipeline/patch", {"session_id": "ss_test", "remove_source_ids": ["src_ok"]}),
            ("/api/pipeline/sources", {"session_id": "ss_test", "url": "https://example.org/new"}),
        ]
        for path, body in requests:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json=body).status_code, 409)
        self.assertEqual(self.executor.pending, [])
        self.assertEqual(self.store.get("ss_test")["status"], "writing")

    def test_review_rejects_unknown_empty_and_contradictory_approvals(self):
        self.seed()
        invalid = [
            {"approved_source_ids": ["not_in_dossier"]},
            {"approved_source_ids": []},
            {"approved_source_ids": ["src_ok"], "rejected_source_ids": ["src_ok"]},
            {"approved_source_ids": ["src_ok"], "rejected_source_ids": ["not_in_dossier"]},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                response = self.client.post("/api/pipeline/review", json={"session_id": "ss_test", **fields})
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.executor.pending, [])

    def test_review_rejects_inaccessible_injected_or_unverified_sources(self):
        for changes in ({"is_accessible": False}, {"has_prompt_injection": True},
                        {"status": "unreachable"}, {"claims": []}, {"claims": [{"is_verified": False}]}):
            with self.subTest(changes=changes):
                self.seed(sources=[source_fixture(**changes)])
                response = self.client.post("/api/pipeline/review", json={"session_id": "ss_test", "approved_source_ids": ["src_ok"]})
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.executor.pending, [])

    def test_review_deduplicates_approved_ids_and_persists_script_after_worker(self):
        self.seed()
        response = self.client.post("/api/pipeline/review", json={"session_id": "ss_test", "approved_source_ids": ["src_ok", "src_ok"]})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "writing")
        self.executor.run_next()
        session = self.store.get("ss_test")
        self.assertEqual(session["status"], "script_ready")
        self.assertEqual(session["active_source_ids"], ["src_ok"])
        self.assertEqual(session["script"]["script_id"], "script_saved")
        self.assertEqual(self.instances[0].calls, [("review", ["src_ok"])])

    def test_patch_rejects_missing_script_and_unknown_active_source(self):
        self.seed()
        body = {"session_id": "ss_test", "remove_source_ids": ["src_ok"]}
        self.assertEqual(self.client.post("/api/pipeline/patch", json=body).status_code, 409)
        self.seed(status="script_ready", with_script=True)
        body["remove_source_ids"] = ["not_active"]
        self.assertEqual(self.client.post("/api/pipeline/patch", json=body).status_code, 422)
        self.assertEqual(self.executor.pending, [])

    def test_failed_patch_preserves_last_script_dossier_and_approvals(self):
        before = self.seed(status="script_ready", with_script=True)
        self.fail_operation = "patch"
        response = self.client.post("/api/pipeline/patch", json={"session_id": "ss_test", "remove_source_ids": ["src_ok"]})
        self.assertEqual(response.status_code, 202)
        self.executor.run_next()
        after = self.store.get("ss_test")
        self.assertEqual(after["status"], "failed")
        self.assertEqual(after["script"], before["script"])
        self.assertEqual(after["dossier"], before["dossier"])
        self.assertEqual(after["active_source_ids"], before["active_source_ids"])
        self.assertNotIn("private provider", after["error_message"])
        self.instances[0].llm.close.assert_called_once()

    def test_add_source_rejects_duplicate_and_non_http_urls_then_persists_new_source(self):
        self.seed(status="script_ready", with_script=True)
        duplicate = self.client.post("/api/pipeline/sources", json={"session_id": "ss_test", "url": "https://example.org/src_ok/"})
        self.assertEqual(duplicate.status_code, 409)
        for url in ("file:///C:/private", "ftp://example.org/file", "https://user:password@example.org/document"):
            with self.subTest(url=url):
                self.assertEqual(self.client.post("/api/pipeline/sources", json={"session_id": "ss_test", "url": url}).status_code, 422)
        response = self.client.post("/api/pipeline/sources", json={"session_id": "ss_test", "url": "https://example.org/new-document"})
        self.assertEqual(response.status_code, 202)
        self.executor.run_next()
        session = self.store.get("ss_test")
        self.assertEqual(session["status"], "awaiting_review")
        self.assertEqual(session["dossier"]["total_urls_scanned"], 2)
        self.assertEqual(session["dossier"]["sources"][-1]["url"], "https://example.org/new-document")
        self.assertEqual(session["script"], script_fixture())
        self.assertEqual(len(session["raw_sources"]), 2)

    def test_exports_include_vietnamese_and_provenance_but_not_full_raw_pages(self):
        self.seed(status="script_ready", with_script=True)
        response = self.client.get("/api/sessions/ss_test/export?format=json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("raw_sources", response.json())
        self.assertIn("snippet_quote", response.text)
        self.assertIn("snippet_translation_vi", response.text)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        markdown = self.client.get("/api/sessions/ss_test/export?format=markdown")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn(LESSON["teaching_style"], markdown.text)
        self.assertIn("Trích dẫn nguyên ngữ", markdown.text)
        self.assertIn("Diễn giải tiếng Việt", markdown.text)
        self.assertIn("https://example.org/src_ok", markdown.text)
        self.assertNotIn("ORIGINAL RAW SOURCE TEXT", markdown.text)
        self.assertEqual(self.client.get("/api/sessions/ss_test/export?format=exe").status_code, 422)

    def test_evidence_endpoint_returns_saved_raw_content_and_unknown_ids_are_404(self):
        self.seed()
        response = self.client.get("/api/sessions/ss_test/sources/src_ok")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["raw_source"]["raw_markdown"], "ORIGINAL RAW SOURCE TEXT")
        self.assertEqual(self.client.get("/api/sessions/ss_test/sources/unknown").status_code, 404)
        self.assertEqual(self.client.get("/api/sessions/unknown").status_code, 404)
        self.assertEqual(self.client.get("/api/sessions").json()["sessions"][0]["session_id"], "ss_test")

    def test_restart_recovers_interrupted_operation_without_losing_saved_script(self):
        before = self.seed(status="patching", with_script=True)
        reopened = SessionStore(self.store.path)
        reopened.recover_interrupted()
        after = reopened.get("ss_test")
        self.assertEqual(after["status"], "failed")
        self.assertEqual(after["script"], before["script"])
        self.assertIn("Máy chủ đã dừng", after["error_message"])

    def test_restart_recovers_active_sessions_older_than_the_recent_listing_limit(self):
        interrupted = self.seed(status="patching", with_script=True)
        for index in range(101):
            newer = copy.deepcopy(interrupted)
            newer["session_id"] = f"ss_recent_{index}"
            newer["status"] = "script_ready"
            self.store.put(newer)
        self.assertNotIn("ss_test", [item["session_id"] for item in self.store.list()])
        self.store.recover_interrupted()
        recovered = self.store.get("ss_test")
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["script"], interrupted["script"])


if __name__ == "__main__":
    unittest.main()
