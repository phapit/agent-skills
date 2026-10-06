import json
import os
import subprocess
import pytest

import supervisor_tools


def test_sec_08_run_verification_tests_simple(tmp_path):
    """
    SEC-08: run_verification_tests chạy lệnh kiểm thử do người dùng chỉ định.
    Input: python3 -c 'print(1)'
    Kỳ vọng: Thực thi thành công, passed=True, exit_code=0.
    """
    res = supervisor_tools.run_verification_tests("python3 -c 'print(1)'", cwd=str(tmp_path))
    assert res["passed"] is True
    assert res["exit_code"] == 0
    assert "1" in res["stdout"]


def test_sec_09_compound_commands_and_exec_isolation(tmp_path, monkeypatch):
    """
    SEC-09: Lệnh do người dùng chỉ định có &&, pipe, biến môi trường inline, chuyển hướng
    -> chạy đúng qua sh -c.
    Lệnh tự phát hiện (test_command='auto') chạy dạng exec KHÔNG qua shell.
    Kỳ vọng: Xác nhận qua kết quả thực thi thật và kiểm tra tham số subprocess.run.
    """
    # 1. Chạy thực tế lệnh compound của người dùng
    compound_cmd = "TEST_VAR=hello && echo $TEST_VAR | grep hello > out.txt"
    res = supervisor_tools.run_verification_tests(compound_cmd, cwd=str(tmp_path))
    assert res["passed"] is True
    assert (tmp_path / "out.txt").exists()
    assert (tmp_path / "out.txt").read_text().strip() == "hello"

    # 2. Kiểm tra bằng chứng gọi qua sh -c vs exec (shell=False)
    recorded_calls = []
    orig_run = subprocess.run

    def mock_run(args, **kwargs):
        recorded_calls.append({"args": args, "kwargs": kwargs})
        return orig_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Lệnh chỉ định bởi người dùng: chạy ["sh", "-c", cmd]
    supervisor_tools.run_verification_tests("echo 1", cwd=str(tmp_path))
    assert len(recorded_calls) == 1
    assert recorded_calls[0]["args"][:2] == ["sh", "-c"]
    assert recorded_calls[0]["kwargs"].get("shell") is False

    # Lệnh tự phát hiện (tạo file pytest.ini để kích hoạt "pytest")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    # Thay vì chạy pytest thật, mock lại để kiểm tra args dạng exec
    recorded_calls.clear()

    def mock_run_auto(args, **kwargs):
        recorded_calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_run_auto)
    supervisor_tools.run_verification_tests("auto", cwd=str(tmp_path))
    assert len(recorded_calls) == 1
    # Auto-detected chạy dạng exec [ "pytest" ], KHÔNG qua sh -c
    assert recorded_calls[0]["args"] == ["pytest"]
    assert recorded_calls[0]["kwargs"].get("shell") is False


def test_sec_10_untrusted_repo_npm_test_sandbox(tmp_path):
    """
    SEC-10: Repo có package.json với scripts.test ghi file PWNED.
    Kỳ vọng phòng thủ: Quality gate 'auto' KHÔNG được tự động thực thi script lạ mà chưa có xác nhận / sandbox.
    """
    pkg = {
        "name": "untrusted-repo",
        "scripts": {
            "test": "touch PWNED",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    # Khi gọi run_verification_tests("auto") trên repo này:
    # Nếu hệ thống an toàn, script test chưa được phê duyệt sẽ bị chặn hoặc yêu cầu xác nhận.
    supervisor_tools.run_verification_tests("auto", cwd=str(tmp_path))

    # Kiểm tra file PWNED
    assert not (tmp_path / "PWNED").exists(), "Script npm test độc hại trong repo đã tự động chạy ngoài tầm kiểm soát!"


def test_sec_18_detect_test_command_matrix(tmp_path):
    """
    SEC-18: detect_test_command cho các loại dự án phổ biến và khi không có gì.
    """
    # 1. Thư mục rỗng -> None & SKIPPED
    assert supervisor_tools.detect_test_command(str(tmp_path)) is None
    res_empty = supervisor_tools.run_verification_tests("auto", cwd=str(tmp_path))
    assert res_empty["status"] == "SKIPPED"
    assert res_empty["passed"] is True

    # 2. tests/ directory -> pytest
    d_pytest = tmp_path / "proj_pytest"
    (d_pytest / "tests").mkdir(parents=True)
    assert supervisor_tools.detect_test_command(str(d_pytest)) == "pytest"

    # 3. pytest.ini -> pytest
    d_ini = tmp_path / "proj_ini"
    d_ini.mkdir(parents=True)
    (d_ini / "pytest.ini").write_text("")
    assert supervisor_tools.detect_test_command(str(d_ini)) == "pytest"

    # 4. package.json -> npm test
    d_npm = tmp_path / "proj_npm"
    d_npm.mkdir(parents=True)
    (d_npm / "package.json").write_text("{}")
    assert supervisor_tools.detect_test_command(str(d_npm)) == "npm test"

    # 5. Cargo.toml -> cargo test
    d_cargo = tmp_path / "proj_cargo"
    d_cargo.mkdir(parents=True)
    (d_cargo / "Cargo.toml").write_text("")
    assert supervisor_tools.detect_test_command(str(d_cargo)) == "cargo test"

    # 6. go.mod -> go test ./...
    d_go = tmp_path / "proj_go"
    d_go.mkdir(parents=True)
    (d_go / "go.mod").write_text("")
    assert supervisor_tools.detect_test_command(str(d_go)) == "go test ./..."


def test_sec_19_timeout_and_unbalanced_quotes(tmp_path, monkeypatch):
    """
    SEC-19: Xử lý timeout và cú pháp nháy hỏng trong chế độ exec:
    - TimeoutExpired -> exit_code=124, passed=False.
    - Dấu nháy không cân bằng -> passed=False, không ném ngoại lệ chưa xử lý.
    """
    # 1. Timeout
    def mock_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="test", timeout=300)

    monkeypatch.setattr(subprocess, "run", mock_timeout)
    res_timeout = supervisor_tools.run_verification_tests("echo 1", cwd=str(tmp_path))
    assert res_timeout["exit_code"] == 124
    assert res_timeout["passed"] is False
    assert "timeout" in res_timeout["stderr"].lower()

    # 2. Dấu nháy không cân bằng ở chế độ exec
    # Khi test_command='auto', detected cmd có dấu nháy lỗi (ví dụ mock detect trả về chuỗi lỗi)
    monkeypatch.setattr(supervisor_tools, "detect_test_command", lambda cwd: "pytest 'unclosed_quote")
    res_unclosed = supervisor_tools.run_verification_tests("auto", cwd=str(tmp_path))
    assert res_unclosed["passed"] is False
    assert res_unclosed["exit_code"] != 0
    assert res_unclosed["stderr"] != ""
