import json
import os
import shutil
import subprocess
import pytest

import profile_manager
import classify_and_split_task


def _setup_fake_tools(fake_bin_dir: str, capture_log: str) -> None:
    os.makedirs(fake_bin_dir, exist_ok=True)

    # Fake dbus-run-session: loại bỏ các cờ tới trước '--' rồi exec phần còn lại
    dbus_script = os.path.join(fake_bin_dir, "dbus-run-session")
    with open(dbus_script, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nwhile [ \"$#\" -gt 0 ]; do\n  if [ \"$1\" = \"--\" ]; then\n    shift\n    break\n  fi\n  shift\ndone\nexec \"$@\"\n")
    os.chmod(dbus_script, 0o755)

    # Fake gnome-keyring-daemon: in ra biến export vô hại
    keyring_script = os.path.join(fake_bin_dir, "gnome-keyring-daemon")
    with open(keyring_script, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\necho 'export FAKE_KEYRING=1'\n")
    os.chmod(keyring_script, 0o755)

    # Fake agy: ghi lại các tham số nhận được vào capture_log
    agy_script = os.path.join(fake_bin_dir, "agy")
    with open(agy_script, "w", encoding="utf-8") as f:
        f.write(
            "#!/usr/bin/env python3\n"
            "import sys, json, os\n"
            "log_path = os.environ.get('CAPTURE_LOG_FILE')\n"
            "if log_path:\n"
            "    with open(log_path, 'w', encoding='utf-8') as f:\n"
            "        json.dump(sys.argv[1:], f)\n"
            "sys.exit(0)\n"
        )
    os.chmod(agy_script, 0o755)


def test_sec_06_wrap_agy_profile_cmd_adversarial(tmp_path, monkeypatch):
    """
    SEC-06: wrap_agy_profile_cmd với cmd_args chứa chuỗi thù địch:
    - 'hello"; id; #'
    - $(touch PWNED)
    - `touch PWNED`
    - \\n touch PWNED
    - Nháy đơn/kép lồng nhau
    Kỳ vọng: Thực thi thật trong tmp_path -> File PWNED KHÔNG được tạo;
             tham số truyền tới agy giữ nguyên vẹn từng ký tự.
    """
    fake_bin = str(tmp_path / "bin")
    capture_log = str(tmp_path / "captured_args.json")
    _setup_fake_tools(fake_bin, capture_log)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["CAPTURE_LOG_FILE"] = capture_log

    adversarial_args = [
        "agy",
        'hello"; id; #',
        "$(touch PWNED)",
        "`touch PWNED`",
        "\n touch PWNED",
        "nested'single\"and\"double'quotes",
    ]

    # Kiểm tra cả 2 module: profile_manager và classify_and_split_task
    for mod_name, mod in [
        ("profile_manager", profile_manager),
        ("classify_and_split_task", classify_and_split_task),
    ]:
        wrapped = mod.wrap_agy_profile_cmd(adversarial_args, "worker_1")
        assert wrapped[:3] == ["dbus-run-session", "--", "sh"]

        # Xóa file log cũ nếu có
        if os.path.exists(capture_log):
            os.remove(capture_log)

        proc = subprocess.run(wrapped, cwd=str(tmp_path), env=env, timeout=10)
        assert proc.returncode == 0, f"Module {mod_name} chạy thất bại với rc={proc.returncode}"

        # Khẳng định 1: File PWNED không được tạo
        pwned_file = tmp_path / "PWNED"
        assert not pwned_file.exists(), f"Lỗ hổng Command Injection: File PWNED đã bị tạo bởi {mod_name}!"

        # Khẳng định 2: Tham số tới agy nguyên vẹn từng ký tự
        assert os.path.exists(capture_log)
        with open(capture_log, "r", encoding="utf-8") as f:
            received_args = json.load(f)
        assert received_args == adversarial_args[1:], f"Tham số bị biến dạng ở {mod_name}: {received_args}"


def test_sec_07_missing_daemon_or_default_profile(monkeypatch):
    """
    SEC-07: Thiếu dbus-run-session hoặc gnome-keyring-daemon -> trả cmd_args nguyên bản;
    profile default / '' / None -> trả cmd_args nguyên bản.
    """
    original_cmd = ["agy", "-p", "hello"]

    # 1. Profile default / "" / None
    for prof in ["default", "", None]:
        assert profile_manager.wrap_agy_profile_cmd(original_cmd, prof) == original_cmd
        assert classify_and_split_task.wrap_agy_profile_cmd(original_cmd, prof) == original_cmd

    # 2. Thiếu daemon (shutil.which trả None)
    monkeypatch.setattr(shutil, "which", lambda cmd: None if "dbus" in cmd else "/bin/gnome-keyring-daemon")
    assert profile_manager.wrap_agy_profile_cmd(original_cmd, "worker_1") == original_cmd
    assert classify_and_split_task.wrap_agy_profile_cmd(original_cmd, "worker_1") == original_cmd

    monkeypatch.setattr(shutil, "which", lambda cmd: None if "gnome-keyring" in cmd else "/bin/dbus-run-session")
    assert profile_manager.wrap_agy_profile_cmd(original_cmd, "worker_1") == original_cmd
    assert classify_and_split_task.wrap_agy_profile_cmd(original_cmd, "worker_1") == original_cmd


def test_sec_17_profile_path_with_special_characters(tmp_path, monkeypatch):
    """
    SEC-17: Đường dẫn profile base chứa khoảng trắng, nháy và ký tự đặc biệt (a b'c"d$e).
    Kỳ vọng: Chuỗi shell sinh ra vẫn an toàn, file PWNED không được tạo, tham số không suy suyển.
    """
    special_base = tmp_path / "a b'c\"d$e"
    special_base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(profile_manager, "DEFAULT_PROFILES_BASE", str(special_base))
    monkeypatch.setattr(classify_and_split_task, "DEFAULT_PROFILES_BASE", str(special_base))

    fake_bin = str(tmp_path / "bin")
    capture_log = str(tmp_path / "captured_args_sec17.json")
    _setup_fake_tools(fake_bin, capture_log)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["CAPTURE_LOG_FILE"] = capture_log

    cmd_args = ["agy", "arg1", "$(touch PWNED)", "hello world"]
    wrapped = profile_manager.wrap_agy_profile_cmd(cmd_args, "worker_special")

    proc = subprocess.run(wrapped, cwd=str(tmp_path), env=env, timeout=10)
    assert proc.returncode == 0
    assert not (tmp_path / "PWNED").exists(), "PWNED file created due to path unescaping"

    with open(capture_log, "r", encoding="utf-8") as f:
        received = json.load(f)
    assert received == cmd_args[1:]
