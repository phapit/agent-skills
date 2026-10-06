"""
Kiểm thử tích hợp THẬT cho lớp thực thi bwrap của worker Antigravity (F5 + khoảng trống kiến trúc).
Chạy bwrap thật; tự bỏ qua nếu máy không có bwrap hoặc không cho user namespace.
Không gọi agy/claude/codex; không đụng ~/.ssh, ~/.agents thật (dùng HOME giả dưới ~/.cache).
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ai-task-router"))
import classify_and_split_task as c  # noqa: E402


def _bwrap_usable() -> bool:
    if not shutil.which("bwrap"):
        return False
    r = subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"], capture_output=True)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _bwrap_usable(), reason="bwrap không khả dụng trên máy này")


@pytest.fixture
def sandbox(monkeypatch):
    """HOME giả + workspace giả; trả hàm run(shell_cmd, env_extra) chạy trong bwrap qua confine_agy_cmd."""
    base = os.path.expanduser("~/.cache")
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix="bwtest-", dir=base)
    home = os.path.join(root, "home")
    ws = os.path.join(root, "ws")
    profile_home = os.path.join(root, "home", ".agents", "profiles", "antigravity_t")
    for d in (home, ws, profile_home):
        os.makedirs(d, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setattr(c, "DEFAULT_PROFILES_BASE", os.path.join(home, ".agents", "profiles"))
    monkeypatch.setattr(c, "SETTINGS_DATA", {"antigravity": {"permission_mode": "bwrap"}})

    class Box:
        pass

    box = Box()
    box.root, box.home, box.ws, box.profile_home = root, home, ws, profile_home

    def run(script, env_extra=None, use_profile=False, timeout=30):
        env = os.environ.copy()
        env["HOME"] = profile_home if use_profile else home
        env.update(env_extra or {})
        cmd = c.confine_agy_cmd(["sh", "-c", script], ws, env)
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)

    box.run = run
    yield box
    shutil.rmtree(root, ignore_errors=True)


def test_bw01_workspace_writable(sandbox):
    """BW-01: ghi trong workspace phải thành công."""
    r = sandbox.run("echo ok > ws_file && cat ws_file")
    assert r.returncode == 0 and "ok" in r.stdout
    assert os.path.isfile(os.path.join(sandbox.ws, "ws_file"))


@pytest.mark.parametrize("target", ["/etc/bw_probe", "/usr/bw_probe", "/var/tmp/bw_probe"])
def test_bw02_system_paths_readonly(sandbox, target):
    """BW-02: ghi vào đường dẫn hệ thống phải bị chặn và không tạo file ngoài thật."""
    r = sandbox.run(f"echo x > {target}")
    assert r.returncode != 0
    assert not os.path.exists(target)


def test_bw03_home_outside_workspace_readonly(sandbox):
    """BW-03: HOME (ngoài workspace/profile) chỉ-đọc."""
    r = sandbox.run("echo x > $HOME/escape.txt")
    assert r.returncode != 0
    assert not os.path.exists(os.path.join(sandbox.home, "escape.txt"))


def test_bw04_secret_dirs_masked(sandbox):
    """BW-04: .ssh/.aws/.gnupg trong HOME bị che (rỗng) dù tồn tại ngoài sandbox."""
    for d in (".ssh", ".aws", ".gnupg"):
        os.makedirs(os.path.join(sandbox.home, d), exist_ok=True)
        with open(os.path.join(sandbox.home, d, "secret"), "w") as f:
            f.write("TOPSECRET")
    r = sandbox.run("cat $HOME/.ssh/secret $HOME/.aws/secret $HOME/.gnupg/secret 2>&1; ls -A $HOME/.ssh | wc -l")
    assert "TOPSECRET" not in r.stdout
    assert r.stdout.strip().endswith("0")


def test_bw05_other_profiles_masked(sandbox):
    """BW-05: token của profile khác không đọc được từ profile đang chạy."""
    other = os.path.join(c.DEFAULT_PROFILES_BASE, "claude_other")
    os.makedirs(other, exist_ok=True)
    with open(os.path.join(other, "token"), "w") as f:
        f.write("OTHERTOKEN")
    r = sandbox.run(f"cat {other}/token 2>&1", use_profile=True)
    assert "OTHERTOKEN" not in r.stdout
    # nhưng chính profile đang chạy vẫn ghi được
    r2 = sandbox.run("echo mine > $HOME/mine && cat $HOME/mine", use_profile=True)
    assert r2.returncode == 0 and "mine" in r2.stdout


def test_bw06_persistence_points_readonly(sandbox):
    """BW-06: .git/hooks, .git/config, .vscode, .envrc bị khóa chỉ-đọc; git commit thường vẫn chạy."""
    ws = sandbox.ws
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.x"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=ws, check=True)
    os.makedirs(os.path.join(ws, ".vscode"))
    open(os.path.join(ws, ".envrc"), "w").write("# orig\n")
    for script, label in [
        ("echo '#!/bin/sh' > .git/hooks/pre-commit", "hooks"),
        ("echo '[alias]' >> .git/config", "git config"),
        ("echo '{}' > .vscode/tasks.json", "vscode"),
        ("echo 'curl x' >> .envrc", "envrc"),
    ]:
        r = sandbox.run(script)
        assert r.returncode != 0, f"{label} phải bị chặn"
    assert not os.path.exists(os.path.join(ws, ".git", "hooks", "pre-commit"))
    assert not os.path.exists(os.path.join(ws, ".vscode", "tasks.json"))
    r = sandbox.run("echo a > a.txt && git add a.txt && git commit -q -m t && git log --oneline | wc -l")
    assert r.returncode == 0 and r.stdout.strip() == "1", r.stderr


def test_bw07_agy_settings_protected(sandbox):
    """BW-07: agent không tự sửa settings.json của agy (nới permissions.allow); file khác trong .gemini vẫn ghi được."""
    gem = os.path.join(sandbox.profile_home, ".gemini")
    os.makedirs(os.path.join(gem, "antigravity-cli"), exist_ok=True)
    for rel in ("settings.json", os.path.join("antigravity-cli", "settings.json")):
        open(os.path.join(gem, rel), "w").write("{}")
    for rel in ("settings.json", "antigravity-cli/settings.json"):
        r = sandbox.run(f'echo \'{{"permissions":{{"allow":["command(*)"]}}}}\' > $HOME/.gemini/{rel}', use_profile=True)
        assert r.returncode != 0, rel
        assert open(os.path.join(gem, rel)).read() == "{}"
    r = sandbox.run("echo s > $HOME/.gemini/state.db && echo ok", use_profile=True)
    assert r.returncode == 0 and "ok" in r.stdout


def _listen_unix(path):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(5)

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
                conn.close()
            except OSError:
                return

    threading.Thread(target=loop, daemon=True).start()
    return srv


CONNECT = (
    "python3 -c \"import socket,sys;s=socket.socket(socket.AF_UNIX);s.connect(sys.argv[1]);print('CONNECTED')\" {path}"
)


@pytest.mark.skipif(not os.path.isdir(f"/run/user/{os.getuid()}"), reason="không có /run/user/UID")
def test_bw08_run_user_sockets_unreachable(sandbox):
    """BW-08: socket trong /run/user/UID (D-Bus, keyring, ssh-agent) không kết nối được từ trong sandbox."""
    path = f"/run/user/{os.getuid()}/bwtest-{os.getpid()}.sock"
    srv = _listen_unix(path)
    try:
        outside = subprocess.run(CONNECT.format(path=path), shell=True, capture_output=True, text=True)
        assert "CONNECTED" in outside.stdout  # đối chứng: bên ngoài kết nối được
        inside = sandbox.run(CONNECT.format(path=path))
        assert "CONNECTED" not in inside.stdout
    finally:
        srv.close()
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.skipif(not os.path.exists("/var/run/docker.sock"), reason="không có docker.sock")
def test_bw09_docker_socket_masked(sandbox):
    """BW-09: docker.sock (tương đương root trên máy) không truy cập được từ trong sandbox."""
    r = sandbox.run(CONNECT.format(path="/var/run/docker.sock"))
    assert "CONNECTED" not in r.stdout


def test_bw10_socket_env_vars_removed(sandbox):
    """BW-10: biến môi trường trỏ tới socket bị gỡ."""
    r = sandbox.run(
        'echo "[$SSH_AUTH_SOCK][$DBUS_SESSION_BUS_ADDRESS][$XDG_RUNTIME_DIR][$GPG_AGENT_INFO]"',
        env_extra={
            "SSH_AUTH_SOCK": "/x/ssh", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/x/bus",
            "XDG_RUNTIME_DIR": "/run/user/1", "GPG_AGENT_INFO": "/x/gpg",
        },
    )
    assert r.stdout.strip() == "[][][][]"


def test_bw11_symlink_escape_from_workspace(sandbox):
    """BW-11: symlink trong workspace trỏ ra ngoài không cho ghi ra ngoài."""
    target = os.path.join(sandbox.home, "outside.txt")
    os.symlink(target, os.path.join(sandbox.ws, "link"))
    r = sandbox.run("echo pwn > link")
    assert r.returncode != 0
    assert not os.path.exists(target)


def test_bw12_die_with_parent_and_exit_code(sandbox):
    """BW-12: mã thoát của lệnh con được truyền ra; lệnh không tồn tại trả mã khác 0."""
    assert sandbox.run("exit 7").returncode == 7
    assert sandbox.run("definitely_not_a_command_xyz").returncode != 0


def test_bw13_tmp_is_private_tmpfs(sandbox):
    """BW-13: /tmp bên trong là tmpfs riêng: file tạo trong sandbox không lộ ra /tmp thật, và ngược lại."""
    outside = f"/tmp/bw_outside_{os.getpid()}"
    open(outside, "w").write("x")
    try:
        r = sandbox.run(f"test -e {outside} && echo SEES || echo HIDDEN; echo y > /tmp/bw_inside_{os.getpid()}")
        assert "HIDDEN" in r.stdout
        assert not os.path.exists(f"/tmp/bw_inside_{os.getpid()}")
    finally:
        os.unlink(outside)


@pytest.mark.skipif(os.environ.get("RUN_NET_PROBE") != "1", reason="thăm dò mạng chỉ chạy khi RUN_NET_PROBE=1")
def test_bw14_known_gap_network_not_isolated(sandbox):
    """BW-14 (KHOẢNG TRỐNG ĐÃ BIẾT, chỉ tài liệu hóa): mạng KHÔNG bị cô lập vì agy cần gọi API -> có thể exfiltrate."""
    r = sandbox.run(
        "python3 -c \"import urllib.request;urllib.request.urlopen('https://example.com',timeout=5);print('NET_OK')\""
    )
    assert "NET_OK" in r.stdout  # nếu fail: mạng đã được cô lập -> cập nhật tài liệu rủi ro
