# Báo Cáo Các Lỗ Hổng & Điểm Yếu Bảo Mật Được Phát Hiện Qua Bộ Kiểm Thử Đối Kháng (Defensive Test Findings)

Tài liệu này ghi nhận các lỗ hổng và lỗi thật (real bugs) trong mã nguồn của `ai-task-router/` được phát hiện thông qua bộ kiểm thử tự động `pytest` (được đánh dấu bằng `@pytest.mark.xfail(strict=True)` để đảm bảo tính nghiêm ngặt và không sửa mã nguồn trong đợt kiểm thử).

---

## 1. FINDING-01: Auto-detected `npm test` trong Quality Gate thực thi mã tùy ý mà không có Sandbox hoặc Xác nhận (SEC-10)

- **Vị trí (File & Hàm):** `ai-task-router/supervisor_tools.py`, hàm `run_verification_tests(test_command="auto", cwd=".")` kết hợp `detect_test_command(cwd)`.
- **Mức độ nghiêm trọng:** HIGH (Cơ hội thực thi mã gián tiếp - Arbitrary Code Execution).
- **Test case:** `tests/test_quality_gate.py::test_sec_10_untrusted_repo_npm_test_sandbox` (`xfail strict`).
- **Dữ liệu đầu vào gây lỗi:**
  Một kho mã nguồn (repository) lạ chứa file `package.json` với script test độc hại:
  ```json
  {
    "name": "untrusted-repo",
    "scripts": {
      "test": "touch PWNED"
    }
  }
  ```
- **Hành vi thực tế:**
  Khi Supervisor kích hoạt Quality Gate ở chế độ mặc định (`test_command="auto"`), hàm `detect_test_command` phát hiện file `package.json` và trả về chuỗi `"npm test"`. Sau đó, `run_verification_tests` gọi `subprocess.run(["npm", "test"], shell=False)` trực tiếp. Binary `npm` tự động đọc `scripts.test` và thực thi câu lệnh shell độc hại trên máy trạm mà không hề hỏi ý kiến người dùng hay chạy trong sandbox.
- **Hành vi mong đợi:**
  Chế độ `auto` khi phát hiện các lệnh kiểm thử phụ thuộc vào script do repo định nghĩa (`npm test`) phải:
  1. Hiển thị nội dung script và yêu cầu người dùng xác nhận trước khi chạy, HOẶC
  2. Bắt buộc thực thi trong sandbox cô lập (như bubblewrap hoặc docker).
- **Trạng thái:** Đã ghi nhận trong FINDINGS, đánh dấu `xfail(strict=True)` trong bộ test.

---

## 2. FINDING-02: `ensure_private_dir` theo Symlink ra ngoài Profiles Base và làm thay đổi quyền của thư mục đích (SEC-15)

- **Vị trí (File & Hàm):**
  - `ai-task-router/classify_and_split_task.py`: hàm `ensure_private_dir(path)` và `get_agy_profile_env(profile_name)`.
  - `ai-task-router/profile_manager.py`: hàm `ensure_private_dir(path)` và `get_profile_dir(agent, profile_name)`.
- **Mức độ nghiêm trọng:** MEDIUM (Phá vỡ phân quyền hệ thống ngoài phạm vi quản lý - Insecure Symlink Following).
- **Test case:** `tests/test_profiles_security.py::test_sec_15_symlink_traversal_prevention` (`xfail strict`).
- **Dữ liệu đầu vào gây lỗi:**
  Thư mục profile bên trong base (ví dụ `~/.agents/profiles/antigravity_p`) là một symlink trỏ tới một thư mục nhạy cảm bên ngoài có quyền mở `0o755`.
- **Hành vi thực tế:**
  `ensure_private_dir(path)` gọi `os.chmod(path, 0o700)`. Trên Linux, lệnh `os.chmod` tự động theo liên kết mềm (follow symlinks) và thay đổi trực tiếp quyền của thư mục đích bên ngoài thành `0o700`, gây thay đổi trạng thái bảo mật của hệ thống tệp ngoài ý muốn.
- **Hành vi mong đợi:**
  `ensure_private_dir` hoặc `get_agy_profile_env` phải kiểm tra `os.path.islink(path)` và từ chối thao tác hoặc ngắt symlink nếu nó trỏ ra ngoài `DEFAULT_PROFILES_BASE`.
- **Trạng thái:** Đã ghi nhận trong FINDINGS, đánh dấu `xfail(strict=True)` trong bộ test.

---

## 3. FINDING-03: `scan_workspace` theo Symlink ra ngoài Workspace để đọc file nhạy cảm (SEC-32)

- **Vị trí (File & Hàm):** `ai-task-router/injection_guard.py`, hàm `scan_workspace(cwd, user_prompt)`.
- **Mức độ nghiêm trọng:** MEDIUM (Rò rỉ hoặc phân tích dữ liệu ngoài phạm vi - Symlink Traversal).
- **Test case:** `tests/test_injection_guard.py::test_sec_32_scan_workspace_symlink_defense` (`xfail strict`).
- **Dữ liệu đầu vào gây lỗi:**
  Trong workspace tồn tại file symlink (ví dụ `README.md` hoặc `.agents/rules/link.md`) trỏ tới file ngoài thư mục dự án (ví dụ `/etc/shadow` hoặc file bẫy ngoài workspace).
- **Hành vi thực tế:**
  Vòng lặp `scan_workspace` lấy `real = os.path.realpath(path)` và mở file bằng `open(real, "r")` mà không kiểm tra xem `real` có nằm bên trong `cwd` hay không. Kết quả là các file bên ngoài workspace bị đọc và quét.
- **Hành vi mong đợi:**
  Phải kiểm tra `os.path.commonpath([os.path.realpath(cwd), real]) == os.path.realpath(cwd)` trước khi mở đọc file, bỏ qua mọi symlink trỏ ra ngoài thư mục làm việc hiện tại.
- **Trạng thái:** Đã ghi nhận trong FINDINGS, đánh dấu `xfail(strict=True)` trong bộ test.

---

## 4. FINDING-04: `parse_planner_output` và `parse_planner_security` bị crash bởi `RecursionError` khi gặp JSON lồng sâu (SEC-41)

- **Vị trí (File & Hàm):** `ai-task-router/classify_and_split_task.py`, hàm `parse_planner_output` và `parse_planner_security`.
- **Mức độ nghiêm trọng:** MEDIUM (Từ chối dịch vụ - Denial of Service DoS).
- **Test case:** `tests/test_planner_parsing.py::test_sec_41_deeply_nested_json_recursion_defense` (`xfail strict`).
- **Dữ liệu đầu vào gây lỗi:**
  Phản hồi từ AI Planner hoặc chuỗi phản chiếu từ người dùng chứa cấu trúc JSON lồng nhau nhiều tầng (độ sâu >= 1.000 tầng, ví dụ: `'{"a":' * 10000 + '1' + '}' * 10000`).
- **Hành vi thực tế:**
  Hàm `json.JSONDecoder().raw_decode` đụng ngưỡng giới hạn đệ quy của Python runtime (`sys.getrecursionlimit()`) và ném ra ngoại lệ `RecursionError`. Khối lệnh chỉ bọc `except ValueError:`, dẫn tới ngoại lệ `RecursionError` không được bắt, làm sập router ngay lập tức.
- **Hành vi mong đợi:**
  Bọc `except (ValueError, RecursionError):` để bắt ngoại lệ đệ quy an toàn và trả về `None` (đối với parser) hoặc `[]` (đối với security findings), ngăn chặn hoàn toàn nguy cơ DoS router.
- **Trạng thái:** Đã ghi nhận trong FINDINGS, đánh dấu `xfail(strict=True)` trong bộ test.
