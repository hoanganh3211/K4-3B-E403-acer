"""API boundaries for the shared source and PDF limits; providers are simulated."""

import base64
import copy
import unittest
from unittest.mock import patch

import api_server as api
from models.limits import MAX_SOURCES, MAX_UPLOAD_MB, MAX_UPLOAD_BYTES

try:
    from tests import test_api as fixtures
except ImportError:
    import test_api as fixtures


class LimitPipeline(fixtures.FakePipeline):
    def add_pdf(self, session, filename, content):
        self._record("upload", {"filename": filename, "size": len(content)})
        dossier = copy.deepcopy(session["dossier"])
        dossier["sources"].append(fixtures.source_fixture(
            "src_uploaded", document_kind="uploaded_pdf", uploaded_filename=filename))
        dossier["total_urls_scanned"] += 1
        return {"dossier": dossier, "raw_sources": session["raw_sources"] + [{
            "source_id": "src_uploaded", "uploaded_filename": filename,
            "uploaded_pdf_base64": base64.b64encode(content).decode("ascii"),
        }]}


class SourceLimitTests(unittest.TestCase):
    def setUp(self):
        fixtures.APITests.setUp(self)

        def factory(progress):
            pipeline = LimitPipeline(progress)
            self.instances.append(pipeline)
            return pipeline

        self.stack.enter_context(patch.object(api, "PipelineService", side_effect=factory))

    def seed_sources(self, count):
        sources = [fixtures.source_fixture(f"src_{index}") for index in range(count)]
        session = fixtures.APITests.seed(self, status="script_ready", with_script=True, sources=sources)
        session["dossier"]["total_urls_scanned"] = count
        session["active_source_ids"] = [source["source_id"] for source in sources]
        self.store.put(session)
        return session

    def upload(self, content):
        return self.client.post("/api/pipeline/sources/upload", data={"session_id": "ss_test"},
                                files={"file": ("research.pdf", content, "application/pdf")})

    def test_start_accepts_fifty_sources_and_preserves_requested_limit(self):
        self.assertEqual(MAX_SOURCES, 50)
        response = self.client.post("/api/pipeline/start", json={**fixtures.LESSON, "max_sources": 50})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["req"]["max_sources"], 50)
        self.executor.run_next()
        self.assertEqual(self.instances[0].calls[0][1]["max_sources"], 50)

    def test_start_rejects_fifty_one_sources_before_creating_work(self):
        response = self.client.post("/api/pipeline/start", json={**fixtures.LESSON, "max_sources": 51})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.executor.pending, [])
        self.assertTrue(any(error["loc"] == ["body", "max_sources"] for error in response.json()["detail"]))

    def test_review_can_approve_all_fifty_sources(self):
        before = self.seed_sources(50)
        ids = before["active_source_ids"]
        response = self.client.post("/api/pipeline/review", json={
            "session_id": "ss_test", "approved_source_ids": ids})
        self.assertEqual(response.status_code, 202)
        self.executor.run_next()
        self.assertEqual(self.instances[0].calls, [("review", ids)])
        self.assertEqual(self.store.get("ss_test")["active_source_ids"], ids)

    def test_patch_can_remove_all_fifty_sources(self):
        before = self.seed_sources(50)
        ids = before["active_source_ids"]
        response = self.client.post("/api/pipeline/patch", json={
            "session_id": "ss_test", "remove_source_ids": ids})
        self.assertEqual(response.status_code, 202)
        self.executor.run_next()
        self.assertEqual(self.instances[0].calls, [("patch", ids)])
        self.assertEqual(self.store.get("ss_test")["active_source_ids"], [])

    def test_review_and_patch_reject_fifty_one_ids_at_request_validation(self):
        self.seed_sources(50)
        ids = [f"src_{index}" for index in range(51)]
        for endpoint, field in (("review", "approved_source_ids"), ("patch", "remove_source_ids")):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(f"/api/pipeline/{endpoint}", json={"session_id": "ss_test", field: ids})
                self.assertEqual(response.status_code, 422)
                self.assertTrue(any(error["loc"] == ["body", field] for error in response.json()["detail"]))
        self.assertEqual(self.executor.pending, [])

    def test_adding_url_reaches_fifty_and_rejects_next_source(self):
        before = self.seed_sources(49)
        response = self.client.post("/api/pipeline/sources", json={
            "session_id": "ss_test", "url": "https://example.org/new-document"})
        self.assertEqual(response.status_code, 202)
        self.executor.run_next()
        after = self.store.get("ss_test")
        self.assertEqual(len(after["dossier"]["sources"]), 50)
        self.assertEqual(after["script"], before["script"])
        rejected = self.client.post("/api/pipeline/sources", json={
            "session_id": "ss_test", "url": "https://example.org/source-fifty-one"})
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("50", rejected.json()["detail"])
        self.assertEqual(self.executor.pending, [])
        self.assertEqual(self.store.get("ss_test"), after)

    def test_adding_pdf_reaches_fifty_and_rejects_next_source(self):
        before = self.seed_sources(49)
        response = self.upload(b"%PDF-1.7\nfixture handled by fake pipeline")
        self.assertEqual(response.status_code, 202)
        self.executor.run_next()
        after = self.store.get("ss_test")
        self.assertEqual(len(after["dossier"]["sources"]), 50)
        self.assertEqual(after["script"], before["script"])
        rejected = self.upload(b"%PDF-1.7\nsecond fixture")
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("50", rejected.json()["detail"])
        self.assertEqual(self.executor.pending, [])
        self.assertEqual(self.store.get("ss_test"), after)

    def test_pdf_upload_accepts_exactly_eight_mb_and_rejects_one_extra_byte(self):
        self.assertEqual(MAX_UPLOAD_MB, 8)
        self.assertEqual(MAX_UPLOAD_BYTES, 8 * 1024 * 1024)
        self.seed_sources(3)
        content = b"%PDF-1.7\n" + b" " * (MAX_UPLOAD_BYTES - len(b"%PDF-1.7\n"))
        response = self.upload(content)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.executor.pending), 1)
        self.assertEqual(len(self.executor.pending[0][1][2]["content"]), MAX_UPLOAD_BYTES)
        self.executor.pending.clear()
        self.seed_sources(3)
        response = self.upload(content + b" ")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.executor.pending, [])


if __name__ == "__main__":
    unittest.main()
