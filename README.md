# ScriptScout — nghiên cứu đa ngôn ngữ, biên soạn bài giảng tiếng Việt

ScriptScout tìm tài liệu theo nhiều ngôn ngữ, tải nội dung nguồn, lập hồ sơ tiếng Việt để giảng viên duyệt, rồi viết lời đọc có dẫn chứng theo phong cách giảng dạy riêng. Khi bỏ một nguồn, ứng dụng chỉ sửa các câu phụ thuộc nguồn đó.

Đây là ứng dụng chạy cục bộ với FastAPI và Streamlit. Luồng chính dùng dịch vụ thật khi được cấu hình; thiếu khóa hoặc dịch vụ lỗi sẽ báo lỗi, không thay bằng hồ sơ/kịch bản mẫu. Các adapter mô phỏng chỉ nằm trong kiểm thử và demo ngoại tuyến.

## Cài đặt trên Windows

Mở PowerShell trong thư mục dự án. Môi trường hiện tại đã chạy bằng Python 3.13; tạo môi trường mới nếu chưa có `venv`:

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Luồng nghiên cứu/viết không cần Redis, Celery, Qdrant hoặc Docker. `requirements-optional.txt` chỉ phục vụ phần vector store thử nghiệm, không phải điều kiện để sử dụng giao diện này. `pypdf` nằm trong bộ cài chính để đọc PDF có lớp văn bản.

Nếu chưa có `.env`, sao chép tệp mẫu:

```powershell
Copy-Item .env.example .env
```

Nếu `.env` đã tồn tại, sửa tệp hiện có thay vì ghi đè. Các khóa mẫu/placeholder không dùng được để gọi dịch vụ. Không đưa `.env` hoặc khóa vào mã nguồn, ảnh chụp hay báo cáo.

| Biến | Cách dùng |
| --- | --- |
| `LLM_PROVIDER` | `openai` hoặc `google` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Khóa và tên model được tài khoản OpenAI của bạn hỗ trợ; dùng khi chọn `openai` |
| `GOOGLE_API_KEY`, `GOOGLE_MODEL` | Cần cho bước kiểm duyệt ngữ nghĩa Gemini; cũng dùng cho nghiên cứu khi chọn `google` |
| `MODERATION_MODEL` | Tùy chọn model Gemini dành riêng cho kiểm duyệt ngắn; để trống để dùng `GOOGLE_MODEL` |
| `TAVILY_API_KEY` | Khóa tìm kiếm; cần cho bước tìm tài liệu ban đầu |
| `OPENAI_BASE_URL` | Tùy chọn endpoint tương thích; để trống khi dùng OpenAI trực tiếp |
| `RESEARCH_MAX_CHARS` | Số ký tự nội dung mỗi nguồn đưa vào bước đọc model; mặc định 24.000 |
| `MAX_TOKENS` | Giới hạn đầu ra mỗi lần gọi model; mặc định 12.000, không phải hạn mức chi phí toàn phiên |
| `WORDS_PER_MINUTE` | Tốc độ lời đọc ước tính; mặc định 140 đơn vị tách bằng khoảng trắng/phút |
| `SESSION_DB_PATH` | Tùy chọn vị trí SQLite; mặc định `data/sessions.sqlite3` trong dự án |

Khi dùng Gemini cho cả kiểm duyệt và nghiên cứu, chỉ cần khóa Google. Nếu chọn OpenAI để nghiên cứu, vẫn cần khóa Google cho bước kiểm duyệt bắt buộc. Tên model trong `.env.example` là cấu hình mẫu; kiểm tra quyền truy cập thực tế trong tài khoản của bạn. Khởi động lại API sau khi sửa cấu hình.

Chạy API trong cửa sổ PowerShell thứ nhất:

```powershell
.\run.ps1 api
```

Chạy giao diện trong cửa sổ PowerShell thứ hai:

```powershell
.\run.ps1 ui
```

Mở [giao diện ScriptScout](http://127.0.0.1:8501) và [tài liệu API](http://127.0.0.1:8000/docs). Hai tiến trình cần tiếp tục chạy. Nếu máy chặn chạy `.ps1`, có thể dùng trực tiếp:

```powershell
.\venv\Scripts\python.exe -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

```powershell
.\venv\Scripts\python.exe -m streamlit run app_ui.py --server.address 127.0.0.1 --server.port 8501
```

Giao diện mặc định kết nối API cục bộ. Khi đổi địa chỉ API, đặt biến môi trường `SCRIPTSCOUT_API_URL` cho tiến trình Streamlit.

## Triển khai bằng Docker Compose

Cài Docker và điền các khóa trong `.env`, rồi chạy tại thư mục dự án:

```sh
docker compose up -d --build
```

Mở [ScriptScout](http://localhost:8501). Compose chạy API và giao diện, chờ API sẵn sàng trước khi khởi động UI, lưu phiên trong volume `scriptscout_data`. Giao diện dùng Streamlit với CSS và theme có sẵn trong dự án; không cần Node, bước build frontend, font bên ngoài hay dịch vụ vector.

```sh
docker compose ps
docker compose logs --tail=50 api ui
docker compose down
```

`down` giữ dữ liệu phiên; không thêm `-v` nếu cần giữ dữ liệu. Sau khi cập nhật mã nguồn, chạy lại lệnh `up -d --build`. Trên máy chủ dùng chung, đặt reverse proxy có HTTPS và đăng nhập trước cổng UI; API và UI mặc định chỉ mở trên `127.0.0.1` của máy chủ. Ứng dụng hiện là một không gian làm việc chung, chưa có tài khoản hay phân quyền từng giảng viên.

Giới hạn PDF là **8 MB mỗi tệp** ở cả ô tải tệp, Streamlit (`.streamlit/config.toml`) và API (`models/limits.py`). Không có bước giữ tệp quá giới hạn để xử lý sau.

## Quy trình sử dụng

Trước khi tạo phiên nghiên cứu, hệ thống xét toàn bộ chủ đề, người học, từng mục tiêu và mô tả phong cách giảng dạy. Bộ lọc cục bộ chỉ chặn nhanh các trường hợp rõ ràng, không có quyền cấp phép nghiên cứu. Mọi yêu cầu còn lại phải được Gemini kiểm duyệt ngữ nghĩa: **cho phép**, **chặn** hoặc **cần làm rõ**. Chỉ kết quả cho phép hợp lệ mới được tạo phiên, xếp tác vụ và bắt đầu tìm kiếm/đọc nguồn/viết kịch bản. Lỗi kết nối, hết thời gian, phản hồi sai cấu trúc hoặc chưa rõ mục đích đều dừng trước research.

Chính sách áp dụng cho mọi yêu cầu hướng dẫn, hỗ trợ, cổ vũ, kiếm lợi từ hoặc che giấu hành vi phạm pháp, kể cả cách nói không nằm trong danh sách từ khóa. Chủ đề liên quan hành vi phạm pháp chỉ được cho phép với mục đích phòng chống, nhận diện, cảnh báo, bảo vệ hoặc hỗ trợ nạn nhân rõ ràng, không kèm hướng dẫn thực hiện hành vi. Phân tích pháp luật chung hoặc nhãn “giáo dục” không tự tạo ngoại lệ; thiếu ngữ cảnh phòng chống thì cần làm rõ. Các bài học thông thường và giáo dục giới tính phù hợp vẫn được phép. Chính sách được định nghĩa ở `services/admission_policy.py`; kết quả của mô hình phải qua bộ kiểm tra quyết định nghiêm ngặt, không được tự mở quyền bằng dữ liệu do người dùng gửi.

Bước chặn cục bộ không tốn API. Bước kiểm duyệt ngữ nghĩa có một lượt Gemini ngắn cho yêu cầu chưa có kết quả hợp lệ trong bộ nhớ: tối đa 768 token đầu ra, giới hạn chờ 20 giây, không tự thử lại, không dùng công cụ tìm kiếm hoặc truy cập nguồn. Đây là phí kiểm duyệt riêng, chưa phải chi phí research. Kết quả được lưu tạm tối đa 10 phút, 128 yêu cầu; thay đổi nội dung hoặc phiên bản chính sách phải kiểm tra lại. Phiên cũ cũng phải qua cửa kiểm duyệt trước các thao tác trả phí. `GOOGLE_API_KEY` cần được cấu hình cho bước này ngay cả khi dùng OpenAI để nghiên cứu; `MODERATION_MODEL` tùy chọn, mặc định dùng `GOOGLE_MODEL`.

Kiểm duyệt ngữ nghĩa mở rộng khả năng xét mục đích vượt ra ngoài từ khóa, nhưng vẫn có thể phân loại sai; đây không phải cơ chế bảo đảm xác định mọi hành vi trái pháp luật. Sau khi thay đổi bộ lọc, khởi động lại API và Streamlit. Giao diện từ chối bắt đầu research nếu máy chủ chưa công bố đúng phiên bản kiểm duyệt bắt buộc, thay vì gửi yêu cầu tới bản cũ.

1. Nhập chủ đề cụ thể, đối tượng học, mục tiêu, thời lượng 1–15 phút và số nguồn 3–50. Đây là số nguồn tối đa sẽ đọc, không bảo đảm tìm đủ nếu kết quả trùng hoặc thiếu tài liệu phù hợp. Tìm nhiều nguồn sẽ tốn thêm thời gian và lượt gọi dịch vụ.
2. Chọn ngôn ngữ nguồn: Việt, Anh, Pháp, Đức, Tây Ban Nha, Nhật, Hàn hoặc Trung. Model tạo truy vấn bằng từng ngôn ngữ; hệ thống tìm tối đa 8 truy vấn, loại URL trùng và phân bổ kết quả giữa các ngôn ngữ. Ngôn ngữ truy vấn không bảo đảm ngôn ngữ trang; thiếu nguồn phù hợp sẽ có cảnh báo.
3. Chọn phong cách có sẵn hoặc mô tả phong cách riêng. Ví dụ: “Xưng cô/các em, bắt đầu bằng tình huống lớp học, giải thích thuật ngữ ngắn, đặt câu hỏi gợi mở sau mỗi ý, ghi chỗ dừng, tránh giọng quảng cáo.” Mô tả này đi vào cả bước viết và bước sửa.
4. Đọc hồ sơ: tóm tắt tiếng Việt, luận điểm, trích dẫn nguyên ngữ, diễn giải tiếng Việt, tác giả/ngày nếu có bằng chứng, điểm sàng lọc và cảnh báo mâu thuẫn. Bấm **Xem bản nội dung đã tải** để đối chiếu đoạn gốc.
5. Chỉ duyệt những nguồn thực sự phù hợp. Nguồn không đọc được, có dấu hiệu chỉ dẫn ẩn hoặc không có trích dẫn khớp không được dùng để viết. Có thể bổ sung URL công khai rồi duyệt lại hồ sơ.
6. Tạo kịch bản. Mỗi cảnh có lời đọc, gợi ý hình ảnh, ghi chú giảng viên; câu thông tin gắn mã luận điểm và đoạn nguồn. Đọc các câu **CẦN KIỂM TRA** trước khi ghi hình.
7. Bỏ nguồn không muốn sử dụng và bấm cập nhật. Hệ thống giữ `line_id`, viết lại các câu liên quan bằng bằng chứng còn lại; thiếu bằng chứng thì để yêu cầu giảng viên bổ sung.
8. Xuất Markdown để đọc/biên tập và JSON để lưu cấu trúc, dẫn chứng, trạng thái kiểm chứng. Kịch bản hiện dùng schema riêng của dự án; chưa có mẫu biểu chính thức của đơn vị/ban tổ chức để đối chiếu, nên không khẳng định đầu ra tuân thủ một template bên ngoài.

Bạn có thể chuyển giữa tài liệu và kịch bản từ thanh bên hoặc nút chuyển ở đầu/cuối nội dung. Danh sách tài liệu có tìm kiếm, lọc và phân trang; lựa chọn nguồn được giữ khi chuyển trang hoặc lọc. Tiến độ tác vụ tự cập nhật; không cần làm mới trạng thái bằng tay.

Giao diện cho giảng viên không hiển thị địa chỉ API, tên model, khóa hoặc trạng thái cấu hình. Thông tin vận hành dành cho quản trị viên ở `GET /api/health` và nhật ký máy chủ; `content_policy_version` cho biết bản chặn cục bộ, còn `research_admission` xác nhận bước kiểm duyệt ngữ nghĩa bắt buộc và phiên bản đã nạp. Khi không thể hoàn thành một thao tác, giao diện chỉ hiển thị thông báo dễ hiểu và giữ kết quả đã có.

Nút có phản hồi khi rê chuột, nhấn và điều hướng bằng bàn phím. Khi bài giảng thực sự đang được xử lý, giao diện hiện chỉ báo tải cùng tên công việc; không dùng phần trăm hay thời gian chờ giả. Các hiệu ứng chuyển động được tắt khi thiết bị bật tùy chọn giảm chuyển động (`prefers-reduced-motion`).

Nút **Xóa vĩnh viễn** xóa cả yêu cầu, hồ sơ, kịch bản, nội dung nguồn và PDF gốc của phiên sau khi xác nhận. Không có thùng rác hay hoàn tác. Cơ sở dữ liệu được thu gọn ngay để trả lại dung lượng; các tệp đã tải xuống máy trước đó không thuộc phiên lưu trên máy chủ. Phiên đang xử lý phải hoàn tất trước khi xóa. Khi nâng cấp từ bản có thùng rác, nội dung của các phiên đã xóa trước đó cũng được dọn khi API khởi động; các phiên còn sử dụng được giữ nguyên.

Nếu trang xuất bản từ chối truy cập, chọn **Tìm bản công khai và đọc lại**. Hệ thống thử tìm bản toàn văn của cùng bài theo mã DOI/arXiv/PMC hoặc mã bài của nhà xuất bản. Bản tìm được phải tải và kiểm tra được; thông tin tìm kiếm không thay thế nội dung bài. Với tài liệu bạn đã có, dùng **Đọc PDF của tôi** để tải PDF tối đa 8 MB, có lớp văn bản. Bản PDF gốc được lưu cùng phiên để đối chiếu; bản scan cần OCR trước khi tải lên.

## Hiểu đúng kết quả kiểm chứng

`is_verified` trên trích dẫn có nghĩa đoạn **nguyên ngữ** xuất hiện trong văn bản đã tải, sau chuẩn hóa Unicode và khoảng trắng. Không dùng khớp gần đúng để chấp nhận việc đổi số hoặc bỏ từ phủ định. `match_start`/`match_end` là vị trí ký tự trong văn bản đã trích xuất, không phải tọa độ trang PDF.

`snippet_translation_vi` là bản diễn giải riêng; khớp trích dẫn gốc không chứng minh bản dịch đúng. Bước kiểm toán ngữ nghĩa dùng model để rà câu tiếng Việt so với bằng chứng, nhưng cùng nhà cung cấp/model với bước viết, vì vậy vẫn có thể mắc cùng lỗi. Giảng viên cần kiểm tra thuật ngữ, số, đơn vị, phủ định và phạm vi kết luận.

Mỗi luận điểm còn giữ `source_context` lấy trực tiếp từ văn bản xung quanh trích dẫn. Bước viết và kiểm toán cùng đọc phần này để tránh cắt mất từ phủ định hoặc điều kiện ở ngay trước/sau đoạn được trích.

Với hồ sơ lớn, đối chiếu chia theo nhóm luận điểm và ghi rõ giới hạn so sánh giữa các nhóm. Bước viết chọn một tập bằng chứng vừa giới hạn ngữ cảnh, có đại diện từ từng nguồn đã duyệt, giữ nguyên đoạn ngữ cảnh gốc của mỗi luận điểm được chọn. Toàn bộ luận điểm và trích dẫn vẫn nằm trong hồ sơ; nếu chỉ dùng một phần để viết, kịch bản sẽ ghi rõ. Duyệt 50 nguồn không có nghĩa một video ngắn sẽ trích dẫn tất cả 50 nguồn.

Số liệu được giữ trạng thái **chưa xác minh độc lập**, kể cả khi model thấy hai URL đồng thuận. Hai trang có thể cùng chép một nghiên cứu. Ứng dụng không tự chứng minh tính độc lập của nguồn hay biến điểm tin cậy thành xác suất thông tin đúng.

Điểm sàng lọc được tính minh bạch:

| Tiêu chí | Trọng số | Cách tính hiện tại |
| --- | --- | --- |
| Xuất xứ tên miền | 30% | 70 cho các hậu tố học thuật/chính phủ được nhận diện, 45 cho tên miền khác |
| Độ mới | 25% | 90 trong một năm; 70 trong ba năm; 40 nếu cũ hơn; 20 nếu thiếu/ngày không hợp lệ |
| Bằng chứng | 25% | Không có trích dẫn khớp: 20; có: 55 + 10 mỗi đoạn, tối đa 95 |
| Thông tin tác giả | 20% | Có thông tin tên tác giả: 60; chưa rõ: 20; chưa xác minh chuyên môn độc lập |

Quy tắc tuổi tài liệu không kết luận một tài liệu nền tảng cũ là sai. Nhận diện hậu tố tên miền, ngày và chỉ dẫn ẩn đều là heuristic có thể bỏ sót hoặc cảnh báo nhầm.

## Tải nguồn và giới hạn

- Đọc HTTP/HTTPS trực tiếp: HTML, văn bản và PDF có lớp text. Không dùng đoạn mô tả trên trang kết quả tìm kiếm làm bằng chứng.
- Chỉ kết nối IP công khai trên cổng 80/443; kiểm tra DNS và từng redirect, giữ IP đã xác nhận cho kết nối. Không đọc localhost hoặc mạng nội bộ.
- Giới hạn tải 8 MB, tối đa 5 redirect, trích tối đa 60.000 ký tự và 100 trang PDF; phần bị giới hạn có cảnh báo. Model có thể chỉ đọc phần đầu theo `RESEARCH_MAX_CHARS`.
- Không đăng nhập website, không vượt tường phí/CAPTCHA, không thực thi JavaScript, chưa OCR PDF scan. Nguồn lỗi/thiếu nội dung được ghi rõ để người dùng chọn nguồn khác.
- Xóa phần tử HTML ẩn và phát hiện một số mẫu chỉ dẫn đáng ngờ trước khi đưa vào model; đây chưa phải bảo đảm phát hiện mọi prompt injection đa ngôn ngữ.
- Thời lượng dựa trên số đơn vị tách bằng khoảng trắng. Tiếng Việt và nhịp giảng thực tế có thể lệch; cần đọc thử.

## Phiên làm việc và API

SQLite lưu yêu cầu, hồ sơ, bản nội dung đã tải, kịch bản, tiến độ và dữ liệu token đã ghi nhận trong `data/sessions.sqlite3`. Mở lại phiên ở thanh bên sau khi tải lại giao diện/khởi động lại API. Tác vụ đang chạy khi API dừng được đánh dấu lỗi để thử lại; đây chưa phải hàng đợi bền vững tự tiếp tục từ bước bị gián đoạn. Dùng một tiến trình API với cấu hình chạy mặc định.

Các thao tác dài trả HTTP **202** với `session_id`; client cần đọc trạng thái qua GET. Trạng thái chính: `researching` → `awaiting_review` → `writing` → `script_ready`; sửa nguồn dùng `patching`; lỗi dùng `failed`. Thao tác mới trên phiên đang bận trả 409.

| Endpoint | Mục đích |
| --- | --- |
| `GET /api/health` | Tình trạng API, cấu hình đã có khóa hay chưa, rubric; không trả khóa |
| `POST /api/pipeline/start` | Bắt đầu nghiên cứu từ thông số bài giảng |
| `GET /api/sessions` | Danh sách tối đa 100 phiên gần nhất |
| `GET /api/sessions/{session_id}` | Trạng thái, tiến độ và kết quả |
| `DELETE /api/sessions/{session_id}` | Xóa vĩnh viễn phiên không chạy tác vụ và thu hồi dung lượng |
| `POST /api/pipeline/review` | Duyệt `approved_source_ids`, tạo/cập nhật kịch bản |
| `POST /api/pipeline/sources` | Bổ sung `url` vào phiên có hồ sơ |
| `POST /api/pipeline/sources/retry` | Thử đọc lại nguồn chưa truy cập được bằng `session_id`, `source_id` |
| `POST /api/pipeline/sources/upload` | Bổ sung PDF qua multipart `session_id`, `file` |
| `POST /api/pipeline/patch` | Bỏ `remove_source_ids` và sửa câu liên quan |
| `GET /api/sessions/{session_id}/sources/{source_id}` | Metadata và nội dung đã tải của nguồn |
| `GET /api/sessions/{session_id}/sources/{source_id}/file` | Tải lại PDF gốc do người dùng cung cấp |
| `GET /api/sessions/{session_id}/export?format=json` | Xuất phiên, không nhúng toàn văn nguồn |
| `GET /api/sessions/{session_id}/export?format=markdown` | Xuất kịch bản và hồ sơ dễ đọc |

Payload và ràng buộc đầy đủ ở `/docs`. Nếu nghiên cứu ban đầu thất bại, tạo bài giảng mới sau khi xử lý nguyên nhân. Nếu sửa/viết thất bại, dữ liệu trước thao tác vẫn được giữ để tiếp tục duyệt hoặc sửa; không có endpoint tự retry toàn phiên.

## Chi phí và dữ liệu gửi ra dịch vụ

Tìm kiếm gửi truy vấn đến Tavily. Các bước đọc/tóm tắt, đối chiếu, viết, kiểm toán và sửa gửi thông số bài học cùng nội dung cần thiết đến nhà cung cấp model đã chọn. Đọc URL công khai dùng HTTP trực tiếp; không cần khóa Jina.

Chi phí một phiên phụ thuộc model, độ dài nguồn, số truy vấn, độ dài kịch bản và số lần sửa:

Khi một bài khoa học bị chặn và đã xác định được DOI, hệ thống có thể dùng thêm tối đa một truy vấn Tavily cơ bản để tìm PDF công khai. Đây là lượt tìm kiếm tính theo gói Tavily; chỉ PDF tải được và khớp mã bài mới được dùng.

```text
Chi phí ước tính = tổng các lần gọi model
                  (token đầu vào × đơn giá đầu vào + token đầu ra × đơn giá đầu ra)
                  + tín dụng/lượt tìm Tavily × đơn giá của gói đang dùng
```

Nếu bảng giá niêm yết theo một triệu token, chia phần token tương ứng cho 1.000.000. Kiểm tra bảng giá và điều kiện tính phí của [OpenAI](https://developers.openai.com/api/docs/pricing), [Google Gemini](https://ai.google.dev/gemini-api/docs/pricing) và [Tavily](https://www.tavily.com/pricing); dự án không gán đơn giá cố định.

Trường `usage` lưu provider/model và số token input/output mà SDK cung cấp. Đây chưa phải sổ thanh toán: có thể thiếu lượt lỗi, retry, token suy luận, cache hoặc khoản phí khác; đối chiếu dashboard nhà cung cấp để biết hóa đơn thực tế. Nhật ký tìm kiếm ghi truy vấn/trạng thái/số kết quả, chưa ghi chi phí tín dụng Tavily. Muốn hạn chế chi phí, bắt đầu bằng 3–4 nguồn, 2 ngôn ngữ và bài 1–3 phút, rồi tăng khi đã đánh giá chất lượng.

## Kiểm thử ngoại tuyến và các tình huống khó

Chạy bộ kiểm thử không cần API key:

```powershell
.\run.ps1 test
```

Tương đương:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Chạy demo có assertion máy kiểm tra:

```powershell
.\venv\Scripts\python.exe tests\demo_hard_cases.py
```

Demo in nhãn **MÔ PHỎNG**, chặn kết nối socket thật, dùng `MockTransport` và adapter LLM/tìm kiếm giả lập. Các số 80%/40%, tên tác giả và tên miền học thuật/chính phủ là dữ liệu dựng để kiểm thử, không phải nghiên cứu thực tế.

- Tình huống chỉ dẫn ẩn: đọc fixture HTML thật qua bộ scraper, loại phần tử ẩn, cách ly nguồn và xác nhận không gửi trang đó vào adapter đọc model.
- Tình huống hai nguồn điểm cao nhưng mâu thuẫn: in hai trích dẫn tiếng Anh, diễn giải/tóm tắt tiếng Việt, rubric và cảnh báo. Model giả lập trả mâu thuẫn có chủ đích; demo chứng minh luồng xử lý, không đo khả năng phát hiện của model thật.
- Bằng chứng sửa cục bộ: bỏ nguồn A, kiểm tra chính xác tập `affected_line_ids`, giữ `line_id`, bảo đảm mọi câu không liên quan bằng nhau ở mức dữ liệu JSON và không còn tham chiếu A. Số liệu vẫn cần kiểm tra dù adapter kiểm toán báo phù hợp.

Thành công kết thúc bằng `PASS: ALL_OFFLINE_DEMOS`; assertion thất bại trả exit code khác 0. Kiểm thử ngoại tuyến không thay thế nghiệm thu dịch vụ trực tuyến.

## Nghiệm thu bằng dịch vụ thật

1. Cấu hình khóa thật và model được phép dùng; khởi động API/UI. Trong `GET /api/health`, `configuration.llm_configured`, `configuration.search_configured`, `research_admission.required` và `research_admission.configured` phải là `true`; `research_admission.policy_version` phải trùng bản hiện tại trong `services/admission_policy.py`. Giá trị cấu hình chỉ xác nhận khóa có dạng đã cấu hình; không chứng minh nhà cung cấp chấp nhận khóa/model.
2. Tạo bài 2 phút: “Học qua truy hồi và đọc lại tài liệu”, đối tượng sinh viên năm nhất, mục tiêu phân biệt hai cách học và nêu giới hạn bằng chứng. Chọn Việt/Anh/Đức, 6 nguồn. Nhập phong cách “xưng cô/các em, câu ngắn, hỏi gợi mở, ghi nhịp dừng”.
3. Đợi hồ sơ; đối chiếu nhật ký truy vấn với các ngôn ngữ đã chọn. Nếu thiếu nguồn một ngôn ngữ hoặc nguồn bị chặn, phải có cảnh báo; không tự tính thiếu nguồn thành thành công.
4. Mở ít nhất một nguồn ngoại ngữ: kiểm tra URL truy cập được, tiêu đề, ngày/tác giả, đoạn trích nằm trong **bản nội dung đã tải**, số liệu/phủ định được giữ trong diễn giải tiếng Việt. Chọn một URL bổ sung do bạn biết và thử đọc nó vào hồ sơ.
5. Duyệt nguồn và tạo kịch bản; xác nhận lời đọc tiếng Việt và cách xưng hô, câu hỏi, ghi chú phù hợp phong cách. Đối chiếu ít nhất một câu thông tin với nguồn; các con số chưa xác minh độc lập phải được đánh dấu.
6. Xuất JSON trước khi sửa. Bỏ một nguồn đang có dẫn chứng; xuất JSON sau khi sửa. Ghép câu bằng `line_id`: tập thay đổi phải là `affected_line_ids`, câu ngoài tập phải giữ nguyên, không còn tham chiếu nguồn bị bỏ. Demo ngoại tuyến cũng thực hiện các assertion này tự động.
7. Khởi động lại API và mở phiên từ lịch sử, xác nhận hồ sơ/kịch bản còn tồn tại. Tải Markdown/JSON và kiểm tra tiếng Việt, trích dẫn, cảnh báo được giữ.
8. Ghi lại model, số nguồn/ngôn ngữ, thời gian xử lý, token đã ghi nhận, lỗi nhà cung cấp và nhận xét của giảng viên. Chỉ đánh dấu đã nghiệm thu trực tuyến sau khi hoàn tất bằng khóa thật; không dùng kết quả demo mô phỏng để thay cho bước này.

## Kết quả kiểm tra bản hiện tại — 18/09/2026

- 213 kiểm thử tự động đạt, gồm API, lưu phiên, kiểm chứng nguồn, pipeline, giao diện, xóa vĩnh viễn và thu hồi dung lượng, PDF 8 MB, hồ sơ 50 nguồn và kiểm duyệt trước nghiên cứu. Các ca ngữ nghĩa dùng chủ đề ngoài danh sách từ khóa, xác nhận chặn/cần làm rõ/lỗi không tạo phiên hay xếp tác vụ; cache gắn đủ bốn trường; mọi thao tác trả phí và phiên cũ được kiểm tra lại. Các kiểm thử tự động dùng dịch vụ mô phỏng, không phát sinh phí API.
- Đã kiểm tra giao diện thật: ô tải tệp hiển thị 8 MB, chuyển trang giữ lựa chọn nguồn, đọc lại phiên đã lưu, nhãn nguồn tương phản rõ và thanh điều hướng mới. Thử yêu cầu không phù hợp ngay trên form: bị chặn, không tạo phiên mới và không chạy tác vụ. Cấu hình Docker Compose hợp lệ; chưa chạy build image Docker trong lần kiểm tra này.
- Đã kiểm tra hiệu ứng nút và xuất hiện nội dung trên trình duyệt; không tràn ngang ở kích thước kiểm tra. AppTest xác nhận chỉ báo tải xuất hiện ở các trạng thái đang xử lý và biến mất khi hoàn tất hoặc lỗi.
- Đã thử riêng 3 lượt kiểm duyệt Gemini thật: một yêu cầu nói vòng về đưa tiền để hồ sơ thiếu điều kiện được duyệt bị chặn dù không khớp bộ lọc cục bộ; bài phòng chống hành vi đó và bài quang hợp hợp lệ được cho phép. Không chạy tìm kiếm/đọc nguồn trong các lần thử này. Đây là kiểm tra nhỏ có phí kiểm duyệt, không chứng minh nhận diện hoàn hảo mọi hành vi hay cách diễn đạt.
- Đã kiểm tra giao diện thật tự khóa nút bắt đầu khi máy chủ đang chạy chưa có phiên bản kiểm duyệt ngữ nghĩa bắt buộc. Cần khởi động lại API sau nâng cấp để kích hoạt luồng mới.
- Demo ngoại tuyến kết thúc bằng `PASS: ALL_OFFLINE_DEMOS`; xác nhận cách ly chỉ dẫn ẩn, xử lý cảnh báo mâu thuẫn và giữ nguyên câu không liên quan khi bỏ nguồn.
- Tải trực tiếp ba trang tài liệu Python bằng tiếng Anh, Pháp và Nhật: HTTP 200, có nội dung và metadata ngôn ngữ.
- Kiểm tra trình duyệt: form phong cách giảng dạy và chọn ngôn ngữ hiển thị được; khóa mẫu khiến nút bắt đầu bị khóa và API trả 503 rõ nguyên nhân.
- Sau khi chuyển cấu hình sang Google, đã gọi thử Gemini thành công với một yêu cầu JSON ngắn. Các kiểm thử với adapter giả không chứng minh chất lượng của model trên chủ đề mới.
- Đã kiểm tra một bản PDF công khai của bài khoa học bị chặn ở nhà xuất bản, đọc được văn bản và mã DOI trên trang đầu. Tìm bản thay thế tự động không bảo đảm thành công: các kết quả chỉ dẫn lại bài gốc hoặc chỉ có metadata được loại bỏ. Người dùng vẫn có thể bổ sung liên kết PDF hoặc tải tệp từ máy.
