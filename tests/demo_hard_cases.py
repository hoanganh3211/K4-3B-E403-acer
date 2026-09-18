r"""Offline demonstration with SIMULATED search/model adapters, never live evidence.

Run from the repository root:
    .\venv\Scripts\python.exe tests\demo_hard_cases.py

Real application code handles scraping, quarantine, exact quotes, rubric,
dependency graphs, and local patching. All search/model responses and article
contents are fixtures; this demonstrates plumbing, not real model accuracy.
"""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from services.pipeline_service import PipelineService, eligible_source
from services.scraper_service import ScraperService


URL_A = "https://demo-alpha.edu/simulated-study-a"
URL_B = "https://demo-beta.gov/simulated-study-b"
URL_ATTACK = "https://example.org/simulated-hidden-injection"
QUOTE_A = "In the simulated 2025 cohort of 100 students, 80% completed the same course by December 31."
QUOTE_B = "In the simulated 2025 cohort of 100 students, 40% completed the same course by December 31."
TRANSLATION_A = "Trong nhóm mô phỏng gồm 100 sinh viên năm 2025, 80% hoàn thành cùng khóa học trước ngày 31 tháng 12."
TRANSLATION_B = "Trong nhóm mô phỏng gồm 100 sinh viên năm 2025, 40% hoàn thành cùng khóa học trước ngày 31 tháng 12."


def article_fixture(label, quote):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <title>SIMULATED document {label}, not a real study</title>
    <meta name="author" content="Simulated Research Team {label}">
    <meta property="article:published_time" content="{date.today().isoformat()}">
    </head><body><article><h1>SIMULATED educational test fixture</h1>
    <p>{quote}</p><p>The figures and institution in this document are invented solely
    for deterministic software testing. They must never be presented as research findings.</p>
    </article></body></html>""".encode("utf-8")


class SimulatedSearch:
    """No search provider is called. The chosen URLs identify local fixtures."""

    warnings = ["DEMO NGOẠI TUYẾN: kết quả tìm kiếm và nội dung nguồn đều là dữ liệu mô phỏng."]
    query_log = []

    def generate_queries(self, topic, objectives, audience, languages, max_sources=6):
        return [{"query": "SIMULATED cohort completion evidence", "language": "en"}]

    def search_multiple(self, queries, max_sources=6):
        return [{"url": url, "title": "SIMULATED fixture"} for url in (URL_ATTACK, URL_A, URL_B)]


class SimulatedLLM:
    """Predictable scripted JSON, not a model and not an evaluation of translation quality."""

    def __init__(self):
        self.calls = []
        self.usage = []  # No tokens were billed; do not manufacture provider usage.

    def generate_json(self, system, payload):
        self.calls.append(deepcopy(payload))
        task = payload["task"]
        if task == "evaluate_source":
            url = payload["untrusted_page"]["url"]
            if url == URL_ATTACK:
                raise AssertionError("Trang có chỉ dẫn ẩn không được gửi vào bộ đọc model.")
            is_a = url == URL_A
            return {
                "language": "en",
                "summary_vi": (
                    f"Tài liệu mô phỏng {'A' if is_a else 'B'} mô tả cùng một nhóm học viên và cùng hạn hoàn thành. "
                    f"Tỷ lệ được ghi là {'80' if is_a else '40'}%. "
                    "Đây là số liệu kiểm thử được đặt trước, không phải kết quả nghiên cứu thực tế."
                ),
                "claims": [{
                    "claim_text": TRANSLATION_A if is_a else TRANSLATION_B,
                    "snippet_quote": QUOTE_A if is_a else QUOTE_B,
                    "snippet_translation_vi": TRANSLATION_A if is_a else TRANSLATION_B,
                    "is_statistical": True,
                }],
                "warnings": ["Nguồn mô phỏng dùng kiểm thử; không được dùng làm bằng chứng giảng dạy."],
            }
        if task == "cross_check":
            claims = payload["claims"]
            a = next(claim for claim in claims if "80%" in claim["source_context"])
            b = next(claim for claim in claims if "40%" in claim["source_context"])
            return {
                "conflicts": [{
                    "claim_ids": [a["claim_id"], b["claim_id"]],
                    "description_vi": "Mâu thuẫn mô phỏng: hai tài liệu cùng nhóm, cùng khóa học và thời hạn nhưng ghi 80% và 40%.",
                    "resolution_vi": "Kiểm tra dữ liệu gốc và định nghĩa hoàn thành; không tự chọn một con số làm đúng.",
                }],
                "agreements": [],
                "warnings": ["Cảnh báo mâu thuẫn do adapter mô phỏng trả về; chưa đo chất lượng nhận diện của model thật."],
            }
        if task == "write_script":
            claims = payload["approved_claims"]
            a = next(claim for claim in claims if "80%" in claim["source_context"])
            b = next(claim for claim in claims if "40%" in claim["source_context"])
            return {"scenes": [{
                "scene_label": "Cùng đọc hai số liệu mô phỏng",
                "visual_cue": "Hai thẻ gắn nhãn MÔ PHỎNG; đặt hai tỷ lệ cạnh nhau.",
                "speaker_note": "Xưng cô/các em; dừng sau câu hỏi như phong cách đã nhập.",
                "lines": [
                    {"text": "Các em hãy cùng cô đọc hai tài liệu mô phỏng sau nhé.", "kind": "transition", "claim_ids": []},
                    {"text": "Theo tài liệu mô phỏng A, tỷ lệ hoàn thành là 80%; số liệu chưa được xác minh độc lập.", "kind": "factual", "claim_ids": [a["claim_id"]]},
                    {"text": "Tài liệu mô phỏng B ghi tỷ lệ 40% cho cùng nhóm và thời hạn; hai số liệu khác nhau nên cần kiểm tra lại.", "kind": "factual", "claim_ids": [a["claim_id"], b["claim_id"]]},
                    {"text": "Các em sẽ kiểm tra điều gì trước khi sử dụng một con số?", "kind": "question", "claim_ids": []},
                    {"text": "Theo tài liệu mô phỏng B, tỷ lệ 40% vẫn cần được xác minh bằng dữ liệu gốc.", "kind": "factual", "claim_ids": [b["claim_id"]]},
                ],
            }]}
        if task == "audit_script":
            # This fixture is intentionally explicit about the semantic audit being simulated.
            return {"lines": [{
                "line_id": line["line_id"], "supported": True,
                "has_factual_content": bool(line["claim_ids"]),
                "reason_vi": "Kết quả kiểm toán mô phỏng, không phải đánh giá của model thật.",
            } for line in payload["lines"]]}
        if task == "patch_script":
            remaining = payload["approved_claims"][0]
            return {"lines": [{
                "line_id": line["line_id"],
                "text": "Sau khi bỏ nguồn A, tài liệu mô phỏng B ghi tỷ lệ hoàn thành 40%; số liệu này chưa được xác minh độc lập.",
                "kind": "factual", "claim_ids": [remaining["claim_id"]],
            } for line in payload["affected_lines"]]}
        raise AssertionError(f"Adapter mô phỏng chưa định nghĩa tác vụ {task!r}.")


def check(condition, label):
    if not condition:
        raise AssertionError(f"FAIL: {label}")
    print(f"PASS: {label}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("DEMO NGOẠI TUYẾN — MỌI NGUỒN/TÌM KIẾM/PHẢN HỒI MODEL ĐỀU MÔ PHỎNG")
    print("Không gọi mạng, không API key, không phát sinh token hoặc chi phí dịch vụ.\n")
    documents = {
        "/simulated-study-a": article_fixture("A", QUOTE_A),
        "/simulated-study-b": article_fixture("B", QUOTE_B),
        "/simulated-hidden-injection": (ROOT / "tests/fixtures/hidden_injection.html").read_bytes(),
    }

    def http_fixture(request):
        if request.url.path not in documents:
            raise AssertionError("Demo không được truy cập URL ngoài fixture.")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=documents[request.url.path])

    scraper = ScraperService(transport=httpx.MockTransport(http_fixture))
    llm = SimulatedLLM()
    pipeline = PipelineService(llm=llm, search=SimulatedSearch(), scraper=scraper, admission=lambda req: None)
    req = {
        "topic": "Đọc và đối chiếu số liệu giáo dục mô phỏng",
        "objectives": ["Giữ nguyên số liệu khi dịch", "Nhận diện mâu thuẫn và yêu cầu bằng chứng gốc"],
        "target_audience": "Giảng viên thử nghiệm phần mềm",
        "duration_minutes": 1,
        "source_languages": ["en"],
        "max_sources": 3,
        "teaching_style": "Xưng cô/các em; giải thích nhẹ nhàng và dừng sau câu hỏi gợi mở.",
    }
    dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
    # A real network attempt fails immediately, even if a future adapter change bypasses the fixture.
    with patch("socket.getaddrinfo", return_value=dns), patch("socket.socket.connect", side_effect=AssertionError("Demo phải ngoại tuyến")):
        research = pipeline.research(req)
        sources = {source["url"]: source for source in research["dossier"]["sources"]}
        attack = sources[URL_ATTACK]
        check(attack["has_prompt_injection"] and attack["status"] == "rejected", "Cách ly trang chứa chỉ dẫn ẩn")
        check(not attack["claims"] and not eligible_source(attack), "Trang bị cách ly không tạo bằng chứng hoặc được duyệt")
        checked_urls = [call["untrusted_page"]["url"] for call in llm.calls if call["task"] == "evaluate_source"]
        check(URL_ATTACK not in checked_urls, "Không gửi trang bị cách ly vào adapter đọc model")

        for url in (URL_A, URL_B):
            source = sources[url]
            check(eligible_source(source) and source["trust_score"] >= 70, f"Nguồn {url} đạt điểm sàng lọc theo metadata mô phỏng")
            claim = source["claims"][0]
            check(claim["is_verified"] and not claim["independently_verified"], "Trích dẫn khớp nhưng số liệu vẫn chưa xác minh độc lập")
            print("  Quote EN:", claim["snippet_quote"])
            print("  Diễn giải VI:", claim["snippet_translation_vi"])
            print("  Tóm tắt VI:", source["summary_vi"])
            print("  Điểm:", source["trust_score"], "/100;", source["trust_reasoning"])

        conflicts = research["dossier"]["conflicts"]
        check(len(conflicts) == 1, "Lưu cảnh báo mâu thuẫn giữa hai nguồn có điểm sàng lọc cao")
        print("  Cảnh báo:", conflicts[0]["description_vi"])
        print("  Cách xử lý:", conflicts[0]["resolution_vi"])
        print("  Rubric:", json.dumps(research["dossier"]["trust_criteria"], ensure_ascii=False))

        ids = [sources[url]["source_id"] for url in (URL_A, URL_B)]
        session = {"req": req, **research}
        written = pipeline.review(session, ids)
        session.update(written)
        before = {line["line_id"]: deepcopy(line) for scene in session["script"]["scenes"] for line in scene["lines"]}
        expected_affected = {line_id for line_id, line in before.items() if any(ref["source_id"] == ids[0] for ref in line["source_refs"])}
        check(all(line["is_unverified"] for line in before.values() if line["source_refs"]), "Kịch bản giữ cảnh báo số liệu dù kiểm toán ngữ nghĩa mô phỏng báo phù hợp")
        check(next(call for call in llm.calls if call["task"] == "write_script")["lesson"]["teaching_style"] == req["teaching_style"], "Truyền nguyên mô tả phong cách giảng dạy vào bước viết")
        patched = pipeline.patch(session, [ids[0]])
        after = {line["line_id"]: line for scene in patched["script"]["scenes"] for line in scene["lines"]}
        check(set(patched["affected_line_ids"]) == expected_affected, "Local patch xác định đúng các câu phụ thuộc nguồn A")
        check(all(before[line_id] == after[line_id] for line_id in before if line_id not in expected_affected), "Câu không liên quan giữ nguyên toàn bộ dữ liệu JSON")
        check(all(before[line_id]["text"] != after[line_id]["text"] for line_id in expected_affected), "Chỉ các câu liên quan được viết lại")
        check(all(ref["source_id"] != ids[0] for line in after.values() for ref in line["source_refs"]), "Không còn dẫn nguồn A sau khi bỏ")
        check(set(before) == set(after), "Giữ nguyên line_id khi sửa")
    print("\nPASS: ALL_OFFLINE_DEMOS")
    print("Đây là kiểm tra luồng phần mềm với adapter mô phỏng, không phải nghiệm thu tìm kiếm/dịch/model thật.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        raise
