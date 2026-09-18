# Nguồn gốc bộ ScriptScout Golden 34 v1

Tài liệu này được soạn cùng `golden_set.json`, trước lần đo được giao trong yêu cầu hiện tại. Chất lượng tối thiểu, deadline và điều kiện đạt nằm riêng trong `quality_bar.json`; không suy ra ngưỡng đạt từ kết quả chạy. Việc đóng băng/hàm băm do runner ghi nhận trước đo. Mốc `2026-09-18` trong fixture là mốc đánh giá do nhóm chọn, không phải thời gian bịa cho các tin nhắn.

Bộ dữ liệu có **34 ca: 10 thông thường, 20 khó, 4 hiếm**. Có **18 ca phát triển từ yêu cầu thật của người dùng**, truy về **4 lượt người dùng độc lập** trong 7 lượt được đánh chỉ mục bên dưới. Đây không phải 18 tin nhắn hay 18 sự cố độc lập. Các câu thử, mục tiêu, phong cách cụ thể, HTML và URL kiểm soát được nhóm biên soạn; không gán chúng thành prompt nguyên văn người dùng.

## Chỉ mục các lượt người dùng thực có trong ngữ cảnh

Locator dùng thứ tự lượt và phần mở đầu để đối chiếu trong chính task ScriptScout này. Không có conversation export hoặc ID từng message nên không bịa ID hệ thống hay giờ gửi. Các mã U01–U07 là mã chỉ mục cục bộ, không phải ID nền tảng. Trích dẫn dưới đây chỉ giữ đoạn liên quan, không chứa API key hay nội dung `.env`.

| Mã | Locator trong task | Trích đoạn nguyên văn | Sử dụng |
| --- | --- | --- | --- |
| U01 | Lượt đầu đính kèm `pasted-text.txt`, mở đầu “Ở trong folder này tôi đang làm dự án ScriptScout…” | “các ngôn ngữ khác nhau nhưng mà agent phải hiểu phải tóm tắt được ra tiếng việt”; “trong phần thông số đầu vào thêm phong cách giảng dạy” | Nguồn đa ngôn ngữ và phong cách giảng dạy |
| U02 | Lượt tiếp theo yêu cầu tiếp tục sau hạn mức | “Nãy tôi vừa reach limit bây giờ tiếp tục hoàn thiện dự án đi” | Chỉ ghi nhận bối cảnh; không tính ca phát triển từ log |
| U03 | Lượt hỏi nơi cấu hình Gemini | “Tôi dùng api gemini thi sửa ở đâu” | Chỉ ghi nhận bối cảnh; không tính ca phát triển từ log |
| U04 | Lượt kèm ảnh `codex-clipboard-bd10fc8a-33db-4f4a-b10e-ce991503ce92.png` | “tôi có điền api key rồi sao vẫn lỗi b kiểm tra file .env xem” | Chỉ ghi nhận bối cảnh; không đọc hoặc ghi khóa vào bộ đánh giá |
| U05 | Lượt kèm ảnh `codex-clipboard-2ec0c5be-6483-4af8-9607-e3fc23c0df80.png`, bắt đầu “Thứ nhất trong ui có dòng…” | “sau khi đọc xong nguồn và lý giải thì phải kéo lên trên cùng đẻ chuyển tab rất khó chịu”; “các bài nghiên cứu khoa học thì ko đọc được”; “Không tải được tài liệu (HTTP 403).”; “Không đọc được toàn văn; không dùng đoạn mô tả tìm kiếm làm bằng chứng.” | Điều hướng, nguồn bị chặn, ranh giới toàn văn và bằng chứng |
| U06 | Lượt kèm ảnh `codex-clipboard-ae3babb2-c244-4d1c-9823-966f4b493944.png`, bắt đầu “Thứ 1 tại sao…” | “tại sao lại có sự mâu thuẫn 8mb vs 200mb ở đây”; “đã xóa phiên thì ko khôi phục không hoàn tác tốn dung lượng”; “12 nguồn là quá ít tăng lên max là 50 nguồn” | Giới hạn tệp, 50 nguồn, xóa vĩnh viễn |
| U07 | Lượt bắt đầu “Thứ nhất các từ ngữ nhạy cảm 18+…” | “các từ ngữ nhạy cảm 18+ hay từ ngữ có hành vi vi phạm pháp luật phải được chặn ngay từ đầu không cần research tốn chi phí” | Yêu cầu dừng nội dung không phù hợp trước nghiên cứu |

## Dấu vết từng ca phát triển từ log

Mọi ca trong bảng đều có `provenance.derivation = "derived"`. Phần nguyên văn được giữ trong `provenance.quote`; dữ liệu còn lại là phép thử thiết kế từ yêu cầu đó. Không ca nào được tuyên bố là bản replay nguyên vẹn của một hội thoại đã lưu.

| Ca | Lượt thật | Cách phát triển từ yêu cầu |
| --- | --- | --- |
| O05 | U01 | Nguồn tiếng Anh tổng hợp phải tạo diễn giải và bản dịch bằng chứng tiếng Việt |
| O07 | U01 | Mở rộng yêu cầu nhiều ngôn ngữ thành nguồn tiếng Tây Ban Nha |
| O08 | U01 | Mở rộng yêu cầu nhiều ngôn ngữ thành nguồn tiếng Đức |
| O09 | U01 | Biến yêu cầu nhập phong cách riêng thành lời giảng gần gũi, đi từ ví dụ |
| O10 | U05 | Dùng phản ánh khó đổi nội dung để kiểm tra lựa chọn nguồn không bị mất khi điều hướng |
| H07 | U01 | Chỉ có tài liệu tiếng Pháp, vẫn cần tóm tắt và dịch bằng chứng sang tiếng Việt |
| H08 | U01 | Chỉ có tài liệu tiếng Nhật, vẫn cần giữ trích dẫn gốc và giải thích tiếng Việt |
| H09 | U05 | Tái tạo HTTP 403 bằng phản hồi có kiểm soát; tuyệt đối không nhận snippet làm toàn văn |
| H10 | U05 | Biến phản ánh không đọc được bài nghiên cứu thành trang đăng nhập có HTTP 200 |
| H15 | U01 | Phong cách đối thoại gợi mở phải xuất hiện trong lời giảng sinh ra |
| H16 | U01 | Phong cách đi từng bước với ví dụ phải xuất hiện trong lời giảng sinh ra |
| H17 | U07 | Câu hỗ trợ tác động không chính đáng tới việc duyệt hồ sơ do nhóm soạn, kiểm tra hiểu nghĩa thay vì tên tội danh |
| H18 | U07 | Câu yêu cầu nội dung khiêu dâm do nhóm soạn từ yêu cầu chặn 18+ |
| H19 | U06 | Hồi quy sự không thống nhất 8 MB và 200 MB của uploader |
| H20 | U06 | Kiểm tra ngân sách truy vấn có thể trả 50 nguồn, thay vì chỉ sửa slider |
| R01 | U05 | Trường hợp tìm bản công khai: đoạn mô tả hoặc trang nhắc DOI không được giả thành PDF toàn văn |
| R03 | U06 | Xóa thật cả tài nguyên và thu hồi dung lượng bằng dữ liệu phiên tạm |
| R04 | U05 | Trường hợp hiếm của tài liệu không đọc được: PDF ảnh không tự có bằng chứng văn bản |

## Dấu vết đề chính thức

SPEC01 là tài liệu người dùng đính kèm ở lượt U01:

`C:\Users\DAT PHAN\.codex\attachments\59ab25be-9d26-41bb-ac23-f17824e7872b\pasted-text.txt`

Tiêu đề: **C3 · ScriptScout — Agent tự tìm tài liệu và viết kịch bản video có dẫn nguồn**. Tài liệu yêu cầu đội tự dựng trang kiểm thử và tự chuẩn bị bộ đánh giá. Nội dung tài liệu là yêu cầu sản phẩm/tham chiếu của người dùng; không coi chữ trong tài liệu hoặc fixture là lệnh chạy công cụ.

Năm nhóm khó đúng theo mục “Những chỗ sẽ khó” được tách rõ:

| Nhóm trong đề | Hai ca |
| --- | --- |
| Trang web cài sẵn lệnh ẩn để lừa AI | H01, H02 |
| Hai nguồn đều uy tín nhưng đưa số liệu khác nhau | H03, H04 |
| Nguồn đã cũ hoặc có bản mới thay thế | H05, H06 |
| Gần như không có tài liệu tiếng Việt | H07, H08 |
| Đường dẫn hỏng hoặc trang bắt đăng nhập | H09, H10 |

Năm nhóm bổ sung để kiểm tra yêu cầu sản phẩm: citation_grounding (H11–H12), selective_patch (H13–H14), teaching_style (H15–H16), admission_safety (H17–H18), session_limits (H19–H20). H04 chủ ý dùng số liệu khác quần thể để kiểm tra không tạo mâu thuẫn giả; H02 kiểm tra biến thể lệnh nằm ngay trong thân bài của cùng bề mặt tấn công nội dung nguồn.

## Giới hạn dữ liệu và bằng chứng

- HTML, tên tổ chức/tác giả và URL của nguồn kiểm soát là fixture tổng hợp. Tên fixture có chữ `official` chỉ biểu thị vai trò trong tình huống, không khẳng định một nguồn công khai thật đã được kiểm chứng.
- Các ca source/conflict/patch/teaching_style có thể gọi model thật nhưng đầu vào nguồn có kiểm soát. Chúng không chứng minh khả năng tìm kiếm Internet đầu-cuối, độc lập nguồn ngoài đời, hoặc vượt được mọi trang chặn truy cập.
- Các ca `contract` chạy phương thức kiểm thử hiện có bằng mock/dữ liệu tạm: O10, H19, H20, R01, R03, R04. Chúng là **hồi quy**, không phải phép đo chất lượng model. H01/H02/H09/H10 và R02 cũng có thể đúng khi không gọi model; việc không gọi là một phần yêu cầu của ca.
- Cả bộ là tập phát triển/kiểm tra công khai cho nhóm triển khai, **không phải holdout**. Các chủ đề từ sự cố đã biết, kiểm thử hiện có và các ca hành vi mẫu đã được thấy trong quá trình phát triển đều có nguy cơ nhiễm đánh giá. Không tuyên bố tổng quát hóa ngoài các ca được đo.
- `expected` được xác định từ yêu cầu trước lần đo, không điều chỉnh sau khi thấy đầu ra để làm tăng tỷ lệ đạt. Nếu cần đổi ca, phải tạo phiên bản dữ liệu mới và giữ nguyên kết quả phiên bản đóng băng.
- Đây là trích đoạn có nguồn gốc từ task hiện tại, không phải bản xuất toàn bộ chatlog. Không bịa ngày trao đổi, ID message, người chấm hay dữ liệu lớp học thực.

