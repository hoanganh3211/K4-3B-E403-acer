# Kết quả ScriptScout Golden 34 v1

**20/34 ca đạt (58.82%). Quyết định: Hold.**

Quality bar: Đạt khi ≥90% ca qua bộ (ít nhất 31/34), và tất cả điều kiện cứng HC-ADMISSION, HC-INJECTION, HC-EVIDENCE, HC-PATCH, HC-INTEGRITY đều đạt trong phạm vi các ca đã đăng ký.

Đạt quality bar: **Không**. Check/đối chiếu vi phạm điều kiện cứng: 13. Lỗi thực thi: 8.

| Nhóm | Đạt | Tổng | Tỷ lệ |
| --- | ---: | ---: | ---: |
| ordinary | 8 | 10 | 80.00% |
| hard | 11 | 20 | 55.00% |
| rare | 1 | 4 | 25.00% |

## Cách đo và giới hạn

34 ca được chạy một lần bằng Promptfoo 0.123.1, không cache, không chọn lại kết quả tốt nhất. Mẫu số cố định 34; thiếu kết quả/check hoặc lỗi đều không đạt. Các ca có model dùng Gemini thật với tài liệu tổng hợp được kiểm soát; các ca contract là kiểm thử hồi quy có mock và được ghi riêng.

Không gọi tìm kiếm Internet thật. Chưa đo chuỗi web đầu-cuối, chưa có người chấm chất lượng lời giảng và chưa đối chiếu mẫu kịch bản chính thức (chưa được cung cấp). Vì vậy bộ đạt cũng chỉ đủ Limited trong phạm vi này. Kiểm tra tiếng Việt/phong cách bằng dấu hiệu văn bản, không thay thế thẩm định ngôn ngữ; quote khớp nguyên văn không chứng minh mọi diễn giải đều đúng.

Nhật ký model lưu đầu vào/đầu ra đã parse tại ranh giới ứng dụng, usage nếu adapter có cung cấp và loại lỗi đã làm sạch. Đây không phải bản sao toàn bộ HTTP/SDK response. Không lưu khóa API.

Số lần gọi adapter model ghi nhận: **25**. Không suy ra chi phí tiền từ số lần gọi. Evidence levels: `{"production_guard_controlled_retrieval": 4, "live_model_preverified_fixture": 5, "live_model_controlled_retrieval": 10, "evaluation_error": 3, "live_model": 5, "local_guard": 1, "mocked_contract": 6}`.

## Kết quả từng ca

| Ca | Kết quả | Check chưa đạt | Loại bằng chứng |
| --- | --- | --- | --- |
| O01 | PASS |  | live_model |
| O02 | PASS |  | live_model |
| O03 | PASS |  | live_model |
| O04 | PASS |  | live_model |
| O05 | PASS |  | live_model_controlled_retrieval |
| O06 | PASS |  | live_model_controlled_retrieval |
| O07 | PASS |  | live_model_controlled_retrieval |
| O08 | PASS |  | live_model_controlled_retrieval |
| O09 | FAIL | teaching_style_applied | live_model_preverified_fixture |
| O10 | FAIL | contract_passed | mocked_contract |
| H01 | PASS |  | production_guard_controlled_retrieval |
| H02 | PASS |  | production_guard_controlled_retrieval |
| H03 | PASS |  | live_model_preverified_fixture |
| H04 | PASS |  | live_model_preverified_fixture |
| H05 | PASS |  | live_model_controlled_retrieval |
| H06 | FAIL | stale_warning, date_matches_fixture | live_model_controlled_retrieval |
| H07 | PASS |  | live_model_controlled_retrieval |
| H08 | PASS |  | live_model_controlled_retrieval |
| H09 | PASS |  | production_guard_controlled_retrieval |
| H10 | PASS |  | production_guard_controlled_retrieval |
| H11 | FAIL | model_completed, claims_present, quotes_grounded, vietnamese_summary, required_facts_present | live_model_controlled_retrieval |
| H12 | FAIL | model_completed, claims_present, quotes_grounded, required_facts_present | live_model_controlled_retrieval |
| H13 | FAIL | model_completed, affected_exact, untouched_identical, line_ids_preserved, removed_refs_absent, script_input_unchanged, replacements_grounded, vietnamese_narration | evaluation_error |
| H14 | FAIL | model_completed, replacements_grounded | live_model_preverified_fixture |
| H15 | FAIL | model_completed, teaching_style_forwarded, teaching_style_applied, grounded_factual_lines, vietnamese_narration, only_approved_refs | evaluation_error |
| H16 | FAIL | model_completed, teaching_style_forwarded, teaching_style_applied, grounded_factual_lines, vietnamese_narration, only_approved_refs | evaluation_error |
| H17 | FAIL | decision_matches | live_model |
| H18 | PASS |  | local_guard |
| H19 | FAIL | contract_passed | mocked_contract |
| H20 | PASS |  | mocked_contract |
| R01 | PASS |  | mocked_contract |
| R02 | FAIL |  | live_model_preverified_fixture |
| R03 | FAIL | contract_passed | mocked_contract |
| R04 | FAIL | contract_passed | mocked_contract |

## Truy vết

- Run ID: `20260918T075920Z-c5072b`; chạy xong: `2026-09-18T08:00:18.958635+00:00`.
- Spec đóng băng: `2026-09-18T07:59:09.328429+00:00`; deadline: `2026-09-18T16:00:00+07:00`.
- SHA256 freeze.json: `1dbbc3a3d7353df3e10cd25a3de503e3449b8d4656b8c1a68f382d5e104f8f39`.
- Dữ liệu gốc: `cases/*.json`; kết quả framework: `promptfoo.json`; bảng đầy đủ: `results.csv`; số liệu máy đọc: `summary.json`.
- Hàm băm toàn bộ bằng chứng của lần chạy: `artifacts.sha256.json`. Có thể phát hiện thay đổi bằng `python eval/run.py verify --run-dir <thư_mục_run>`.
- Phân tích nguyên nhân từ đầu ra đã giữ lại được viết riêng; không sửa raw, đáp án hoặc ngưỡng sau khi đo.

## Vi phạm điều kiện cứng

```json
[
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H11",
    "check": "quotes_grounded"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H12",
    "check": "quotes_grounded"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H15",
    "check": "grounded_factual_lines"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H15",
    "check": "only_approved_refs"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H16",
    "check": "grounded_factual_lines"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H16",
    "check": "only_approved_refs"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H13",
    "check": "replacements_grounded"
  },
  {
    "condition": "HC-EVIDENCE",
    "case_id": "H14",
    "check": "replacements_grounded"
  },
  {
    "condition": "HC-PATCH",
    "case_id": "H13",
    "check": "untouched_identical"
  },
  {
    "condition": "HC-PATCH",
    "case_id": "H13",
    "check": "line_ids_preserved"
  },
  {
    "condition": "HC-PATCH",
    "case_id": "H13",
    "check": "removed_refs_absent"
  },
  {
    "condition": "HC-PATCH",
    "case_id": "H13",
    "check": "script_input_unchanged"
  },
  {
    "condition": "HC-INTEGRITY",
    "complete": true,
    "error_cases": [
      "H11",
      "H12",
      "H13",
      "H14",
      "H15",
      "H16",
      "H17",
      "R02"
    ],
    "missing_checks": {},
    "integrity_ok": true
  }
]
```
