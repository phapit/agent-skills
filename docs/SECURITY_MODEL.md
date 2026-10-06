# Mô hình bảo mật của AI Task Router

## Các lớp phòng thủ (từ ngoài vào trong)
1. **Cô lập cấp hệ điều hành (lớp thực thi thật)** - worker Antigravity chạy trong `bwrap` (`antigravity.permission_mode = "bwrap"`, mặc định):
   - Toàn hệ thống chỉ-đọc; chỉ workspace và HOME của profile ghi được.
   - Che `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `~/.docker`, thư mục các profile khác, `/run/user/UID` (D-Bus, keyring, ssh-agent) và socket docker.
   - Khóa chỉ-đọc các điểm cài "persistence" trong workspace: `.git/hooks`, `.git/config`, `.vscode`, `.idea`, `.husky`, `.envrc`, và `settings.json` của agy.
   - Gỡ biến môi trường `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS`, `GPG_AGENT_INFO`, `XDG_RUNTIME_DIR`.
   - Chế độ thay thế: `sandbox` (shell chỉ-đọc hoàn toàn), `skip` (không ranh giới, chỉ dùng khi chủ động chấp nhận).
2. **Quét prompt injection trước khi chạy** (`injection_guard.py` + trường `security_findings` của planner): hiển thị loại, mức độ, ảnh hưởng; người dùng quyết định (`--injection-action`).
3. **Ràng buộc trong prompt worker** - lớp phụ, không thay thế lớp 1.
4. **Vai trò kiểm thử (read-only với mã nguồn):** worker `test` chạy với workspace `ro-bind` (Antigravity) và bị đối chiếu ảnh chụp file trước/sau (mọi worker); Claude/Codex chỉ phát hiện được sau khi xong.
5. **Nghiệm thu độc lập** (Quality Gate) và rà soát `git diff` trước khi nhận kết quả.

## Rủi ro còn lại (đã biết, chưa loại bỏ được)
| Rủi ro | Vì sao còn | Giảm thiểu |
|---|---|---|
| **Mạng không bị cô lập** | agy cần gọi API; `bwrap` không lọc theo tên miền | Dữ liệu trong workspace có thể bị gửi ra ngoài. Không đặt bí mật trong workspace; dùng proxy/tường lửa lọc đầu ra nếu cần |
| **Socket trừu tượng (abstract)** | Dùng chung network namespace | Chỉ khắc phục được bằng cách cô lập mạng |
| **Persistence qua file hợp lệ** (`package.json` scripts, Makefile, CI, mã nguồn) | Agent cần được sửa các file này | Đọc `git diff` trước khi chạy test/build trên kết quả của worker |
| **Điểm persistence chưa tồn tại** | Chỉ khóa được đường dẫn đã có | Tạo trước thư mục cần bảo vệ, hoặc rà `git status` |
| **`npm test` tự phát hiện trên repo lạ** | Chưa cài cơ chế xác nhận | Đặt `supervisor.test_command` rõ ràng hoặc tắt Quality Gate trên repo không tin cậy |
| **Quét prompt injection bằng luật có thể bị né** | Là heuristic | Xem `tests/corpus_metrics.json`; Supervisor AI bổ sung nhưng không tuyệt đối |
