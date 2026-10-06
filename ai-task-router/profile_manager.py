#!/usr/bin/env python3
"""
Profile Manager for AI Coding Agent CLIs:
Quản lý các profile độc lập (multi-account) cho Antigravity, Claude Code, và Codex.
Cho phép khởi tạo, đăng nhập và chạy session với biến môi trường tách biệt hoàn toàn.
"""
from __future__ import annotations

import argparse
import glob
import json
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
        f'eval $(gnome-keyring-daemon --start --components=secrets --control-directory="{keyring_dir}" 2>>"{profile_dir}/.keyring.log"); '
        f'exec {quoted_args}'
    )
    return ["dbus-run-session", "--", "sh", "-c", shell_cmd]


def launch_login(agent: str, profile_name: str = "supervisor", force: bool = False) -> int:
    """
    Khởi động CLI trong môi trường profile độc lập để người dùng xác thực tài khoản thứ 2.
    Nếu profile đã đăng nhập sẵn thì báo rõ và hỏi xác nhận (trừ khi force=True).
    """
    norm_agent = normalize_agent_name(agent)
    if not force and is_profile_initialized(norm_agent, profile_name):
        email = get_profile_email(norm_agent, profile_name)
        who = f" ({email})" if email else ""
        print(f"Profile '{norm_agent}_{profile_name}' đã đăng nhập{who}.")
        print(f"Muốn đổi tài khoản: logout {norm_agent} {profile_name} rồi login lại.")
        try:
            answer = input("Vẫn mở CLI trong profile này? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Đã hủy, không mở CLI.")
            return ALREADY_LOGGED_IN
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


_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _dir_size_mb(path: str) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp):
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    return total / (1024 * 1024)


def _profiles_listed_in_settings(agent: str, profile_name: str) -> bool:
    """True nếu profile còn được liệt kê trong antigravity.profiles của settings.json."""
    if normalize_agent_name(agent) != "antigravity":
        return False
    candidates = [
        os.path.expanduser("~/.agents/settings.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agents", "settings.json"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        profiles = (data.get("antigravity") or {}).get("profiles", [])
        if isinstance(profiles, list) and profile_name in [str(x).strip() for x in profiles]:
            return True
    return False


SUPERVISOR_PROFILE = "supervisor"
ALREADY_LOGGED_IN = -1  # launch_login bị hủy vì profile đã đăng nhập
GLOBAL_AGENTS_DIR = os.path.expanduser("~/.agents")
REPO_AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agents")


def resolve_settings_path() -> str:
    """Luôn ghi vào ~/.agents/settings.json của người dùng (router để file này ghi đè lên mặc định trong repo)."""
    return os.path.join(GLOBAL_AGENTS_DIR, "settings.json")


def _mutate_settings(mutator) -> str | None:
    """Đọc-sửa-ghi settings.json an toàn (ghi nguyên tử). Trả mô tả thay đổi hoặc None nếu không đổi."""
    path = resolve_settings_path()
    data: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"[CẢNH BÁO] Không đọc được {path} ({e}) -> KHÔNG tự cập nhật settings.")
            return None
        if not isinstance(data, dict):
            print(f"[CẢNH BÁO] {path} không phải JSON object -> KHÔNG tự cập nhật settings.")
            return None
    change = mutator(data)
    if not change:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if os.path.isfile(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)
    return f"{change} ({path})"


def sync_settings_after_login(agent: str, profile_name: str) -> None:
    norm_agent = normalize_agent_name(agent)

    def mutate(data: dict) -> str | None:
        if profile_name == SUPERVISOR_PROFILE:
            sup = data.setdefault("supervisor", {})
            if sup.get("enabled") is True and sup.get("model") == norm_agent and sup.get("profile") == SUPERVISOR_PROFILE:
                return None
            sup.update({"enabled": True, "model": norm_agent, "profile": SUPERVISOR_PROFILE})
            return f"Đã BẬT supervisor (model={norm_agent})"
        if norm_agent == "antigravity":
            agy = data.setdefault("antigravity", {})
            pool = agy.get("profiles")
            if not isinstance(pool, list):
                pool = []
            if profile_name in pool:
                return None
            agy["profiles"] = pool + [profile_name]
            return f"Đã thêm '{profile_name}' vào antigravity.profiles"
        return None

    msg = _mutate_settings(mutate)
    if msg:
        print(f"[Settings] {msg}")


def sync_settings_after_logout(agent: str, profile_name: str) -> None:
    norm_agent = normalize_agent_name(agent)

    def mutate(data: dict) -> str | None:
        if profile_name == SUPERVISOR_PROFILE:
            sup = data.get("supervisor")
            if isinstance(sup, dict) and sup.get("enabled") and sup.get("model") == norm_agent:
                sup["enabled"] = False
                return "Đã TẮT supervisor"
            return None
        if norm_agent == "antigravity":
            agy = data.get("antigravity")
            pool = agy.get("profiles") if isinstance(agy, dict) else None
            if isinstance(pool, list) and profile_name in pool:
                agy["profiles"] = [x for x in pool if x != profile_name]
                note = "" if agy["profiles"] else " (pool rỗng: router sẽ dùng tài khoản agy mặc định của máy)"
                return f"Đã gỡ '{profile_name}' khỏi antigravity.profiles{note}"
        return None

    msg = _mutate_settings(mutate)
    if msg:
        print(f"[Settings] {msg}")


def logout_profile(agent: str, profile_name: str, assume_yes: bool = False, sync: bool = True) -> int:
    """
    Đăng xuất = xóa toàn bộ thư mục profile cô lập (token, keyring, log, cache).
    Chỉ xóa được thư mục nằm TRỰC TIẾP trong ~/.agents/profiles/; không đụng tài khoản gốc của máy.
    """
    norm_agent = normalize_agent_name(agent)
    if not _PROFILE_NAME_RE.fullmatch(profile_name) or profile_name in ("default",):
        print(f"[LỖI] Tên profile không hợp lệ hoặc không được phép xóa: {profile_name!r}")
        return 2

    base = os.path.realpath(DEFAULT_PROFILES_BASE)
    target = get_profile_dir(norm_agent, profile_name)
    if os.path.islink(target) or os.path.dirname(os.path.realpath(target)) != base:
        print(f"[LỖI] Từ chối xóa vì đường dẫn không nằm trực tiếp trong {base}: {target}")
        return 2
    if not os.path.isdir(target):
        print(f"[Thông báo] Profile '{norm_agent}_{profile_name}' không tồn tại, không có gì để xóa.")
        if sync:
            sync_settings_after_logout(norm_agent, profile_name)
        return 0

    email = get_profile_email(norm_agent, profile_name)
    print(f"Profile      : {norm_agent}_{profile_name}")
    print(f"Thư mục      : {target}")
    print(f"Tài khoản    : {email or '(không xác định)'}")
    print(f"Dung lượng   : {_dir_size_mb(target):.1f} MB")
    if not sync and _profiles_listed_in_settings(norm_agent, profile_name):
        print(f"[!] Profile '{profile_name}' vẫn nằm trong antigravity.profiles của settings.json; "
              f"router sẽ bỏ qua nó (chưa đăng nhập) cho tới khi bạn gỡ tên khỏi danh sách hoặc đăng nhập lại.")

    if not assume_yes:
        try:
            answer = input("Xóa vĩnh viễn profile này và đăng xuất? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Đã hủy, không xóa gì.")
            return 1

    shutil.rmtree(target)
    if sync:
        sync_settings_after_logout(norm_agent, profile_name)
    print(f"[OK] Đã xóa profile '{norm_agent}_{profile_name}'. Đăng nhập lại: "
          f"python3 profile_manager.py login {norm_agent} {profile_name}")
    return 0


def sync_all_profiles() -> None:
    """Đối chiếu settings.json với các profile đã đăng nhập sẵn (dùng một lần cho profile tạo trước khi có tự động hóa)."""
    if not os.path.isdir(DEFAULT_PROFILES_BASE):
        print("(Chưa có profile nào)")
        return
    for entry in sorted(os.listdir(DEFAULT_PROFILES_BASE)):
        agent, _, name = entry.partition("_")
        if agent in SUPPORTED_AGENTS and name and is_profile_initialized(agent, name):
            sync_settings_after_login(agent, name)
    print(f"[Settings] Đã đối chiếu xong: {resolve_settings_path()}")


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
    login_p.add_argument("--force", action="store_true", help="Không hỏi xác nhận khi profile đã đăng nhập sẵn")
    login_p.add_argument("--no-sync", action="store_true", help="Không tự cập nhật settings.json sau khi đăng nhập")

    # sync
    subparsers.add_parser("sync", help="Đối chiếu settings.json với các profile đã đăng nhập sẵn")

    # logout
    logout_p = subparsers.add_parser("logout", help="Đăng xuất: xóa toàn bộ thư mục profile cô lập")
    logout_p.add_argument("agent", choices=["antigravity", "agy", "claude", "codex"], help="Tên Model AI")
    logout_p.add_argument("profile", help="Tên profile cần xóa")
    logout_p.add_argument("-y", "--yes", action="store_true", help="Bỏ qua bước xác nhận")
    logout_p.add_argument("--no-sync", action="store_true", help="Không tự cập nhật settings.json sau khi xóa")

    # status
    subparsers.add_parser("status", help="Xem danh sách profile hiện có và trạng thái")

    # run
    run_p = subparsers.add_parser("run", help="Chạy một lệnh với môi trường của profile chỉ định")
    run_p.add_argument("agent", choices=["antigravity", "agy", "claude", "codex"], help="Tên Model AI")
    run_p.add_argument("profile", help="Tên profile")
    run_p.add_argument("cmd", nargs=argparse.REMAINDER, help="Lệnh cần chạy")

    args = parser.parse_args()

    if args.command == "login":
        rc = launch_login(args.agent, args.profile, force=args.force)
        if rc == ALREADY_LOGGED_IN:
            sys.exit(0)
        if not args.no_sync and is_profile_initialized(args.agent, args.profile):
            sync_settings_after_login(args.agent, args.profile)
        elif not args.no_sync:
            print("[Settings] Profile chưa đăng nhập xong -> không cập nhật settings.json.")
        sys.exit(rc)
    elif args.command == "logout":
        sys.exit(logout_profile(args.agent, args.profile, assume_yes=args.yes, sync=not args.no_sync))
    elif args.command == "sync":
        sync_all_profiles()
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
