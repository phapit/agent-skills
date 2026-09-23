---
name: repo-map
description: Generate a PageRank-ranked repository map (aider-style) of the most structurally important source files and their definition signatures for Python, TypeScript/JavaScript (Vue, Next.js, React) and PHP projects, to understand project architecture during the Explore/Plan phase. Compatible with Antigravity, Claude Code, OpenAI Codex, Cursor, and Gemini.
disable-model-invocation: false
---

# Skill: Repo Map (PageRank)

Tạo **bản đồ repository xếp hạng theo tầm quan trọng cấu trúc** thay vì chỉ liệt kê cây thư mục thông thường. Dùng trước khi lập kế hoạch (Plan Mode) hoặc khi thực hiện thay đổi lớn trên nhiều module, giúp các AI Coding Agents định vị nhanh các file cốt lõi mà không tiêu tốn context window và không cần đọc thừa mã nguồn.

## Thuật toán (5 bước)
1. **Liệt kê file**: Dùng `git ls-files --cached --others --exclude-standard` nếu là git repository; nếu không thì tự duyệt thư mục (tự động loại trừ các thư mục phụ thuộc, build artifacts, và thư mục cấu hình agent như `node_modules`, `.git`, `.agents`, `.claude`, `.gemini`, `dist`...).
2. **Trích xuất ký hiệu**: Ưu tiên dùng **tree-sitter** (parser AST thực) nếu môi trường đã cài đặt `tree-sitter tree-sitter-python tree-sitter-php tree-sitter-typescript`; nếu chưa có, tự động chuyển về fallback bằng `ast` (Python) hoặc regex heuristic (TS/JS/Vue/PHP) — trích xuất các chữ ký `def`, `class`, `function`, `interface`, `type`, `enum`, component và các tham chiếu chéo giữa các file.
3. **Đồ thị tham chiếu**: Xây dựng đồ thị có hướng giữa các file: cạnh $A \rightarrow B$ có trọng số = (số lần A tham chiếu ký hiệu được định nghĩa trong B) $\times$ IDF(tên ký hiệu). Các định danh quá phổ biến (`get`, `run`, `value`…) tự động bị hạ trọng số nhằm triệt tiêu nhiễu.
4. **PageRank**: Xếp hạng file theo thuật toán PageRank — các file đóng vai trò kiến trúc trung tâm hoặc được nhiều module khác import/tham chiếu nhất sẽ có điểm PR cao nhất.
5. **Render & Phân trang**: Định dạng danh sách chữ ký hàm/lớp theo thứ hạng quan trọng, tự động phân trang theo token budget định sẵn (tránh cắt vụn nội dung).

## Hướng dẫn sử dụng cho AI Coding Agents (Antigravity, Claude Code, Codex, Cursor, Gemini...):

### 1. Cách gọi lệnh theo từng môi trường
Tùy vào công cụ/Agent CLI đang sử dụng, gọi script theo đường dẫn tương ứng:
- **Chạy trực tiếp từ repo**:
  ```bash
  python3 repo-map/repo_map.py .
  ```
- **Antigravity CLI (`agy`) / Agent Runner chuẩn**:
  ```bash
  python3 ~/.agents/skills/repo-map/repo_map.py .
  ```
- **Claude Code CLI**:
  ```bash
  python3 ~/.claude/skills/repo-map/repo_map.py .
  ```
- **OpenAI Codex CLI**:
  ```bash
  python3 ~/.codex/skills/repo-map/repo_map.py .
  ```
- **Gemini CLI**:
  ```bash
  python3 ~/.gemini/config/skills/repo-map/repo_map.py .
  ```

### 2. Các tham số dòng lệnh
```bash
python3 <path-to-skill>/repo_map.py [root] [budget] [--exclude <paths...>] [--out <output_dir>]
```
- **`root`** (mặc định: `.`): Thư mục gốc cần quét (có thể chỉ định sub-path như `./backend`, `./src/core`).
- **`budget`** (mặc định: `2000`): Giới hạn token xấp xỉ cho mỗi trang markdown sinh ra.
- **`--exclude` / `-e`**: Loại trừ đường dẫn hoặc pattern wildcard. Thích hợp cho dự án đa module hoặc multi-site:
  ```bash
  python3 repo-map/repo_map.py . --exclude ./app/vendor --exclude "./sites/*/storage"
  ```
- **`--output-dir` / `--out` / `-o`** (mặc định: `repo-map`): Thư mục lưu kết quả. Thư mục này luôn được tạo tại thư mục thực thi hiện tại (`cwd`).

### 3. Cấu trúc kết quả đầu ra
- **Prefix theo thư mục**: Kết quả scan sinh ra file có tên theo thư mục quét (ví dụ: quét `./app/backend` cho ra `backend_repo_map.md` hoặc `backend_repo_map.part.1.md`, `backend_repo_map.part.2.md`...).
- **Gom nhiều lần scan**: Cho phép quét nhiều sub-path (`./frontend`, `./backend`) độc lập, kết quả gom chung về `repo-map/` mà không bị ghi đè lẫn nhau.
- **Mục lục `INDEX.md`**: File `repo-map/INDEX.md` tổng hợp toàn bộ các phân vùng đã quét, đường dẫn nguồn, số lượng file và tên file kết quả.

### 4. Quy trình làm việc chuẩn cho Agent (Standard Protocol)
Khi nhận một task mới trên codebase lạ hoặc phức tạp:
1. **Quét bản đồ**: Chạy `python3 <path>/repo_map.py .`
2. **Kiểm tra mục lục**: Đọc `repo-map/INDEX.md` để xác định các file bản đồ đã được sinh.
3. **Định vị trọng tâm**: Mở file bản đồ tương ứng, tập trung vào các file có điểm **`PR` cao nhất**.
4. **Đọc chi tiết**: Chỉ mở và đọc toàn bộ nội dung của những file cốt lõi thực sự liên quan đến yêu cầu trước khi tiến hành code hoặc lập plan.

## Ngôn ngữ hỗ trợ
- **Python** (`.py`): Dùng `tree-sitter-python` hoặc `ast` built-in.
- **TypeScript / JavaScript** (`.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`): Hỗ trợ đầy đủ class, interface, function, type alias, enum, arrow function.
- **Vue** (`.vue`): Trích xuất thẻ `<script>` / `<script setup>`, suy luận tên component từ file.
- **PHP** (`.php`): Trích xuất class, interface, trait, function và method.

## Lưu ý kỹ thuật
- **PageRank tối ưu**: Tự động sử dụng `networkx` nếu môi trường đã cài (`pip install networkx`). Nếu không có, tự động rơi về PageRank thuần Python (không yêu cầu cài đặt thêm).
- **Bộ phân tích AST**: Ưu tiên `tree-sitter` (`pip install tree-sitter tree-sitter-python tree-sitter-php tree-sitter-typescript`). Nếu thiếu, tự động fallback sang regex/ast an toàn.
- **Tự động bỏ qua**: Đã cấu hình bỏ qua các thư mục dependencies (`node_modules`, `vendor`), build output (`dist`, `.next`, `.output`), và thư mục AI/IDE (`.agents`, `.claude`, `.gemini`, `.antigravity`, `.cursor`, `.vscode`).
