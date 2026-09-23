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

## Quick Installation for the 3 AI Model CLIs (Linux & macOS)

Before using the Router, you can quickly install the 3 AI Model CLIs using the terminal one-liners below:

### 1. Antigravity (`agy`)
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

### 2. Claude Code (`claude`)
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

### 3. Codex CLI (`codex`)
```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

---

## Universal Skill Installation

### Method 1: Using the `skills` CLI (Recommended — One-liner)

Install globally for all AI Agents on your machine:
```bash
npx skills add phapit/agent-skills --skill ai-task-router -g
```

Or install locally for the current project only:
```bash
npx skills add phapit/agent-skills --skill ai-task-router
```

### Method 2: Manual Installation via Git & Symlink

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

# Flexibly disable one or more AI Models
python3 ai-task-router/classify_and_split_task.py --disable codex "your prompt..."
python3 ai-task-router/classify_and_split_task.py --no-agy "your prompt..."
python3 ai-task-router/classify_and_split_task.py --enable codex,claude "your prompt..."
```

---

## Enabling / Disabling AI Models

End users can flexibly enable or disable any of the 3 AI models (`antigravity`, `codex`, `claude`) in two ways:

### 1. Via Command-Line Flags
- `--disable <agents>`: Disable one or more models (e.g. `--disable codex` or `--disable antigravity,claude`).
- `--no-agy` / `--no-antigravity`: Quickly disable Antigravity CLI.
- `--no-codex`: Quickly disable Codex CLI.
- `--no-claude`: Quickly disable Claude Code CLI.
- `--enable <agents>`: Only enable the specified models (e.g. `--enable codex,claude`).

*Dynamic Rerouting:* When a model is disabled:
- Any sub-task originally designated for it is automatically rerouted to the best available active model (following its fallback chain or alternative capabilities).
- Disabled models are automatically omitted from all fallback chains.

### 2. Persistent Configuration in `settings.json`
Edit [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):
```json
{
  "enabled_agents": {
    "antigravity": true,
    "codex": false,
    "claude": true
  }
}
```
Or as a list: `"disabled_agents": ["codex"]`.

---

## Context & Token Limit Configuration

Configure context limits and fallback behavior at [`ai-task-router/.agents/settings.json`](ai-task-router/.agents/settings.json):

```json
{
  "enabled_agents": {
    "antigravity": true,
    "codex": true,
    "claude": true
  },
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

