# AI Router — Điều phối Multi-Agent giữa Antigravity, Codex và Claude Code

**[Tiếng Việt](README.md) | [English](README.en.md)**

Router cục bộ giúp phân loại một yêu cầu nghiệp vụ và tự động điều phối từng phần việc tới đúng AI Coding Agent CLI:

- **Antigravity** (`agy`) — Frontend/UI (React, Vue, HTML/CSS) và các thao tác đơn giản: scan path, đọc file, `cd`, kiểm tra/xác nhận trạng thái service, sửa lỗi giao diện nhỏ. Chạy qua CLI print mode với khả năng duy trì ngữ cảnh qua `--continue` / `--conversation`.
- **Codex** (`codex`) — Code Generation tốc độ cao, viết Unit/Integration Tests, boilerplate, database migrations, thuật toán, refactor hàm chuyên biệt.
- **Claude Code** (`claude`) — Suy luận nghiệp vụ phức tạp: phân tích yêu cầu, viết tài liệu bàn giao (handoff), phân chia task, thiết kế kiến trúc hệ thống & DB schema.

Toàn bộ logic nằm trong file:
[`ai-task-router/classify_and_split_task.py`](ai-task-router/classify_and_split_task.py),
đóng gói sẵn dưới dạng **Universal Skill** `ai-task-router`.

---

## Tính năng chính

- **Phân loại 3-Tier rule-based**: Tách yêu cầu thành nhiều mệnh đề, gán tương ứng cho Antigravity, Codex hoặc Claude Code. Mệnh đề mơ hồ hoặc phức tạp mặc định về Claude Code (an toàn nhất).
- **Antigravity chạy CLI trực tiếp với Resume**: Thực thi qua print mode (`-p`), tự động tiếp tục ngữ cảnh bằng `--continue` (hoặc `--conversation <ID>`) khi cần hỏi người dùng hoặc tiếp tục task.
- **Codex chạy non-interactive qua `codex exec`**: Thực thi nhanh chóng, an toàn trong workspace sandbox, tự động fallback nếu lỗi.
- **Claude Code chạy qua `--session-id` + `--resume`**: Tự động lưu session; khi cần hỏi người dùng sẽ dừng lại và resume phiên để tiết kiệm token.
- **Tự động Fallback thông minh 3 tầng**:
  - Antigravity lỗi/timeout hoặc quota 5 giờ > 90% $\rightarrow$ Fallback sang Codex/Claude Code.
  - Codex lỗi $\rightarrow$ Fallback sang Claude Code.
- **Antigravity Worker Pool & Tự động Failover (Auto-Handoff)**: Hỗ trợ đa profile (`worker1`, `worker2`, `worker3`). Khi một profile chạm hạn mức quota 5 giờ (> 90%) hoặc gặp lỗi `ResourceExhausted` / `429`, Router sẽ tự động lập báo cáo bàn giao chi tiết (tiến độ, `git diff`, tệp đã sửa) rồi chuyển giao liền mạch sang worker kế tiếp.
- **Báo cáo bàn giao bắt buộc**: Mọi task phân tích/tạo-sửa code đều ghi 1 file markdown vào `.ai_router_reports/`.
- **Kiểm tra trạng thái & Quota 3 Model**: Cờ `--check-quota` kiểm tra % hạn mức và trạng thái sẵn sàng của `agy`, `claude`, và `codex`.

---

## Cài đặt nhanh 3 Model AI CLI (Linux & macOS)

Trước khi sử dụng Router, bạn có thể cài đặt nhanh các CLI của 3 Model AI thông qua các lệnh terminal sau:

### 1. Antigravity (`agy`)
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

### 2. Claude Code (`claude`)
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

### 3. Codex CLI (`codex`)
```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

---

## Cài đặt Universal Skill

### Cách 1: Sử dụng `skills` CLI (Khuyến nghị — 1 dòng lệnh)

Cài đặt toàn cục (Global) cho mọi AI Agent trên máy:
```bash
npx skills add phapit/agent-skills --skill ai-task-router -g
```

Hoặc chỉ cài cho project hiện tại:
```bash
npx skills add phapit/agent-skills --skill ai-task-router
```

### Cách 2: Cài đặt thủ công qua Git & Symlink

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

# Tùy ý tắt 1 hoặc nhiều Model AI khi chạy
python3 ai-task-router/classify_and_split_task.py --disable codex "yêu cầu..."
python3 ai-task-router/classify_and_split_task.py --no-agy "yêu cầu..."
python3 ai-task-router/classify_and_split_task.py --enable codex,claude "yêu cầu..."
```

---

## Tùy chọn Bật / Tắt Model AI

Người dùng có thể tuỳ ý tắt bất kỳ Model AI nào trong 3 model (`antigravity`, `codex`, `claude`) theo 2 cách:

### 1. Qua cờ dòng lệnh (CLI Flags)
- `--disable <agents>`: Tắt một hoặc nhiều model (ví dụ: `--disable codex` hoặc `--disable antigravity,claude`).
- `--no-agy` / `--no-antigravity`: Tắt nhanh Antigravity CLI.
- `--agy-continue`: Tiếp tục phiên hội thoại gần nhất của Antigravity (`agy --continue`).
- `--agy-conversation <ID>`: Chỉ định Conversation ID cụ thể để Antigravity khôi phục (`agy --conversation <ID>`).
- `--agy-profiles <p1,p2,...>`: Chỉ định danh sách profile Antigravity làm pool luân chuyển (ví dụ: `--agy-profiles worker1,worker2,worker3`).
- `--no-codex`: Tắt nhanh Codex CLI.
- `--no-claude`: Tắt nhanh Claude Code CLI.
- `--enable <agents>`: Chỉ bật các model được liệt kê (ví dụ: `--enable codex,claude`).

*Cơ chế tự động điều phối lại:* Khi một model bị tắt:
- Các sub-task vốn thuộc về model đó sẽ tự động được chuyển sang model phù hợp nhất tiếp theo (theo chuỗi fallback hoặc năng lực thay thế).
- Model bị tắt sẽ tự động bị loại bỏ khỏi mọi chuỗi fallback.

### 2. Cấu hình cố định trong `settings.json`
Chỉnh sửa file [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):
```json
{
  "enabled_agents": {
    "antigravity": true,
    "codex": false,
    "claude": true
  }
}
```
Hoặc dạng danh sách: `"disabled_agents": ["codex"]`.

---

## Cấu hình Context & Token Limit

Cấu hình tại [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):

```json
{
  "enabled_agents": {
    "antigravity": true,
    "codex": true,
    "claude": true
  },
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

## Chế độ AI Supervisor & Quality Gate (Phương án A + B)

Thay vì chỉ điều khiển bằng code Python cứng nhắc, bạn có thể chỉ định một **AI Model đóng vai trò Supervisor (Tech Lead)**:
- **Phương án A (Terminal Control):** Giám sát trực tiếp các terminal tmux của Worker (`agy_worker`, `codex_worker`, `claude_worker`), đọc màn hình terminal và gửi phím xác nhận khi Worker gặp prompt `[y/N]`.
- **Phương án B (Quality Gate):** Nghiệm thu độc lập sau khi Worker hoàn tất — tự động kiểm tra `git diff` và chạy test suite (`pytest`, `npm test`...) để đảm bảo chất lượng code trước khi bàn giao.

```bash
# Chỉ định Claude làm Supervisor kiêm Quality Gate
python3 ai-task-router/classify_and_split_task.py --supervisor claude "yêu cầu..."

# Chỉ định Antigravity làm Supervisor với profile riêng
python3 ai-task-router/classify_and_split_task.py --supervisor antigravity --supervisor-profile supervisor "yêu cầu..."

# Bật hoặc tắt riêng cổng kiểm thử độc lập (Quality Gate)
python3 ai-task-router/classify_and_split_task.py --quality-gate "yêu cầu..."
```

Tài liệu chi tiết hướng dẫn Supervisor: [`ai-task-router/SUPERVISOR_SYSTEM_PROMPT.md`](ai-task-router/SUPERVISOR_SYSTEM_PROMPT.md).

---

## Quản lý Đa tài khoản (Multi-Account Profile Manager)

Để chạy 2 tài khoản Antigravity (hoặc Claude, Codex) độc lập cùng lúc trên tmux mà không bị xung đột token/quota:

```bash
# 1. Khởi tạo và đăng nhập tài khoản thứ 2 cho Antigravity (hoặc claude, codex)
python3 ai-task-router/profile_manager.py login antigravity supervisor

# 2. Xem danh sách profile hiện có
python3 ai-task-router/profile_manager.py status

# 3. Khởi chạy CLI trong tmux với profile riêng
tmux new-session -s agy_supervisor "python3 ai-task-router/profile_manager.py run antigravity supervisor"
```

Toàn bộ thông tin tài khoản và cấu hình của profile thứ 2 được cách ly an toàn trong `~/.agents/profiles/`.

---

## Antigravity Worker Pool & Tự động Chuyển giao (Auto-Failover)

Nhằm giải quyết bài toán tài khoản Antigravity đạt giới hạn hạn mức (5-hour quota) hoặc lỗi quota token trong quá trình xử lý, Router hỗ trợ cơ chế **Worker Pool** luân chuyển giữa các profile (`worker1` $\rightarrow$ `worker2` $\rightarrow$ `worker3`):

### 1. Đăng nhập các Profile độc lập
Tạo và đăng nhập lần lượt 3 tài khoản Antigravity vào các thư mục profile biệt lập:
```bash
python3 ai-task-router/profile_manager.py login antigravity worker1
python3 ai-task-router/profile_manager.py login antigravity worker2
python3 ai-task-router/profile_manager.py login antigravity worker3
```

### 2. Cấu hình trong `settings.json` hoặc CLI
Khai báo danh sách profile trong [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):
```json
{
  "antigravity": {
    "profiles": ["worker1", "worker2", "worker3"],
    "quota_threshold_percent": 90
  }
}
```
Hoặc chỉ định trực tiếp qua cờ CLI:
```bash
python3 ai-task-router/classify_and_split_task.py --agy-profiles worker1,worker2,worker3 "yêu cầu..."
```

### 3. Quy trình Bàn giao Tự động (Auto-Handoff Protocol)
Trước khi chuyển sang worker mới, Router đảm bảo **ngữ cảnh không bị mất mát**:
1. **Kiểm tra Pre-flight Quota**: Trước khi gọi worker, router kiểm tra quota 5 giờ. Nếu đã vượt ngưỡng cấu hình (mặc định > 90%), worker sẽ tự động được bỏ qua để nhường chỗ cho worker sẵn sàng tiếp theo.
2. **Bắt lỗi Quota Runtime**: Nếu worker đang xử lý mà gặp lỗi hết quota (`ResourceExhausted`, `429 Too Many Requests`, hoặc `quota exceeded`), Router kích hoạt quy trình chuyển giao.
3. **Lập tài liệu bàn giao bắt buộc (`ensure_worker_handoff_report`)**:
   - Router trích xuất hiện trạng công việc: tóm tắt tiến độ, `git status --short`, `git diff --stat`, và danh sách tệp đang chỉnh sửa.
   - Ghi vào báo cáo bàn giao: `.ai_router_reports/<timestamp>_handoff_agy_<profile>.md`.
4. **Tiếp nối liền mạch**: Worker mới kế tiếp (`worker2`) được kích hoạt và nạp toàn bộ nội dung bàn giao này vào prompt, tiếp tục hoàn thành các phần việc còn dở dang mà không cần người dùng can thiệp.

---

## Tuyên bố miễn trừ trách nhiệm (Disclaimer)

- Dự án này là công cụ điều phối mã nguồn mở độc lập, không phải là sản phẩm chính thức và không có liên kết, tài trợ hay bảo trợ bởi Anthropic, Google, hoặc OpenAI.
- Mọi thương hiệu và tên sản phẩm (`Claude`, `Antigravity`, `Codex`) thuộc quyền sở hữu của các tổ chức tương ứng.
- Khi sử dụng tính năng điều phối tự động (như `codex exec` hay `agy`), hãy đảm bảo bạn kiểm soát kỹ các thiết lập sandbox và quyền hạn thực thi lệnh để tránh rủi ro ngoài ý muốn cho hệ thống tệp tin của bạn.

---

## Giấy phép (License)

Dự án được phân phối dưới giấy phép [MIT](LICENSE). Xem file `LICENSE` để biết thêm chi tiết.


