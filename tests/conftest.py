import os
import sys
import pytest

# Ensure ai-task-router and repo-map are in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_TASK_ROUTER_DIR = os.path.join(BASE_DIR, "ai-task-router")
REPO_MAP_DIR = os.path.join(BASE_DIR, "repo-map")

if AI_TASK_ROUTER_DIR not in sys.path:
    sys.path.insert(0, AI_TASK_ROUTER_DIR)
if REPO_MAP_DIR not in sys.path:
    sys.path.insert(0, REPO_MAP_DIR)

import profile_manager
import classify_and_split_task


@pytest.fixture(autouse=True)
def isolated_home(request, tmp_path, monkeypatch):
    """
    Fixture cô lập HOME và DEFAULT_PROFILES_BASE:
    - HOME đặt về tmp_path
    - DEFAULT_PROFILES_BASE đặt về tmp_path / .agents / profiles
    Đảm bảo test không bao giờ đọc/ghi vào thư mục gốc của hệ thống (~/.agents, ~/.gemini, ~/.ssh...).
    Không can thiệp vào test_bwrap_integration (phần của agent khác quản lý sandbox riêng).
    """
    if "test_bwrap_integration" in str(request.node.fspath):
        return None

    profiles_base = str(tmp_path / ".agents" / "profiles")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(profile_manager, "DEFAULT_PROFILES_BASE", profiles_base)
    monkeypatch.setattr(classify_and_split_task, "DEFAULT_PROFILES_BASE", profiles_base)
    return tmp_path
