# Repo Map — PageRank-ranked Repository Map for AI Agents

Công cụ và Skill phân tích cấu trúc codebase theo thuật toán **PageRank** (tương tự cơ chế của Aider), hỗ trợ đa dạng các trợ lý lập trình và AI coding agents như **Antigravity**, **Claude Code**, **OpenAI Codex**, **Cursor**, và **Gemini**.

---

## 🌟 Tính năng nổi bật

- **Xếp hạng theo PageRank**: Không chỉ duyệt file theo cây thư mục đơn thuần, `repo-map` xây dựng đồ thị tham chiếu (reference graph) kết hợp trọng số nghịch đảo tần suất (IDF) để tìm ra các file có tầm quan trọng kiến trúc cao nhất trong repository.
- **Tiết kiệm Context Window**: Thay vì đọc toàn bộ nội dung file làm tràn token hoặc tăng chi phí, agent chỉ cần đọc chữ ký hàm, lớp, interface quan trọng nhất của các file cốt lõi.
- **Hỗ trợ đa ngôn ngữ**:
  - **Python**: Phân tích class, async/sync function, decorators.
  - **TypeScript & JavaScript**: Full ES6+, JSX, TSX, type alias, interface, arrow function.
  - **Vue**: Phân tích script block (`<script setup>`).
  - **PHP**: Phân tích class, interface, trait, method.
- **Fallback linh hoạt**: Ưu tiên sử dụng `tree-sitter` và `networkx`. Nếu môi trường chưa cài đặt, script tự động fallback sang `ast` (Python), regex heuristic và PageRank thuần Python (zero external dependencies).
- **Phân trang thông minh**: Tự động chia file theo `token_budget` (mặc định 2000 token/trang) và tổng hợp tại `repo-map/INDEX.md`.

---

## 🚀 Cài đặt nhanh

Để tự động liên kết skill vào các thư mục cấu hình của Antigravity, Claude Code, Codex và Agents CLI:

```bash
bash repo-map/install.sh
```

Cài đặt các gói phụ trợ để đạt độ chính xác và tốc độ phân tích tối đa (tùy chọn):
```bash
pip install networkx tree-sitter tree-sitter-python tree-sitter-typescript tree-sitter-php
```

---

## 💻 Hướng dẫn sử dụng

### 1. Dành cho lập trình viên (CLI)

Quét toàn bộ thư mục hiện tại:
```bash
python3 repo-map/repo_map.py .
```

Quét một sub-folder với token budget 3000:
```bash
python3 repo-map/repo_map.py ./src/backend 3000
```

Bỏ qua các thư mục không liên quan hoặc dự án multi-site:
```bash
python3 repo-map/repo_map.py . --exclude ./app/vendor --exclude "./sites/*/storage"
```

Chỉ định thư mục lưu kết quả:
```bash
python3 repo-map/repo_map.py . --out ./custom-map
```

### 2. Dành cho AI Coding Agents

Các Agent có thể chủ động kích hoạt script trong giai đoạn **Explore / Plan**:
```bash
# Antigravity / Agents CLI chuẩn
python3 ~/.agents/skills/repo-map/repo_map.py .

# Claude Code
python3 ~/.claude/skills/repo-map/repo_map.py .

# OpenAI Codex
python3 ~/.codex/skills/repo-map/repo_map.py .
```

Sau khi chạy:
1. Đọc `repo-map/INDEX.md` để nắm mục lục phân vùng đã quét.
2. Mở file bản đồ tương ứng, ưu tiên xem các file có điểm `PR` cao nhất.
3. Tiến hành lập kế hoạch hoặc định vị chính xác vị trí cần chỉnh sửa mà không cần tìm kiếm mù quáng.

---

## 📄 License

Phát hành dưới giấy phép [MIT License](../LICENSE).
