# Kiểm tra tính nhất quán sau đo

Kiểm tra tự động và một lượt rà soát độc lập bởi agent đọc kết quả đã hoàn thành. Đây không phải chứng nhận của giảng viên hoặc người chấm độc lập bên ngoài.

- Dataset: 34 ID duy nhất, 10 thường / 20 khó / 4 hiếm; 10 lớp khó × 2; 18 ca derived từ 4 lượt chat.
- Freeze: 14:59:09 ngày 18/09/2026, trước deadline 16:00; 58 file và snapshot ZIP khớp hash.
- Run `20260918T075920Z-c5072b`: 34 record, 20 pass / 14 fail, 58,82%, Hold. Raw, check bắt buộc, Promptfoo và CSV khớp từng ca; 41 artifact có hash nguyên vẹn.
- Có 8 ca lỗi thực thi; báo cáo không nhầm `Promptfoo errors=0` thành không có lỗi model.
- 23 ca thử gọi model / 6 contract / 5 xử lý cục bộ; 25 lời gọi adapter = 17 trả kết quả + 8 lỗi.
- Phân loại nguyên nhân phủ đủ đúng 14 ca không đạt, không trùng, không loại ca khỏi mẫu số.
- Regression 117/213 và chẩn đoán 213/213 được lưu riêng. Điểm chẩn đoán không thay thế golden v1.
- `REPORT_DATA.json` chứa nguyên summary golden; các số liệu tổng hợp trong `REPORT.md` khớp dữ liệu.
- Đã kiểm tra các artifact và nội dung snapshot không chứa giá trị API key đang cấu hình. Các file `.env`, DB phiên và thư mục môi trường không được đóng gói.

Không thay code sản phẩm, dataset, expected hoặc quality bar sau freeze. Script chẩn đoán Windows là file mới riêng, có lý do, hash và kết quả riêng. Mã hash giúp phát hiện thay đổi tại máy; không phải chữ ký số hay dịch vụ đóng dấu thời gian.
