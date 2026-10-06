# AI Router & Tools

Kho lưu trữ cá nhân tổng hợp và chia sẻ các kinh nghiệm thực tế, ý tưởng ứng dụng, cùng các công cụ AI hữu ích nhằm tối ưu hóa quy trình làm việc và phát triển phần mềm với AI agents.

---

## 📌 Nội dung nổi bật

- **[AI Task Router](./ai-task-router)**: Công cụ và skill định tuyến, phân loại và phân rã nhiệm vụ tự động cho multi-agent workflows. Chi tiết hướng dẫn xem tại [ai-task-router/README.md](./ai-task-router/README.md) (hoặc [bản tiếng Anh](./ai-task-router/README.en.md)).
- **[Repo Map](./repo-map)**: Skill phân tích và tạo bản đồ codebase xếp hạng theo thuật toán PageRank, trích xuất cấu trúc và chữ ký định nghĩa cho Antigravity, Claude Code, Codex, Cursor và Gemini ([repo-map/README.md](./repo-map/README.md)).
- **Tài liệu & Nghiên cứu**: Các tài liệu thiết kế và báo cáo quy trình ([docs/](./docs)).

## 🛡️ Bảo mật & Kết quả kiểm thử (AI Task Router)

> **Tóm tắt cho người dùng cuối:** Router đã được rà soát và gia cố bảo mật, nhưng **không có hệ thống nào an toàn tuyệt đối**. Lớp bảo vệ quan trọng nhất vẫn là **bạn đọc kỹ nội dung prompt và các file dự án trước khi giao việc cho Agent**.

### Đã làm và kiểm chứng
| Hạng mục | Kết quả |
|---|---|
| Rà soát bảo mật (Claude, Antigravity; Codex hết quota nên Antigravity làm thay) | Phát hiện và vá F1–F7, N1, N2 (lỗi chèn lệnh qua tên profile, path traversal, quyền thư mục, chạy test bằng shell, lọc ký tự điều khiển, giới hạn đọc file, ẩn báo cáo khỏi git) |
| Bộ kiểm thử tự động `tests/` | **61 test đạt, 1 bỏ qua** (thăm dò mạng, chỉ chạy khi bật `RUN_NET_PROBE=1`); chạy bằng `python3 -m pytest tests -q` |
| Phát hiện từ kiểm thử đối kháng | 4 lỗi thật (theo symlink, JSON lồng sâu, `npm test` của repo lạ...) đã sửa; chi tiết ở [tests/FINDINGS.md](./tests/FINDINGS.md) |
| Cô lập worker Antigravity bằng `bwrap` | Kiểm tra thật: ghi trong workspace được; ghi ra hệ thống, HOME, hook git, cấu hình IDE bị chặn; socket D-Bus/docker và thư mục khóa SSH bị che |
| Quét prompt injection trước khi chạy | Có (hiển thị loại, mức độ, ảnh hưởng; **người dùng quyết định** tiếp tục hay dừng) |

### Điều cần hiểu đúng về giới hạn
- **Bộ test không chứng minh "hết lỗi".** Test chỉ xác nhận những tình huống đã được nghĩ tới.
- **Quét prompt injection bằng luật chỉ bắt được khoảng 78%** trên tập 72 mẫu tấn công thử nghiệm (có thể bị né bằng đồng nghĩa hoặc chia dòng). Với các mẫu bình thường thì không báo nhầm trong tập thử (0/58), nhưng vẫn có trường hợp báo nhầm đã biết, ví dụ lệnh cài đặt hợp lệ trong tài liệu.
- **Mạng không bị cô lập** (Agent cần gọi API), nên dữ liệu trong workspace về lý thuyết vẫn có thể bị gửi ra ngoài nếu Agent bị đánh lừa.
- Các file hợp lệ như script trong `package.json`, Makefile, mã nguồn vẫn có thể bị Agent sửa.
- Hành vi của mô hình AI không cố định; chưa có kiểm thử đo mức độ "nghe lời" của mô hình khi bị tấn công thật.
- Danh sách đầy đủ rủi ro còn lại: [docs/SECURITY_MODEL.md](./docs/SECURITY_MODEL.md).

### Khuyến nghị cho người dùng cuối
Chúng tôi **cố ý không siết quá chặt** để công cụ vẫn dễ dùng (không bắt xác nhận từng thao tác, không chặn mạng). Đổi lại, bạn nên:
1. **Đọc kỹ prompt trước khi giao việc**, nhất là khi dán nội dung từ nguồn ngoài (email, issue, trang web, tài liệu nhận từ người khác).
2. **Xem lại các file chỉ dẫn trong dự án** (`README`, `AGENTS.md`, `CLAUDE.md`, `.agents/rules/`) khi dùng repo không phải của bạn.
3. **Coi trọng cảnh báo của Supervisor.** Nếu có cảnh báo mức cao, hãy đọc phần "Loại / Mức độ / Ảnh hưởng" rồi mới chọn tiếp tục.
4. **Không để thông tin bí mật trong workspace** (khóa API, file `.env` thật). Dùng bản mẫu thay cho bản thật.
5. **Xem `git diff` kết quả của Agent** trước khi chạy test, build hoặc commit, đặc biệt với repo lạ.
6. Chỉ chuyển sang chế độ không giới hạn (`antigravity.permission_mode: "skip"`) khi bạn hoàn toàn tin tưởng nội dung đang xử lý.

## 🎯 Mục tiêu

Repository này là không gian ghi chép và chia sẻ mở để:
- Lưu trữ và thử nghiệm các ý tưởng, workflow mới với AI.
- Xây dựng các tiện ích mở rộng, skills và công cụ tự động hóa.
- Chia sẻ kinh nghiệm ứng dụng AI trong lập trình và giải quyết các bài toán thực tế.

## 📄 Giấy phép

Dự án được phân phối dưới giấy phép [MIT License](./LICENSE).
