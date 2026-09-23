#!/usr/bin/env bash
# Universal Skill Installer for repo-map
# Hỗ trợ tự động symlink skill cho Antigravity, Claude Code, Codex, và các AI Agent CLI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="repo-map"

echo "============================================================"
echo "  Cài đặt Skill: ${SKILL_NAME} (PageRank Repository Map)"
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
echo "Kiểm tra môi trường Python và các gói phụ trợ:"

if command -v python3 >/dev/null 2>&1; then
  echo "  [✓] python3: $(which python3)"
else
  echo "  [✗] python3: Chưa cài đặt. Vui lòng cài đặt Python 3!"
fi

# Kiểm tra các thư viện tăng tốc / AST parser (tuỳ chọn)
python3 -c "
import sys

def check_pkg(pkg, desc):
    try:
        __import__(pkg)
        print(f'  [✓] {pkg}: Đã cài đặt ({desc})')
    except ImportError:
        print(f'  [i] {pkg}: Chưa cài đặt ({desc} - script sẽ tự động dùng fallback)')

check_pkg('networkx', 'Tối ưu tốc độ PageRank')
check_pkg('tree_sitter', 'Phân tích cú pháp AST chính xác cao')
check_pkg('tree_sitter_python', 'Grammar Python')
check_pkg('tree_sitter_typescript', 'Grammar TS/JS')
check_pkg('tree_sitter_php', 'Grammar PHP')
" || true

echo "------------------------------------------------------------"
echo "Để cài đặt đầy đủ các thư viện phân tích nâng cao (tùy chọn):"
echo "  pip install networkx tree-sitter tree-sitter-python tree-sitter-typescript tree-sitter-php"
echo "============================================================"
echo "Cài đặt thành công! Skill sẵn sàng hoạt động trên Antigravity, Claude Code, Codex và các AI CLI."
echo "============================================================"
