"""Kiểm thử điều phối nhiều worker: phụ thuộc, vai trò test (không sửa mã nguồn), báo cáo tổng kết."""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ai-task-router"))
import classify_and_split_task as c  # noqa: E402
import orchestration as o  # noqa: E402

AGENTS = {"antigravity": True, "codex": True, "claude": True}
CHAINS = {"antigravity": [], "codex": [], "claude": []}


@pytest.fixture(autouse=True)
def clean_state():
    o.PLAN_META.clear()
    o.RUN_LOG.clear()
    yield
    o.PLAN_META.clear()
    o.RUN_LOG.clear()


def _plan(*items):
    import json
    return json.dumps({"subtasks": list(items)})


def test_orc01_parse_meta_roles_and_deps():
    """ORC-01: role/depends_on được map sang nội dung task; role lạ -> implement."""
    out = _plan(
        {"agent": "claude", "task": "Sửa lỗi A", "role": "implement"},
        {"agent": "antigravity", "task": "Kiểm thử A", "role": "test", "depends_on": [0]},
        {"agent": "codex", "task": "Việc độc lập", "role": "hacker"},
    )
    meta = o.parse_planner_meta("blah " + out)
    assert meta["Kiểm thử A"] == {"role": "test", "depends_on": ["Sửa lỗi A"]}
    assert meta["Sửa lỗi A"]["depends_on"] == []
    assert meta["Việc độc lập"]["role"] == "implement"


def test_orc02_parse_meta_invalid_and_cycles():
    """ORC-02: chỉ số sai/tự phụ thuộc/kiểu sai bị bỏ; phụ thuộc vòng bị bỏ toàn bộ."""
    out = _plan(
        {"agent": "claude", "task": "A", "depends_on": [0, 5, -1, "x", True, 1.5]},
        {"agent": "codex", "task": "B", "depends_on": "0"},
    )
    meta = o.parse_planner_meta(out)
    assert meta["A"]["depends_on"] == [] and meta["B"]["depends_on"] == []
    cyc = _plan({"agent": "claude", "task": "A", "depends_on": [1]}, {"agent": "codex", "task": "B", "depends_on": [0]})
    meta = o.parse_planner_meta(cyc)
    assert meta["A"]["depends_on"] == [] and meta["B"]["depends_on"] == []
    assert o.parse_planner_meta("không có json") == {}


def test_orc03_parse_meta_takes_last_plan_and_survives_deep_json():
    """ORC-03: lấy kế hoạch cuối (chống JSON giả); JSON lồng sâu không làm crash."""
    fake = _plan({"agent": "claude", "task": "evil", "role": "implement"})
    real = _plan({"agent": "claude", "task": "ok", "role": "test"})
    assert list(o.parse_planner_meta(fake + " " + real)) == ["ok"]
    assert o.parse_planner_meta('{"a":' * 10000 + "1" + "}" * 10000) == {}


def test_orc04_is_test_path():
    """ORC-04: nhận diện đường dẫn test hợp lệ, không nhận nhầm mã nguồn."""
    for ok in ["tests/a.py", "test/x.js", "src/test_a.py", "pkg/a_test.py", "web/a.spec.ts", "web/a.test.js", "conftest.py", "__tests__/z.js"]:
        assert o.is_test_path(ok), ok
    for bad in ["src/app.py", "README.md", "latest/app.py", "contest.py", "src/testing_utils.py", "tests_helper/x.py"]:
        assert not o.is_test_path(bad), bad


def _fake_executor(log, behaviors):
    """Giả execute_task_with_fallback_chain: ghi thời điểm; behaviors[task] = (sleep, exit_code, hàm_side_effect)."""
    async def fake(agent, task, cwd, ctx, chains, enabled, **kw):
        sleep, code, side = behaviors.get(task, (0.05, 0, None))
        o.note_agent_attempt(agent)
        log.append(("start", task, time.monotonic()))
        await asyncio.sleep(sleep)
        if side:
            side(cwd)
        log.append(("end", task, time.monotonic()))
        if code == 0:
            o.RUN_LOG[ctx["task_id"]]["final_agent"] = agent
        return code
    return fake


def _run(tmp_path, monkeypatch, tasks_dict, meta, behaviors):
    monkeypatch.chdir(tmp_path)
    o.PLAN_META.update(meta)
    log: list = []
    monkeypatch.setattr(c, "execute_task_with_fallback_chain", _fake_executor(log, behaviors))
    asyncio.run(c.dispatch(tasks_dict, CHAINS, AGENTS))
    t = {}
    for kind, task, ts in log:
        t[(kind, task)] = ts
    return t


def test_orc05_dependency_order_and_parallelism(tmp_path, monkeypatch, capsys):
    """ORC-05: worker test chờ worker sửa code xong; task độc lập chạy song song với worker sửa code."""
    t = _run(
        tmp_path, monkeypatch,
        {"claude_tasks": ["Sửa mã A"], "antigravity_tasks": ["Test A"], "codex_tasks": ["Việc độc lập"]},
        {"Test A": {"role": "test", "depends_on": ["Sửa mã A"]}},
        {"Sửa mã A": (0.4, 0, None), "Test A": (0.1, 0, None), "Việc độc lập": (0.1, 0, None)},
    )
    assert t[("start", "Test A")] >= t[("end", "Sửa mã A")]          # chờ xong mới chạy
    assert t[("start", "Việc độc lập")] < t[("end", "Sửa mã A")]      # chạy song song
    assert t[("start", "Sửa mã A")] < t[("end", "Sửa mã A")]
    out = capsys.readouterr().out
    assert "Số worker đã sử dụng: 3" in out
    reports = [p for p in os.listdir(tmp_path / ".ai_router_reports") if p.endswith("_SUMMARY.md")]
    assert len(reports) == 1


def test_orc06_blocked_when_dependency_fails(tmp_path, monkeypatch):
    """ORC-06: dependency thất bại -> task phụ thuộc BLOCKED, không được chạy."""
    t = _run(
        tmp_path, monkeypatch,
        {"claude_tasks": ["Sửa mã"], "antigravity_tasks": ["Kiểm thử"]},
        {"Kiểm thử": {"role": "test", "depends_on": ["Sửa mã"]}},
        {"Sửa mã": (0.05, 3, None)},
    )
    assert ("start", "Kiểm thử") not in t
    assert [r["status"] for r in o.RUN_LOG.values() if r["task"] == "Kiểm thử"] == ["BLOCKED"]


def test_orc07_test_role_modifying_source_is_violation(tmp_path, monkeypatch):
    """ORC-07: worker role=test sửa/xóa/tạo mã nguồn -> VIOLATION; chỉ sửa tests/ -> OK."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()

    def tamper(cwd):
        (tmp_path / "src" / "app.py").write_text("x = 2\n")
        (tmp_path / "src" / "new.py").write_text("y")

    def good(cwd):
        (tmp_path / "tests" / "test_app.py").write_text("def test_x(): pass\n")

    _run(tmp_path, monkeypatch, {"claude_tasks": ["Test bẩn"], "codex_tasks": ["Test sạch"]},
         {"Test bẩn": {"role": "test", "depends_on": []}, "Test sạch": {"role": "test", "depends_on": []}},
         {"Test bẩn": (0.05, 0, tamper), "Test sạch": (0.2, 0, good)})
    by_task = {r["task"]: r for r in o.RUN_LOG.values()}
    assert by_task["Test bẩn"]["status"] == "VIOLATION"
    assert set(by_task["Test bẩn"]["violations"]) >= {"src/app.py", "src/new.py"} or "src/app.py" in by_task["Test bẩn"]["violations"]
    # Test sạch chạy song song với Test bẩn nên có thể bị ghi nhận chung thay đổi của Test bẩn; ít nhất không được tự gây vi phạm tests/
    assert not any(p.startswith("tests/") for p in by_task["Test sạch"]["violations"])


def test_orc08_dependency_on_disabled_or_unknown_task_does_not_deadlock(tmp_path, monkeypatch):
    """ORC-08: phụ thuộc vào task không tồn tại bị bỏ qua, không treo."""
    t = _run(tmp_path, monkeypatch, {"claude_tasks": ["Chỉ mình tôi"]},
             {"Chỉ mình tôi": {"role": "implement", "depends_on": ["không tồn tại"]}}, {})
    assert ("end", "Chỉ mình tôi") in t


def test_orc09_summary_content(tmp_path, monkeypatch):
    """ORC-09: báo cáo có số worker, vai trò, phụ thuộc và vi phạm."""
    _run(tmp_path, monkeypatch,
         {"claude_tasks": ["Sửa mã A"], "antigravity_tasks": ["Test A"]},
         {"Test A": {"role": "test", "depends_on": ["Sửa mã A"]}}, {})
    path = [p for p in os.listdir(tmp_path / ".ai_router_reports") if p.endswith("_SUMMARY.md")][0]
    text = (tmp_path / ".ai_router_reports" / path).read_text()
    assert "Số worker đã sử dụng: 2" in text
    assert "kiểm thử (không sửa mã nguồn)" in text and "triển khai" in text
    assert "#1" in text and "OK" in text
    assert oct(os.stat(tmp_path / ".ai_router_reports" / path).st_mode & 0o777) == "0o600"


def test_orc10_unique_task_ids_same_second():
    """ORC-10: hai sub-task cùng tiền tố/cùng giây có task_id khác nhau nhờ seq."""
    a = c.build_task_context("Viết test cho module X", ".", seq=1)
    b = c.build_task_context("Viết test cho module X", ".", seq=2)
    assert a["task_id"] != b["task_id"] and a["report_path"] != b["report_path"]


def test_orc11_prompt_contains_role_and_deps():
    """ORC-11: prompt worker test chứa ràng buộc 'không sửa mã nguồn' và danh sách việc đã xong; implement thì không."""
    ctx = {"report_path": "r", "task_id": "i", "question_path": "q", "role": "test", "dep_tasks": ["Sửa mã A"]}
    p = c.build_base_prompt("Test A", ".", ctx)
    assert "KHÔNG sửa mã nguồn" in p and "Sửa mã A" in p
    ctx2 = dict(ctx, role="implement", dep_tasks=[])
    assert "VAI TRÒ: KIỂM THỬ" not in c.build_base_prompt("Sửa", ".", ctx2)
    assert "NEVER modify" in o.role_directive_text("test", "en")


def test_orc12_confine_cmd_readonly_workspace_for_test_role(tmp_path, monkeypatch):
    """ORC-12: role=test -> workspace ro-bind, tests/ bind ghi được; implement -> workspace bind ghi được."""
    monkeypatch.setattr(c, "SETTINGS_DATA", {"antigravity": {"permission_mode": "bwrap"}})
    monkeypatch.setattr(c, "agy_permission_mode", lambda: "bwrap")
    ws = str(tmp_path)
    tok = o.CURRENT_ROLE.set("test")
    try:
        cmd = c.confine_agy_cmd(["agy"], ws, {"HOME": str(tmp_path / "h")})
    finally:
        o.CURRENT_ROLE.reset(tok)
    i = cmd.index("--ro-bind", cmd.index("--tmpfs"))
    pairs = [(cmd[k], cmd[k + 1], cmd[k + 2]) for k in range(len(cmd) - 2) if cmd[k] in ("--ro-bind", "--bind")]
    assert ("--ro-bind", ws, ws) in pairs and ("--bind", os.path.join(ws, "tests"), os.path.join(ws, "tests")) in pairs
    assert ("--bind", ws, ws) not in pairs
    cmd2 = c.confine_agy_cmd(["agy"], ws, {"HOME": str(tmp_path / "h")})
    pairs2 = [(cmd2[k], cmd2[k + 1], cmd2[k + 2]) for k in range(len(cmd2) - 2) if cmd2[k] in ("--ro-bind", "--bind")]
    assert ("--bind", ws, ws) in pairs2
