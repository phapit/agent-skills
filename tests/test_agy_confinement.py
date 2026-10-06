import os
import shutil
import pytest

import classify_and_split_task


def test_sec_23_agy_permission_mode_matrix(monkeypatch):
    """
    SEC-23: Kiểm thử agy_permission_mode với các cấu hình và môi trường khác nhau:
    - Mặc định: 'bwrap' (khi có binary bwrap trên PATH).
    - Cấu hình 'sandbox', 'skip', hoặc giá trị lạ (-> 'sandbox').
    - Thiếu binary bwrap -> tự lùi về 'sandbox'.
    - SETTINGS_DATA['antigravity'] không phải dict -> an toàn, không ném ngoại lệ.
    """
    # 1. Mặc định có bwrap
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None)
    monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", {})
    assert classify_and_split_task.agy_permission_mode() == "bwrap"

    # 2. Cấu hình rõ ràng: sandbox, skip
    monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", {"antigravity": {"permission_mode": "sandbox"}})
    assert classify_and_split_task.agy_permission_mode() == "sandbox"

    monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", {"antigravity": {"permission_mode": "skip"}})
    assert classify_and_split_task.agy_permission_mode() == "skip"

    # 3. Giá trị lạ -> tự đưa về sandbox
    monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", {"antigravity": {"permission_mode": "unknown_value"}})
    assert classify_and_split_task.agy_permission_mode() == "sandbox"

    # 4. Thiếu bwrap binary -> tự lùi về sandbox
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", {"antigravity": {"permission_mode": "bwrap"}})
    assert classify_and_split_task.agy_permission_mode() == "sandbox"

    # 5. SETTINGS_DATA['antigravity'] không phải dict (None, string, int)
    for bad_conf in [None, "invalid_string", 123, []]:
        monkeypatch.setattr(classify_and_split_task, "SETTINGS_DATA", {"antigravity": bad_conf})
        assert classify_and_split_task.agy_permission_mode() in ("bwrap", "sandbox")


def test_sec_24_agy_permission_args(monkeypatch):
    """
    SEC-24: agy_permission_args trả về danh sách cờ chính xác cho từng mode:
    - bwrap hoặc skip: ['--dangerously-skip-permissions']
    - sandbox: ['--sandbox', '--dangerously-skip-permissions']
    """
    monkeypatch.setattr(classify_and_split_task, "agy_permission_mode", lambda: "bwrap")
    assert classify_and_split_task.agy_permission_args() == ["--dangerously-skip-permissions"]

    monkeypatch.setattr(classify_and_split_task, "agy_permission_mode", lambda: "skip")
    assert classify_and_split_task.agy_permission_args() == ["--dangerously-skip-permissions"]

    monkeypatch.setattr(classify_and_split_task, "agy_permission_mode", lambda: "sandbox")
    assert classify_and_split_task.agy_permission_args() == ["--sandbox", "--dangerously-skip-permissions"]


def test_sec_25_confine_agy_cmd_properties(tmp_path, monkeypatch):
    """
    SEC-25: confine_agy_cmd ở chế độ bwrap:
    - Bắt đầu bằng bwrap
    - Chứa cặp '--ro-bind', '/', '/'
    - Có '--bind', <workspace>, <workspace>
    - Có '--bind' cho HOME của profile khi env['HOME'] khác HOME thật
    - Có '--die-with-parent'
    - Có '--' ngay trước cmd_args và cmd_args nằm nguyên vẹn ở cuối
    - Ở mode khác (sandbox/skip) -> trả cmd_args không đổi.
    """
    monkeypatch.setattr(classify_and_split_task, "agy_permission_mode", lambda: "bwrap")

    workspace = str(tmp_path / "my_workspace")
    os.makedirs(workspace, exist_ok=True)
    real_home = str(tmp_path)
    profile_home = str(tmp_path / ".agents" / "profiles" / "antigravity_worker1")
    os.makedirs(profile_home, exist_ok=True)

    cmd_args = ["agy", "-p", "task prompt", "--verbose"]
    confined = classify_and_split_task.confine_agy_cmd(
        cmd_args,
        cwd=workspace,
        env={"HOME": profile_home},
    )

    # 1. Bắt đầu bằng bwrap
    assert confined[0] == "bwrap"

    # 2. Cặp --ro-bind / /
    ro_bind_indices = [i for i, x in enumerate(confined) if x == "--ro-bind"]
    assert any(confined[i + 1] == "/" and confined[i + 2] == "/" for i in ro_bind_indices)

    # 3. --bind <workspace> <workspace>
    bind_indices = [i for i, x in enumerate(confined) if x == "--bind"]
    assert any(confined[i + 1] == workspace and confined[i + 2] == workspace for i in bind_indices)

    # 4. --bind cho HOME profile
    assert any(confined[i + 1] == profile_home and confined[i + 2] == profile_home for i in bind_indices)

    # 5. Có --die-with-parent
    assert "--die-with-parent" in confined

    # 6. Có '--' ngay trước cmd_args và cmd_args nằm nguyên vẹn ở cuối
    dash_dash_idx = len(confined) - len(cmd_args) - 1
    assert confined[dash_dash_idx] == "--"
    assert confined[dash_dash_idx + 1:] == cmd_args

    # 7. Chế độ khác trả về cmd_args không đổi
    for other_mode in ["sandbox", "skip"]:
        monkeypatch.setattr(classify_and_split_task, "agy_permission_mode", lambda: other_mode)
        assert classify_and_split_task.confine_agy_cmd(cmd_args, cwd=workspace, env=None) == cmd_args


def test_sec_26_secret_dirs_tmpfs_masking(tmp_path, monkeypatch):
    """
    SEC-26: Thư mục bí mật (.ssh, .aws, .gnupg...) chỉ được che (--tmpfs) khi tồn tại trong HOME thật;
    khi không tồn tại thì KHÔNG được thêm --tmpfs tới đường dẫn đó (tránh lỗi khởi động bwrap).
    """
    monkeypatch.setattr(classify_and_split_task, "agy_permission_mode", lambda: "bwrap")
    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)

    # isolated_home đặt HOME về tmp_path
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    # .aws và .gnupg KHÔNG tồn tại

    cmd = ["agy", "test"]
    confined = classify_and_split_task.confine_agy_cmd(cmd, cwd=workspace, env=None)

    tmpfs_dirs = [confined[i + 1] for i, x in enumerate(confined) if x == "--tmpfs"]

    # .ssh tồn tại -> phải có --tmpfs
    assert str(ssh_dir) in tmpfs_dirs

    # .aws và .gnupg không tồn tại -> KHÔNG được có --tmpfs
    assert str(tmp_path / ".aws") not in tmpfs_dirs
    assert str(tmp_path / ".gnupg") not in tmpfs_dirs
