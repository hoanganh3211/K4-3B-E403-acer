"""Permanent session deletion and source recovery, without live providers."""

import base64
import copy
from contextlib import ExitStack, closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject,
)

import api_server as api
from services.pipeline_service import PipelineService
from services.session_store import SessionStore, now_iso

try:
    from tests import test_api as api_fixtures, test_pipeline as pipeline_fixtures
except ImportError:
    import test_api as api_fixtures
    import test_pipeline as pipeline_fixtures


def pdf_bytes(*, with_text=True):
    """A real one-page PDF exercises the same parser used for uploaded papers."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Sequence research", "/Author": "Test Author"})
    if with_text:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 10 Tf 20 700 Td (" + pipeline_fixtures.EN_QUOTE + ") Tj ET").encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class SessionActionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="scriptscout-session-actions-")
        self.addCleanup(directory.cleanup)
        self.store = SessionStore(Path(directory.name) / "sessions.sqlite3")
        self.executor = api_fixtures.ControlledExecutor()
        self.llm = pipeline_fixtures.FakeLLM({})
        self.llm.close = Mock()
        self.llm.handlers["evaluate_source"] = pipeline_fixtures.evaluation("en", pipeline_fixtures.EN_QUOTE)
        self.scraper = pipeline_fixtures.FakeScraper([])
        self.scraper.fetch_url = Mock(wraps=self.scraper.fetch_url)
        self.instances = []
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(api, "store", self.store))
        stack.enter_context(patch.object(api, "executor", self.executor))
        stack.enter_context(patch.object(api, "require_research_admission", return_value=None))
        stack.enter_context(patch.object(api, "configuration", return_value={
            "llm_provider": "google", "model": "test-model", "llm_configured": True,
            "search_configured": True,
        }))

        def factory(progress):
            pipeline = PipelineService(llm=self.llm, scraper=self.scraper, search=Mock(), progress=progress,
                                       admission=lambda req: None)
            self.instances.append(pipeline)
            return pipeline

        stack.enter_context(patch.object(api, "PipelineService", side_effect=factory))
        self.client = stack.enter_context(TestClient(api.app))

    def seed(self, *, status="script_ready", unavailable=True):
        session = {"session_id": "ss_actions", "req": copy.deepcopy(api_fixtures.LESSON),
                   "dossier": api_fixtures.dossier_fixture(), "script": api_fixtures.script_fixture(),
                   "active_source_ids": ["src_ok"], "progress": [], "status": status,
                   "created_at": now_iso(),
                   "raw_sources": [{"source_id": "src_ok", "raw_markdown": "Original evidence"}]}
        if unavailable:
            source = api_fixtures.source_fixture("src_blocked", claims=[], is_accessible=False,
                                                 status="unreachable", url="https://publisher.example/paper")
            session["dossier"]["sources"].append(source)
            session["dossier"]["total_urls_scanned"] += 1
            session["raw_sources"].append({"source_id": "src_blocked", "raw_markdown": "Stale failed response"})
        self.store.put(session)
        return session

    def retry(self, source_id="src_blocked"):
        return self.client.post("/api/pipeline/sources/retry", json={
            "session_id": "ss_actions", "source_id": source_id})

    def upload(self, content, filename="research.pdf"):
        return self.client.post("/api/pipeline/sources/upload", data={"session_id": "ss_actions"},
                                files={"file": (filename, content, "application/pdf")})

    def configure_recovery(self):
        original_url = "https://publisher.example/paper"
        final_url = "https://repository.example/paper.pdf"
        self.scraper.sources[original_url] = pipeline_fixtures.raw_source(
            "src_newly_fetched", "en", pipeline_fixtures.EN_QUOTE,
            url=final_url, final_url=final_url, original_url=original_url,
            retrieval_method="open_access", retrieval_note="Bản công khai của cùng nghiên cứu.")
        return original_url, final_url

    def test_legacy_store_migration_and_stale_updates_cannot_resurrect_deleted_session(self):
        legacy_path = Path(self.store.path).with_name("legacy.sqlite3")
        original = self.seed()
        with closing(sqlite3.connect(legacy_path)) as connection, connection:
            connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                               (original["session_id"], json.dumps(original), original["updated_at"]))
        migrated = SessionStore(legacy_path)
        self.assertEqual(migrated.get("ss_actions"), original)
        self.assertTrue(migrated.delete("ss_actions"))
        stale = copy.deepcopy(original)
        stale["script"]["script_id"] = "must_not_resurrect_deleted_session"
        self.assertFalse(migrated.update(stale))
        reopened = SessionStore(legacy_path)
        self.assertIsNone(reopened.get("ss_actions"))
        self.assertFalse(reopened.update(stale))
        self.assertEqual(reopened.list(), [])
        with closing(sqlite3.connect(legacy_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_legacy_soft_deleted_records_are_purged_and_storage_reclaimed(self):
        legacy_path = Path(self.store.path).with_name("soft-delete-legacy.sqlite3")
        original = self.seed()
        removed = copy.deepcopy(original)
        removed["session_id"] = "ss_legacy_removed"
        removed["raw_sources"][0]["raw_markdown"] = "REMOVED_SOURCE_CONTENT " * 100000
        with closing(sqlite3.connect(legacy_path)) as connection, connection:
            connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)")
            connection.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)", [
                (original["session_id"], json.dumps(original), original["updated_at"], None),
                (removed["session_id"], json.dumps(removed), removed["updated_at"], now_iso()),
            ])
        size_before = legacy_path.stat().st_size
        migrated = SessionStore(legacy_path)
        self.assertEqual(migrated.get("ss_actions"), original)
        self.assertIsNone(migrated.get("ss_legacy_removed"))
        self.assertEqual([item["session_id"] for item in migrated.list()], ["ss_actions"])
        with closing(sqlite3.connect(legacy_path)) as connection:
            self.assertEqual(connection.execute("SELECT id FROM sessions").fetchall(), [("ss_actions",)])
        self.assertLess(legacy_path.stat().st_size, size_before // 2)
        self.assertNotIn(b"REMOVED_SOURCE_CONTENT", legacy_path.read_bytes())

    def test_delete_permanently_removes_resources_and_reclaims_storage(self):
        session = self.seed()
        session["raw_sources"][0]["raw_markdown"] = "DELETE_THIS_EVIDENCE " * 100000
        self.store.put(session)
        survivor = copy.deepcopy(session)
        survivor["session_id"] = "ss_survivor"
        survivor["raw_sources"][0]["raw_markdown"] = "Keep this original evidence"
        self.store.put(survivor)
        db_path = Path(self.store.path)
        size_before = db_path.stat().st_size
        response = self.client.delete("/api/sessions/ss_actions")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertEqual([item["session_id"] for item in self.client.get("/api/sessions").json()["sessions"]], ["ss_survivor"])
        self.assertEqual(self.client.get("/api/sessions?deleted=true").status_code, 422)
        for suffix in ("", "/export", "/sources/src_ok", "/sources/src_ok/file"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.get("/api/sessions/ss_actions" + suffix).status_code, 404)
        self.assertEqual(self.client.post("/api/sessions/ss_actions/restore").status_code, 404)
        self.assertEqual(self.client.delete("/api/sessions/ss_actions").status_code, 404)
        with closing(sqlite3.connect(db_path)) as connection:
            self.assertEqual(connection.execute("SELECT id FROM sessions").fetchall(), [("ss_survivor",)])
        reopened = SessionStore(db_path)
        self.assertIsNone(reopened.get("ss_actions"))
        self.assertEqual(reopened.get("ss_survivor"), survivor)
        self.assertLess(db_path.stat().st_size, size_before // 2)
        self.assertNotIn(b"DELETE_THIS_EVIDENCE", db_path.read_bytes())

    def test_delete_rejects_busy_sessions_and_missing_sessions(self):
        for status in api.ACTIVE_STATUSES:
            with self.subTest(status=status):
                self.seed(status=status)
                self.assertEqual(self.client.delete("/api/sessions/ss_actions").status_code, 409)
                self.assertEqual(self.store.get("ss_actions")["status"], status)
        self.assertEqual(self.client.delete("/api/sessions/missing").status_code, 404)
        self.assertEqual(self.client.post("/api/sessions/missing/restore").status_code, 404)
        self.assertEqual(self.executor.pending, [])

    def test_retry_is_queued_then_preserves_script_and_active_approvals(self):
        before = self.seed()
        self.configure_recovery()
        response = self.retry()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "researching")
        self.assertEqual(len(self.executor.pending), 1)
        self.assertEqual(self.instances, [])
        with patch.object(self.store, "put", side_effect=AssertionError("Workers must update existing sessions only")):
            self.executor.run_next()
        after = self.store.get("ss_actions")
        self.assertEqual(after["status"], "awaiting_review")
        self.assertEqual(after["script"], before["script"])
        self.assertEqual(after["active_source_ids"], before["active_source_ids"])
        self.assertTrue(after["dossier"]["sources"][1]["claims"][0]["is_verified"])
        self.llm.close.assert_called_once()

    def test_retry_rejects_sources_with_evidence_or_references_before_queueing(self):
        for restriction in ("accessible", "claims", "approved", "referenced"):
            with self.subTest(restriction=restriction):
                session = self.seed()
                blocked = session["dossier"]["sources"][1]
                if restriction == "accessible":
                    blocked["is_accessible"] = True
                elif restriction == "claims":
                    blocked["claims"] = [{"claim_id": "existing"}]
                elif restriction == "approved":
                    session["active_source_ids"].append("src_blocked")
                else:
                    session["script"]["scenes"][0]["lines"][0]["source_refs"].append({"source_id": "src_blocked"})
                self.store.put(session)
                self.assertEqual(self.retry().status_code, 409)
                self.assertEqual(self.executor.pending, [])

    def test_retry_rejects_busy_missing_and_uploaded_sources(self):
        self.seed(status="writing")
        self.assertEqual(self.retry().status_code, 409)
        session = self.seed()
        self.assertEqual(self.retry("missing").status_code, 404)
        session["dossier"]["sources"][1]["document_kind"] = "uploaded_pdf"
        self.store.put(session)
        self.assertEqual(self.retry().status_code, 422)
        self.assertEqual(self.executor.pending, [])

    def test_retry_pipeline_preserves_identity_actual_location_and_input(self):
        session = self.seed()
        session["raw_sources"].append(copy.deepcopy(session["raw_sources"][1]))
        before = copy.deepcopy(session)
        original_url, final_url = self.configure_recovery()
        pipeline = PipelineService(llm=self.llm, scraper=self.scraper, search=Mock(), admission=lambda req: None)
        result = pipeline.retry_source(session, "src_blocked")
        self.assertEqual(session, before)
        self.assertNotIn("script", result)
        replacement = result["dossier"]["sources"][1]
        self.assertEqual(replacement["source_id"], "src_blocked")
        self.assertEqual(replacement["claims"][0]["claim_id"], "src_blocked_c1")
        self.assertEqual(replacement["url"], final_url)
        self.assertEqual(replacement["final_url"], final_url)
        self.assertEqual(replacement["original_url"], original_url)
        recovered_raws = [raw for raw in result["raw_sources"] if raw["source_id"] == "src_blocked"]
        self.assertEqual(len(recovered_raws), 1)
        self.assertIn(pipeline_fixtures.EN_QUOTE, recovered_raws[0]["raw_markdown"])
        self.assertNotIn("Stale failed response", json.dumps(result))
        self.assertEqual(result["dossier"]["total_urls_scanned"], before["dossier"]["total_urls_scanned"])
        self.scraper.fetch_url.assert_called_once_with(original_url)

    def test_upload_checks_actual_bytes_and_size_before_dispatch(self):
        before = self.seed()
        for content, expected in ((b"<html>not a PDF</html>", 422),
                                  (b"%PDF-1.7\n" + b"x" * (8 * 1024 * 1024), 413)):
            with self.subTest(expected=expected):
                self.assertEqual(self.upload(content).status_code, expected)
                self.assertEqual(self.store.get("ss_actions"), before)
        self.assertEqual(self.executor.pending, [])

    def test_upload_rejects_busy_or_absent_dossier(self):
        for status in api.ACTIVE_STATUSES:
            with self.subTest(status=status):
                self.seed(status=status)
                self.assertEqual(self.upload(pdf_bytes()).status_code, 409)
        session = self.seed()
        session["dossier"] = None
        self.store.put(session)
        self.assertEqual(self.upload(pdf_bytes()).status_code, 409)
        self.assertEqual(self.executor.pending, [])

    def test_pdf_upload_extracts_quotes_keeps_script_and_downloads_original_bytes(self):
        before = self.seed()
        content = pdf_bytes()
        response = self.upload(content, "C:\\folder\\tài liệu.pdf")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.instances, [])
        self.executor.run_next()
        after = self.store.get("ss_actions")
        self.assertEqual(after["status"], "awaiting_review")
        self.assertEqual(after["script"], before["script"])
        added = after["dossier"]["sources"][-1]
        self.assertTrue(added["is_accessible"])
        self.assertEqual(added["document_kind"], "uploaded_pdf")
        self.assertEqual(added["uploaded_filename"], "tài liệu.pdf")
        self.assertEqual(added["claims"][0]["snippet_quote"], pipeline_fixtures.EN_QUOTE)
        self.assertTrue(added["claims"][0]["is_verified"])
        evidence_url = f"/api/sessions/ss_actions/sources/{added['source_id']}"
        evidence = self.client.get(evidence_url).json()
        self.assertNotIn("uploaded_pdf_base64", evidence["raw_source"])
        self.assertNotIn(base64.b64encode(content).decode("ascii"), json.dumps(evidence))
        download = self.client.get(evidence_url + "/file")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["content-type"], "application/pdf")
        self.assertEqual(download.content, content)
        self.assertIn("filename*=UTF-8''", download.headers["content-disposition"])
        self.assertEqual(self.client.get("/api/sessions/ss_actions/sources/src_ok/file").status_code, 404)
        self.scraper.fetch_url.assert_not_called()

    def test_scanned_pdf_is_retained_but_never_becomes_evidence(self):
        before = self.seed()
        content = pdf_bytes(with_text=False)
        self.assertEqual(self.upload(content).status_code, 202)
        self.executor.run_next()
        after = self.store.get("ss_actions")
        added = after["dossier"]["sources"][-1]
        self.assertEqual(after["status"], "awaiting_review")
        self.assertEqual(after["script"], before["script"])
        self.assertFalse(added["is_accessible"])
        self.assertEqual(added["status"], "unreachable")
        self.assertEqual(added["claims"], [])
        self.assertIn("bản quét", added["error_message"])
        self.assertFalse(any(call["task"] == "evaluate_source" for call in self.llm.calls))
        download = self.client.get(f"/api/sessions/ss_actions/sources/{added['source_id']}/file")
        self.assertEqual(download.content, content)


if __name__ == "__main__":
    unittest.main()
