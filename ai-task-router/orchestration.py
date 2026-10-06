#!/usr/bin/env python3
"""
Điều phối nhiều worker có phụ thuộc + vai trò + báo cáo tổng kết cho AI Task Router.

- Vai trò "implement": được sửa mã nguồn. Vai trò "test": chỉ viết/chạy test, KHÔNG sửa mã nguồn.
- depends_on: sub-task chờ các sub-task khác xong rồi mới chạy; sub-task độc lập chạy song song.
- Thực thi vai trò test: (1) lời nhắc, (2) bwrap ro-bind workspace trừ thư mục test (với worker Antigravity),
  (3) so sánh ảnh chụp file trước/sau - agent-agnostic - để phát hiện sửa mã nguồn.
- Báo cáo tổng kết: số worker đã dùng, công việc từng worker, thứ tự điều phối, vi phạm.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime

ROLES = ("implement", "test")
TEST_WRITABLE_DIRS = ("tests", "test", "__tests__", "spec", ".ai_router_reports")
_TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[A-Za-z]+|conftest\.py)$")
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", ".ai_router_reports"}
MAX_HASH_BYTES = 2 * 1024 * 1024

CURRENT_TASK_ID: contextvars.ContextVar = contextvars.ContextVar("router_task_id", default=None)
CURRENT_ROLE: contextvars.ContextVar = contextvars.ContextVar("router_role", default="implement")

# task_text -> {"role": str, "depends_on": [task_text, ...]}  (do planner AI cung cấp)
PLAN_META: dict[str, dict] = {}
# task_id -> bản ghi chạy
RUN_LOG: dict[str, dict] = {}


# ---------------------------------------------------------------- planner meta
def _last_plan_obj(output: str):
    decoder = json.JSONDecoder()
    found = None
    for m in re.finditer(r"\{", output):
        try:
            obj, _ = decoder.raw_decode(output[m.start():])
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("subtasks"), list):
            found = obj
    return found


def _has_cycle(deps: dict[int, list[int]]) -> bool:
    state: dict[int, int] = {}

    def visit(n: int) -> bool:
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(visit(d) for d in deps.get(n, [])):
            return True
        state[n] = 2
        return False

    return any(visit(n) for n in deps)


def parse_planner_meta(output: str) -> dict[str, dict]:
    """Rút role/depends_on từ JSON CUỐI của planner. Dữ liệu sai -> bỏ qua (mặc định implement, không phụ thuộc)."""
    obj = _last_plan_obj(output)
    if not obj:
        return {}
    items = obj["subtasks"]
    texts: list[str | None] = []
    for it in items:
        t = it.get("task") if isinstance(it, dict) else None
        texts.append(t.strip() if isinstance(t, str) and t.strip() else None)
    deps_idx: dict[int, list[int]] = {}
    roles: dict[int, str] = {}
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        role = str(it.get("role", "implement")).lower()
        roles[i] = role if role in ROLES else "implement"
        raw = it.get("depends_on", [])
        ds = [d for d in raw if isinstance(d, int) and not isinstance(d, bool) and 0 <= d < len(items) and d != i] \
            if isinstance(raw, list) else []
        deps_idx[i] = sorted(set(ds))
    if _has_cycle(deps_idx):
        print("[Router CẢNH BÁO] Planner trả phụ thuộc vòng -> bỏ qua toàn bộ depends_on.")
        deps_idx = {i: [] for i in deps_idx}
    meta: dict[str, dict] = {}
    for i, t in enumerate(texts):
        if t is None or i not in roles:
            continue
        meta[t] = {"role": roles[i], "depends_on": [texts[d] for d in deps_idx[i] if texts[d]]}
    return meta


# ---------------------------------------------------------------- role enforcement
def role_directive_text(role: str, lang: str = "vi") -> str:
    if role != "test":
        return ""
    if lang == "vi":
        return (
            "\n\n--- VAI TRÒ: KIỂM THỬ (BẮT BUỘC) ---\n"
            "- Bạn CHỈ viết test và chạy kiểm thử. TUYỆT ĐỐI KHÔNG sửa mã nguồn của dự án (kể cả để 'cho test qua').\n"
            "- Chỉ được tạo/sửa file trong các thư mục test (tests/, test/, __tests__/, spec/) hoặc file test_*.py, *_test.*, *.test.*, *.spec.*.\n"
            "- Nếu test lộ lỗi trong mã nguồn: KHÔNG tự sửa. Ghi rõ lỗi (file, hàm, input, kết quả thực tế/mong đợi) vào báo cáo bàn giao để worker phụ trách sửa.\n"
            "- Hệ thống sẽ kiểm tra lại sau khi bạn xong; sửa mã nguồn bị coi là vi phạm và task bị đánh dấu thất bại.\n"
        )
    return (
        "\n\n--- ROLE: TESTER (MANDATORY) ---\n"
        "- You ONLY write and run tests. NEVER modify the project's source code (not even to make tests pass).\n"
        "- You may only create/edit files in test directories (tests/, test/, __tests__/, spec/) or files named test_*.py, *_test.*, *.test.*, *.spec.*.\n"
        "- If tests expose a source bug: do NOT fix it. Describe it (file, function, input, actual vs expected) in the handoff report.\n"
        "- The system re-checks after you finish; modifying source code counts as a violation and fails the task.\n"
    )


def deps_context_text(dep_tasks: list[str], lang: str = "vi") -> str:
    if not dep_tasks:
        return ""
    listing = "\n".join(f"- {t}" for t in dep_tasks)
    if lang == "vi":
        return ("\n\n--- CÔNG VIỆC ĐÃ HOÀN TẤT TRƯỚC BẠN ---\n" + listing +
                "\nĐọc báo cáo bàn giao của các sub-task trên trong .ai_router_reports/ và `git diff` để biết phần đã thay đổi.\n")
    return ("\n\n--- WORK COMPLETED BEFORE YOU ---\n" + listing +
            "\nRead those sub-tasks' handoff reports in .ai_router_reports/ and `git diff` to see what changed.\n")


def is_test_path(rel: str) -> bool:
    rel = rel.replace(os.sep, "/")
    return rel.split("/")[0] in TEST_WRITABLE_DIRS or bool(_TEST_FILE_RE.search(rel))


def _list_files(cwd: str) -> list[str]:
    try:
        r = subprocess.run(["git", "-C", cwd, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                           capture_output=True, timeout=60)
        if r.returncode == 0:
            return [p for p in r.stdout.decode("utf-8", errors="replace").split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        out += [os.path.relpath(os.path.join(root, f), cwd) for f in files]
    return out


def snapshot_source(cwd: str) -> dict[str, str]:
    """Ảnh chụp các file KHÔNG phải test (path -> dấu vân tay) để phát hiện worker test sửa mã nguồn."""
    snap: dict[str, str] = {}
    for rel in _list_files(cwd):
        if is_test_path(rel) or rel.split("/")[0] in _SKIP_DIRS:
            continue
        p = os.path.join(cwd, rel)
        try:
            st = os.lstat(p)
            if os.path.islink(p) or st.st_size > MAX_HASH_BYTES:
                snap[rel] = f"{st.st_size}:{st.st_mtime_ns}"
            else:
                with open(p, "rb") as f:
                    snap[rel] = hashlib.sha1(f.read()).hexdigest()
        except OSError:
            snap[rel] = "unreadable"
    return snap


def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


# ---------------------------------------------------------------- run log
def new_record(task_id: str, task: str, role: str, deps: list[str], planned_agent: str) -> dict:
    rec = {"task_id": task_id, "task": task, "role": role, "depends_on": deps, "planned_agent": planned_agent,
           "agents_tried": [], "agy_worker": None, "status": "PENDING", "exit_code": None,
           "started": None, "ended": None, "violations": [], "final_agent": None}
    RUN_LOG[task_id] = rec
    return rec


def note_agent_attempt(agent: str) -> None:
    rec = RUN_LOG.get(CURRENT_TASK_ID.get())
    if rec is not None:
        rec["agents_tried"].append(agent)


def note_agy_worker(label: str) -> None:
    rec = RUN_LOG.get(CURRENT_TASK_ID.get())
    if rec is not None:
        rec["agy_worker"] = label


def worker_label(rec: dict, agent: str) -> str:
    if agent == "antigravity" and rec.get("agy_worker"):
        return f"antigravity ({rec['agy_worker']})"
    return agent


# ---------------------------------------------------------------- summary report
def _fmt(ts) -> str:
    return ts.strftime("%H:%M:%S") if ts else "-"


def build_summary(records: list[dict], started: datetime, ended: datetime, lang: str = "vi") -> str:
    vi = lang == "vi"
    ran = [r for r in records if r["agents_tried"]]
    workers: dict[str, list[dict]] = {}
    for r in ran:
        for a in dict.fromkeys(r["agents_tried"]):
            workers.setdefault(worker_label(r, a), []).append(r)
    has_deps = any(r["depends_on"] for r in records)
    L = []
    L.append(f"# {'Báo cáo điều phối worker' if vi else 'Worker orchestration report'}")
    L.append("")
    L.append(f"- {'Bắt đầu' if vi else 'Started'}: {started:%Y-%m-%d %H:%M:%S}; "
             f"{'thời lượng' if vi else 'duration'}: {(ended - started).total_seconds():.0f}s")
    L.append(f"- **{'Số worker đã sử dụng' if vi else 'Workers used'}: {len(workers)}** ({', '.join(workers) or '-'})")
    L.append(f"- {'Số sub-task' if vi else 'Sub-tasks'}: {len(records)}; "
             f"{'chế độ' if vi else 'mode'}: "
             f"{('song song + phụ thuộc (tuần tự theo depends_on)' if has_deps else 'song song hoàn toàn') if vi else ('parallel + dependencies' if has_deps else 'fully parallel')}")
    L.append("")
    L.append(f"## {'Công việc của từng worker' if vi else 'Work per worker'}")
    L.append("")
    L.append("| Worker | " + ("Vai trò | Sub-task | Phụ thuộc | Kết quả | Thời gian" if vi else "Role | Sub-task | Depends on | Result | Time"))
    L.append("|---|---|---|---|---|---|")
    idx = {r["task"]: i + 1 for i, r in enumerate(records)}
    for r in records:
        used = [worker_label(r, a) for a in dict.fromkeys(r["agents_tried"])] or ["-"]
        final = worker_label(r, r["final_agent"]) if r["final_agent"] else used[-1]
        deps = ", ".join(f"#{idx[d]}" for d in r["depends_on"] if d in idx) or "-"
        role = ("kiểm thử (không sửa mã nguồn)" if vi else "tester (no source edits)") if r["role"] == "test" \
            else ("triển khai" if vi else "implement")
        note = "" if len(used) == 1 else (" (fallback: " + " → ".join(used) + ")" if vi else " (fallback: " + " → ".join(used) + ")")
        task = r["task"].replace("|", "\\|").replace("\n", " ")
        L.append(f"| {final}{note} | {role} | #{idx[r['task']]} {task[:140]} | {deps} | {r['status']} | {_fmt(r['started'])}–{_fmt(r['ended'])} |")
    L.append("")
    L.append(f"## {'Thứ tự điều phối' if vi else 'Orchestration timeline'}")
    L.append("")
    for r in sorted(records, key=lambda x: (x["started"] is None, x["started"])):
        wait = ""
        if r["depends_on"]:
            wait = (" — chờ " if vi else " — waited for ") + ", ".join(f"#{idx[d]}" for d in r["depends_on"] if d in idx)
        L.append(f"- {_fmt(r['started'])} → {_fmt(r['ended'])}  #{idx[r['task']]} [{r['status']}]{wait}")
    viol = [r for r in records if r["violations"]]
    if viol:
        L.append("")
        L.append(f"## {'Vi phạm vai trò' if vi else 'Role violations'}")
        for r in viol:
            L.append(f"- #{idx[r['task']]}: " + ", ".join(f"`{p}`" for p in r["violations"][:30]))
        L.append("")
        L.append("Kiểm tra bằng `git diff` và hoàn tác nếu không mong muốn (`git checkout -- <file>`)." if vi
                 else "Review with `git diff` and revert if unwanted (`git checkout -- <file>`).")
    L.append("")
    return "\n".join(L)


def write_summary(cwd: str, run_id: str, records: list[dict], started: datetime, ended: datetime, lang: str = "vi") -> str:
    text = build_summary(records, started, ended, lang)
    d = os.path.join(cwd, ".ai_router_reports")
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, f"{run_id}_SUMMARY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
