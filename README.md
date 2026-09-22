# AI Router — Điều phối Multi-Agent giữa Antigravity, Codex và Claude Code

**[Tiếng Việt](README.md) | [English](README.en.md)**

Router cục bộ giúp phân loại một yêu cầu nghiệp vụ và tự động điều phối từng phần việc tới đúng AI Coding Agent CLI:

- **Antigravity** (`agy`) — Frontend/UI (React, Vue, HTML/CSS) và các thao tác đơn giản: scan path, đọc file, `cd`, kiểm tra/xác nhận trạng thái service, sửa lỗi giao diện nhỏ. Chạy trong `tmux` session sống để duy trì ngữ cảnh.
- **Codex** (`codex`) — Code Generation tốc độ cao, viết Unit/Integration Tests, boilerplate, database migrations, thuật toán, refactor hàm chuyên biệt.
- **Claude Code** (`claude`) — Suy luận nghiệp vụ phức tạp: phân tích yêu cầu, viết tài liệu bàn giao (handoff), phân chia task, thiết kế kiến trúc hệ thống & DB schema.

Toàn bộ logic nằm trong file:
[`ai-task-router/classify_and_split_task.py`](ai-task-router/classify_and_split_task.py),
đóng gói sẵn dưới dạng **Universal Skill** `ai-task-router`.

---

## Tính năng chính

- **Phân loại 3-Tier rule-based**: Tách yêu cầu thành nhiều mệnh đề, gán tương ứng cho Antigravity, Codex hoặc Claude Code. Mệnh đề mơ hồ hoặc phức tạp mặc định về Claude Code (an toàn nhất).
- **Antigravity chạy trong tmux session sống**: Mỗi project được cấp 1 tmux session riêng, tự động khởi tạo nếu chưa có. Giữ ngữ cảnh hội thoại liên tục giữa các sub-task.
- **Codex chạy non-interactive qua `codex exec`**: Thực thi nhanh chóng, an toàn trong workspace sandbox, tự động fallback nếu lỗi.
- **Claude Code chạy qua `--session-id` + `--resume`**: Tự động lưu session; khi cần hỏi người dùng sẽ dừng lại và resume phiên để tiết kiệm token.
- **Tự động Fallback thông minh 3 tầng**:
  - Antigravity lỗi/timeout hoặc quota 5 giờ > 90% $\rightarrow$ Fallback sang Codex/Claude Code.
  - Codex lỗi $\rightarrow$ Fallback sang Claude Code.
- **Báo cáo bàn giao bắt buộc**: Mọi task phân tích/tạo-sửa code đều ghi 1 file markdown vào `.ai_router_reports/`.
- **Kiểm tra trạng thái & Quota 3 Model**: Cờ `--check-quota` kiểm tra % hạn mức và trạng thái sẵn sàng của `agy`, `claude`, và `codex`.

---

## Cài đặt Universal Skill

Để kích hoạt skill cho **tất cả** các AI CLI trên máy (Claude Code, Antigravity, Codex):

```bash
# Clone repository (nếu chưa có)
git clone https://github.com/phapit/agent-skills.git
cd agent-skills/ai-task-router

# Chạy installer
./install.sh
```

Script sẽ tự động tạo symlink vào:
- `~/.claude/skills/ai-task-router`
- `~/.gemini/config/skills/ai-task-router`
- `~/.codex/skills/ai-task-router`
- `~/.agents/skills/ai-task-router`

---

## Cách dùng

```bash
# Phân loại và điều phối 1 yêu cầu nghiệp vụ
python3 ai-task-router/classify_and_split_task.py "sửa màu nút login trên UI react, viết unit test cho hàm auth, và viết tài liệu kiến trúc bàn giao"

# Kiểm tra quota & trạng thái của 3 CLI
python3 ai-task-router/classify_and_split_task.py --check-quota
```

---

## Cấu hình Context & Token Limit

Cấu hình tại [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):

```json
{
  "context": {
    "auto_compact": true,
    "claude_max_token_threshold": 300000,
    "agy_max_token_threshold": 600000,
    "codex_max_token_threshold": 200000
  },
  "fallback_chains": {
    "antigravity": ["claude"],
    "codex": ["claude"],
    "claude": []
  }
}
```

### Tùy biến thứ tự Fallback

Người dùng có thể tự cấu hình thứ tự fallback theo nhu cầu:
- **Trong file cấu hình**: chỉnh sửa mục `"fallback_chains"` trong `settings.json`.
  - Mặc định:
    - `"antigravity": ["claude"]`: Antigravity lỗi/hết quota -> chuyển sang Claude Code.
    - `"codex": ["claude"]`: Codex lỗi -> chuyển sang Claude Code.
    - `"claude": []`: Claude Code lỗi -> dừng hẳn (không fallback).
  - Chuỗi đa tầng: `"antigravity": ["codex", "claude"]` (Antigravity lỗi -> thử Codex, Codex lỗi -> thử tiếp Claude).
- **Ghi đè nhanh qua CLI**:
  ```bash
  python3 ai-task-router/classify_and_split_task.py --fallback "antigravity:claude,codex:claude,claude:none" "yêu cầu..."
  ```

---

## Tuyên bố miễn trừ trách nhiệm (Disclaimer)

- Dự án này là công cụ điều phối mã nguồn mở độc lập, không phải là sản phẩm chính thức và không có liên kết, tài trợ hay bảo trợ bởi Anthropic, Google, hoặc OpenAI.
- Mọi thương hiệu và tên sản phẩm (`Claude`, `Antigravity`, `Codex`) thuộc quyền sở hữu của các tổ chức tương ứng.
- Khi sử dụng tính năng điều phối tự động (như `codex exec` hay `agy`), hãy đảm bảo bạn kiểm soát kỹ các thiết lập sandbox và quyền hạn thực thi lệnh để tránh rủi ro ngoài ý muốn cho hệ thống tệp tin của bạn.

---

## Giấy phép (License)

Dự án được phân phối dưới giấy phép [MIT](LICENSE). Xem file `LICENSE` để biết thêm chi tiết.


