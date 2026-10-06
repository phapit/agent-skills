import os
import stat
import subprocess
import pytest

import profile_manager
import classify_and_split_task


def test_sec_11_ensure_private_dir_creates_0700(tmp_path):
    """
    SEC-11: ensure_private_dir tạo thư mục mới đạt quyền 0o700 (chỉ chủ sở hữu).
    """
    target = tmp_path / "new_private_dir"
    profile_manager.ensure_private_dir(str(target))
    assert target.is_dir()
    mode = stat.S_IMODE(os.stat(str(target)).st_mode)
    assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"


def test_sec_12_ensure_private_dir_tightens_existing_0755(tmp_path):
    """
    SEC-12: ensure_private_dir siết quyền thư mục đã tồn tại từ 0o755 về 0o700.
    """
    target = tmp_path / "existing_dir"
    target.mkdir(mode=0o755)
    os.chmod(str(target), 0o755)
    assert stat.S_IMODE(os.stat(str(target)).st_mode) == 0o755

    classify_and_split_task.ensure_private_dir(str(target))
    mode = stat.S_IMODE(os.stat(str(target)).st_mode)
    assert mode == 0o700, f"Expected tightened 0o700, got {oct(mode)}"


def test_sec_13_list_profiles_status_creates_base_with_0700(tmp_path, monkeypatch, capsys):
    """
    SEC-13: list_profiles_status khởi tạo DEFAULT_PROFILES_BASE với 0o700 khi chưa tồn tại.
    """
    base = tmp_path / ".agents" / "profiles"
    if base.exists():
        os.rmdir(str(base))
    monkeypatch.setattr(profile_manager, "DEFAULT_PROFILES_BASE", str(base))

    profile_manager.list_profiles_status()
    assert base.is_dir()
    mode = stat.S_IMODE(os.stat(str(base)).st_mode)
    assert mode == 0o700, f"Expected 0o700 for DEFAULT_PROFILES_BASE, got {oct(mode)}"


def test_sec_20_reports_dir_creates_0700(tmp_path):
    """
    SEC-20: reports_dir(cwd) tạo thư mục .ai_router_reports với quyền 0o700.
    """
    rep_dir = classify_and_split_task.reports_dir(str(tmp_path))
    assert os.path.isdir(rep_dir)
    assert os.path.basename(rep_dir) == ".ai_router_reports"
    mode = stat.S_IMODE(os.stat(rep_dir).st_mode)
    assert mode == 0o700, f"Expected reports_dir 0o700, got {oct(mode)}"


def test_sec_21_gitignore_covers_reports():
    """
    SEC-21: .gitignore của repository chứa .ai_router_reports/ và git check-ignore xác nhận.
    (Chỉ đọc file gốc của repo, không sửa đổi).
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gitignore_path = os.path.join(repo_root, ".gitignore")
    assert os.path.isfile(gitignore_path)

    with open(gitignore_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert ".ai_router_reports/" in content

    # Chạy git check-ignore trong repo thật để xác thực quy tắc git
    sample_report = os.path.join(repo_root, ".ai_router_reports", "test_report.md")
    proc = subprocess.run(
        ["git", "check-ignore", sample_report],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0, "Git không ignore file trong .ai_router_reports/"


def test_sec_22_hostile_umask_defense(tmp_path):
    """
    SEC-22: Umask thù địch (os.umask(0) cho phép toàn quyền 0777)
    vẫn đảm bảo ensure_private_dir tạo thư mục quyền 0o700.
    """
    old_umask = os.umask(0)
    try:
        target = tmp_path / "hostile_umask_dir"
        profile_manager.ensure_private_dir(str(target))
        mode = stat.S_IMODE(os.stat(str(target)).st_mode)
        assert mode == 0o700, f"Umask 0 làm hỏng quyền thư mục: got {oct(mode)}"
    finally:
        os.umask(old_umask)
