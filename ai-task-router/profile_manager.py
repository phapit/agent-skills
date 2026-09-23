#!/usr/bin/env python3
"""
Profile Manager for AI Coding Agent CLIs:
Quản lý các profile độc lập (multi-account) cho Antigravity, Claude Code, và Codex.
Cho phép khởi tạo, đăng nhập và chạy session với biến môi trường tách biệt hoàn toàn.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys

DEFAULT_PROFILES_BASE = os.path.expanduser("~/.agents/profiles")

SUPPORTED_AGENTS = ("antigravity", "codex", "claude")

AGENT_CMDS = {
    "antigravity": "agy",
    "claude": "claude",
    "codex": "codex",
}


def normalize_agent_name(name: str) -> str:
    cleaned = str(name).strip().lower().replace("_", "-")
    if cleaned in ("antigravity", "agy", "gemini"):
        return "antigravity"
    if cleaned in ("codex", "openai"):
        return "codex"
    if cleaned in ("claude", "claude-code", "anthropic"):
        return "claude"
    return cleaned


def get_profile_dir(agent: str, profile_name: str = "supervisor") -> str:
    norm_agent = normalize_agent_name(agent)
    folder_name = f"{norm_agent}_{profile_name}"
    return os.path.join(DEFAULT_PROFILES_BASE, folder_name)


def get_profile_env(agent: str, profile_name: str = "supervisor") -> dict[str, str]:
    """
    Tạo biến môi trường cách ly cho agent theo profile chỉ định.
    """
    norm_agent = normalize_agent_name(agent)
    profile_dir = get_profile_dir(norm_agent, profile_name)
    os.makedirs(profile_dir, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = profile_dir

    if norm_agent == "claude":
        env["CLAUDE_CONFIG_DIR"] = os.path.join(profile_dir, ".claude")
    elif norm_agent == "codex":
        env["CODEX_HOME"] = os.path.join(profile_dir, ".codex")
    elif norm_agent == "antigravity":
        env["GEMINI_CLI_HOME"] = os.path.join(profile_dir, ".gemini")
        # Cô lập hoàn toàn D-Bus keyring để không đọc/ghi đè token vào OS keyring chung của máy
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/dev/null"

    # Đảm bảo symlink gitconfig từ user gốc nếu có để agent commit được
    user_gitconfig = os.path.expanduser("~/.gitconfig")
    profile_gitconfig = os.path.join(profile_dir, ".gitconfig")
    if os.path.isfile(user_gitconfig) and not os.path.exists(profile_gitconfig):
        try:
            os.symlink(user_gitconfig, profile_gitconfig)
        except OSError:
            pass

    return env


def get_profile_email(agent: str, profile_name: str = "supervisor") -> str | None:
    """
    Trích xuất địa chỉ email đã xác thực gần nhất trong profile.
    """
    norm_agent = normalize_agent_name(agent)
    profile_dir = get_profile_dir(norm_agent, profile_name)
    if norm_agent == "antigravity":
        log_dir = os.path.join(profile_dir, ".gemini", "antigravity-cli", "log")
        if not os.path.isdir(log_dir):
            return None
        logs = sorted(glob.glob(os.path.join(log_dir, "cli-*.log")), reverse=True)
        for log_file in logs[:10]:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                matches = re.findall(
                    r"(?:OAuth|consumerOAuth):\s+authenticated successfully as\s+([\w\.\+-]+@[\w\.-]+)",
                    content,
                )
                if matches:
                    return matches[-1]
            except OSError:
                continue
    return None


def is_profile_initialized(agent: str, profile_name: str = "supervisor") -> bool:
    norm_agent = normalize_agent_name(agent)
    profile_dir = get_profile_dir(norm_agent, profile_name)
    if not os.path.isdir(profile_dir):
        return False

    if norm_agent == "antigravity":
        email = get_profile_email(norm_agent, profile_name)
        return bool(email) and os.path.isdir(os.path.join(profile_dir, ".gemini"))
    elif norm_agent == "claude":
        return os.path.isdir(os.path.join(profile_dir, ".claude")) or os.path.isfile(
            os.path.join(profile_dir, ".claude.json")
        )
    elif norm_agent == "codex":
        return os.path.isdir(os.path.join(profile_dir, ".codex"))
    return False


def wrap_agy_profile_cmd(cmd_args: list[str], profile_name: str) -> list[str]:
    """
    Bọc lệnh gọi Antigravity trong session D-Bus và GNOME Keyring biệt lập
    để token OAuth được lưu vào keyring riêng của profile thay vì keyring chung của máy.
    """
    if profile_name in ("default", "", None):
        return cmd_args
    if not shutil.which("dbus-run-session") or not shutil.which("gnome-keyring-daemon"):
        return cmd_args

    norm_name = profile_name if profile_name.startswith("antigravity_") else f"antigravity_{profile_name}"
    profile_dir = os.path.join(DEFAULT_PROFILES_BASE, norm_name)
    keyring_dir = os.path.join(profile_dir, ".keyring")
    share_dir = os.path.join(profile_dir, ".local", "share", "keyrings")
    os.makedirs(keyring_dir, mode=0o700, exist_ok=True)
    os.makedirs(share_dir, mode=0o700, exist_ok=True)

    quoted_args = " ".join(shlex.quote(a) for a in cmd_args)
    shell_cmd = (
        f'export XDG_DATA_HOME="{profile_dir}/.local/share"; '
        f'eval $(gnome-keyring-daemon --start --components=secrets --control-directory="{keyring_dir}"); '
        f'exec {quoted_args}'
    )
    return ["dbus-run-session", "--", "sh", "-c", shell_cmd]


def launch_login(agent: str, profile_name: str = "supervisor") -> int:
    """
    Khởi động CLI trong môi trường profile độc lập để người dùng xác thực tài khoản thứ 2.
    """
    norm_agent = normalize_agent_name(agent)
    cmd = AGENT_CMDS.get(norm_agent, norm_agent)
    profile_dir = get_profile_dir(norm_agent, profile_name)
    os.makedirs(profile_dir, exist_ok=True)

    print("=" * 60)
    print(f"  KHỞI TẠO ĐĂNG NHẬP CHO PROFILE: {norm_agent.upper()} ({profile_name})")
    print(f"  Thư mục lưu trữ cô lập: {profile_dir}")
    print("=" * 60)
    print(f"Đang khởi động '{cmd}' trong profile riêng...")
    print("Vui lòng hoàn tất đăng nhập theo hướng dẫn trên màn hình/trình duyệt.\n")

    env = get_profile_env(norm_agent, profile_name)
    cmd_args = [cmd]
    if norm_agent == "antigravity":
        cmd_args = wrap_agy_profile_cmd([cmd], profile_name)

    try:
        proc = subprocess.run(cmd_args, env=env)
        return proc.returncode
    except FileNotFoundError:
        print(f"[LỖI] Không tìm thấy lệnh '{cmd}' trên PATH. Hãy cài đặt CLI trước.")
        return 127


def list_profiles_status() -> None:
    print("\n" + "=" * 65)
    print("DANH SÁCH PROFILE ĐỘC LẬP (MULTI-ACCOUNT)")
    print("=" * 65)
    os.makedirs(DEFAULT_PROFILES_BASE, exist_ok=True)
    profiles = sorted(os.listdir(DEFAULT_PROFILES_BASE))
    if not profiles:
        print("  (Chưa có profile nào được khởi tạo trong ~/.agents/profiles/)")
        print("\nĐể tạo profile mới:")
        print("  python3 profile_manager.py login <agent> [profile_name]")
        print("=" * 65 + "\n")
        return

    email_map: dict[str, list[str]] = {}

    for p in profiles:
        full_path = os.path.join(DEFAULT_PROFILES_BASE, p)
        if not os.path.isdir(full_path):
            continue
        parts = p.split("_", 1)
        agent = parts[0]
        p_name = parts[1] if len(parts) > 1 else "default"
        is_init = is_profile_initialized(agent, p_name)
        status = "ĐÃ ĐĂNG NHẬP / SẴN SÀNG" if is_init else "CHƯA HOÀN TẤT SETUP"
        email = get_profile_email(agent, p_name)
        email_str = f" [Tài khoản: {email}]" if email else " [Chưa xác thực tài khoản]"
        if email:
            email_map.setdefault(email, []).append(p)
        print(f"  • {p:<28} [{status}]{email_str}")
        print(f"    Thư mục: {full_path}")

    # Cảnh báo nếu các profile bị trùng tài khoản
    has_duplicate = False
    for email, profs in email_map.items():
        if len(profs) > 1:
            if not has_duplicate:
                print("\n  " + "-" * 61)
                has_duplicate = True
            print(f"  [!] CẢNH BÁO: Các profile {profs} đang dùng CHUNG tài khoản '{email}'!")
            print(f"      -> Chạy 'python3 ai-task-router/profile_manager.py login <agent> <profile>' để đăng nhập tài khoản riêng biệt.")

    print("=" * 65 + "\n")


def run_in_profile(agent: str, profile_name: str, cmd_args: list[str]) -> int:
    norm_agent = normalize_agent_name(agent)
    env = get_profile_env(norm_agent, profile_name)
    if norm_agent == "antigravity":
        cmd_args = wrap_agy_profile_cmd(cmd_args, profile_name)
    proc = subprocess.run(cmd_args, env=env)
    return proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile Manager: Quản lý profile và tài khoản độc lập cho Antigravity, Claude, Codex."
    )
    subparsers = parser.add_subparsers(dest="command", help="Lệnh thao tác")

    # login
    login_p = subparsers.add_parser("login", help="Khởi động CLI để đăng nhập tài khoản cho profile riêng")
    login_p.add_argument("agent", choices=["antigravity", "agy", "claude", "codex"], help="Tên Model AI")
    login_p.add_argument("profile", nargs="?", default="supervisor", help="Tên profile (mặc định: supervisor)")

    # status
    subparsers.add_parser("status", help="Xem danh sách profile hiện có và trạng thái")

    # run
    run_p = subparsers.add_parser("run", help="Chạy một lệnh với môi trường của profile chỉ định")
    run_p.add_argument("agent", choices=["antigravity", "agy", "claude", "codex"], help="Tên Model AI")
    run_p.add_argument("profile", help="Tên profile")
    run_p.add_argument("cmd", nargs=argparse.REMAINDER, help="Lệnh cần chạy")

    args = parser.parse_args()

    if args.command == "login":
        sys.exit(launch_login(args.agent, args.profile))
    elif args.command == "status":
        list_profiles_status()
    elif args.command == "run":
        if not args.cmd:
            norm = normalize_agent_name(args.agent)
            cmd = [AGENT_CMDS.get(norm, norm)]
        else:
            cmd = args.cmd
            if cmd and cmd[0] == "--":
                cmd = cmd[1:]
        sys.exit(run_in_profile(args.agent, args.profile, cmd))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
