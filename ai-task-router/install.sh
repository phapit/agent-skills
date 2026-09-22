#!/usr/bin/env bash
# Universal Skill Installer for ai-task-router
# Hỗ trợ tự động symlink skill cho Claude Code, Antigravity, và Codex.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="ai-task-router"

echo "============================================================"
echo "  Cài đặt Skill: ${SKILL_NAME} (Multi-Agent Router)"
echo "  Source path: ${SCRIPT_DIR}"
echo "============================================================"

# Danh sách các thư mục skill chuẩn của các AI CLI
TARGETS=(
  "$HOME/.claude/skills/${SKILL_NAME}"
  "$HOME/.gemini/config/skills/${SKILL_NAME}"
  "$HOME/.codex/skills/${SKILL_NAME}"
  "$HOME/.agents/skills/${SKILL_NAME}"
)

# Tạo symlink cho từng target
for target in "${TARGETS[@]}"; do
  parent_dir="$(dirname "$target")"
  mkdir -p "$parent_dir"
  
  if [ -L "$target" ]; then
    echo "[Symlink] Đã tồn tại symlink: $target -> cập nhật lại."
    rm "$target"
  elif [ -d "$target" ]; then
    echo "[Cảnh báo] Thư mục $target đã tồn tại (không phải symlink). Đổi tên thành ${target}.bak"
    mv "$target" "${target}.bak.$(date +%s)"
  fi

  ln -sf "$SCRIPT_DIR" "$target"
  echo "[OK] Đã link: $target -> $SCRIPT_DIR"
done

echo "------------------------------------------------------------"
echo "Kiểm tra các công cụ phụ thuộc trên hệ thống:"
for cmd in python3 agy claude codex tmux; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "  [✓] $cmd: $(which "$cmd")"
  else
    echo "  [✗] $cmd: Chưa cài đặt / không có trên PATH"
  fi
done

echo "============================================================"
echo "Cài đặt thành công! Skill sẵn sàng hoạt động trên Claude, Antigravity và Codex."
echo "============================================================"
