"""Studio workflow tests: real Streamlit rendering, deterministic API boundary."""
import copy
import json
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest
from services.admission_policy import ADMISSION_POLICY_VERSION


APP_PATH = Path(__file__).resolve().parents[1] / "app_ui.py"


def response(data=None, status=200, content=None):
    result = requests.Response()
    result.status_code = status
    result._content = content if content is not None else json.dumps(data).encode("utf-8")
    return result


def source(source_id, **overrides):
    result = {
        "source_id": source_id, "title": f"Nghiên cứu {source_id}",
        "url": f"https://example.org/{source_id}", "language": "en", "trust_score": 75,
        "status": "pending", "is_accessible": True, "summary_vi": "Tóm tắt bằng tiếng Việt.",
        "claims": [{
            "claim_id": f"{source_id}C1", "claim_text": "Thông tin thay đổi.",
            "snippet_quote": "Information changes.", "snippet_translation_vi": "Thông tin thay đổi.",
            "is_verified": True, "is_statistical": False,
        }],
    }
    result.update(overrides)
    return result


class FakeAPI:
    def __init__(self):
        self.session = None
        self.posts = []
        self.configured = True
        self.admission = {"required": True, "policy_version": ADMISSION_POLICY_VERSION, "configured": True}
        self.auto_complete = True
        self.other_sessions = {}
        self.deletes = []
        self.calls = []
        self.sources = [
            source("S1"), source("S2"), source("S3", status="blocked"),
            source("S4", claims=[{"is_verified": False}]), source("S5", is_accessible=False),
            source("S6", status="rejected"),
        ]
        self.script = {
            "title": "Bài giảng", "teaching_style": "Hỏi đáp", "estimated_duration_minutes": 5,
            "verification_summary": {
                "total_lines": 1, "factual_lines": 1, "unverified_lines": 1,
                "original_quotes_matched": 1, "human_review_required": True,
            }, "warnings": [],
            "scenes": [{
                "scene_number": 1, "scene_label": "Mở đầu", "estimated_duration_seconds": 40,
                "visual_cue": "Hình minh họa", "speaker_note": "Dừng lại để hỏi.",
                "lines": [{
                    "text": "Thông tin thay đổi.", "has_factual_content": True, "is_unverified": True,
                    "verification_note": "Cần đối chiếu ý nghĩa", "source_refs": [{
                        "source_id": "S1", "claim_id": "S1C1", "url": "https://example.org/S1",
                        "snippet_quote": "Information changes.", "snippet_translation_vi": "Thông tin thay đổi.",
                        "is_verified": True,
                    }],
                }],
            }],
        }

    def envelope(self, session=None):
        session = session if session is not None else self.session
        return {"session_id": session["session_id"], "status": session["status"], "data": copy.deepcopy(session)}

    def __call__(self, method, url, json=None, **kwargs):
        path = url.split(":8000")[-1]
        self.calls.append((method, path))
        if path == "/api/health":
            return response({
                **({"research_admission": self.admission} if self.admission is not None else {}),
                "status": "ok", "configuration": {
                    "llm_provider": "openai", "model": "test", "llm_configured": self.configured,
                    "search_configured": self.configured,
                }, "trust_criteria": {
                    "domain_authority": {"weight": .30, "description": "Nguồn gốc là một dấu hiệu để sàng lọc."},
                },
            })
        if path == "/api/sessions":
            sessions = list(self.other_sessions.values()) + ([self.session] if self.session else [])
            return response({"sessions": [{"session_id": item["session_id"], "topic": "Bài giảng", "status": item["status"]} for item in sessions]})
        if method == "DELETE":
            session_id = path.rsplit("/", 1)[-1]
            self.deletes.append(session_id)
            if self.session and self.session["session_id"] == session_id:
                self.session = None
            else:
                self.other_sessions.pop(session_id)
            return response({"deleted": True, "session_id": session_id})
        if method == "POST":
            self.posts.append((path, json))
            if path.endswith("/start"):
                self.session = {
                    "session_id": "test-ui", "status": "researching", "req": json,
                    "dossier": {
                        "sources": copy.deepcopy(self.sources), "warnings": ["Cần đối chiếu"],
                        "conflicts": [{
                            "topic": "Hai cách giải thích", "source_a_id": "S1", "source_b_id": "S2",
                            "source_a_claim": "Luận điểm một", "source_b_claim": "Luận điểm hai",
                        }], "search_queries_used": ["attention", "chú ý"],
                    },
                    "progress": [{"step": "research", "message": "Đang đọc nguồn"}],
                    "active_source_ids": [], "script": None,
                }
            elif path.endswith("/review"):
                self.session.update(status="writing", active_source_ids=json["approved_source_ids"])
            elif path.endswith("/patch"):
                self.session.update(status="patching", active_source_ids=[
                    sid for sid in self.session["active_source_ids"] if sid not in json["remove_source_ids"]
                ])
            elif path.endswith("/sources"):
                self.session["status"] = "adding_source"
            elif path.endswith("/sources/retry"):
                self.session["status"] = "researching"
            return response(self.envelope())
        if "/export?" in path:
            return response(content=b"export content")
        if "/sources/" in path:
            return response({"source": self.sources[0], "raw_source": {
                "raw_markdown": "Information changes. <script>alert('untrusted')</script>",
                "content_hash": "sha256-test", "fetched_at": "2026-09-18T00:00:00Z",
            }})
        if path.startswith("/api/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            if session_id in self.other_sessions:
                return response(self.envelope(self.other_sessions[session_id]))
            if self.auto_complete:
                if self.session["status"] in {"researching", "adding_source"}:
                    self.session["status"] = "awaiting_review"
                elif self.session["status"] in {"writing", "patching"}:
                    self.session.update(status="script_ready", script=copy.deepcopy(self.script))
            return response(self.envelope())
        raise AssertionError((method, url))


def button(app, label):
    return next(item for item in app.button if item.label == label)


class StudioTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.api = FakeAPI()
        self.network = patch("requests.request", side_effect=self.api)
        self.network.start()
        self.env = patch.dict("os.environ", {"SCRIPTSCOUT_API_URL": "http://localhost:8000"})
        self.env.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.env.stop)

    def app(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()
        self.assertFalse(app.exception)
        return app

    def submit_request(self, app):
        app.text_input[0].set_value("Transformer")
        app.text_input[1].set_value("Sinh viên CNTT")
        app.text_area[0].set_value("Hiểu cơ chế chú ý\nBiết ứng dụng")
        app.text_area[1].set_value("Tôi dùng ví dụ Việt Nam và câu hỏi gợi mở.")
        button(app, "Tìm tài liệu và lập hồ sơ").click().run()
        self.assertFalse(app.exception)

    def test_complete_workflow_and_source_removal_sync(self):
        app = self.app()
        self.submit_request(app)
        self.assertEqual(self.api.posts[0][1]["source_languages"], ["vi", "en"])
        self.assertIn("Tôi dùng ví dụ Việt Nam", self.api.posts[0][1]["teaching_style"])
        self.assertEqual(app.session_state["session"]["status"], "awaiting_review")
        checks = {item.key: item for item in app.checkbox}
        for sid in ["S1", "S2", "S6"]:
            self.assertTrue(checks[f"approve:test-ui:{sid}"].value)
        for sid in ["S3", "S4", "S5"]:
            self.assertTrue(checks[f"approve:test-ui:{sid}"].disabled)
            self.assertFalse(checks[f"approve:test-ui:{sid}"].value)
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts[-1][1]["approved_source_ids"], ["S1", "S2", "S6"])
        self.assertEqual(app.session_state["session"]["status"], "script_ready")
        self.assertTrue(any(item.value == "Cần đối chiếu ý nghĩa" for item in app.warning))
        self.assertEqual([item.label for item in app.metric], [
            "Tổng số câu", "Câu chứa thông tin thực tế", "Câu cần kiểm tra thêm", "Trích dẫn khớp nguyên văn",
        ])
        self.assertTrue(any("Uy tín nơi xuất bản" in item.value for item in app.markdown))
        self.assertFalse(any("domain_authority" in item.value or "total_lines" in item.value for item in app.markdown))
        self.assertEqual(app.session_state["workspace_view"], "script")
        app.button(key="view_sources:bottom").click().run()
        self.assertFalse(button(app, "Cập nhật nguồn đã duyệt").disabled)
        app.button(key="view_script:bottom").click().run()
        next(item for item in app.multiselect if item.label == "Nguồn muốn loại bỏ").set_value(["S1"]).run()
        button(app, "Bỏ nguồn và cập nhật kịch bản").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts[-1][1]["remove_source_ids"], ["S1"])
        app.button(key="view_sources:bottom").click().run()
        checks = {item.key: item for item in app.checkbox}
        self.assertFalse(checks["approve:test-ui:S1"].value, "Removed source must not silently rejoin a rewritten script")
        button(app, "Chuẩn bị tệp tải xuống").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("download_button")), 2)
        button(app, "＋ Bài giảng mới").click().run()
        self.assertIsNone(app.session_state["session_id"])
        button(app, "Mở phiên đã chọn").click().run()
        self.assertEqual(app.session_state["session_id"], "test-ui")
        self.assertFalse(app.exception)

    def test_existing_script_update_label_and_removing_all_sources(self):
        app = self.app()
        self.submit_request(app)
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        app.button(key="view_sources:bottom").click().run()
        app.checkbox(key="approve:test-ui:S6").uncheck().run()
        button(app, "Cập nhật nguồn đã duyệt").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts[-1][1]["approved_source_ids"], ["S1", "S2"])
        next(item for item in app.multiselect if item.label == "Nguồn muốn loại bỏ").set_value(["S1", "S2"]).run()
        self.assertFalse(button(app, "Bỏ nguồn và cập nhật kịch bản").disabled)
        button(app, "Bỏ nguồn và cập nhật kịch bản").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts[-1][1]["remove_source_ids"], ["S1", "S2"])
        self.assertEqual(app.session_state["session"]["active_source_ids"], [])
        app.button(key="view_sources:bottom").click().run()
        self.assertFalse(app.checkbox(key="approve:test-ui:S1").value)
        self.assertFalse(app.checkbox(key="approve:test-ui:S2").value)

    def test_saved_evidence_is_plaintext_and_add_source_preserves_script(self):
        app = self.app()
        self.submit_request(app)
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        app.button(key="view_sources:bottom").click().run()
        app.button(key="evidence:test-ui:S1").click().run()
        snapshot = app.text_area(key="raw:test-ui:S1")
        self.assertTrue(snapshot.disabled)
        self.assertIn("<script>", snapshot.value)
        original_script = copy.deepcopy(app.session_state["session"]["script"])
        next(item for item in app.text_input if item.label == "Đường dẫn tài liệu").set_value("https://example.org/paper.pdf")
        button(app, "Đọc và bổ sung nguồn").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["session"]["script"], original_script)
        self.assertEqual(self.api.posts[-1][1]["url"], "https://example.org/paper.pdf")
        self.assertEqual(app.session_state["workspace_view"], "sources")

    def test_busy_session_locks_mutations(self):
        self.api.auto_complete = False
        app = self.app()
        self.submit_request(app)
        self.assertEqual(app.session_state["session"]["status"], "researching")
        for label in ["＋ Bài giảng mới", "Xóa phiên", "Duyệt nguồn và viết kịch bản", "Đọc và bổ sung nguồn", "Đọc PDF của tôi", "Chuẩn bị tệp tải xuống"]:
            self.assertTrue(button(app, label).disabled)
        self.assertTrue(all(item.disabled for item in app.checkbox))
        self.assertTrue(all(item.disabled for item in app.button if item.label == "Tìm bản công khai và đọc lại"))

    def test_activity_indicator_follows_actual_job_status_and_stops_when_done(self):
        self.api.auto_complete = False
        app = self.app()
        self.submit_request(app)
        for status in ("researching", "writing", "patching", "adding_source"):
            self.api.session["status"] = status
            app.session_state["session"]["status"] = status
            app.run()
            indicators = [item.value for item in app.markdown if '<div class="ss-activity-track"' in item.value]
            self.assertEqual(len(indicators), 1, status)
            self.assertIn('role="progressbar"', indicators[0])
            self.assertNotIn("aria-valuenow", indicators[0], "An unknown duration must not be represented as a made-up percentage")
            self.assertTrue(any("Tự cập nhật mỗi 3 giây" in item.value for item in app.caption))
        self.api.session["status"] = "researching"
        app.session_state["session"]["status"] = "researching"
        self.api.auto_complete = True
        app.run()
        self.assertEqual(app.session_state["session"]["status"], "awaiting_review")
        self.assertFalse(any('<div class="ss-activity-track"' in item.value for item in app.markdown))
        self.api.session["status"] = "failed"
        app.session_state["session"]["status"] = "failed"
        app.run()
        self.assertFalse(any('<div class="ss-activity-track"' in item.value for item in app.markdown))

    def test_navigation_preserves_unsubmitted_source_choices(self):
        app = self.app()
        self.submit_request(app)
        app.checkbox(key="approve:test-ui:S2").uncheck().run()
        app.button(key="view_script:bottom").click().run()
        self.assertEqual(app.session_state["workspace_view"], "script")
        self.assertEqual(len(app.checkbox), 0, "Only the chosen view should render")
        app.button(key="view_sources:sidebar").click().run()
        self.assertFalse(app.checkbox(key="approve:test-ui:S2").value)
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        self.assertEqual(self.api.posts[-1][1]["approved_source_ids"], ["S1", "S6"])
        self.assertEqual(app.session_state["workspace_view"], "script")
        app.button(key="view_sources:top").click().run()
        app.checkbox(key="approve:test-ui:S6").uncheck().run()
        app.button(key="view_script:sidebar").click().run()
        app.button(key="view_sources:bottom").click().run()
        self.assertFalse(app.checkbox(key="approve:test-ui:S6").value)
        self.assertFalse(any(item.label == "Làm mới trạng thái phiên" for item in app.button))

    def test_permanent_delete_current_session_cleans_only_its_state(self):
        app = self.app()
        self.submit_request(app)
        app.button(key="evidence:test-ui:S1").click().run()
        app.session_state["evidence"]["unrelated:S9"] = {"raw_markdown": "Keep me"}
        app.session_state["source_choices"]["unrelated:S9"] = {"selected": True, "active": False}
        button(app, "Xóa phiên").click().run()
        self.assertEqual(self.api.deletes, [])
        button(app, "Xóa vĩnh viễn").click().run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state["session_id"])
        self.assertIsNone(app.session_state["session"])
        self.assertEqual(list(app.session_state["evidence"]), ["unrelated:S9"])
        self.assertEqual(list(app.session_state["source_choices"]), ["unrelated:S9"])
        self.assertEqual(self.api.deletes, ["test-ui"])
        self.assertTrue(any(item.value.startswith("Đã xóa vĩnh viễn") for item in app.get("toast")))
        self.assertIsNone(self.api.session)
        self.assertFalse(any(item.label in {"Hoàn tác xóa", "Khôi phục phiên"} for item in app.button))
        self.assertFalse(any("deleted=" in path or path.endswith("/restore") for _, path in self.api.calls))

    def test_delete_other_session_keeps_current_work_and_stays_deleted_after_reload(self):
        app = self.app()
        self.submit_request(app)
        app.checkbox(key="approve:test-ui:S2").uncheck().run()
        other = copy.deepcopy(self.api.session)
        other["session_id"] = "other-session"
        self.api.other_sessions["other-session"] = other
        app.run()
        next(item for item in app.selectbox if item.label == "Chọn bài giảng").set_value("other-session").run()
        button(app, "Xóa phiên").click().run()
        button(app, "Xóa vĩnh viễn").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["session_id"], "test-ui")
        self.assertFalse(app.checkbox(key="approve:test-ui:S2").value)
        self.assertNotIn("other-session", self.api.other_sessions)
        reloaded = self.app()
        self.assertFalse(reloaded.exception)
        self.assertEqual(len(next(item for item in reloaded.selectbox if item.label == "Chọn bài giảng").options), 1)
        self.assertFalse(any(item.label in {"Hoàn tác xóa", "Khôi phục phiên"} for item in reloaded.button))

    def test_cancel_permanent_deletion_keeps_session(self):
        app = self.app()
        self.submit_request(app)
        button(app, "Xóa phiên").click().run()
        button(app, "Hủy").click().run()
        self.assertEqual(self.api.deletes, [])
        self.assertEqual(app.session_state["session_id"], "test-ui")
        self.assertFalse(any(item.label == "Xóa vĩnh viễn" for item in app.button))

    def test_fifty_sources_paginate_filter_and_preserve_all_approval_choices(self):
        self.api.sources = [source(f"S{index}") for index in range(1, 51)]
        app = self.app()
        next(item for item in app.slider if item.label == "Số nguồn tối đa để đọc và thẩm định").set_value(50)
        self.submit_request(app)
        self.assertEqual(self.api.posts[0][1]["max_sources"], 50)
        self.assertEqual(len(app.checkbox), 8)
        app.checkbox(key="approve:test-ui:S2").uncheck().run()
        next(item for item in app.selectbox if item.label == "Trang tài liệu").set_value(7).run()
        self.assertEqual(len(app.checkbox), 2)
        app.checkbox(key="approve:test-ui:S49").uncheck().run()
        app.text_input(key="source-query:test-ui").set_value("S1").run()
        self.assertTrue(all(item.key not in {"approve:test-ui:S2", "approve:test-ui:S49"} for item in app.checkbox))
        app.button(key="view_script:bottom").click().run()
        app.button(key="view_sources:bottom").click().run()
        self.assertEqual(app.text_input(key="source-query:test-ui").value, "S1")
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        approved = self.api.posts[-1][1]["approved_source_ids"]
        self.assertEqual(len(approved), 48)
        self.assertNotIn("S2", approved)
        self.assertNotIn("S49", approved)
        self.assertIn("S50", approved)

    def test_upload_widget_and_helper_share_eight_mb_limit(self):
        app = self.app()
        self.submit_request(app)
        uploader = app.get("file_uploader")[0]
        self.assertEqual(uploader.proto.max_upload_size_mb, 8)
        self.assertEqual(list(uploader.proto.type), [".pdf"])
        self.assertTrue(any("tối đa 8 MB" in item.value for item in app.caption))

    def test_readable_source_labels_and_verified_notes_stay_in_citations(self):
        self.api.sources = [source("src_9f03e", title="Nghiên cứu về học tập", language="unknown")]
        line = self.api.script["scenes"][0]["lines"][0]
        line.update(is_unverified=False, verification_note="Trích dẫn khớp; giảng viên vẫn cần duyệt.")
        line["source_refs"][0]["source_id"] = "src_9f03e"
        self.api.script["scenes"][0]["lines"].append({
            "text": "Tiếp theo, hãy cùng xem một ví dụ.", "source_refs": [],
            "is_unverified": False, "has_factual_content": False,
            "verification_note": line["verification_note"],
        })
        app = self.app()
        self.submit_request(app)
        self.assertTrue(any("01 · Nghiên cứu về học tập" in item.value for item in app.markdown))
        self.assertTrue(any("ss-meta" in item.value and "Chưa rõ ngôn ngữ" in item.value and "Điểm sàng lọc" in item.value for item in app.markdown))
        self.assertFalse(any("src_9f03e" in item.value for item in app.markdown))
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        self.assertFalse(app.exception)
        citation = next(item for item in app.expander if item.label == "Xem dẫn chứng · 1 nguồn")
        self.assertTrue(any(item.value == line["verification_note"] for item in citation.caption))
        self.assertEqual(sum(item.value == line["verification_note"] for item in app.caption), 1)
        self.assertFalse(any("src_9f03e" in item.value for item in app.markdown))
        self.assertTrue(next(item for item in app.multiselect if item.label == "Nguồn muốn loại bỏ").options[0].startswith("Nguồn 01"))

    def test_403_recovery_and_old_warning_copy(self):
        self.api.sources[0].update(warnings=["Đã loại 16 phần tử HTML bị ẩn khỏi nội dung dùng làm dẫn chứng.", "Cần kiểm tra số liệu."])
        self.api.sources[4].update(
            error_message="Không tải được tài liệu (HTTP 403).",
            trust_reasoning="Không đọc được toàn văn; không dùng đoạn mô tả tìm kiếm làm bằng chứng.",
        )
        self.api.sources[2].update(has_prompt_injection=True, warnings=["Phát hiện chỉ dẫn đáng ngờ."])
        app = self.app()
        self.submit_request(app)
        messages = [item.value for name in ("warning", "info", "error", "caption") for item in app.get(name)]
        self.assertFalse(any("phần tử HTML" in message or "HTTP 403" in message for message in messages))
        self.assertTrue(any("Trang xuất bản không cho phép" in message for message in messages))
        self.assertTrue(any("chỉ dẫn đáng ngờ" in message for message in messages))
        self.assertTrue(any("Cần kiểm tra số liệu" in message for message in messages))
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        original_script = copy.deepcopy(app.session_state["session"]["script"])
        app.button(key="view_sources:bottom").click().run()
        app.button(key="retry:test-ui:S5").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts[-1], ("/api/pipeline/sources/retry", {"session_id": "test-ui", "source_id": "S5"}))
        self.assertEqual(app.session_state["workspace_view"], "sources")
        self.assertEqual(app.session_state["session"]["script"], original_script)

    def test_recovered_and_uploaded_source_provenance(self):
        self.api.sources[0].update(original_url="https://publisher.example/paper", final_url="https://repository.example/paper.pdf", retrieval_method="public_repository")
        self.api.sources[1].update(url="urn:scriptscout:upload:local", document_kind="uploaded_pdf", uploaded_filename="nghien-cuu.pdf")
        app = self.app()
        self.submit_request(app)
        links = {item.proto.label: item.proto.url for item in app.get("link_button")}
        self.assertEqual(links["Mở bản công khai đã đọc ↗"], "https://repository.example/paper.pdf")
        self.assertEqual(links["Trang xuất bản ban đầu ↗"], "https://publisher.example/paper")
        self.assertTrue(any("nghien-cuu.pdf" in item.value for item in app.caption))

    def test_missing_configuration_blocks_start(self):
        self.api.configured = False
        app = self.app()
        self.assertTrue(button(app, "Tìm tài liệu và lập hồ sơ").disabled)
        self.assertTrue(any("tạm gián đoạn" in item.value for item in app.warning))
        self.assertFalse(any(item.label == "Trạng thái kết nối" for item in app.expander))
        self.assertFalse(any(item.label == "Kiểm tra lại kết nối" for item in app.button))

    def test_unknown_or_outdated_admission_capability_blocks_new_research(self):
        for capability in (
            None,
            {},
            {"required": False, "policy_version": "outdated", "configured": True},
            {"required": False, "policy_version": ADMISSION_POLICY_VERSION, "configured": True},
            {"required": "true", "policy_version": ADMISSION_POLICY_VERSION, "configured": True},
            {"required": True, "policy_version": "outdated", "configured": True},
            {"required": True, "policy_version": None, "configured": True},
            {"required": True, "policy_version": ADMISSION_POLICY_VERSION, "configured": False},
        ):
            with self.subTest(capability=capability):
                st.cache_data.clear()
                self.api.admission = capability
                app = self.app()
                self.assertTrue(button(app, "Tìm tài liệu và lập hồ sơ").disabled)
                self.assertTrue(any("Ứng dụng đang cập nhật bước kiểm tra nội dung" in item.value for item in app.warning))
                self.assertFalse(any(method == "POST" for method, _ in self.api.calls))
                self.assertIsNone(app.session_state["session_id"])

    def test_old_backend_blocks_existing_paid_actions_but_keeps_read_delete_export(self):
        app = self.app()
        self.submit_request(app)
        before = list(self.api.posts)
        self.api.admission = None
        # Keep the positive display cache: a downgraded server must still be
        # detected by a fresh capability check immediately before each POST.
        app.run()
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        self.assertEqual(self.api.posts, before)
        self.assertTrue(any("Ứng dụng đang cập nhật bước kiểm tra nội dung" in item.value for item in app.error))
        next(item for item in app.text_input if item.label == "Đường dẫn tài liệu").set_value("https://example.org/paper.pdf")
        button(app, "Đọc và bổ sung nguồn").click().run()
        app.button(key="retry:test-ui:S5").click().run()
        self.assertEqual(self.api.posts, before)
        self.api.session.update(status="script_ready", script=copy.deepcopy(self.api.script), active_source_ids=["S1", "S2"])
        app.session_state["session"] = copy.deepcopy(self.api.session)
        app.button(key="view_script:top").click().run()
        next(item for item in app.multiselect if item.label == "Nguồn muốn loại bỏ").set_value(["S1"]).run()
        button(app, "Bỏ nguồn và cập nhật kịch bản").click().run()
        self.assertEqual(self.api.posts, before)
        app.button(key="view_sources:top").click().run()
        pdf = BytesIO(b"%PDF-1.4\nlocal test placeholder")
        pdf.name = "lesson.pdf"
        pdf.size = len(pdf.getvalue())
        with patch("streamlit.file_uploader", return_value=pdf):
            app.run()
            button(app, "Đọc PDF của tôi").click().run()
        self.assertEqual(self.api.posts, before)
        self.assertTrue(any("Ứng dụng đang cập nhật bước kiểm tra nội dung" in item.value for item in app.error))
        app.button(key="evidence:test-ui:S1").click().run()
        self.assertIn("Information changes", app.text_area(key="raw:test-ui:S1").value)
        button(app, "Chuẩn bị tệp tải xuống").click().run()
        self.assertEqual(len(app.get("download_button")), 2)
        button(app, "＋ Bài giảng mới").click().run()
        button(app, "Mở phiên đã chọn").click().run()
        self.assertEqual(app.session_state["session_id"], "test-ui")
        button(app, "Xóa phiên").click().run()
        button(app, "Xóa vĩnh viễn").click().run()
        self.assertEqual(self.api.deletes, ["test-ui"])
        self.assertEqual(self.api.posts, before)
        self.assertFalse(app.exception)

    def test_local_content_guard_blocks_before_any_post(self):
        app = self.app()
        app.text_input[0].set_value("Viết kịch bản khiêu dâm 18+")
        app.text_input[1].set_value("Người học")
        app.text_area[0].set_value("Xây dựng nội dung video")
        button(app, "Tìm tài liệu và lập hồ sơ").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts, [])
        self.assertFalse(any(method == "POST" for method, _ in self.api.calls))
        self.assertIsNone(app.session_state["session_id"])
        self.assertTrue(any("môi trường học tập" in item.value for item in app.error))

    def test_reported_gambling_phrase_is_rejected_before_any_post(self):
        app = self.app()
        topic = "Hướng dẫn đánh bạc trên mạng kiếm tiền"
        app.text_input[0].set_value(topic)
        app.text_input[1].set_value("Người học trưởng thành")
        app.text_area[0].set_value("Hiểu chủ đề và các ví dụ")
        button(app, "Tìm tài liệu và lập hồ sơ").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts, [])
        self.assertFalse(any(method == "POST" for method, _ in self.api.calls))
        self.assertIsNone(self.api.session)
        self.assertIsNone(app.session_state["session_id"])
        self.assertEqual(app.text_input[0].value, topic, "Keep the input so the teacher can revise it")
        self.assertTrue(any("phòng ngừa" in item.value for item in app.error))

    def test_preventive_gambling_title_cannot_hide_profit_objective_before_post(self):
        app = self.app()
        topic = "Phòng chống cờ bạc trực tuyến"
        objective = "Biết cách nạp tiền vào nhà cái để kiếm lời"
        app.text_input[0].set_value(topic)
        app.text_input[1].set_value("Người học trưởng thành")
        app.text_area[0].set_value(objective)
        button(app, "Tìm tài liệu và lập hồ sơ").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts, [])
        self.assertFalse(any(method == "POST" for method, _ in self.api.calls))
        self.assertIsNone(self.api.session)
        self.assertIsNone(app.session_state["session_id"])
        self.assertEqual(app.text_area[0].value, objective)
        self.assertTrue(any("phòng ngừa" in item.value for item in app.error))

    def test_local_content_guard_allows_educational_sexual_health(self):
        app = self.app()
        app.text_input[0].set_value("Giáo dục giới tính và sức khỏe sinh sản")
        app.text_input[1].set_value("Sinh viên đại học")
        app.text_area[0].set_value("Hiểu về sự đồng thuận\nPhòng ngừa bệnh lây truyền qua đường tình dục")
        button(app, "Tìm tài liệu và lập hồ sơ").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(self.api.posts[0][0], "/api/pipeline/start")

    def test_saved_unsafe_lesson_cannot_trigger_paid_action(self):
        app = self.app()
        self.submit_request(app)
        prior_posts = list(self.api.posts)
        app.session_state["session"]["req"]["topic"] = "Cách sản xuất ma túy"
        app.run()
        button(app, "Duyệt nguồn và viết kịch bản").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts, prior_posts)
        self.assertEqual(app.session_state["session_id"], "test-ui")
        self.assertTrue(any("phòng ngừa" in item.value for item in app.error))

    def test_unsafe_source_url_is_rejected_before_post(self):
        app = self.app()
        self.submit_request(app)
        prior_posts = list(self.api.posts)
        next(item for item in app.text_input if item.label == "Đường dẫn tài liệu").set_value("https://example.org/phim-sex")
        button(app, "Đọc và bổ sung nguồn").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.api.posts, prior_posts)
        self.assertTrue(any("môi trường học tập" in item.value for item in app.error))

    def test_metadata_badges_and_native_navigation_replace_radio(self):
        self.api.sources[3].update(language="vi", trust_score=36)
        app = self.app()
        self.submit_request(app)
        badges = [item.value for item in app.markdown if '<div class="ss-meta">' in item.value]
        self.assertTrue(any('ss-badge--review' in value and 'Ngôn ngữ: Tiếng Việt' in value and '<strong>36/100</strong>' in value for value in badges))
        self.assertTrue(any('ss-badge--ready' in value for value in badges))
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(app.button(key="view_sources:top").proto.type, "primary")
        app.button(key="view_script:top").click().run()
        self.assertEqual(app.session_state["workspace_view"], "script")
        self.assertEqual(app.button(key="view_script:top").proto.type, "primary")
        app.button(key="view_sources:sidebar").click().run()
        self.assertEqual(app.session_state["workspace_view"], "sources")

    def test_saved_diagnostics_and_provider_errors_are_not_shown(self):
        app = self.app()
        self.submit_request(app)
        saved = app.session_state["session"]
        diagnostic = "Gemini API_KEY in .env failed at endpoint localhost:8000 (HTTP 429); provider quota"
        saved.update(status="failed", error_message=diagnostic, progress=[{"step": "failed", "message": diagnostic}])
        saved["dossier"]["warnings"].append(diagnostic)
        saved["dossier"]["sources"][0]["warnings"] = [diagnostic, "Cần đối chiếu số liệu trước khi giảng."]
        app.run()
        self.assertFalse(app.exception)
        messages = "\n".join(item.value for kind in ("error", "warning", "info", "caption", "markdown") for item in app.get(kind))
        for token in ("Gemini", "API_KEY", ".env", "HTTP 429", "localhost", "provider quota"):
            self.assertNotIn(token, messages)
        self.assertIn("Cần đối chiếu số liệu trước khi giảng", messages)
        self.assertFalse(any(item.label == "Trạng thái kết nối" for item in app.expander))
        original = self.api.__call__

        def provider_failure(method, url, **kwargs):
            if method == "POST":
                return response({"detail": diagnostic}, status=429)
            return original(method, url, **kwargs)

        with patch("requests.request", side_effect=provider_failure):
            button(app, "Duyệt nguồn và viết kịch bản").click().run()
        self.assertTrue(any("Chưa thể hoàn tất" in item.value for item in app.error))
        self.assertFalse(any("Gemini" in item.value or "HTTP" in item.value for item in app.error))

    def test_server_content_rejection_keeps_public_message(self):
        app = self.app()
        original = self.api.__call__
        message = "Hãy chọn chủ đề phù hợp với môi trường học tập."

        def reject_post(method, url, **kwargs):
            if method == "POST":
                return response({"detail": {"code": "content_not_allowed", "message": message, "field": "topic", "category": "adult_content"}}, status=422)
            return original(method, url, **kwargs)

        with patch("requests.request", side_effect=reject_post):
            self.submit_request(app)
        self.assertTrue(any(item.value == message for item in app.error))
        self.assertIsNone(app.session_state["session_id"])

    def test_semantic_review_outcomes_preserve_inputs_without_retry_or_research(self):
        outcomes = (
            ("content_not_allowed", 422, "Nội dung này chưa phù hợp với phạm vi học tập. Hãy chuyển sang mục đích phòng chống rõ ràng."),
            ("content_needs_clarification", 422, "Hãy mô tả rõ mục đích phòng chống và điều người học cần biết trước khi tiếp tục."),
            ("content_review_unavailable", 503, "Chưa thể kiểm tra mục đích bài giảng lúc này. Vui lòng thử lại sau."),
        )
        for code, status, message in outcomes:
            with self.subTest(code=code):
                app = self.app()
                submitted = []
                original = self.api.__call__

                def moderate_request(method, url, json=None, **kwargs):
                    if method == "POST":
                        submitted.append((url, copy.deepcopy(json)))
                        return response({"detail": {"code": code, "message": message, "field": "objectives"}}, status=status)
                    return original(method, url, json=json, **kwargs)

                app.text_input[0].set_value("An toàn thông tin cho sinh viên")
                app.text_input[1].set_value("Sinh viên năm nhất")
                app.text_area[0].set_value("Hiểu cách bảo vệ dữ liệu\nNhận diện rủi ro trực tuyến")
                app.text_area[1].set_value("Xưng thầy và các em, dùng ví dụ gần gũi.")
                next(item for item in app.selectbox if item.label == "Phong cách giảng dạy").set_value("Gợi mở bằng câu hỏi")
                next(item for item in app.multiselect if item.label == "Ngôn ngữ tài liệu cần tìm").set_value(["vi", "fr", "ja"])
                next(item for item in app.slider if item.label == "Thời lượng video (phút)").set_value(9)
                next(item for item in app.slider if item.label == "Số nguồn tối đa để đọc và thẩm định").set_value(12)
                with patch("requests.request", side_effect=moderate_request):
                    button(app, "Tìm tài liệu và lập hồ sơ").click().run()
                    app.run()  # An ordinary rerender must never retry a paid review.
                self.assertFalse(app.exception)
                self.assertEqual(len(submitted), 1)
                self.assertTrue(submitted[0][0].endswith("/api/pipeline/start"))
                self.assertIsNone(app.session_state["session_id"])
                self.assertIsNone(app.session_state["session"])
                self.assertIsNone(self.api.session)
                self.assertEqual(self.api.posts, [], "Rejected admission must not enter the research workflow")
                self.assertTrue(any(item.value == message for item in app.error))
                self.assertEqual(app.text_input[0].value, "An toàn thông tin cho sinh viên")
                self.assertEqual(app.text_input[1].value, "Sinh viên năm nhất")
                self.assertEqual(app.text_area[0].value, "Hiểu cách bảo vệ dữ liệu\nNhận diện rủi ro trực tuyến")
                self.assertEqual(app.text_area[1].value, "Xưng thầy và các em, dùng ví dụ gần gũi.")
                self.assertEqual(next(item for item in app.selectbox if item.label == "Phong cách giảng dạy").value, "Gợi mở bằng câu hỏi")
                self.assertEqual(next(item for item in app.multiselect if item.label == "Ngôn ngữ tài liệu cần tìm").value, ["vi", "fr", "ja"])
                self.assertEqual(next(item for item in app.slider if item.label == "Thời lượng video (phút)").value, 9)
                self.assertEqual(next(item for item in app.slider if item.label == "Số nguồn tối đa để đọc và thẩm định").value, 12)
                self.assertFalse(any('<div class="ss-activity-track"' in item.value for item in app.markdown))
                self.assertTrue(any("kiểm tra trước khi tìm tài liệu" in item.value for item in app.caption))

    def test_connection_and_post_timeout_are_recoverable(self):
        with patch("requests.request", side_effect=requests.ConnectionError):
            app = self.app()
            self.assertTrue(button(app, "Tìm tài liệu và lập hồ sơ").disabled)
            self.assertTrue(any("Chưa thể tải" in item.value for item in app.error))
        st.cache_data.clear()
        app = self.app()
        original = self.api.__call__

        def slow_post(method, url, **kwargs):
            if method == "POST":
                raise requests.Timeout()
            return original(method, url, **kwargs)

        with patch("requests.request", side_effect=slow_post):
            self.submit_request(app)
        self.assertIsNone(app.session_state["session_id"])
        self.assertTrue(any("Tác vụ có thể vẫn đang chạy" in item.value for item in app.error))


if __name__ == "__main__":
    unittest.main()
