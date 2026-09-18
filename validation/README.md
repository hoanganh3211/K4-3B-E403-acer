# Nhật ký Validation (Feedback Log)

## Bảng theo dõi người dùng thử

| Người thử (Tên/Vai — Willing User?) | Task (Nhiệm vụ) | Quan sát (Hành động, khó khăn) | Quote nguyên văn | Mức nghiêm trọng |
| :--- | :--- | :--- | :--- | :--- |
| Nguyễn Hữu Chương  | Nhập chủ đề "Lịch sử AI", dùng hệ thống để cào nguồn và duyệt danh sách nguồn. | Bất ngờ vì tốc độ tìm link. Tuy nhiên, khi màn hình hiển thị danh sách nguồn kèm tóm tắt để duyệt, user tỏ ra lười đọc và chần chừ tìm nút "Chọn tất cả". | "Nó gom link nhanh thật. Nhưng bước kiểm duyệt này hơi nhiều chữ, mình lười đọc quá, có nút chọn tất cả không?" | Vừa |
| Võ Trường An | Đọc kịch bản AI sinh ra, bấm vào các số trích dẫn [1], [2] để đối chiếu với nguồn gốc. | Click thử liên tục vào các con số trích dẫn. Nhưng khi bôi đen để sửa văn phong thì không được. | "Không sửa được nội dụng kịch bản à" | Trung bình |
| Phạm Đình Duy  | Cố gắng loại bỏ các nguồn từ blog cá nhân, chỉ giữ lại bài báo uy tín trước khi cho AI viết kịch bản. | Loay hoay tìm bộ lọc (filter) tên miền nhưng không thấy. Phải tự dò bằng mắt và bấm xoá tay 2 link blog. Thấy kịch bản tự cập nhật lại ngay sau khi xoá nguồn. | "Tính năng tự cập nhật kịch bản khi bỏ nguồn hay. Nhưng giá mà có nút lọc 'chỉ lấy web .edu hay báo chí' thì mình đỡ phải dò mắt xoá tay." | Nghiêm trọng |

*(Ghi chú: Cần ít nhất 2 người ngoài nhóm. Ưu tiên những người dùng đã ghi trong mục willing users ở CP1. Đánh giá hành vi theo PAIR 5.1)*

## Tổng hợp sau Validation

1. **Chủ đề lặp lại nhiều nhất:**
   - Việc quản lý nguồn (Human-in-the-loop) trước khi sinh kịch bản đang bị thủ công, người dùng tốn công sức thao tác tay và lười đọc (cần filter hoặc công cụ chọn nhanh).
   - Thắc mắc/lo ngại về rủi ro hỏng trích dẫn khi con người can thiệp chỉnh sửa văn phong kịch bản ở bước cuối.

2. **1-2 Thay đổi làm trước demo (Cập nhật vào Changelog spec §9):**
   - Bổ sung thanh công cụ lọc nhanh (Filter: báo chí, học thuật, blog) và nút "Select All / Deselect All" ở màn hình duyệt nguồn.
   - Thêm dòng chú thích (Tooltip) ở giao diện Editor: *"Bạn có thể sửa văn phong thoải mái, hệ thống sẽ tự động bảo toàn mã trích dẫn."*

3. **Giữ nguyên (Có lý do):**
   - Vẫn bắt buộc người dùng phải qua màn hình hiển thị tóm tắt nguồn trước khi sinh kịch bản (không cho auto-skip). 
   - **Lý do:** Dù Chương chê "nhiều chữ, lười đọc", nhưng đây là chốt chặn quan trọng nhất để giải quyết nỗi đau "dùng nhầm nguồn rác" của Duy. Cần ép người dùng chịu trách nhiệm với đầu vào.

4. **Đưa vào backlog (Cho vào slide 6):**
   - Bổ sung cơ chế "Smart Lock": Khóa cứng các con số trích dẫn [1] trong trình soạn thảo văn bản, ngăn người dùng vô tình xoá mất khi sửa lời thoại.
   - Tính năng tự động học hỏi (Learn): Ghi nhớ các tên miền mà user hay xoá (vd: wikipedia) để tự động blacklist cho các lần search sau.
