# Context Management Rules

> **Lưu ý về hiệu lực**: file này KHÔNG được `claude` hay `agy` tự động nạp —
> đã kiểm chứng bằng `claude --help`/`claude doctor` (schema settings thật
> của Claude Code không có mục `context.*`) và `agy --help`/`agy install`
> (không có flag đọc rules/system-prompt từ file). Muốn các rule dưới đây
> thực sự có hiệu lực, phải chủ động đưa nó vào ngữ cảnh bằng 1 trong các
> cách sau:
> - **Claude Code**: `claude --append-system-prompt-file ~/.agents/rules/context-management.md ...`
>   (flag này có thật, đã xác nhận qua `claude --help`).
> - **Antigravity (`agy`)**: không có flag tương đương — phải nối nội dung
>   file này vào đầu prompt gửi cho `agy` (agy có đọc + tuân theo AGENTS.md ở
>   gốc workspace theo `AntigravityCLI.md`, nhưng đó là rule *theo từng
>   project*, không phải rule *toàn cục* theo user như file này).
> - Hoặc copy nội dung phù hợp vào `AGENTS.md`/`CLAUDE.md` ở gốc từng project
>   cụ thể (cả 2 CLI đều tự đọc file đó theo đúng tài liệu chính thức).

## 1. Output Conciseness
- Chỉ trả lời trực tiếp vào câu hỏi, không lặp lại mã nguồn hoặc giải thích các khái niệm cơ bản trừ khi được yêu cầu.
- Sử dụng pseudocode hoặc chỉ trích xuất đoạn code cần sửa thay vì chép lại toàn bộ file.
- Không dán lại nguyên văn output của lệnh/diff vừa chạy trong cùng lượt nếu người dùng đã thấy nó rồi — chỉ tóm tắt phần thay đổi/kết quả quan trọng.

## 2. Context Compaction Prompt
- Khi lượng token hội thoại đạt khoảng 80% ngưỡng tối đa của phiên (xem
  `settings.json` → `context.claude_max_token_threshold` /
  `context.agy_max_token_threshold`), chủ động tự tóm tắt các bước đã thực
  hiện thành một danh sách ngắn gọn (bullet points) TRƯỚC KHI bị nén/xóa bắt
  buộc — chủ động luôn tốt hơn để tới ngưỡng cứng mới xử lý.
- Xóa bỏ các log lỗi cũ đã được giải quyết ra khỏi bộ nhớ đệm (scratchpad).
- Với Claude Code: ngưỡng cứng do CLI tự quản qua `--autocompact` (tự tóm
  tắt, không mất hoàn toàn ngữ cảnh). Với Antigravity: không có lệnh compact
  thật, vượt ngưỡng đồng nghĩa `/clear` sẽ XÓA SẠCH hội thoại — vì vậy nên
  tự tóm tắt tiến độ ra file/báo cáo (không chỉ giữ trong bộ nhớ hội thoại)
  trước khi có nguy cơ bị `/clear`, để không mất thông tin vĩnh viễn.

## 3. Scope Limitation
- Chỉ tập trung vào các file trong thư mục làm việc hiện tại được chỉ định.
- Không tự ý đọc các file tài liệu định dạng `.pdf`, `.md` dài dòng trừ khi có lệnh đích danh từ người dùng.
- Ưu tiên tìm kiếm có mục tiêu (grep/glob theo từ khóa hoặc đường dẫn cụ thể)
  thay vì liệt kê/đọc toàn bộ nội dung một thư mục lớn khi chỉ cần 1 vài file.
- Với file lớn hơn `context.max_file_size_kb`, đọc theo từng đoạn (offset/
  limit) thay vì đọc nguyên file một lần, trừ khi người dùng yêu cầu xem toàn
  bộ nội dung.

## 4. Đa agent chạy song song (bối cảnh router `ai-task-router`)
- Khi nhiều task con chạy song song qua router (`classify_and_split_task.py`),
  chỉ đọc các file báo cáo bàn giao (`.ai_router_reports/*.md`) LIÊN QUAN
  trực tiếp tới task hiện tại — không đọc toàn bộ lịch sử báo cáo của mọi
  task trước đó chỉ để "cho chắc".
- Mỗi task con tự giới hạn đúng phạm vi được giao; không tự ý mở rộng sang
  làm luôn phần việc của agent khác (tăng context/nguy cơ đụng độ vô ích).
