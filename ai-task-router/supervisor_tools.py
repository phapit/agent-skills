#!/usr/bin/env python3
"""
Supervisor Tools (Phương án A + C):
Bộ công cụ dành cho AI Supervisor:
- Nhóm A (Terminal Control): Đọc màn hình tmux, gửi phím bấm, kiểm tra trạng thái session worker.
- Nhóm C (Quality Gate): Đọc git diff, chạy kiểm thử độc lập, đọc báo cáo bàn giao.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

TMUX_CMD = "tmux"
REPORTS_DIR_NAME = ".ai_router_reports"


# ==============================================================================
# NHÓM A: TERMINAL CONTROL (TMUX)
# ==============================================================================

def tmux_run(*args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [TMUX_CMD, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc.returncode, proc.stdout
    except FileNotFoundError:
        return 127, "tmux is not installed or not in PATH"


def tmux_list_sessions() -> list[dict[str, str]]:
    """Liệt kê các tmux session đang chạy trên hệ thống."""
    code, out = tmux_run("list-sessions", "-F", "#{session_name}:#{session_windows}:#{session_attached}")
    if code != 0 or not out.strip():
        return []
    sessions = []
    for line in out.strip().splitlines():
        parts = line.split(":", 2)
        if len(parts) >= 1:
            sessions.append({
                "session_name": parts[0],
                "windows": parts[1] if len(parts) > 1 else "1",
                "attached": parts[2] if len(parts) > 2 else "0",
            })
    return sessions


def tmux_session_exists(session_name: str) -> bool:
    code, _ = tmux_run("has-session", "-t", session_name)
    return code == 0


def tmux_read_pane(session_name: str, lines: int = 60) -> str:
    """
    Đọc N dòng cuối cùng từ pane của session tmux.
    Giúp Supervisor nắm bắt chính xác Worker đang làm gì, có hỏi [y/N] hoặc bị lỗi không.
    """
    if not tmux_session_exists(session_name):
        return f"[LỖI] Không tìm thấy tmux session: '{session_name}'"
    # capture-pane với -S -<lines> để lấy lịch sử gần nhất
    code, out = tmux_run("capture-pane", "-t", session_name, "-p", "-J", "-S", f"-{lines}")
    if code != 0:
        return f"[LỖI] Không đọc được pane của session '{session_name}'"
    return out


def tmux_send_keys(session_name: str, keys: str, press_enter: bool = True) -> bool:
    """
    Gửi phím hoặc câu lệnh vào tmux session của Worker.
    Hỗ trợ cả phím đặc biệt như 'C-c', 'Escape', 'Enter', 'y', 'n'.
    """
    if not tmux_session_exists(session_name):
        print(f"[LỖI] Session '{session_name}' không tồn tại.", file=sys.stderr)
        return False

    # Gửi chuỗi literal
    code, _ = tmux_run("send-keys", "-t", session_name, "-l", keys)
    if press_enter:
        tmux_run("send-keys", "-t", session_name, "Enter")
    return code == 0


def tmux_send_special_key(session_name: str, key_name: str) -> bool:
    """Gửi phím điều khiển đặc biệt: Enter, C-c, Escape, Up, Down..."""
    code, _ = tmux_run("send-keys", "-t", session_name, key_name)
    return code == 0


# ==============================================================================
# NHÓM C: QUALITY GATE & VERIFICATION (NGHIỆM THU)
# ==============================================================================

def inspect_git_diff(cwd: str = ".") -> dict:
    """
    Kiểm tra các thay đổi thực tế trên Git (git status & git diff).
    Supervisor dùng hàm này để review trực tiếp code mà Worker đã sinh ra.
    """
    try:
        status_proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        diff_proc = subprocess.run(
            ["git", "diff"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stat_proc = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return {
            "status": status_proc.stdout.strip(),
            "stat": stat_proc.stdout.strip(),
            "diff": diff_proc.stdout,
            "has_changes": bool(status_proc.stdout.strip() or diff_proc.stdout.strip()),
        }
    except FileNotFoundError:
        return {"error": "git command not found", "has_changes": False}


def detect_test_command(cwd: str = ".") -> str | None:
    """Tự động nhận diện lệnh test phù hợp với repo."""
    if os.path.isfile(os.path.join(cwd, "pytest.ini")) or os.path.isdir(os.path.join(cwd, "tests")):
        return "pytest"
    if os.path.isfile(os.path.join(cwd, "package.json")):
        return "npm test"
    if os.path.isfile(os.path.join(cwd, "Cargo.toml")):
        return "cargo test"
    if os.path.isfile(os.path.join(cwd, "go.mod")):
        return "go test ./..."
    return None


def run_verification_tests(test_command: str = "auto", cwd: str = ".") -> dict:
    """
    Chạy bộ test kiểm thử độc lập do Supervisor kích hoạt.
    Worker báo xong không có nghĩa là code chạy đúng -> Supervisor bắt buộc phải test lại.
    """
    cmd_to_run = test_command
    if test_command in ("auto", "", None):
        detected = detect_test_command(cwd)
        if not detected:
            return {
                "status": "SKIPPED",
                "message": "Không nhận diện được test suite tự động (không có tests/, package.json, go.mod...)",
                "passed": True,
            }
        cmd_to_run = detected

    print(f"[Quality Gate] Đang thực thi lệnh test: {cmd_to_run}")
    try:
        proc = subprocess.run(
            cmd_to_run,
            cwd=cwd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        return {
            "command": cmd_to_run,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": cmd_to_run,
            "exit_code": 124,
            "passed": False,
            "stdout": "",
            "stderr": "Lệnh kiểm thử bị timeout sau 300s.",
        }
    except Exception as e:
        return {
            "command": cmd_to_run,
            "exit_code": 1,
            "passed": False,
            "stdout": "",
            "stderr": str(e),
        }


def read_handoff_reports(cwd: str = ".") -> list[dict]:
    """
    Đọc tất cả các báo cáo bàn giao của Worker từ thư mục .ai_router_reports/.
    """
    rep_dir = os.path.join(cwd, REPORTS_DIR_NAME)
    if not os.path.isdir(rep_dir):
        return []

    reports = []
    for f in sorted(os.listdir(rep_dir)):
        if f.endswith(".md") and not f.endswith(".question.md"):
            p = os.path.join(rep_dir, f)
            try:
                with open(p, "r", encoding="utf-8") as file:
                    content = file.read()
                reports.append({"filename": f, "path": p, "content": content})
            except OSError:
                pass
    return reports


# ==============================================================================
# CLI DISPATCHER
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Supervisor Tools: Điều khiển Terminal & Nghiệm thu chất lượng.")
    subparsers = parser.add_subparsers(dest="action", help="Thao tác")

    # list-sessions
    subparsers.add_parser("list-sessions", help="Xem danh sách tmux sessions đang chạy")

    # read-pane
    read_p = subparsers.add_parser("read-pane", help="Đọc output từ tmux session")
    read_p.add_argument("session", help="Tên tmux session")
    read_p.add_argument("--lines", type=int, default=50, help="Số dòng cuối cần đọc (mặc định: 50)")

    # send-keys
    send_p = subparsers.add_parser("send-keys", help="Gửi lệnh hoặc phím bấm vào tmux session")
    send_p.add_argument("session", help="Tên tmux session")
    send_p.add_argument("keys", help="Chuỗi lệnh hoặc phím")
    send_p.add_argument("--no-enter", action="store_true", help="Không nhấn Enter sau khi gửi")

    # git-diff
    subparsers.add_parser("git-diff", help="Kiểm tra git status và git diff hiện tại")

    # run-tests
    test_p = subparsers.add_parser("run-tests", help="Chạy kiểm thử độc lập")
    test_p.add_argument("cmd", nargs="?", default="auto", help="Lệnh test (mặc định: auto)")

    # reports
    subparsers.add_parser("reports", help="Đọc danh sách báo cáo bàn giao trong .ai_router_reports/")

    args = parser.parse_args()

    if args.action == "list-sessions":
        sessions = tmux_list_sessions()
        print(json.dumps(sessions, indent=2, ensure_ascii=False))
    elif args.action == "read-pane":
        print(tmux_read_pane(args.session, args.lines))
    elif args.action == "send-keys":
        ok = tmux_send_keys(args.session, args.keys, press_enter=not args.no_enter)
        print("OK" if ok else "FAILED")
    elif args.action == "git-diff":
        diff = inspect_git_diff()
        print(json.dumps(diff, indent=2, ensure_ascii=False))
    elif args.action == "run-tests":
        res = run_verification_tests(args.cmd)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.action == "reports":
        reps = read_handoff_reports()
        print(json.dumps(reps, indent=2, ensure_ascii=False))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
