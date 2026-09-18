
# AI SPEC — [ScriptScout] · Nhóm [acer] · Zone [4]
Hướng: [ ] A — VLearn  [ ] B — Trợ lý Học viên  [X] C — Làn mở
Loại: [ ] Tối ưu tính năng có sẵn  [X] Tính năng mới

## §1. User & Job
- Job executor + workflow (đính kèm worksheet JTBD / ảnh sơ đồ): Người viết kịch bản muốn nhanh chóng tìm hiểu một chủ đề để viết kịch bản video bài giảng. 
https://drive.google.com/file/d/1SP_VSnu5QCZhxAfLibLWk4tmhxV_0uuW/view?usp=sharing

- Core JTBD (không tên sản phẩm/AI trong câu): Tra cứu, tổng hợp thông tin từ các nguồn tài liệu uy tín và soạn thảo kịch bản video bài giảng có trích dẫn nguồn gốc rõ ràng, nhằm đảm bảo tính chính xác và tiết kiệm thời gian nghiên cứu, kiểm duyệt.
- Problem statement (KHÔNG chữ AI): Người viết kịch bản video bài giảng đang phải mất nhiều ngày để tự tra cứu và tổng hợp tài liệu thủ công. Đồng thời, việc thiếu cơ chế gắn trích dẫn nguồn gốc cụ thể cho từng câu thoại khiến khâu kiểm duyệt gặp khó khăn, mất nhiều thời gian xác minh và tiềm ẩn rủi ro sai lệch kiến thức.
- Evidence (chuẩn A và/hoặc B — log đầy đủ trong repo):
  - Số liệu mining / kết quả khảo sát (n = 3, 100% xác nhận): 100% (3/3) xác nhận khâu tra cứu, tổng hợp tài liệu thủ công tiêu tốn phần lớn thời gian (trung bình 3-5 ngày/kịch bản).
  - ≥5 quote/ví dụ nguyên văn + nguồn:

  "Mỗi lần nhận một chủ đề mới, mình phải mở hàng chục tab để đọc và chắt lọc. Quá trình tra cứu thủ công này ngốn của mình mất 3-4 ngày trước khi thực sự bắt tay vào viết." — Nguồn: Nguyễn Hữu Chương.

"Lúc tìm tài liệu mình có copy link lưu ra một file riêng, nhưng đến lúc ghép lời thoại vào kịch bản thì loạn hết lên, không biết link nào là bằng chứng cho câu nào nữa." — Nguồn: Võ Trường An.

"Có lần mình vô tình lấy nhầm thông tin từ một blog cá nhân chưa được kiểm chứng. Đến khâu review bị đánh giá là nguồn không đủ độ tin cậy, phải làm lại từ đầu rất mệt." — Nguồn: Phạm Đình Duy.

## §2. Impact & quyết định chọn
- Bảng impact ≥3 ứng viên (bao nhiêu người · tần suất · tốn gì mỗi lần · khả thi):
- Ứng viên ĐÃ LOẠI + vì sao:
- Ứng viên CHỌN + vì sao (bằng số):

## §3. Giải pháp tương tự đã nghiên cứu
- [Sản phẩm 1]: Perplexity AI

Flow: Người dùng nhập prompt/câu hỏi ➔ AI tự động search web đa luồng ➔ Trả về văn bản tổng hợp có gắn các con số chú thích [1], [2] trỏ đến link nguồn tương ứng.

Đáng học: Tốc độ tìm kiếm web và xử lý dữ liệu song song cực nhanh. Giao diện hiển thị nguồn trực quan, cho phép người dùng click để kiểm tra ngay lập tức.

Đáng né: Đôi khi bị "ảo giác trích dẫn". Đầu ra chỉ dừng ở mức văn bản cung cấp thông tin, không có cấu trúc chuyên biệt của một kịch bản video bài giảng.

Mình khác gì: ScriptScout tập trung sâu vào định dạng Kịch bản Video. Đặc biệt, ScriptScout có bước Human-in-the-loop ở giữa luồng: cho phép người dùng kiểm tra, thêm hoặc loại bỏ nguồn trước khi AI bắt tay vào viết, giúp chủ động kiểm soát chất lượng đầu vào.

- [Sản phẩm 2]: Google NotebookLM

Flow: Người dùng tự tải tài liệu lên ➔ Đặt câu hỏi hoặc yêu cầu viết ➔ AI sinh văn bản có đánh dấu trích dẫn trỏ thẳng đến vị trí text gốc trong tài liệu đã nộp.

Đáng học: Khả năng Grounding xuất sắc, gần như không bịa. Trích dẫn cực kỳ chặt chẽ ở cấp độ từng dòng.

Đáng né: Flow bị thụ động. Quy trình đòi hỏi người dùng phải tự đi lùng sục, tra cứu tài liệu trên mạng, đánh giá xem có đáng tin không rồi mới tải lên cho AI đọc.

Mình khác gì: ScriptScout chủ động hoàn toàn. Người dùng chỉ cần nhập "Chủ đề video", hệ thống sẽ tự sinh từ khóa, tự đi cào web, tự đánh giá độ tin cậy, trích xuất thông tin rồi mới viết. ScriptScout giải phóng con người khỏi cả hai khâu: Tìm kiếm nguyên liệu và Nấu thành kịch bản.

- [Sản phẩm 3]: Các LLM Chatbot thông thường (ChatGPT / Claude)

Flow: Prompt "Viết kịch bản video dài 4 phút về..." ➔ AI sinh ngay ra một kịch bản với đầy đủ hình ảnh, lời đọc.

Đáng học: Văn phong mượt mà, sáng tạo ngôn từ tốt.

Đáng né: Thường xuyên chỉ sinh nháp 50 giây dù yêu cầu 4 phút. Dễ bịa số liệu, ví dụ để kịch bản nghe có vẻ thuyết phục. Không có cơ chế quản lý bằng chứng độc lập, người duyệt không thể biết số liệu AI đưa ra lấy từ đâu.

Mình khác gì: Mình chia nhỏ quá trình thành pipeline (Search ➔ Evaluate ➔ Extract ➔ Write) thay vì bắt AI làm tất cả trong một prompt. Mọi dữ kiện quan trọng đưa vào kịch bản đều bị ép phải có mã truy vết (tXX) trỏ về tệp sự kiện thực tế. Ngoài ra, ScriptScout có module xử lý cập nhật cục bộ: nếu người duyệt loại bỏ 1 nguồn, hệ thống tự động dò tìm các câu thoại bị ảnh hưởng để viết lại mà không làm xáo trộn toàn bộ kịch bản.
## §4. Thiết kế
- Lát cắt MỘT CÂU (1 user · 1 việc · 1 quyết định AI · 1 kết quả):
- Non-goals (≥3 thứ KHÔNG build):
Không build tính năng tự động tạo video/slide/hình ảnh minh họa (vì chi phí cao và dễ hallucinate).

Không hỗ trợ tìm kiếm tài liệu từ các kho dữ liệu nội bộ đóng hoặc cơ sở dữ liệu vật lý (chỉ dùng Search Web mở).

Không build chức năng xuất trực tiếp thành định dạng Word hay PDF phức tạp (chỉ xuất file JSON/Markdown phục vụ hệ thống nội bộ).
- Mức prototype nhắm tới: [ ] Sketch [ ] Mock [X] Working — phần nào mock, phần nào thật:
- Automation: [ ] augment [X] conditional [ ] automate — lý do theo cost-of-error:
- §4b. Nguyên tắc đã áp dụng (≥4 — HAX/PAIR, xem guide):

| Nguyên tắc | Áp cụ thể vào đâu trong prototype |
| --- | --- |
| **G2 (HAX): Làm rõ hệ thống có thể làm tốt đến đâu** | Hệ thống định lượng và hiển thị rõ trạng thái của nguồn (vd: Độ tin cậy: Cao/Trung bình/Thấp) và trạng thái của thông tin (Đã xác minh / Chưa xác minh), giúp người dùng biết mức độ chắc chắn của AI. |
| **G7 (HAX): Hỗ trợ việc kêu gọi và điều chỉnh hệ thống (Support efficient invocation)** | Hệ thống cho phép người dùng can thiệp vào giữa luồng: tự thêm link nguồn thủ công (`pipeline_add_source`) hoặc yêu cầu loại bỏ một nguồn (`pipeline_remove_source`) ngay trên giao diện (Human-in-the-loop). |
| **G11 (HAX): Làm rõ lý do (Make clear why the system did what it did)** | Mọi câu thoại chứa số liệu hoặc sự kiện trong kịch bản đều buộc phải gắn mã nguồn (vd: t01, t02). Người dùng click/đọc mã này sẽ đối chiếu ngược lại được dòng trích xuất nguyên văn tương ứng từ trang web nào. |
| **G13 (HAX): Học từ hành vi người dùng (Learn from user behavior)** | Khi người dùng thực hiện thao tác "Loại bỏ nguồn", Agent không chỉ xóa nguồn đó mà còn tự động phân tích và viết lại chỉ những câu bị ảnh hưởng bởi nguồn vừa xóa (`UPDATE_SENTENCES_PROMPT`), bảo toàn công sức của người dùng ở các đoạn khác. |

## §5. Kiểu lỗi — 4 lớp chỗ khó + kịch bản (≥8) [bảng theo guide §2.5]

## §6. Bốn đường đi của trải nghiệm
- Happy path: · Low-confidence (②): · Failure/không căn cứ (①): · Correction (user sửa):
- Khi bị đòi ngoài phạm vi (③): · Case đặc thù domain (④):
Happy path: Nhập yêu cầu "Ngữ cảnh AI" ➔ AI search 5 nguồn uy tín ➔ Trích xuất 10 facts ➔ User duyệt OK ➔ AI sinh kịch bản 4 phút chuẩn xác, gắn nguồn t01-t10.

Low-confidence (②): AI tìm thấy web blog cá nhân, đánh giá độ tin cậy "Thấp", đưa vào trạng thái "Chưa xác minh" và cảnh báo người dùng tự quyết.

Failure/không căn cứ (①): Yêu cầu chủ đề quá hẹp/mới, AI không tìm thấy đủ nguồn. Hệ thống dừng lại, báo lỗi "Không tìm được kết quả" thay vì bịa chuyện.

Correction (user sửa): User click "Loại nguồn t02" do thấy nó thiên vị. Agent chạy pipeline_remove_source, lập tức gạch bỏ các câu thoại xài t02 và render lại kịch bản.

Khi bị đòi ngoài phạm vi (③): User nhập "Viết cho tôi đoạn code C++" ➔ Tool phản hồi: "Tôi chỉ chuyên viết kịch bản video, vui lòng nhập chủ đề video".

Case đặc thù domain (④): Khi nhập chủ đề y khoa, hệ thống tự động thắt chặt tiêu chuẩn, chỉ quét các domain .gov, .edu, hoặc PubMed.

## §7. Kiểm thử
- Chiều chất lượng + định nghĩa kiểm chứng được: Độ chính xác Grounding mọi fact sinh ra phải có tXX đối chiếu với trích dẫn gốc, khả năng tự bảo vệ trước lỗi model, và khả năng update cục bộ.
- Golden set (≥20 case theo cơ cấu trong guide §2.6, file trong eval/): 34 ca: 10 ca thường, 20 ca khó thuộc 10 lớp (2 ca/lớp) và 4 ca hiếm. Phát triển từ chatlog thật (18 ca được phát triển từ 4 lượt chat thật)
- Quality bar (chốt từ hạn chốt spec của khoá, giữ nguyên sau đó): "Đạt khi ≥ 90% ca qua bộ (ít nhất 31/34), và tất cả điều kiện cứng HC-ADMISSION, HC-INJECTION, HC-EVIDENCE, HC-PATCH, HC-INTEGRITY đều đạt trong phạm vi các ca đã đăng ký."
- Kết quả các lượt chạy (bảng % — cập nhật đến trước CP6):
```
| Nhóm | Đạt | Không đạt | Tổng | Tỷ lệ đạt |
| Thông thường | 8 | 2 | 10 | 80,00% |
| Khó | 11 | 9 | 20 | 55,00% |
| Hiếm | 1 | 3 | 4 | 25,00% |
| Toàn bộ | 20 | 14 | 34 | 58,82% |
```

## §8. Phân công & kế hoạch
- Phân công có tên: spec / evidence / prompt / code / demo:
 Mai Hoàng Anh: Quản lý dự án & Spec, Hoàng Văn Sơn: Thiết kế workflow, Phan Danh Đạt: Prompt + Golden Set |
- Willing users (≥2 tên) + kế hoạch vòng validation *(bonus, nếu làm)*:
Nguyễn Hữu Chương, Võ Trường An.
- Multi-prototype (nếu làm): trục khác biệt của ≥2 phương án + lý do chọn:

## §9. Changelog
| Thời điểm | Đổi gì | Vì sao (trỏ về feedback/case nào) |
