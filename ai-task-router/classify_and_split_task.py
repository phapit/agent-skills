#!/usr/bin/env python3
"""
AI Task Router:
Phân loại một yêu cầu nghiệp vụ thành các sub-task và điều phối tới đúng AI Coding Agent CLI:
  - Antigravity (`agy`): Frontend/UI + thao tác đơn giản (scan path, read file, check/restart service, sửa lỗi giao diện nhỏ).
  - Codex (`codex`): Code generation tốc độ cao, viết unit tests, migration script, boilerplate, thuật toán, refactor hàm.
  - Claude Code (`claude`): Suy luận nghiệp vụ, phân tích kiến trúc, tài liệu bàn giao, thiết kế DB, backend phức tạp.

Cơ chế Fallback thông minh & có thể tùy biến:
  - Thứ tự fallback được cấu hình qua `.agents/settings.json` trong mục `fallback_chains`.
  - Mặc định:
      + Antigravity lỗi/hết quota -> fallback sang Claude Code.
      + Codex lỗi -> fallback sang Claude Code.
      + Claude Code lỗi -> dừng (không fallback).
  - Người dùng có thể tùy biến thứ tự bất kỳ (ví dụ: antigravity -> codex -> claude, hoặc claude -> codex).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import uuid
from datetime import datetime

ANTIGRAVITY_CMD = "agy"
CLAUDE_CMD = "claude"
CODEX_CMD = "codex"

GLOBAL_AGENTS_DIR = os.path.expanduser("~/.agents")
REPO_AGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agents")


def resolve_agents_file(relative_path: str) -> str | None:
    for base in (GLOBAL_AGENTS_DIR, REPO_AGENTS_DIR):
        candidate = os.path.join(base, relative_path)
        if os.path.isfile(candidate):
            return candidate
    return None


SETTINGS_PATH = resolve_agents_file("settings.json")
CONTEXT_RULES_PATH = resolve_agents_file(os.path.join("rules", "context-management.md"))

_DEFAULT_CLAUDE_CONTEXT_LIMIT = 300_000
_DEFAULT_AGY_CONTEXT_LIMIT = 600_000
_DEFAULT_CODEX_CONTEXT_LIMIT = 200_000

DEFAULT_FALLBACK_CHAINS = {
    "antigravity": ["claude"],
    "codex": ["claude"],
    "claude": [],
}


def load_settings_data() -> dict:
    if not SETTINGS_PATH:
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[Router] Cảnh báo: không đọc được {SETTINGS_PATH} ({e}).")
        return {}


SETTINGS_DATA = load_settings_data()


def load_context_token_limits() -> tuple[int, int, int]:
    ctx = SETTINGS_DATA.get("context", {})
    return (
        int(ctx.get("claude_max_token_threshold", _DEFAULT_CLAUDE_CONTEXT_LIMIT)),
        int(ctx.get("agy_max_token_threshold", _DEFAULT_AGY_CONTEXT_LIMIT)),
        int(ctx.get("codex_max_token_threshold", _DEFAULT_CODEX_CONTEXT_LIMIT)),
    )


CLAUDE_CONTEXT_TOKEN_LIMIT, AGY_CONTEXT_TOKEN_LIMIT, CODEX_CONTEXT_TOKEN_LIMIT = load_context_token_limits()


def load_fallback_chains() -> dict[str, list[str]]:
    """
    Đọc thứ tự fallback từ settings.json:
    "fallback_chains": {
        "antigravity": ["claude"],
        "codex": ["claude"],
        "claude": []
    }
    """
    raw_chains = SETTINGS_DATA.get("fallback_chains", {})
    chains = {k: list(v) for k, v in DEFAULT_FALLBACK_CHAINS.items()}

    for agent, targets in raw_chains.items():
        agent_key = agent.strip().lower()
        if isinstance(targets, list):
            chains[agent_key] = [str(t).strip().lower() for t in targets if str(t).strip().lower() not in ("none", "null", "")]
        elif isinstance(targets, str):
            t_str = targets.strip().lower()
            chains[agent_key] = [] if t_str in ("none", "null", "", "stop") else [t_str]

    return chains


FALLBACK_CHAINS = load_fallback_chains()


def parse_fallback_cli_arg(arg_val: str) -> dict[str, list[str]]:
    """Cho phép override fallback qua CLI, ví dụ: 'antigravity:claude,codex:claude,claude:none'"""
    res = dict(FALLBACK_CHAINS)
    for pair in arg_val.split(","):
        if ":" in pair or "=" in pair:
            delimiter = ":" if ":" in pair else "="
            k, v = pair.split(delimiter, 1)
            k = k.strip().lower()
            v_list = [x.strip().lower() for x in v.split("->") if x.strip().lower() not in ("none", "stop", "")]
            res[k] = v_list
    return res


def load_context_rules_text() -> str:
    if not CONTEXT_RULES_PATH:
        return ""
    try:
        with open(CONTEXT_RULES_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


CONTEXT_RULES_TEXT = load_context_rules_text()


def context_rules_directive() -> str:
    if not CONTEXT_RULES_TEXT:
        return ""
    return (
        "\n\n--- QUY TẮC QUẢN LÝ CONTEXT (BẮT BUỘC TUÂN THỦ) ---\n"
        f"{CONTEXT_RULES_TEXT}\n"
    )


def claude_system_prompt_args() -> list[str]:
    if CONTEXT_RULES_PATH:
        return ["--append-system-prompt-file", CONTEXT_RULES_PATH]
    return []


REPORTS_DIR_NAME = ".ai_router_reports"

ANTIGRAVITY_KEYWORDS = [
    "frontend", "giao diện", "ui", "react", "vue", "css", "html", "tailwind",
    "scan", "quét", "đọc file", "read file", "cd ", "check service",
    "kiểm tra service", "trạng thái service", "restart service",
    "sửa đơn giản", "fix nhỏ", "sửa lỗi nhỏ", "style", "nút", "button",
]

CODEX_KEYWORDS = [
    "unit test", "unittest", "viết test", "sinh test", "test case", "pytest",
    "jest", "sinh mã", "generate code", "code gen", "boilerplate", "migration",
    "database migration", "script chuyển đổi", "convert script", "thuật toán",
    "algorithm", "refactor hàm", "hàm xử lý", "tối ưu hàm",
]

CLAUDE_KEYWORDS = [
    "phân tích yêu cầu", "nghiệp vụ", "tài liệu bàn giao", "handoff",
    "phân chia task", "break down", "kiến trúc", "architecture",
    "backend phức tạp", "thiết kế hệ thống", "database schema",
    "business logic", "api", "authentication", "jwt", "bảo mật",
]

READONLY_KEYWORDS = [
    "scan", "quét", "đọc file", "read file", "cd ", "check service",
    "kiểm tra service", "trạng thái service",
]


def classify_and_split_task(user_prompt: str) -> dict:
    clauses = [c.strip() for c in re.split(r"[.;\n]| và | and ", user_prompt) if c.strip()]

    antigravity_tasks: list[str] = []
    codex_tasks: list[str] = []
    claude_tasks: list[str] = []

    for clause in clauses:
        lower = clause.lower()
        is_antigravity = any(k in lower for k in ANTIGRAVITY_KEYWORDS)
        is_codex = any(k in lower for k in CODEX_KEYWORDS)
        is_claude = any(k in lower for k in CLAUDE_KEYWORDS)

        if is_antigravity and not is_claude and not is_codex:
            antigravity_tasks.append(clause)
        elif is_codex and not is_claude:
            codex_tasks.append(clause)
        else:
            claude_tasks.append(clause)

    return {
        "antigravity_tasks": antigravity_tasks,
        "codex_tasks": codex_tasks,
        "claude_tasks": claude_tasks,
    }


def task_requires_report(task: str, is_readonly: bool) -> bool:
    if is_readonly:
        return False
    lower = task.lower()
    return not any(k in lower for k in READONLY_KEYWORDS)


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "task"


def reports_dir(cwd: str) -> str:
    path = os.path.join(cwd, REPORTS_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def existing_reports_context(cwd: str) -> str:
    files = sorted(f for f in os.listdir(reports_dir(cwd)) if f.endswith(".md"))
    if not files:
        return ""
    listing = "\n".join(f"- {f}" for f in files[-10:])
    return (
        "\n\n--- BỐI CẢNH TỪ CÁC AGENT KHÁC ---\n"
        f"Các báo cáo bàn giao đã có trong thư mục {REPORTS_DIR_NAME}/ "
        f"(đọc file liên quan trước khi làm để tránh trùng lặp/mâu thuẫn):\n"
        f"{listing}\n"
    )


def build_task_context(task: str, cwd: str) -> dict:
    task_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{slugify(task)}"
    d = reports_dir(cwd)
    return {
        "task_id": task_id,
        "report_path": os.path.join(d, f"{task_id}.md"),
        "question_path": os.path.join(d, f"{task_id}.question.md"),
    }


def report_directive_text(task: str, report_path: str) -> str:
    return (
        "\n\n--- YÊU CẦU BÀN GIAO (BẮT BUỘC) ---\n"
        "Sau khi hoàn thành (hoặc buộc phải dừng) công việc trên, hãy TẠO một "
        f"file markdown tại đúng đường dẫn: {report_path}\n"
        "Nội dung bắt buộc gồm:\n"
        f"- Tên task: {task}\n"
        "- Agent thực hiện: (ghi rõ tên CLI/Model của bạn)\n"
        "- Trạng thái: Hoàn tất / Chưa hoàn tất (kèm lý do nếu chưa xong)\n"
        "- Đã thực hiện đúng theo spec: chi tiết phần đã làm\n"
        "- Tự thêm ngoài spec: phần chủ động bổ sung (nếu có)\n"
        "- Lưu ý khác: điểm cần chú ý khi review (rủi ro, giả định, test case)\n"
    )


def confirmation_directive_text(question_path: str) -> str:
    return (
        "\n\n--- XÁC NHẬN VỚI NGƯỜI DÙNG (NẾU CẦN) ---\n"
        "Nếu có nhiều phương án hợp lý và cần người dùng chọn trước khi tiếp tục, "
        f"hãy dừng lại, ghi rõ câu hỏi và các phương án vào file: {question_path}\n"
        "rồi kết thúc lượt làm việc này. Router sẽ hỏi người dùng và gọi lại đúng phiên với câu trả lời.\n"
    )


TASK_DONE_MARKER = "Đã hoàn tất task."


def task_done_marker(task_id: str) -> str:
    return f"{TASK_DONE_MARKER} [id:{task_id}]"


def completion_directive_text(task_id: str) -> str:
    marker = task_done_marker(task_id)
    return (
        "\n\n--- KẾT THÚC (BẮT BUỘC) ---\n"
        "Sau khi hoàn tất công việc và ghi xong báo cáo bàn giao (nếu có yêu cầu), "
        f"dòng CUỐI CÙNG trong phản hồi của bạn phải là đúng cụm từ sau: {marker}\n"
    )


def build_base_prompt(task: str, cwd: str, ctx: dict, is_readonly: bool = False) -> str:
    prompt = task + existing_reports_context(cwd)
    if task_requires_report(task, is_readonly):
        prompt += report_directive_text(task, ctx["report_path"])
    prompt += completion_directive_text(ctx["task_id"])
    return prompt


async def run_capture(cmd_args: list[str]) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, ""
    stdout, _ = await process.communicate()
    return process.returncode, stdout.decode("utf-8", errors="replace")


def parse_agy_quota(output: str) -> dict | None:
    match = re.search(
        r"Gemini Models\s+Five Hour Limit Remaining\s+(\d+)%\s+(\S+)", output
    )
    if not match:
        return None
    return {"remaining_percent": int(match.group(1)), "reset_at": match.group(2)}


def parse_claude_quota(output: str) -> dict | None:
    match = re.search(
        r"Current session:\s*(\d+)%\s*used\s*·\s*resets\s*(.+)", output
    )
    if not match:
        return None
    return {"used_percent": int(match.group(1)), "resets": match.group(2).strip()}


async def check_agy_quota() -> dict | None:
    _, output = await run_capture([ANTIGRAVITY_CMD, "-p", "/usage"])
    return parse_agy_quota(output)


async def check_claude_quota() -> dict | None:
    _, output = await run_capture([CLAUDE_CMD, "-p", "/usage"])
    return parse_claude_quota(output)


async def check_codex_status() -> dict | None:
    code, output = await run_capture([CODEX_CMD, "--version"])
    if code == 0:
        return {"version": output.strip(), "status": "Ready"}
    return None


async def print_quota_status(cwd: str) -> None:
    agy_quota, claude_quota, codex_status = await asyncio.gather(
        check_agy_quota(), check_claude_quota(), check_codex_status()
    )

    print("\n" + "=" * 55)
    print("AI ROUTER - TRẠNG THÁI QUOTA & MODEL CLI")
    print("=" * 55)

    print("[1] Antigravity (Gemini, Five Hour Limit):")
    if agy_quota:
        print(f"    Còn lại {agy_quota['remaining_percent']}% - reset lúc {agy_quota['reset_at']}")
    else:
        print("    Không đọc được / CLI 'agy' chưa sẵn sàng.")

    print("[2] Claude Code (Current session):")
    if claude_quota:
        print(f"    Đã dùng {claude_quota['used_percent']}% - reset lúc {claude_quota['resets']}")
    else:
        print("    Không đọc được / CLI 'claude' chưa sẵn sàng.")

    print("[3] Codex CLI:")
    if codex_status:
        print(f"    {codex_status['version']} - Sẵn sàng ({codex_status['status']})")
    else:
        print("    Không tìm thấy lệnh 'codex' trên PATH.")

    print("-" * 55)
    print("CẤU HÌNH THỨ TỰ FALLBACK HIỆN TẠI:")
    for src, targets in FALLBACK_CHAINS.items():
        chain_str = " -> ".join(targets) if targets else "(Dừng / Không fallback)"
        print(f"  • {src.upper()}: fallback -> {chain_str}")
    print("=" * 55 + "\n")


async def run_agent(agent_name: str, cmd_args: list[str]) -> int:
    print(f"[{agent_name}] Bắt đầu: {' '.join(shlex.quote(a) for a in cmd_args)}")
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        print(f"[{agent_name} ERROR] Không tìm thấy lệnh '{cmd_args[0]}' trên PATH.")
        return 127

    async def stream_output(stream, prefix):
        while True:
            line = await stream.readline()
            if not line:
                break
            print(f"[{prefix}] {line.decode('utf-8', errors='replace').rstrip()}")

    await asyncio.gather(
        stream_output(process.stdout, agent_name),
        stream_output(process.stderr, f"{agent_name} ERROR"),
    )
    await process.wait()
    print(f"[{agent_name}] Hoàn thành, exit code: {process.returncode}")
    return process.returncode


CONFIRMATION_LOCK = asyncio.Lock()


async def ask_user(question_text: str) -> str:
    async with CONFIRMATION_LOCK:
        print("\n" + "=" * 50)
        print(f"[Router] Cần xác nhận trước khi agent tiếp tục:\n{question_text}")
        print("=" * 50)
        return await asyncio.get_event_loop().run_in_executor(
            None, input, "[Router] Nhập câu trả lời rồi Enter: "
        )


async def run_claude_agent(prompt: str, question_path: str) -> int:
    session_id = str(uuid.uuid4())
    extra_args = ["--autocompact", str(CLAUDE_CONTEXT_TOKEN_LIMIT), *claude_system_prompt_args()]
    cmd_args = [CLAUDE_CMD, "--session-id", session_id, *extra_args, "-p", prompt]

    while True:
        exit_code = await run_agent("Claude Code", cmd_args)
        if not os.path.exists(question_path):
            return exit_code

        with open(question_path, "r", encoding="utf-8") as f:
            question_text = f.read()
        os.remove(question_path)

        answer = await ask_user(question_text)
        cmd_args = [CLAUDE_CMD, "--resume", session_id, *extra_args, "-p", answer]


async def run_codex_agent(prompt: str, question_path: str, cwd: str) -> int:
    full_prompt = prompt + context_rules_directive()
    cmd_args = [
        CODEX_CMD, "exec",
        "-C", cwd,
        "-s", "workspace-write",
        full_prompt,
    ]

    exit_code = await run_agent("Codex", cmd_args)

    if os.path.exists(question_path):
        with open(question_path, "r", encoding="utf-8") as f:
            question_text = f.read()
        os.remove(question_path)
        answer = await ask_user(question_text)
        resume_prompt = f"Tiếp tục thực hiện với câu trả lời từ người dùng: {answer}\n" + full_prompt
        cmd_args = [CODEX_CMD, "exec", "-C", cwd, "-s", "workspace-write", resume_prompt]
        exit_code = await run_agent("Codex", cmd_args)

    return exit_code


TMUX_CMD = "tmux"
AGY_SESSION_PREFIX = "ai_router_agy"
AGY_USAGE_FALLBACK_THRESHOLD = 90
AGY_SESSION_READY_TIMEOUT = 30.0
AGY_TASK_TIMEOUT = 1800.0
AGY_POLL_INTERVAL = 2.0


def agy_session_name(cwd: str) -> str:
    return f"{AGY_SESSION_PREFIX}_{slugify(os.path.basename(os.path.abspath(cwd)))}"


async def tmux_run(*args: str) -> tuple[int, str]:
    return await run_capture([TMUX_CMD, *args])


async def tmux_session_exists(session: str) -> bool:
    code, _ = await tmux_run("has-session", "-t", session)
    return code == 0


async def tmux_capture(session: str) -> str:
    code, out = await tmux_run("capture-pane", "-t", session, "-p", "-J")
    return out if code == 0 else ""


async def tmux_send_task(session: str, prompt: str) -> None:
    single_line = " ".join(prompt.split("\n"))
    await tmux_run("send-keys", "-t", session, "-l", single_line)
    await tmux_run("send-keys", "-t", session, "Enter")


async def wait_pane_stable(
    session: str, stable_checks: int = 2, interval: float = 1.5,
    timeout: float = AGY_SESSION_READY_TIMEOUT,
) -> None:
    start = asyncio.get_event_loop().time()
    last = None
    stable = 0
    while asyncio.get_event_loop().time() - start < timeout:
        current = await tmux_capture(session)
        if current == last:
            stable += 1
            if stable >= stable_checks:
                return
        else:
            stable = 0
        last = current
        await asyncio.sleep(interval)


async def ensure_agy_session(session: str, cwd: str) -> None:
    if await tmux_session_exists(session):
        return
    code, _ = await tmux_run("new-session", "-d", "-s", session, "-c", cwd, ANTIGRAVITY_CMD)
    if code != 0:
        raise RuntimeError(
            f"Không thể tạo tmux session '{session}' (thiếu tmux hoặc lệnh '{ANTIGRAVITY_CMD}')."
        )
    print(f"[Antigravity-tmux] Đã tạo session '{session}', đợi TUI sẵn sàng...")
    await wait_pane_stable(session)


def parse_token_amount(text: str) -> float | None:
    match = re.match(r"^([\d.]+)\s*([kKmM]?)$", text.strip())
    if not match:
        return None
    amount = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "k":
        amount *= 1_000
    elif suffix == "m":
        amount *= 1_000_000
    return amount


def parse_agy_context_tokens(pane_text: str) -> int | None:
    match = re.search(r"·\s*([\d.]+[kKmM]?)\s*/\s*([\d.]+[kKmM]?)", pane_text)
    if not match:
        return None
    used = parse_token_amount(match.group(1))
    return int(used) if used is not None else None


async def check_and_compact_agy_context(session: str) -> None:
    await tmux_send_task(session, "/context")
    await asyncio.sleep(1.5)
    pane = await tmux_capture(session)
    used_tokens = parse_agy_context_tokens(pane)

    await tmux_run("send-keys", "-t", session, "Escape")
    await asyncio.sleep(0.3)

    if used_tokens is None:
        print(f"[Antigravity-tmux] Không đọc được context usage của session '{session}'.")
        return

    if used_tokens > AGY_CONTEXT_TOKEN_LIMIT:
        print(
            f"[Antigravity-tmux] Session '{session}' đang dùng ~{used_tokens} token "
            f"(> {AGY_CONTEXT_TOKEN_LIMIT}) -> gọi /clear để reset ngữ cảnh."
        )
        await tmux_send_task(session, "/clear")
        await asyncio.sleep(1.0)


async def antigravity_usage_exceeded() -> bool:
    quota = await check_agy_quota()
    if quota is None:
        return False
    used_percent = 100 - quota["remaining_percent"]
    return used_percent > AGY_USAGE_FALLBACK_THRESHOLD


async def run_antigravity_agent(prompt: str, question_path: str, marker: str, cwd: str) -> int:
    if await antigravity_usage_exceeded():
        print(f"[Router] Antigravity usage > {AGY_USAGE_FALLBACK_THRESHOLD}% (cạn quota 5h).")
        return 99

    session = agy_session_name(cwd)
    await ensure_agy_session(session, cwd)
    await check_and_compact_agy_context(session)

    await tmux_send_task(session, prompt)
    await asyncio.sleep(1.5)
    baseline_count = (await tmux_capture(session)).count(marker)

    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < AGY_TASK_TIMEOUT:
        if os.path.exists(question_path):
            with open(question_path, "r", encoding="utf-8") as f:
                question_text = f.read()
            os.remove(question_path)
            answer = await ask_user(question_text)
            await tmux_send_task(session, answer)
            start = asyncio.get_event_loop().time()
            continue

        pane = await tmux_capture(session)
        if pane.count(marker) > baseline_count:
            print(f"[Antigravity-tmux] Phát hiện marker hoàn tất trong session '{session}'.")
            return 0

        await asyncio.sleep(AGY_POLL_INTERVAL)

    print(f"[Antigravity-tmux] Timeout ({AGY_TASK_TIMEOUT}s) trong session '{session}'.")
    return 1


async def execute_task_with_fallback_chain(
    initial_agent: str, task: str, cwd: str, ctx: dict, chains: dict[str, list[str]]
) -> int:
    """
    Thực thi một task theo chuỗi fallback cấu hình:
    initial_agent -> targets[0] -> targets[1] -> ... -> dừng
    """
    # Chuỗi thực thi đầy đủ
    execution_chain = [initial_agent] + chains.get(initial_agent, [])

    base_prompt = build_base_prompt(task, cwd, ctx, is_readonly=False)
    marker = task_done_marker(ctx["task_id"])

    for idx, current_agent in enumerate(execution_chain):
        print(f"\n[Router] [Task: {ctx['task_id']}] -> Đang thực thi bằng '{current_agent.upper()}'...")
        exit_code = 1

        try:
            if current_agent == "antigravity":
                antigravity_prompt = base_prompt + context_rules_directive()
                exit_code = await run_antigravity_agent(
                    antigravity_prompt, ctx["question_path"], marker, cwd
                )
            elif current_agent == "codex":
                codex_prompt = base_prompt + confirmation_directive_text(ctx["question_path"])
                exit_code = await run_codex_agent(codex_prompt, ctx["question_path"], cwd)
            elif current_agent == "claude":
                claude_prompt = base_prompt + confirmation_directive_text(ctx["question_path"])
                exit_code = await run_claude_agent(claude_prompt, ctx["question_path"])
            else:
                print(f"[Router ERROR] Không hỗ trợ agent '{current_agent}'.")
                exit_code = 127
        except Exception as e:
            print(f"[Router ERROR] Ngoại lệ khi chạy {current_agent}: {e}")
            exit_code = 1

        if exit_code == 0:
            print(f"[Router] [Task: {ctx['task_id']}] -> Thành công bởi '{current_agent.upper()}'.")
            return 0

        # Nếu thất bại, kiểm tra agent tiếp theo
        if idx + 1 < len(execution_chain):
            next_agent = execution_chain[idx + 1]
            print(
                f"[Router] '{current_agent.upper()}' thất bại (mã {exit_code}) "
                f"-> Tự động fallback sang: '{next_agent.upper()}'."
            )
        else:
            print(
                f"[Router] '{current_agent.upper()}' thất bại (mã {exit_code}). "
                "Không còn agent fallback nào trong chuỗi -> Dừng task này."
            )

    return exit_code


async def dispatch(tasks_dict: dict, chains: dict[str, list[str]]) -> None:
    cwd = os.getcwd()
    concurrent = []

    for task in tasks_dict.get("antigravity_tasks", []):
        ctx = build_task_context(task, cwd)
        concurrent.append(
            execute_task_with_fallback_chain("antigravity", task, cwd, ctx, chains)
        )

    for task in tasks_dict.get("codex_tasks", []):
        ctx = build_task_context(task, cwd)
        concurrent.append(
            execute_task_with_fallback_chain("codex", task, cwd, ctx, chains)
        )

    for task in tasks_dict.get("claude_tasks", []):
        ctx = build_task_context(task, cwd)
        concurrent.append(
            execute_task_with_fallback_chain("claude", task, cwd, ctx, chains)
        )

    if not concurrent:
        print("[Router] Không có sub-task nào được nhận diện.")
        return

    print("[Router] Bắt đầu chạy song song các Agent...\n" + "-" * 50)
    await asyncio.gather(*concurrent)
    print("-" * 50 + "\n[Router] Tất cả các task đã hoàn tất.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Task Router: Phân loại & điều phối task cho Antigravity / Codex / Claude Code."
    )
    parser.add_argument(
        "prompt", nargs="?", default=None,
        help="Yêu cầu nghiệp vụ gốc cần phân loại và điều phối.",
    )
    parser.add_argument(
        "--check-quota", action="store_true",
        help="Kiểm tra quota/usage và chuỗi fallback của các CLI (agy, claude, codex) rồi thoát.",
    )
    parser.add_argument(
        "--fallback", default=None,
        help="Ghi đè chuỗi fallback qua CLI (ví dụ: 'antigravity:claude,codex:claude,claude:none')",
    )
    args = parser.parse_args()

    chains = FALLBACK_CHAINS
    if args.fallback:
        chains = parse_fallback_cli_arg(args.fallback)

    if args.check_quota:
        asyncio.run(print_quota_status(os.getcwd()))
        return

    if not args.prompt:
        parser.error("Thiếu 'prompt' (bỏ qua chỉ khi dùng --check-quota).")

    tasks_dict = classify_and_split_task(args.prompt)
    print("[Router] Kết quả phân loại:")
    print(json.dumps(tasks_dict, ensure_ascii=False, indent=2))
    print("[Router] Thứ tự fallback áp dụng cho phiên này:")
    for k, v in chains.items():
        chain_label = " -> ".join(v) if v else "(Dừng / Không fallback)"
        print(f"  • {k.upper()} -> {chain_label}")

    asyncio.run(dispatch(tasks_dict, chains))


if __name__ == "__main__":
    main()
