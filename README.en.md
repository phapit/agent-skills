# AI Router — Multi-Agent Orchestration across Antigravity, Codex, and Claude Code

**[English](README.en.md) | [Tiếng Việt](README.md)**

A local router that classifies engineering requirements and automatically dispatches each sub-task to the most suitable AI Coding Agent CLI:

- **Antigravity** (`agy`) — Frontend/UI (React, Vue, HTML/CSS) and lightweight operational tasks: scanning paths, reading files, `cd`, checking/confirming service status, and small UI fixes. Runs inside a persistent `tmux` session to preserve conversational context.
- **Codex** (`codex`) — High-speed code generation, unit/integration test authoring, boilerplate scaffolding, database migrations, algorithms, and isolated function refactoring.
- **Claude Code** (`claude`) — Complex business reasoning: requirements analysis, handoff documentation, task decomposition, system architecture design, and database schema planning.

All routing logic resides in:
[`ai-task-router/classify_and_split_task.py`](ai-task-router/classify_and_split_task.py),
packaged as the **Universal Skill** `ai-task-router`.

---

## Key Features

- **3-Tier Rule-Based Classification**: Deconstructs user prompts into discrete clauses and maps each to Antigravity, Codex, or Claude Code. Ambiguous or high-complexity clauses default safely to Claude Code.
- **Persistent Antigravity Execution via tmux**: Each project is assigned a dedicated tmux session, automatically provisioned on demand. Maintains conversational memory and state across multiple sub-tasks.
- **Non-Interactive Codex Runs via `codex exec`**: Fast and secure execution inside a workspace sandbox with automatic error fallback.
- **Stateful Claude Code Sessions via `--session-id` + `--resume`**: Automatically persists sessions; pauses for human input when necessary and resumes cleanly to conserve token budget.
- **Intelligent 3-Level Fallback Chain**:
  - Antigravity error/timeout or 5-hour quota > 90% $\rightarrow$ Falls back to Codex/Claude Code.
  - Codex error $\rightarrow$ Falls back to Claude Code.
- **Mandatory Handoff Reporting**: Every code modification or analysis task writes a detailed markdown report into `.ai_router_reports/`.
- **Status & Quota Monitoring**: The `--check-quota` flag inspects remaining limits and operational readiness across `agy`, `claude`, and `codex`.

---

## Universal Skill Installation

To enable the skill across **all** installed AI CLIs on your machine (Claude Code, Antigravity, Codex):

```bash
# Clone repository (if not already cloned)
git clone https://github.com/phapit/agent-skills.git
cd agent-skills/ai-task-router

# Run installer
./install.sh
```

The script automatically creates symlinks in:
- `~/.claude/skills/ai-task-router`
- `~/.gemini/config/skills/ai-task-router`
- `~/.codex/skills/ai-task-router`
- `~/.agents/skills/ai-task-router`

---

## Usage

```bash
# Classify and orchestrate a multi-faceted task
python3 ai-task-router/classify_and_split_task.py "fix login button styling in React UI, write unit tests for auth function, and draft architecture handoff docs"

# Check quota & CLI availability
python3 ai-task-router/classify_and_split_task.py --check-quota
```

---

## Context & Token Limit Configuration

Configure context limits and fallback behavior at [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):

```json
{
  "context": {
    "auto_compact": true,
    "claude_max_token_threshold": 300000,
    "agy_max_token_threshold": 600000,
    "codex_max_token_threshold": 200000
  },
  "fallback_chains": {
    "antigravity": ["claude"],
    "codex": ["claude"],
    "claude": []
  }
}
```

### Customizing Fallback Chains

You can customize the fallback priority to suit your workflow:
- **In Configuration File**: Edit the `"fallback_chains"` block in `settings.json`.
  - Default:
    - `"antigravity": ["claude"]`: Antigravity error/quota depleted -> route to Claude Code.
    - `"codex": ["claude"]`: Codex error -> route to Claude Code.
    - `"claude": []`: Claude Code error -> terminate (no fallback).
  - Multi-tier chain: `"antigravity": ["codex", "claude"]` (Antigravity fails -> try Codex, Codex fails -> try Claude Code).
- **CLI Override**:
  ```bash
  python3 ai-task-router/classify_and_split_task.py --fallback "antigravity:claude,codex:claude,claude:none" "your prompt..."
  ```

---

## Disclaimer

- This project is an independent open-source orchestration tool and is not officially associated with, maintained by, or endorsed by Anthropic, Google, or OpenAI.
- All product and service names (`Claude`, `Antigravity`, `Codex`) are trademarks or registered trademarks of their respective holders.
- When running automated agents (such as `codex exec` or `agy`), ensure that you review workspace sandbox configurations and execution permissions to prevent unintended system side effects.

---

## License

This project is licensed under the [MIT](LICENSE) License. See the `LICENSE` file for details.

