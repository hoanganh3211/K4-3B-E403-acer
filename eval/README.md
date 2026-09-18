# ScriptScout — Golden set 34 ca

Bộ đánh giá do nhóm tự xây theo đề gốc và yêu cầu thực trong task ScriptScout. Mục tiêu là đo trung thực cả chất lượng model và các ranh giới an toàn của sản phẩm, đồng thời tách hai loại bằng chứng này trong báo cáo.

- `golden_set.json`: 10 ca thông thường, 20 ca khó (10 lớp × 2), 4 ca hiếm.
- `chatlog_provenance.md`: trích đoạn, locator và phép phát triển của 18 ca từ 4 lượt chat thật; không tuyên bố 18 chat độc lập.
- `quality_bar.json`: ≥90% (31/34), cộng tất cả điều kiện cứng. Deadline 16:00 ngày 18/09/2026, giờ Việt Nam; đóng băng thực tế được ghi bằng UTC trong `freeze.json`.
- `fixtures/`: tài liệu tổng hợp có kiểm soát, không giả làm dữ liệu nghiên cứu thật.
- `runs/<run_id>/`: đầu ra từng ca, kết quả Promptfoo, log, cấu hình đã lược bỏ bí mật, CSV, báo cáo và hàm băm.
- `frozen/spec-v1.zip`: bản chụp code/dataset/tiêu chí/fixture lúc đóng băng, không chứa `.env` hoặc dữ liệu phiên của người dùng.

## Chạy và kiểm chứng

Từ thư mục gốc trên Windows, dùng môi trường Python hiện có và Node ≥22.22.0. Promptfoo được ghim ở 0.123.1. `.env` chỉ được ứng dụng đọc để gọi Gemini; không đưa khóa vào file đánh giá.

```powershell
# Chỉ chuẩn bị một lần trước lần đo đầu tiên:
.\venv\Scripts\python.exe eval\prepare_spec.py
.\venv\Scripts\python.exe -m unittest eval.test_harness -v
.\venv\Scripts\python.exe eval\run.py validate
.\venv\Scripts\python.exe eval\run.py freeze

# Mỗi lệnh tạo một run mới, không ghi đè run cũ:
.\venv\Scripts\python.exe eval\run.py run
.\venv\Scripts\python.exe eval\run.py verify --run-dir eval\runs\<run_id>
```

Không chạy lại để chọn số đẹp. Một lần chạy lại phải được báo cáo cùng run trước và lý do chạy lại. Không gọi `prepare_spec` hoặc `freeze` sau khi đã khóa bộ; các lệnh này cố ý từ chối ghi đè.

Runner tắt telemetry, sharing, cache và retry ở cấp ca; chạy tuần tự một lần/ca. SDK Gemini giới hạn một attempt. Cơ sở dữ liệu runtime được chuyển vào thư mục tạm để không ảnh hưởng các phiên đang dùng. Không cần dừng server đang chạy.

## Cách đọc kết quả

Một ca PASS chỉ khi **toàn bộ check bắt buộc** là boolean `true`. Ca lỗi, thiếu dữ liệu hoặc không chạy vẫn nằm trong mẫu số 34 và khiến HC-INTEGRITY không đạt. 213 kiểm thử hồi quy cũ (nếu chạy thêm) được báo riêng, không cộng vào tử số của golden set.

Model thật được gọi với tài liệu kiểm soát ở các ca source, conflict, patch và teaching_style; kiểm duyệt dùng adapter Gemini thật nếu không bị bộ lọc cục bộ chặn trước. Sáu ca contract dùng test hiện có và mock, không thể gọi là chất lượng model. Kết quả chỉ là tỷ lệ ca đạt trên tập phát triển này, không phải độ chính xác tổng quát của ScriptScout.

Tiếng Việt và phong cách giảng dạy được kiểm bằng dấu hiệu tự động; quote nguyên văn được đối chiếu với nguồn fixture. Chưa thay thế đánh giá độ đúng ngữ nghĩa bởi người. Bộ chưa đo tìm kiếm Internet thực, trải nghiệm trình duyệt hoàn chỉnh hoặc độ tự nhiên khi giảng; kết quả tốt cũng chỉ đủ **Limited** theo phạm vi đã chốt.

Nhật ký model là dữ liệu tại ranh giới ứng dụng: prompt/input, JSON đã parse, usage nếu adapter trả về và lỗi đã làm sạch. Không tuyên bố đã ghi mọi byte HTTP/SDK response. Timestamp và SHA256 giúp kiểm tra thay đổi; đây là dấu vết cục bộ, không phải chữ ký số hoặc timestamp từ bên thứ ba.

Thiết lập framework dựa trên tài liệu chính thức của [Promptfoo Python provider](https://www.promptfoo.dev/docs/providers/python/), [CLI](https://www.promptfoo.dev/docs/usage/command-line/), [cache](https://www.promptfoo.dev/docs/configuration/caching/) và [telemetry](https://www.promptfoo.dev/docs/configuration/telemetry/).
