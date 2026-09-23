#!/usr/bin/env python3
"""
Profile Manager for AI Coding Agent CLIs:
Quản lý các profile độc lập (multi-account) cho Antigravity, Claude Code, và Codex.
Cho phép khởi tạo, đăng nhập và chạy session với biến môi trường tách biệt hoàn toàn.
"""
from __future__ import annotations

import argparse
import os
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

    # Đảm bảo symlink gitconfig từ user gốc nếu có để agent commit được
    user_gitconfig = os.path.expanduser("~/.gitconfig")
    profile_gitconfig = os.path.join(profile_dir, ".gitconfig")
    if os.path.isfile(user_gitconfig) and not os.path.exists(profile_gitconfig):
        try:
            os.symlink(user_gitconfig, profile_gitconfig)
        except OSError:
            pass

    return env


def is_profile_initialized(agent: str, profile_name: str = "supervisor") -> bool:
    norm_agent = normalize_agent_name(agent)
    profile_dir = get_profile_dir(norm_agent, profile_name)
    if not os.path.isdir(profile_dir):
        return False

    if norm_agent == "antigravity":
        return os.path.isdir(os.path.join(profile_dir, ".gemini"))
    elif norm_agent == "claude":
        return os.path.isdir(os.path.join(profile_dir, ".claude")) or os.path.isfile(
            os.path.join(profile_dir, ".claude.json")
        )
    elif norm_agent == "codex":
        return os.path.isdir(os.path.join(profile_dir, ".codex"))
    return False


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
    try:
        proc = subprocess.run([cmd], env=env)
        return proc.returncode
    except FileNotFoundError:
        print(f"[LỖI] Không tìm thấy lệnh '{cmd}' trên PATH. Hãy cài đặt CLI trước.")
        return 127


def list_profiles_status() -> None:
    print("\n" + "=" * 60)
    print("DANH SÁCH PROFILE ĐỘC LẬP (MULTI-ACCOUNT)")
    print("=" * 60)
    os.makedirs(DEFAULT_PROFILES_BASE, exist_ok=True)
    profiles = sorted(os.listdir(DEFAULT_PROFILES_BASE))
    if not profiles:
        print("  (Chưa có profile nào được khởi tạo trong ~/.agents/profiles/)")
        print("\nĐể tạo profile mới:")
        print("  python3 profile_manager.py login <agent> [profile_name]")
        print("=" * 60 + "\n")
        return

    for p in profiles:
        full_path = os.path.join(DEFAULT_PROFILES_BASE, p)
        if not os.path.isdir(full_path):
            continue
        parts = p.split("_", 1)
        agent = parts[0]
        p_name = parts[1] if len(parts) > 1 else "default"
        is_init = is_profile_initialized(agent, p_name)
        status = "ĐÃ ĐĂNG NHẬP / SẴN SÀNG" if is_init else "CHƯA HOÀN TẤT SETUP"
        print(f"  • {p:<30} [{status}]")
        print(f"    Thư mục: {full_path}")
    print("=" * 60 + "\n")


def run_in_profile(agent: str, profile_name: str, cmd_args: list[str]) -> int:
    norm_agent = normalize_agent_name(agent)
    env = get_profile_env(norm_agent, profile_name)
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
