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
import glob
import json
import os
import re
import shlex
import shutil
import sys
import uuid
from datetime import datetime

ANTIGRAVITY_CMD = "agy"
CLAUDE_CMD = "claude"
CODEX_CMD = "codex"

SUPPORTED_AGENTS = ("antigravity", "codex", "claude")

AGENT_ALIASES = {
    "antigravity": "antigravity",
    "agy": "antigravity",
    "gemini": "antigravity",
    "codex": "codex",
    "openai": "codex",
    "claude": "claude",
    "claude-code": "claude",
    "anthropic": "claude",
}


def normalize_agent_name(name: str) -> str:
    cleaned = str(name).strip().lower().replace("_", "-")
    return AGENT_ALIASES.get(cleaned, cleaned)


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

DEFAULT_ENABLED_AGENTS = {
    "antigravity": True,
    "codex": True,
    "claude": True,
}

DEFAULT_FALLBACK_CHAINS = {
    "antigravity": ["claude"],
    "codex": ["claude"],
    "claude": [],
}


def load_settings_data() -> dict:
    data = {}
    for base in (GLOBAL_AGENTS_DIR, REPO_AGENTS_DIR):
        candidate = os.path.join(base, "settings.json")
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except (OSError, ValueError, json.JSONDecodeError) as e:
                print(f"[Router] Cảnh báo: không đọc được {candidate} ({e}).")
    return data


SETTINGS_DATA = load_settings_data()


def load_enabled_agents() -> dict[str, bool]:
    """
    Đọc trạng thái kích hoạt của từng Agent từ settings.json:
    - enabled_agents: {"antigravity": true, "codex": false, "claude": true}
      hoặc list: ["antigravity", "claude"]
    - disabled_agents: ["codex"]
    """
    enabled = dict(DEFAULT_ENABLED_AGENTS)

    raw_enabled = SETTINGS_DATA.get("enabled_agents")
    if isinstance(raw_enabled, dict):
        for k, v in raw_enabled.items():
            norm = normalize_agent_name(k)
            if norm in enabled:
                enabled[norm] = bool(v)
    elif isinstance(raw_enabled, list):
        norm_list = {normalize_agent_name(x) for x in raw_enabled}
        for k in enabled:
            enabled[k] = k in norm_list

    raw_disabled = SETTINGS_DATA.get("disabled_agents")
    if isinstance(raw_disabled, list):
        for k in raw_disabled:
            norm = normalize_agent_name(k)
            if norm in enabled:
                enabled[norm] = False

    raw_agents = SETTINGS_DATA.get("agents")
    if isinstance(raw_agents, dict):
        for k, v in raw_agents.items():
            norm = normalize_agent_name(k)
            if norm in enabled and isinstance(v, dict) and "enabled" in v:
                enabled[norm] = bool(v["enabled"])

    return enabled


ENABLED_AGENTS = load_enabled_agents()


def load_supervisor_config() -> dict:
    raw = SETTINGS_DATA.get("supervisor", {})
    return {
        "enabled": bool(raw.get("enabled", False)),
        "model": normalize_agent_name(raw.get("model", "claude")),
        "profile": str(raw.get("profile", "supervisor")),
        "enable_quality_gate": bool(raw.get("enable_quality_gate", True)),
        "test_command": str(raw.get("test_command", "auto")),
    }


SUPERVISOR_CONFIG = load_supervisor_config()

DEFAULT_PROFILES_BASE = os.path.expanduser("~/.agents/profiles")


def load_antigravity_profiles() -> list[str]:
    raw_agy = SETTINGS_DATA.get("antigravity", {})
    if isinstance(raw_agy, dict) and "profiles" in raw_agy:
        profiles = raw_agy.get("profiles", [])
        if isinstance(profiles, list) and profiles:
            return [str(p).strip() for p in profiles if str(p).strip()]

    raw_profiles = SETTINGS_DATA.get("antigravity_profiles")
    if isinstance(raw_profiles, list) and raw_profiles:
        return [str(p).strip() for p in raw_profiles if str(p).strip()]

    return ["default"]


def get_agy_profile_env(profile_name: str) -> dict[str, str] | None:
    if profile_name in ("default", "", None):
        return None
    norm_name = profile_name
    if not norm_name.startswith("antigravity_"):
        folder_name = f"antigravity_{norm_name}"
    else:
        folder_name = norm_name

    profile_dir = os.path.join(DEFAULT_PROFILES_BASE, folder_name)
    os.makedirs(profile_dir, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = profile_dir
    env["GEMINI_CLI_HOME"] = os.path.join(profile_dir, ".gemini")
    # Cô lập hoàn toàn D-Bus keyring để không đọc/ghi đè token vào OS keyring chung của máy
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/dev/null"

    user_gitconfig = os.path.expanduser("~/.gitconfig")
    profile_gitconfig = os.path.join(profile_dir, ".gitconfig")
    if os.path.isfile(user_gitconfig) and not os.path.exists(profile_gitconfig):
        try:
            os.symlink(user_gitconfig, profile_gitconfig)
        except OSError:
            pass
    return env


def get_agy_profile_email(profile_name: str) -> str | None:
    """
    Trích xuất địa chỉ email đã xác thực gần nhất của profile Antigravity.
    """
    if profile_name in ("default", "", None):
        log_dir = os.path.expanduser("~/.gemini/antigravity-cli/log")
    else:
        norm_name = profile_name if profile_name.startswith("antigravity_") else f"antigravity_{profile_name}"
        log_dir = os.path.join(DEFAULT_PROFILES_BASE, norm_name, ".gemini", "antigravity-cli", "log")

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


def is_agy_profile_ready(profile_name: str) -> bool:
    if profile_name in ("default", "", None):
        return True
    norm_name = profile_name
    if not norm_name.startswith("antigravity_"):
        folder_name = f"antigravity_{norm_name}"
    else:
        folder_name = norm_name

    profile_dir = os.path.join(DEFAULT_PROFILES_BASE, folder_name)
    if not os.path.isdir(profile_dir):
        return False
    email = get_agy_profile_email(profile_name)
    return bool(email) and os.path.isdir(os.path.join(profile_dir, ".gemini"))


def wrap_agy_profile_cmd(cmd_args: list[str], profile_name: str | None) -> list[str]:
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
        f'eval $(gnome-keyring-daemon --start --components=secrets --control-directory="{keyring_dir}"); '
        f'exec {quoted_args}'
    )
    return ["dbus-run-session", "--", "sh", "-c", shell_cmd]


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
        agent_key = normalize_agent_name(agent)
        if isinstance(targets, list):
            chains[agent_key] = [
                normalize_agent_name(str(t))
                for t in targets
                if str(t).strip().lower() not in ("none", "null", "")
            ]
        elif isinstance(targets, str):
            t_str = targets.strip().lower()
            chains[agent_key] = [] if t_str in ("none", "null", "", "stop") else [normalize_agent_name(t_str)]

    return chains


FALLBACK_CHAINS = load_fallback_chains()


def parse_fallback_cli_arg(arg_val: str) -> dict[str, list[str]]:
    """Cho phép override fallback qua CLI, ví dụ: 'antigravity:claude,codex:claude,claude:none'"""
    res = dict(FALLBACK_CHAINS)
    for pair in arg_val.split(","):
        if ":" in pair or "=" in pair:
            delimiter = ":" if ":" in pair else "="
            k, v = pair.split(delimiter, 1)
            k = normalize_agent_name(k)
            v_list = [
                normalize_agent_name(x)
                for x in v.split("->")
                if x.strip().lower() not in ("none", "stop", "")
            ]
            res[k] = v_list
    return res


def find_substitute_agent(
    primary_agent: str,
    enabled_agents: dict[str, bool],
    chains: dict[str, list[str]],
) -> str | None:
    """
    Tìm agent thay thế tốt nhất khi primary_agent bị tắt:
    1. Tìm trong chuỗi fallback đã cấu hình của primary_agent
    2. Nếu không có trong chuỗi fallback, chọn theo mức độ phù hợp tự nhiên:
       - antigravity -> claude -> codex
       - codex -> claude -> antigravity
       - claude -> codex -> antigravity
    3. Bất kỳ agent nào đang bật
    """
    for candidate in chains.get(primary_agent, []):
        if enabled_agents.get(candidate, False):
            return candidate

    natural_preferences = {
        "antigravity": ["claude", "codex"],
        "codex": ["claude", "antigravity"],
        "claude": ["codex", "antigravity"],
    }
    for candidate in natural_preferences.get(primary_agent, []):
        if enabled_agents.get(candidate, False):
            return candidate

    for candidate, is_on in enabled_agents.items():
        if is_on and candidate != primary_agent:
            return candidate

    return None


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


def classify_and_split_task(
    user_prompt: str,
    enabled_agents: dict[str, bool] | None = None,
    chains: dict[str, list[str]] | None = None,
) -> dict:
    if enabled_agents is None:
        enabled_agents = load_enabled_agents()
    if chains is None:
        chains = FALLBACK_CHAINS

    # Chỉ tách ở dấu chấm KẾT CÂU. Dấu chấm nằm giữa hai ký tự chữ/số là một phần
    # của tên file (interview.html), đường dẫn (base.py) hoặc số thập phân —
    # tách ở đó sẽ băm nhỏ tên file thành các sub-task cụt nghĩa.
    clauses = [
        c.strip()
        for c in re.split(r"\.(?![A-Za-z0-9])|[;\n]| và | and ", user_prompt)
        if c.strip()
    ]

    raw_assignments: list[tuple[str, str]] = []

    for clause in clauses:
        lower = clause.lower()
        is_antigravity = any(k in lower for k in ANTIGRAVITY_KEYWORDS)
        is_codex = any(k in lower for k in CODEX_KEYWORDS)
        is_claude = any(k in lower for k in CLAUDE_KEYWORDS)

        if is_antigravity and not is_claude and not is_codex:
            raw_assignments.append((clause, "antigravity"))
        elif is_codex and not is_claude:
            raw_assignments.append((clause, "codex"))
        else:
            raw_assignments.append((clause, "claude"))

    tasks: dict[str, list[str]] = {
        "antigravity_tasks": [],
        "codex_tasks": [],
        "claude_tasks": [],
    }

    for clause, agent in raw_assignments:
        target_agent = agent
        if not enabled_agents.get(agent, False):
            substitute = find_substitute_agent(agent, enabled_agents, chains)
            if substitute:
                print(
                    f"[Router] Model '{agent.upper()}' đang bị tắt -> Điều phối subtask sang '{substitute.upper()}': {clause!r}"
                )
                target_agent = substitute
            else:
                print(
                    f"[Router CẢNH BÁO] Model '{agent.upper()}' đang bị tắt và không có Model thay thế khả dụng cho subtask: {clause!r}"
                )
                continue

        tasks[f"{target_agent}_tasks"].append(clause)

    return tasks


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


VIETNAMESE_DIACRITICS = re.compile(
    r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ]",
    re.IGNORECASE,
)

VIETNAMESE_COMMON_WORDS = {
    "và", "hoặc", "cho", "với", "của", "hãy", "làm", "sửa", "viết", "tạo",
    "kiểm tra", "chức năng", "nghiệp vụ", "giao diện", "hệ thống", "báo cáo",
    "hoàn thành", "cần", "không", "được", "các", "những", "trong", "trên",
    "va", "hoac", "voi", "cua", "hay", "sua", "viet", "khong", "duoc", "nhung",
    "giao dien", "kiem tra", "he thong", "bao cao", "hoan thanh",
}


def detect_language(text: str) -> str:
    """
    Tự động xác định ngôn ngữ người dùng:
    - 'vi' nếu chứa ký tự dấu tiếng Việt hoặc từ khóa tiếng Việt thông dụng (kể cả không dấu).
    - 'en' cho các trường hợp còn lại.
    """
    if not text:
        return "vi"
    if VIETNAMESE_DIACRITICS.search(text):
        return "vi"

    lower = f" {text.lower()} "
    for keyword in VIETNAMESE_COMMON_WORDS:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, lower):
            return "vi"
    return "en"


TASK_DONE_MARKER_VI = "Đã hoàn tất task."
TASK_DONE_MARKER_EN = "Task completed."
TASK_DONE_MARKER = TASK_DONE_MARKER_VI


def get_task_done_marker(lang: str = "vi") -> str:
    return TASK_DONE_MARKER_VI if lang == "vi" else TASK_DONE_MARKER_EN


def task_done_marker(task_id: str, lang: str = "vi") -> str:
    marker_phrase = get_task_done_marker(lang)
    return f"{marker_phrase} [id:{task_id}]"


def report_directive_text(task: str, report_path: str, lang: str = "vi") -> str:
    if lang == "vi":
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
    return (
        "\n\n--- HANDOFF REPORT (MANDATORY) ---\n"
        "After completing (or being forced to stop) this task, CREATE a markdown "
        f"file at the exact path: {report_path}\n"
        "Mandatory content includes:\n"
        f"- Task name: {task}\n"
        "- Executing agent: (specify your CLI/Model name)\n"
        "- Status: Completed / Incomplete (with reason if incomplete)\n"
        "- Implemented per spec: details of what was done\n"
        "- Additions beyond spec: voluntary enhancements (if any)\n"
        "- Other notes: points to consider during review (risks, assumptions, test cases)\n"
    )


def confirmation_directive_text(question_path: str, lang: str = "vi") -> str:
    if lang == "vi":
        return (
            "\n\n--- XÁC NHẬN VỚI NGƯỜI DÙNG (NẾU CẦN) ---\n"
            "Nếu có nhiều phương án hợp lý và cần người dùng chọn trước khi tiếp tục, "
            f"hãy dừng lại, ghi rõ câu hỏi và các phương án vào file: {question_path}\n"
            "rồi kết thúc lượt làm việc này. Router sẽ hỏi người dùng và gọi lại đúng phiên với câu trả lời.\n"
        )
    return (
        "\n\n--- USER CONFIRMATION (IF NEEDED) ---\n"
        "If there are multiple reasonable options requiring user confirmation before proceeding, "
        f"pause and write the question and options to: {question_path}\n"
        "then end this turn. The router will ask the user and resume this session with their response.\n"
    )


def completion_directive_text(task_id: str, lang: str = "vi") -> str:
    marker = task_done_marker(task_id, lang=lang)
    if lang == "vi":
        return (
            "\n\n--- KẾT THÚC (BẮT BUỘC) ---\n"
            "Sau khi hoàn tất công việc và ghi xong báo cáo bàn giao (nếu có yêu cầu), "
            f"dòng CUỐI CÙNG trong phản hồi của bạn phải là đúng cụm từ sau: {marker}\n"
        )
    return (
        "\n\n--- COMPLETION (MANDATORY) ---\n"
        "After completing the work and writing the handoff report (if required), "
        f"the FINAL line of your response must be exactly: {marker}\n"
    )


def build_base_prompt(task: str, cwd: str, ctx: dict, is_readonly: bool = False, lang: str = "vi") -> str:
    prompt = task + existing_reports_context(cwd)
    if task_requires_report(task, is_readonly):
        prompt += report_directive_text(task, ctx["report_path"], lang=lang)
    prompt += completion_directive_text(ctx["task_id"], lang=lang)
    return prompt


async def run_capture(cmd_args: list[str], env: dict | None = None) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            env=env,
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


async def check_agy_quota(env: dict | None = None, profile_name: str | None = None) -> dict | None:
    cmd_args = [ANTIGRAVITY_CMD, "--print-timeout", "5s", "-p", "/usage"]
    if profile_name:
        cmd_args = wrap_agy_profile_cmd(cmd_args, profile_name)
    _, output = await run_capture(cmd_args, env=env)
    return parse_agy_quota(output)


async def check_claude_quota() -> dict | None:
    _, output = await run_capture([CLAUDE_CMD, "-p", "/usage"])
    return parse_claude_quota(output)


async def check_codex_status() -> dict | None:
    code, output = await run_capture([CODEX_CMD, "--version"])
    if code == 0:
        return {"version": output.strip(), "status": "Ready"}
    return None


async def print_quota_status(
    cwd: str,
    enabled_agents: dict[str, bool] | None = None,
    chains: dict[str, list[str]] | None = None,
    agy_profiles: list[str] | None = None,
) -> None:
    if enabled_agents is None:
        enabled_agents = load_enabled_agents()
    if chains is None:
        chains = FALLBACK_CHAINS
    if agy_profiles is None:
        agy_profiles = load_antigravity_profiles()

    async def get_all_agy_quotas():
        results = []
        for p in agy_profiles:
            env = get_agy_profile_env(p)
            if not is_agy_profile_ready(p):
                results.append((p, None))
                continue
            quota = await check_agy_quota(env=env, profile_name=p)
            results.append((p, quota))
        return results

    agy_coro = get_all_agy_quotas() if enabled_agents.get("antigravity", True) else asyncio.sleep(0, result=[])
    claude_coro = check_claude_quota() if enabled_agents.get("claude", True) else asyncio.sleep(0, result=None)
    codex_coro = check_codex_status() if enabled_agents.get("codex", True) else asyncio.sleep(0, result=None)

    agy_results, claude_quota, codex_status = await asyncio.gather(
        agy_coro, claude_coro, codex_coro
    )

    print("\n" + "=" * 55)
    print("AI ROUTER - TRẠNG THÁI QUOTA & MODEL CLI")
    print("=" * 55)

    print("[1] Antigravity (Gemini, Five Hour Limit):")
    if not enabled_agents.get("antigravity", True):
        print("    [TẮT] Đang bị tắt theo cấu hình.")
    elif agy_results:
        email_map: dict[str, list[str]] = {}
        for p_name, q in agy_results:
            p_label = f"Worker '{p_name}'" if p_name != "default" else "Mặc định"
            email = get_agy_profile_email(p_name)
            email_info = f" ({email})" if email else " (Chưa có tài khoản)"
            if email:
                email_map.setdefault(email, []).append(p_name)
            if q:
                print(f"    • {p_label}{email_info}: Còn lại {q['remaining_percent']}% - reset lúc {q['reset_at']}")
            else:
                print(f"    • {p_label}{email_info}: Chưa đăng nhập / Không đọc được quota")

        for email, p_list in email_map.items():
            if len(p_list) > 1:
                print(f"    [!] CẢNH BÁO: Các worker {p_list} đang dùng CHUNG tài khoản Google ({email})!")
                print(f"        -> Để tách biệt, chạy: python3 ai-task-router/profile_manager.py login antigravity <worker>")
    else:
        print("    Không đọc được / CLI 'agy' chưa sẵn sàng.")
        print("    -> Cài đặt nhanh: curl -fsSL https://antigravity.google/cli/install.sh | bash")

    print("[2] Claude Code (Current session):")
    if not enabled_agents.get("claude", True):
        print("    [TẮT] Đang bị tắt theo cấu hình.")
    elif claude_quota:
        print(f"    Đã dùng {claude_quota['used_percent']}% - reset lúc {claude_quota['resets']}")
    else:
        print("    Không đọc được / CLI 'claude' chưa sẵn sàng.")
        print("    -> Cài đặt nhanh: curl -fsSL https://claude.ai/install.sh | bash")

    print("[3] Codex CLI:")
    if not enabled_agents.get("codex", True):
        print("    [TẮT] Đang bị tắt theo cấu hình.")
    elif codex_status:
        print(f"    {codex_status['version']} - Sẵn sàng ({codex_status['status']})")
    else:
        print("    Không tìm thấy lệnh 'codex' trên PATH.")
        print("    -> Cài đặt nhanh: curl -fsSL https://chatgpt.com/codex/install.sh | sh")

    print("-" * 55)
    print("TRẠNG THÁI KÍCH HOẠT & THỨ TỰ FALLBACK:")
    for src in SUPPORTED_AGENTS:
        is_on = enabled_agents.get(src, True)
        state_tag = "BẬT" if is_on else "TẮT"
        targets = [t for t in chains.get(src, []) if enabled_agents.get(t, True)]
        chain_str = " -> ".join(t.upper() for t in targets) if targets else "(Dừng / Không fallback)"
        print(f"  • {src.upper():12} [{state_tag:4}]: fallback -> {chain_str}")
    print("=" * 55 + "\n")


async def run_agent(
    agent_name: str,
    cmd_args: list[str],
    cwd: str | None = None,
    env: dict | None = None,
    output_collector: list[str] | None = None,
) -> int:
    print(f"[{agent_name}] Bắt đầu: {' '.join(shlex.quote(a) for a in cmd_args)}")
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            cwd=cwd,
            env=env,
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
            decoded = line.decode('utf-8', errors='replace').rstrip()
            if output_collector is not None:
                output_collector.append(decoded)
            print(f"[{prefix}] {decoded}")

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


async def run_claude_agent(prompt: str, question_path: str, cwd: str = ".") -> int:
    session_id = str(uuid.uuid4())
    extra_args = ["--autocompact", str(CLAUDE_CONTEXT_TOKEN_LIMIT), *claude_system_prompt_args()]
    cmd_args = [CLAUDE_CMD, "--session-id", session_id, *extra_args, "-p", prompt]

    while True:
        exit_code = await run_agent("Claude Code", cmd_args, cwd=cwd)
        if not os.path.exists(question_path):
            return exit_code

        with open(question_path, "r", encoding="utf-8") as f:
            question_text = f.read()
        os.remove(question_path)

        answer = await ask_user(question_text)
        cmd_args = [CLAUDE_CMD, "--resume", session_id, *extra_args, "-p", answer]


async def run_codex_agent(prompt: str, question_path: str, cwd: str = ".") -> int:
    full_prompt = prompt + context_rules_directive()
    cmd_args = [
        CODEX_CMD, "exec",
        "-C", cwd,
        "-s", "workspace-write",
        full_prompt,
    ]

    exit_code = await run_agent("Codex", cmd_args, cwd=cwd)

    if os.path.exists(question_path):
        with open(question_path, "r", encoding="utf-8") as f:
            question_text = f.read()
        os.remove(question_path)
        answer = await ask_user(question_text)
        resume_prompt = f"Tiếp tục thực hiện với câu trả lời từ người dùng: {answer}\n" + full_prompt
        cmd_args = [CODEX_CMD, "exec", "-C", cwd, "-s", "workspace-write", resume_prompt]
        exit_code = await run_agent("Codex", cmd_args, cwd=cwd)

    return exit_code


AGY_USAGE_FALLBACK_THRESHOLD = 90

QUOTA_ERROR_PATTERNS = [
    r"ResourceExhausted",
    r"429\s+Too\s+Many\s+Requests",
    r"quota\s+exceeded",
    r"rate\s+limit",
    r"Five\s+Hour\s+Limit",
    r"Usage\s+limit\s+reached",
    r"credit\s+limit",
]


def is_quota_exhausted_error(exit_code: int, output_text: str) -> bool:
    if exit_code == 99:
        return True
    for pattern in QUOTA_ERROR_PATTERNS:
        if re.search(pattern, output_text, re.IGNORECASE):
            return True
    return False


async def antigravity_usage_exceeded(env: dict | None = None, profile_name: str | None = None) -> bool:
    quota = await check_agy_quota(env=env, profile_name=profile_name)
    if quota is None:
        return False
    used_percent = 100 - quota["remaining_percent"]
    return used_percent > AGY_USAGE_FALLBACK_THRESHOLD


async def ensure_worker_handoff_report(
    worker_name: str,
    task: str,
    report_path: str,
    cwd: str,
    env: dict | None = None,
    captured_output: str = "",
) -> str:
    """
    Đảm bảo có báo cáo bàn giao hoàn chỉnh trước khi chuyển giao sang worker mới.
    1. Nếu worker cũ đã tạo file báo cáo hợp lệ -> đọc và bổ sung ghi chú bàn giao.
    2. Nếu chưa có -> thử yêu cầu worker cũ tạo báo cáo tổng kết.
    3. Nếu worker cũ bị chặn API (429/quota) -> router tự động trích xuất git diff
       và output gần nhất để tạo báo cáo bàn giao đầy đủ cho worker tiếp theo.
    """
    if report_path and os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if len(content) > 50:
                print(f"[Router Handoff] Worker '{worker_name}' đã có sẵn báo cáo bàn giao tại: {report_path}")
                return content
        except OSError:
            pass

    # Thử yêu cầu worker cũ viết báo cáo bàn giao nếu API còn phản hồi được
    if report_path:
        try:
            handoff_prompt = (
                f"Phiên làm việc của bạn ({worker_name}) đã đạt giới hạn token/quota và chuẩn bị bàn giao cho worker tiếp theo.\n"
                f"YÊU CẦU BẮT BUỘC: Hãy tạo file báo cáo bàn giao tại đường dẫn: {report_path}\n"
                "Nội dung gồm:\n"
                f"- Nhiệm vụ: {task}\n"
                f"- Worker bàn giao: {worker_name}\n"
                "- Trạng thái: Đang thực hiện dở dang, chuyển tiếp cho worker mới\n"
                "- Chi tiết các việc đã làm xong\n"
                "- Các việc còn lại cần làm tiếp\n"
                "- Danh sách các file đã tạo hoặc sửa đổi\n"
            )
            cmd_args = [ANTIGRAVITY_CMD, "--continue", "--dangerously-skip-permissions", "-p", handoff_prompt]
            code = await run_agent(f"Antigravity ({worker_name}) [Handoff]", cmd_args, cwd=cwd, env=env)
            if code == 0 and os.path.isfile(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if len(content) > 50:
                    print(f"[Router Handoff] Worker '{worker_name}' đã viết xong báo cáo bàn giao tại: {report_path}")
                    return content
        except Exception as e:
            print(f"[Router Handoff] Worker '{worker_name}' không thể ghi báo cáo bàn giao ({e}).")

    # Fallback Router-level Synthesizer: tự động tổng hợp từ git diff và log
    print(f"[Router Handoff] Tự động tổng hợp báo cáo bàn giao từ thay đổi Git thực tế...")
    diff_status = ""
    diff_stat = ""
    try:
        st_code, st_out = await run_capture(["git", "status", "--short"], env=env)
        if st_code == 0:
            diff_status = st_out.strip()
        df_code, df_out = await run_capture(["git", "diff", "--stat"], env=env)
        if df_code == 0:
            diff_stat = df_out.strip()
    except Exception:
        pass

    synthesized_content = (
        f"# Báo Cáo Bàn Giao Tiến Độ (Chuyển Giao Worker Tự Động)\n\n"
        f"- **Nhiệm vụ:** {task}\n"
        f"- **Worker thực hiện trước:** {worker_name} (Antigravity)\n"
        f"- **Lý do chuyển giao:** Đạt giới hạn token / cạn hạn mức quota API (5-hour limit hoặc rate limit).\n"
        f"- **Trạng thái:** Đang thực hiện dở dang, sẵn sàng cho worker tiếp theo tiếp quản.\n\n"
        f"## 1. Các tệp đã thay đổi trên workspace\n\n"
        f"```text\n"
        f"{diff_status or '(Chưa có thay đổi tệp nào được ghi nhận)'}\n"
        f"```\n\n"
        f"```text\n"
        f"{diff_stat}\n"
        f"```\n\n"
        f"## 2. Hướng dẫn tiếp quản cho Worker kế tiếp\n"
        f"- Worker trước ({worker_name}) đã bị dừng do đạt ngưỡng quota/token.\n"
        f"- Worker mới cần kiểm tra các tệp thay đổi ở trên, kế thừa công việc hiện tại và tiếp tục hoàn thiện mục tiêu của task:\n"
        f"  `{task}`\n"
    )

    if report_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(synthesized_content)
            print(f"[Router Handoff] Đã tạo thành công báo cáo bàn giao tại: {report_path}")
        except OSError as e:
            print(f"[Router Handoff CẢNH BÁO] Không ghi được file {report_path}: {e}")

    return synthesized_content


async def run_antigravity_agent(
    prompt: str,
    question_path: str,
    task: str = "",
    report_path: str = "",
    cwd: str = ".",
    conversation_id: str | None = None,
    agy_continue: bool = False,
    profiles: list[str] | None = None,
) -> int:
    worker_pool = profiles if profiles else load_antigravity_profiles()
    if not worker_pool:
        worker_pool = ["default"]

    current_prompt = prompt
    last_exit_code = 1

    for idx, worker_name in enumerate(worker_pool):
        is_last_worker = (idx == len(worker_pool) - 1)
        worker_label = f"worker:{worker_name}" if worker_name != "default" else "default"
        worker_env = get_agy_profile_env(worker_name)

        if not is_agy_profile_ready(worker_name):
            print(
                f"[Antigravity Pool] CẢNH BÁO: Profile '{worker_name}' chưa được đăng nhập "
                f"(gợi ý: python3 ai-task-router/profile_manager.py login antigravity {worker_name}) -> Bỏ qua."
            )
            continue

        if await antigravity_usage_exceeded(env=worker_env, profile_name=worker_name):
            print(f"[Antigravity Pool] Profile '{worker_name}' usage > {AGY_USAGE_FALLBACK_THRESHOLD}% (cạn quota 5h).")
            if not is_last_worker:
                print(f"[Antigravity Pool] -> Tự động chuyển sang profile tiếp theo trong pool...")
                continue
            else:
                print(f"[Antigravity Pool] Toàn bộ worker trong pool đều đã hết quota.")
                return 99

        print(f"\n[Antigravity Pool] >>> Bắt đầu xử lý bởi [{worker_label.upper()}] <<<")
        cmd_args = [ANTIGRAVITY_CMD, "--dangerously-skip-permissions"]
        if conversation_id:
            cmd_args.extend(["--conversation", conversation_id])
        elif agy_continue:
            cmd_args.append("--continue")
        cmd_args.extend(["-p", current_prompt])

        worker_exhausted = False
        while True:
            captured_lines: list[str] = []
            wrapped_cmd_args = wrap_agy_profile_cmd(cmd_args, worker_name)
            exit_code = await run_agent(
                f"Antigravity [{worker_label}]",
                wrapped_cmd_args,
                cwd=cwd,
                env=worker_env,
                output_collector=captured_lines,
            )
            last_exit_code = exit_code
            output_text = "\n".join(captured_lines)

            # Kiểm tra xem có lỗi cạn quota / 429 hay không
            if is_quota_exhausted_error(exit_code, output_text):
                print(f"[Antigravity Pool] Phát hiện Worker '{worker_name}' cạn hạn mức token/quota trong phiên!")
                worker_exhausted = True
                break

            if not os.path.exists(question_path):
                # Không có câu hỏi nào đang chờ -> kết thúc lượt chạy của worker này
                break

            # Có câu hỏi cần người dùng giải đáp
            with open(question_path, "r", encoding="utf-8") as f:
                question_text = f.read()
            os.remove(question_path)

            answer = await ask_user(question_text)
            cmd_args = [ANTIGRAVITY_CMD, "--dangerously-skip-permissions"]
            if conversation_id:
                cmd_args.extend(["--conversation", conversation_id])
            else:
                cmd_args.append("--continue")
            cmd_args.extend(["-p", answer])

        if not worker_exhausted and last_exit_code == 0:
            # Thành công trọn vẹn
            return 0

        if worker_exhausted:
            # Bắt buộc tạo tài liệu bàn giao trước khi chuyển giao sang worker mới
            print(f"[Antigravity Pool] Chuẩn bị chuyển giao: Đảm bảo tài liệu bàn giao từ '{worker_name}'...")
            handoff_content = await ensure_worker_handoff_report(
                worker_name=worker_name,
                task=task,
                report_path=report_path,
                cwd=cwd,
                env=worker_env,
                captured_output=output_text,
            )

            if not is_last_worker:
                next_worker = worker_pool[idx + 1]
                print(f"[Antigravity Pool] >>> CHUYỂN GIAO TIẾN ĐỘ: '{worker_name}' -> '{next_worker}' <<<")
                handoff_directive = (
                    f"\n\n--- THÔNG TIN TIẾP QUẢN TỪ WORKER TRƯỚC ({worker_name}) ---\n"
                    f"Worker trước ({worker_name}) đã đạt giới hạn token/quota và đã lập tài liệu bàn giao.\n"
                    f"Dưới đây là BÁO CÁO BÀN GIAO:\n\n{handoff_content}\n\n"
                    f"--- CHỈ DẪN CHO BẠN ({next_worker}) ---\n"
                    f"Hãy đọc kỹ báo cáo bàn giao trên, kiểm tra workspace hiện tại và tiếp tục hoàn thiện mục tiêu của task:\n"
                    f"{task}\n"
                )
                current_prompt = prompt + handoff_directive
                # Reset conversation_id và agy_continue cho worker mới vì đây là profile mới
                conversation_id = None
                agy_continue = False
                continue
            else:
                print(f"[Antigravity Pool] Toàn bộ worker trong pool đã đạt giới hạn quota.")
                return 99

        # Nếu thất bại vì lý do khác (không phải quota):
        return last_exit_code

    return last_exit_code


async def execute_task_with_fallback_chain(
    initial_agent: str,
    task: str,
    cwd: str,
    ctx: dict,
    chains: dict[str, list[str]],
    enabled_agents: dict[str, bool] | None = None,
    lang: str | None = None,
    agy_conversation: str | None = None,
    agy_continue: bool = False,
    agy_profiles: list[str] | None = None,
) -> int:
    """
    Thực thi một task theo chuỗi fallback cấu hình:
    initial_agent -> targets[0] -> targets[1] -> ... -> dừng
    Tự động bỏ qua các agent đã bị tắt và dùng ngôn ngữ phù hợp.
    """
    if enabled_agents is None:
        enabled_agents = load_enabled_agents()
    if lang is None:
        lang = detect_language(task)

    # Chuỗi thực thi đầy đủ, chỉ giữ các agent đang bật
    raw_chain = [initial_agent] + chains.get(initial_agent, [])
    execution_chain: list[str] = []
    for a in raw_chain:
        if enabled_agents.get(a, False) and a not in execution_chain:
            execution_chain.append(a)

    if not execution_chain:
        substitute = find_substitute_agent(initial_agent, enabled_agents, chains)
        if substitute:
            execution_chain = [substitute]
        else:
            print(f"[Router ERROR] Không có agent nào khả dụng để thực thi task: {ctx['task_id']}")
            return 1

    base_prompt = build_base_prompt(task, cwd, ctx, is_readonly=False, lang=lang)

    for idx, current_agent in enumerate(execution_chain):
        print(f"\n[Router] [Task: {ctx['task_id']}] -> Đang thực thi bằng '{current_agent.upper()}'...")
        exit_code = 1

        try:
            if current_agent == "antigravity":
                antigravity_prompt = (
                    base_prompt
                    + context_rules_directive()
                    + confirmation_directive_text(ctx["question_path"], lang=lang)
                )
                exit_code = await run_antigravity_agent(
                    antigravity_prompt,
                    ctx["question_path"],
                    task=task,
                    report_path=ctx["report_path"],
                    cwd=cwd,
                    conversation_id=agy_conversation,
                    agy_continue=agy_continue,
                    profiles=agy_profiles,
                )
            elif current_agent == "codex":
                codex_prompt = base_prompt + confirmation_directive_text(ctx["question_path"], lang=lang)
                exit_code = await run_codex_agent(codex_prompt, ctx["question_path"], cwd=cwd)
            elif current_agent == "claude":
                claude_prompt = base_prompt + confirmation_directive_text(ctx["question_path"], lang=lang)
                exit_code = await run_claude_agent(claude_prompt, ctx["question_path"], cwd=cwd)
            else:
                print(f"[Router ERROR] Không hỗ trợ agent '{current_agent}'.")
                exit_code = 127
        except Exception as e:
            print(f"[Router ERROR] Ngoại lệ khi chạy {current_agent}: {e}")
            exit_code = 1

        if exit_code == 0:
            if lang == "vi":
                print(f"[Router] [Task: {ctx['task_id']}] -> Thành công bởi '{current_agent.upper()}'.")
            else:
                print(f"[Router] [Task: {ctx['task_id']}] -> Successfully completed by '{current_agent.upper()}'.")
            return 0

        # Nếu thất bại, kiểm tra agent tiếp theo
        if idx + 1 < len(execution_chain):
            next_agent = execution_chain[idx + 1]
            if lang == "vi":
                print(
                    f"[Router] '{current_agent.upper()}' thất bại (mã {exit_code}) "
                    f"-> Tự động fallback sang: '{next_agent.upper()}'."
                )
            else:
                print(
                    f"[Router] '{current_agent.upper()}' failed (code {exit_code}) "
                    f"-> Automatically falling back to: '{next_agent.upper()}'."
                )
        else:
            if lang == "vi":
                print(
                    f"[Router] '{current_agent.upper()}' thất bại (mã {exit_code}). "
                    "Không còn agent fallback nào trong chuỗi -> Dừng task này."
                )
            else:
                print(
                    f"[Router] '{current_agent.upper()}' failed (code {exit_code}). "
                    "No remaining fallback agents in chain -> Terminating this task."
                )

    return exit_code


async def dispatch(
    tasks_dict: dict,
    chains: dict[str, list[str]],
    enabled_agents: dict[str, bool] | None = None,
    overall_lang: str = "vi",
    agy_conversation: str | None = None,
    agy_continue: bool = False,
    agy_profiles: list[str] | None = None,
) -> None:
    if enabled_agents is None:
        enabled_agents = load_enabled_agents()

    cwd = os.getcwd()
    concurrent = []

    for agent in SUPPORTED_AGENTS:
        tasks = tasks_dict.get(f"{agent}_tasks", [])
        if not tasks:
            continue
        for task in tasks:
            effective_agent = agent
            if not enabled_agents.get(agent, False):
                substitute = find_substitute_agent(agent, enabled_agents, chains)
                if substitute:
                    print(
                        f"[Router] Chuyển hướng task của '{agent.upper()}' sang '{substitute.upper()}' do '{agent.upper()}' đã bị tắt."
                    )
                    effective_agent = substitute
                else:
                    print(f"[Router CẢNH BÁO] Bỏ qua task vì '{agent.upper()}' bị tắt và không có agent thay thế.")
                    continue
            ctx = build_task_context(task, cwd)
            task_lang = detect_language(task)
            concurrent.append(
                execute_task_with_fallback_chain(
                    effective_agent,
                    task,
                    cwd,
                    ctx,
                    chains,
                    enabled_agents,
                    lang=task_lang,
                    agy_conversation=agy_conversation,
                    agy_continue=agy_continue,
                    agy_profiles=agy_profiles,
                )
            )

    if not concurrent:
        msg = (
            "[Router] Không có sub-task nào được nhận diện hoặc thực thi."
            if overall_lang == "vi"
            else "[Router] No sub-tasks recognized or executed."
        )
        print(msg)
        return

    banner_start = (
        "[Router] Bắt đầu chạy song song các Agent...\n"
        if overall_lang == "vi"
        else "[Router] Dispatching agents concurrently...\n"
    )
    banner_end = (
        "\n[Router] Tất cả các task đã hoàn tất."
        if overall_lang == "vi"
        else "\n[Router] All tasks completed."
    )
    print(banner_start + "-" * 50)
    await asyncio.gather(*concurrent)
    print("-" * 50 + banner_end)


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
    parser.add_argument(
        "--disable", action="append", default=[],
        help="Tắt một hoặc nhiều Model AI (có thể dùng nhiều lần hoặc phân cách bằng dấu phẩy, ví dụ: '--disable codex' hoặc '--disable agy,claude')",
    )
    parser.add_argument(
        "--enable", action="append", default=[],
        help="Chỉ bật các Model AI được chỉ định (có thể dùng nhiều lần hoặc phân cách bằng dấu phẩy, ví dụ: '--enable codex,claude')",
    )
    parser.add_argument(
        "--no-agy", "--no-antigravity", dest="disable_agy", action="store_true",
        help="Tắt Antigravity CLI cho lượt chạy này.",
    )
    parser.add_argument(
        "--agy-continue", action="store_true",
        help="Tiếp tục phiên làm việc gần nhất của Antigravity ('agy --continue').",
    )
    parser.add_argument(
        "--agy-conversation", default=None,
        help="Khôi phục phiên làm việc của Antigravity theo Conversation ID ('agy --conversation <ID>').",
    )
    parser.add_argument(
        "--agy-profiles", default=None,
        help="Danh sách profile của Antigravity phân cách bằng dấu phẩy (ví dụ: 'worker1,worker2,worker3')",
    )
    parser.add_argument(
        "--no-codex", dest="disable_codex", action="store_true",
        help="Tắt Codex CLI cho lượt chạy này.",
    )
    parser.add_argument(
        "--no-claude", dest="disable_claude", action="store_true",
        help="Tắt Claude Code CLI cho lượt chạy này.",
    )
    parser.add_argument(
        "--supervisor", default=None,
        help="Chỉ định Model AI làm Supervisor (ví dụ: '--supervisor claude' hoặc '--supervisor antigravity' hoặc '--supervisor off')",
    )
    parser.add_argument(
        "--supervisor-profile", default=None,
        help="Tên profile độc lập của Supervisor (mặc định: supervisor)",
    )
    parser.add_argument(
        "--quality-gate", dest="quality_gate", action="store_true",
        help="Bật cổng nghiệm thu chất lượng độc lập (chạy test & kiểm tra git diff sau khi hoàn tất)",
    )
    parser.add_argument(
        "--no-quality-gate", dest="no_quality_gate", action="store_true",
        help="Tắt cổng nghiệm thu chất lượng độc lập",
    )
    args = parser.parse_args()

    # 1. Xác định cấu hình bật/tắt Model AI
    enabled_agents = load_enabled_agents()

    if args.enable:
        enabled_list = []
        for item in args.enable:
            for x in item.split(","):
                if x.strip():
                    enabled_list.append(normalize_agent_name(x))
        for k in enabled_agents:
            enabled_agents[k] = k in enabled_list

    if args.disable:
        for item in args.disable:
            for x in item.split(","):
                norm = normalize_agent_name(x)
                if norm in enabled_agents:
                    enabled_agents[norm] = False

    if args.disable_agy:
        enabled_agents["antigravity"] = False
    if args.disable_codex:
        enabled_agents["codex"] = False
    if args.disable_claude:
        enabled_agents["claude"] = False

    # Kiểm tra phải có ít nhất 1 agent đang bật
    active_agents = [k for k, v in enabled_agents.items() if v]
    if not active_agents:
        print("[Router LỖI] Tất cả các Model AI đều bị tắt! Cần kích hoạt ít nhất một Model (antigravity, codex, claude).")
        sys.exit(1)

    # 2. Cấu hình Supervisor & Quality Gate (Phương án A + C)
    supervisor_enabled = SUPERVISOR_CONFIG.get("enabled", False)
    supervisor_model = SUPERVISOR_CONFIG.get("model", "claude")
    supervisor_profile = SUPERVISOR_CONFIG.get("profile", "supervisor")
    quality_gate = SUPERVISOR_CONFIG.get("enable_quality_gate", True)
    test_cmd = SUPERVISOR_CONFIG.get("test_command", "auto")

    if args.supervisor is not None:
        if args.supervisor.lower() in ("none", "off", "false", "0"):
            supervisor_enabled = False
        else:
            supervisor_enabled = True
            supervisor_model = normalize_agent_name(args.supervisor)

    if args.supervisor_profile:
        supervisor_profile = args.supervisor_profile

    if args.quality_gate:
        quality_gate = True
    elif args.no_quality_gate:
        quality_gate = False

    # 3. Xác định chuỗi fallback
    chains = FALLBACK_CHAINS
    if args.fallback:
        chains = parse_fallback_cli_arg(args.fallback)

    agy_profiles = None
    if args.agy_profiles:
        agy_profiles = [p.strip() for p in args.agy_profiles.split(",") if p.strip()]

    if args.check_quota:
        asyncio.run(print_quota_status(os.getcwd(), enabled_agents, chains, agy_profiles=agy_profiles))
        return

    if not args.prompt:
        parser.error("Thiếu 'prompt' (bỏ qua chỉ khi dùng --check-quota).")

    user_lang = detect_language(args.prompt)
    tasks_dict = classify_and_split_task(args.prompt, enabled_agents, chains)

    print("[Router] Trạng thái các Model AI:")
    for k in SUPPORTED_AGENTS:
        status_tag = "BẬT (ACTIVE)" if enabled_agents.get(k, True) else "TẮT (DISABLED)"
        print(f"  • {k.upper():12}: {status_tag}")

    if supervisor_enabled:
        print("[Router] Chế độ AI Supervisor (Phương án A + C): BẬT")
        print(f"  • Model Supervisor: {supervisor_model.upper()} (Profile: '{supervisor_profile}')")
        print(f"  • Quality Gate (Nghiệm thu độc lập): {'BẬT' if quality_gate else 'TẮT'}")

    print("[Router] Kết quả phân loại sub-tasks:")
    print(json.dumps(tasks_dict, ensure_ascii=False, indent=2))

    print("[Router] Thứ tự fallback áp dụng cho phiên này:")
    for k in SUPPORTED_AGENTS:
        if not enabled_agents.get(k, True):
            print(f"  • {k.upper():12} -> (Đã tắt)")
            continue
        v = [t for t in chains.get(k, []) if enabled_agents.get(t, True)]
        chain_label = " -> ".join(t.upper() for t in v) if v else "(Dừng / Không fallback)"
        print(f"  • {k.upper():12} -> {chain_label}")

    asyncio.run(
        dispatch(
            tasks_dict,
            chains,
            enabled_agents,
            overall_lang=user_lang,
            agy_conversation=args.agy_conversation,
            agy_continue=args.agy_continue,
            agy_profiles=agy_profiles,
        )
    )

    # Nghiệm thu chất lượng độc lập (Quality Gate - Phương án C)
    if quality_gate:
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        if _this_dir not in sys.path:
            sys.path.insert(0, _this_dir)
        try:
            from supervisor_tools import inspect_git_diff, run_verification_tests
            print("\n" + "=" * 55)
            print("[Quality Gate] TIẾN HÀNH NGHIỆM THU ĐỘC LẬP (Phương án C)...")
            print("=" * 55)
            diff_info = inspect_git_diff(os.getcwd())
            if diff_info.get("has_changes"):
                print("[Quality Gate] Thay đổi mã nguồn được ghi nhận:")
                if diff_info.get("stat"):
                    print(diff_info["stat"])
            else:
                print("[Quality Gate] Không phát hiện thay đổi mã nguồn mới.")

            test_result = run_verification_tests(test_cmd, cwd=os.getcwd())
            if test_result.get("status") == "SKIPPED":
                print(f"[Quality Gate] Kiểm thử: {test_result.get('message')}")
            elif test_result.get("passed"):
                print(f"[Quality Gate] [PASS] Kiểm thử độc lập THÀNH CÔNG (Exit Code: 0).")
            else:
                print(f"[Quality Gate] [FAIL] Kiểm thử độc lập THẤT BẠI (Exit Code: {test_result.get('exit_code')}).")
            print("=" * 55 + "\n")
        except ImportError:
            pass


if __name__ == "__main__":
    main()
