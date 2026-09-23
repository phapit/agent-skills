---
name: ai-task-router
description: >-
  Điều phối yêu cầu kỹ thuật tới đúng AI Coding Agent CLI bằng router script
  (classify_and_split_task.py): Antigravity (agy) cho frontend/UI và thao tác đơn giản,
  Codex (codex) cho code gen / unit tests / migrations, Claude Code (claude) cho
  suy luận nghiệp vụ / kiến trúc / handoff docs. Tự động phân loại, chạy song song,
  hỗ trợ resume session và fallback thông minh khi có agent lỗi hoặc cạn quota.
  Kích hoạt khi người dùng muốn "điều phối task", "phân chia task cho agent",
  "multi-agent", "route task cho AI khác", "chạy song song claude, agy, codex",
  hoặc kiểm tra usage/quota của các CLI.
---

# AI Task Router (Universal Skill)

Skill này cung cấp cơ chế **Multi-Agent Orchestration** điều phối công việc giữa 3 AI Coding Agent CLI:
1. **Antigravity (`agy`)**: Phụ trách Frontend/UI (React, Vue, HTML/CSS), scan path, đọc file, test/restart service, sửa lỗi giao diện nhỏ. Chạy trong `tmux` session sống theo từng project để giữ ngữ cảnh.
2. **Codex (`codex`)**: Phụ trách Code Generation tốc độ cao, viết Unit/Integration Tests, viết boilerplate, migration scripts, thuật toán, chuyển đổi hàm.
3. **Claude Code (`claude`)**: Phụ trách Suy luận nghiệp vụ phức tạp, phân tích kiến trúc hệ thống, tài liệu bàn giao (handoff), thiết kế DB schema, bảo mật/auth.

---

## 1. Cài đặt nhanh 3 Model AI CLI (Linux & macOS)

Nếu môi trường chưa có sẵn các CLI, hãy cài đặt nhanh qua các lệnh terminal:
- **Antigravity (`agy`)**:
  ```bash
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```
- **Claude Code (`claude`)**:
  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```
- **Codex CLI (`codex`)**:
  ```bash
  curl -fsSL https://chatgpt.com/codex/install.sh | sh
  ```

---

## 2. Cài đặt đa nền tảng (Universal Skill Discovery)

Để bất kỳ Agent nào (Claude Code, Antigravity, Codex) cũng có thể tự động nhận diện và sử dụng skill này:

### Cách 1: Qua `skills` CLI (Khuyến nghị)
```bash
npx skills add phapit/agent-skills --skill ai-task-router -g
```

### Cách 2: Chạy script installer cục bộ
```bash
bash ./install.sh
```
Script sẽ tự động tạo symlink vào các vị trí chuẩn:
- **Claude Code**: `~/.claude/skills/ai-task-router`
- **Antigravity (AGY)**: `~/.gemini/config/skills/ai-task-router` hoặc `.agents/skills/ai-task-router`
- **Codex / Open Agent**: `~/.codex/skills/ai-task-router`

---

## 3. Hướng dẫn dành cho Agent đang nhận yêu cầu

Khi bạn (Claude, Antigravity, hoặc Codex) nhận được yêu cầu điều phối đa agent từ người dùng:

### A. Phân loại và chạy điều phối Task
Chạy script `classify_and_split_task.py` với đường dẫn tới thư mục chứa skill hiện tại:

```bash
python3 <path_to_skill>/classify_and_split_task.py "<nguyên văn yêu cầu của người dùng>"
```
*Lưu ý:* Giữ nguyên `cwd` là thư mục làm việc của dự án người dùng (không `cd` đi nơi khác).

### B. Chỉ kiểm tra Quota & Trạng thái CLI
```bash
python3 <path_to_skill>/classify_and_split_task.py --check-quota
```

### C. Tùy ý bật / tắt một hoặc nhiều Model AI
Người dùng có thể chủ động tắt bất kỳ Model AI nào (ví dụ: cạn quota, chưa cài CLI, hoặc chỉ muốn dùng 1-2 model):
```bash
# Tắt một hoặc nhiều model qua cờ --disable
python3 <path_to_skill>/classify_and_split_task.py --disable codex "<yêu cầu...>"
python3 <path_to_skill>/classify_and_split_task.py --disable antigravity,claude "<yêu cầu...>"

# Hoặc dùng cờ tắt nhanh
python3 <path_to_skill>/classify_and_split_task.py --no-codex "<yêu cầu...>"
python3 <path_to_skill>/classify_and_split_task.py --no-agy "<yêu cầu...>"
python3 <path_to_skill>/classify_and_split_task.py --no-claude "<yêu cầu...>"

# Hoặc chỉ định rõ danh sách model ĐƯỢC PHÉP dùng qua --enable
python3 <path_to_skill>/classify_and_split_task.py --enable antigravity,claude "<yêu cầu...>"
```
*Ghi chú:* Khi một model bị tắt, các sub-task vốn thuộc về model đó sẽ tự động được router chuyển tiếp sang model khả dụng tốt nhất trong chuỗi fallback. Model bị tắt cũng được tự động loại khỏi mọi chuỗi fallback.

---

## 4. Cơ chế vận hành & Báo cáo bàn giao

- **Chạy song song**: Các sub-task được router dispatch đồng thời dưới dạng subprocess độc lập.
- **Báo cáo bắt buộc**: Mọi task tạo/sửa code hoặc phân tích đều tự động ghi báo cáo bàn giao vào thư mục `.ai_router_reports/` trong project để các agent khác và người dùng dễ dàng review.
- **Tương tác khi cần hỏi (Human-in-the-loop)**: Nếu agent sub-task cần người dùng ra quyết định, nó sẽ tạo file `.question.md`. Router sẽ tạm dừng, hỏi người dùng qua terminal, và resume đúng session làm việc.
- **Thứ tự Fallback có thể tùy biến** (cấu hình trong `.agents/settings.json` qua `fallback_chains`):
  - Mặc định:
    - `Antigravity` lỗi/timeout/quota > 90% $\rightarrow$ Fallback sang `Claude Code`.
    - `Codex` lỗi $\rightarrow$ Fallback sang `Claude Code`.
    - `Claude Code` lỗi $\rightarrow$ Dừng task.
  - Hỗ trợ chuỗi đa tầng (ví dụ: `antigravity -> codex -> claude`) hoặc ghi đè nhanh qua cờ `--fallback`.

---

## 5. Quản lý Context Token

Router đọc ngưỡng token từ `.agents/settings.json`:
- **Claude Code**: 300.000 token (tự động compact qua `--autocompact`).
- **Antigravity**: 600.000 token (tự động reset qua `/clear` khi đầy).
- **Codex**: 200.000 token.

---

## 6. Cấu hình Bật / Tắt Model mặc định trong `settings.json`

Để tắt hẳn một Model mà không cần truyền cờ CLI mỗi lần chạy, chỉnh sửa mục `enabled_agents` trong `.agents/settings.json`:
```json
{
  "enabled_agents": {
    "antigravity": true,
    "codex": false,
    "claude": true
  }
}
```
Hoặc dùng danh sách: `"disabled_agents": ["codex"]`. Router sẽ tự động nạp cấu hình và điều phối task tương ứng.
