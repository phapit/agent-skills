"""Repo Map — bản đồ repository xếp hạng theo PageRank (kiểu aider).

Hỗ trợ: Python, TypeScript/JavaScript (Vue, Next.js, React), PHP.

5 bước:
  1. Liệt kê file: `git ls-files` nếu là git repo, ngược lại duyệt thư mục.
  2. Trích xuất ký hiệu: `ast` cho Python; regex theo ngôn ngữ cho JS/TS/Vue/PHP
     (def/class/function/interface/type + tham chiếu chéo qua tên định danh).
  3. Đồ thị tham chiếu: cạnh A->B với trọng số = số lần A tham chiếu ký hiệu
     định nghĩa trong B, nhân IDF của tên ký hiệu (tên phổ biến bị hạ trọng số).
  4. PageRank: xếp hạng file theo tầm quan trọng cấu trúc (thuần Python).
  5. Render: in chữ ký định nghĩa theo thứ hạng, dừng khi chạm token budget.
"""

import argparse
import ast
import glob
import json
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime

try:
    from tree_sitter import Language, Parser, Query, QueryCursor
    import tree_sitter_python as _ts_python
    import tree_sitter_php as _ts_php
    import tree_sitter_typescript as _ts_typescript
    TREE_SITTER_OK = True
except ImportError:
    TREE_SITTER_OK = False

try:
    import networkx as nx
    NETWORKX_OK = True
except ImportError:
    NETWORKX_OK = False

OUTPUT_DIR = "repo-map"
DEFAULT_TOKEN_BUDGET = 2000
MAX_SIGS_PER_FILE = 25

EXCLUDE_DIRS = {
    '.git', 'node_modules', '__pycache__', 'vendor',
    'dist', 'build', 'venv', '.venv', 'target', 'coverage',
    '.next', '.nuxt', '.output', 'out',
    '.claude', '.gemini', '.antigravity', '.cursor', '.agents',
    '.vscode', '.idea', OUTPUT_DIR,
}

# Định danh chung dùng để đếm tham chiếu (đa ngôn ngữ)
IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")


# ---------- Bước 1: Liệt kê file ----------
LANG_EXTS = {
    '.py': 'python',
    '.js': 'js', '.jsx': 'js', '.mjs': 'js', '.cjs': 'js',
    '.ts': 'js', '.tsx': 'js',
    '.vue': 'vue',
    '.php': 'php',
}


def normalize_excludes(patterns):
    """Chuẩn hoá các pattern --exclude thành đường dẫn tuyệt đối, có xử lý wildcard.

    Pattern luôn được hiểu theo cwd (nơi lệnh được thực thi) — giống cách gõ
    `root` — chứ không theo root_dir đang scan, để hỗ trợ đúng cả trường hợp
    wildcard nhiều cấp như `./app/*/vendor` khi root là `./app`.
    """
    norm = []
    for pattern in patterns or []:
        pattern = pattern.strip()
        if not pattern:
            continue
        if any(ch in pattern for ch in "*?["):
            norm.extend(os.path.normpath(os.path.abspath(p)) for p in glob.glob(pattern))
        else:
            norm.append(os.path.normpath(os.path.abspath(pattern)))
    return norm


def is_excluded(path, excludes):
    norm = os.path.normpath(os.path.abspath(path))
    for ex in excludes:
        ex_abs = os.path.normpath(os.path.abspath(ex))
        if norm == ex_abs or norm.startswith(ex_abs + os.sep):
            return True
    return False


def is_dir_excluded(path):
    parts = set(os.path.normpath(path).split(os.sep))
    return bool(parts & EXCLUDE_DIRS)


def get_source_files(root_dir=".", excludes=None):
    """git ls-files nếu là git repo; nếu không thì duyệt thư mục."""
    excludes = excludes or []

    try:
        result = subprocess.run(
            ["git", "-C", root_dir, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            files = [os.path.join(root_dir, f) for f in result.stdout.splitlines()]
            files = [f for f in files if os.path.splitext(f)[1] in LANG_EXTS]
            files = [f for f in files if not is_dir_excluded(f) and not is_excluded(f, excludes)]
            if files:
                return files
    except FileNotFoundError:
        pass  # không có git → fallback

    files = []
    for root, dirs, names in os.walk(root_dir):
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDE_DIRS and not d.startswith('.')
            and not is_excluded(os.path.join(root, d), excludes)
        ]
        for n in names:
            if os.path.splitext(n)[1] in LANG_EXTS:
                path = os.path.join(root, n)
                if not is_excluded(path, excludes):
                    files.append(path)
    return files


# ---------- Bước 2: Trích xuất ký hiệu ----------
def _refs_from_source(source):
    return Counter(IDENT_RE.findall(source))


# --- Python (ast) ---
def _py_signature(node):
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(_py_name(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    args = [a.arg for a in node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)})"


def _py_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "?"


def _extract_python_ast(source):
    """Fallback khi không có tree-sitter: dùng `ast` (chỉ Python)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return [], Counter()
    defs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.append((node.name, _py_signature(node)))
    return defs, _refs_from_source(source)


def extract_python(source):
    if TREE_SITTER_OK:
        try:
            parser, query = _get_ts_lang('python')
            src_bytes = source.encode("utf-8", "ignore")
            tree = parser.parse(src_bytes)
            matches = QueryCursor(query).matches(tree.root_node)
            defs = _ts_collect_defs(matches, src_bytes, skip_kinds={"constant"})
            return defs, _refs_from_source(source)
        except Exception:
            pass
    return _extract_python_ast(source)


# --- JS / TS / Vue (regex) ---
_JS_PATTERNS = [
    # (regex, template) — template dùng nhóm bắt (1) name, (2) params (nếu có)
    (re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"), "class {0}"),
    (re.compile(r"(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)"), "interface {0}"),
    (re.compile(r"(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*="), "type {0}"),
    (re.compile(r"(?:export\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)"), "enum {0}"),
    (re.compile(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
                r"([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"), "function {0}({1})"),
    (re.compile(r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                r"(?:async\s+)?(\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"), "const {0} = {1} =>"),
]


def _extract_js_regex(source):
    """Fallback khi không có tree-sitter: heuristic bằng regex."""
    found = {}  # name -> (pos, signature)  giữ định nghĩa đầu tiên theo vị trí
    for pattern, template in _JS_PATTERNS:
        for m in pattern.finditer(source):
            name = m.group(1)
            params = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
            sig = template.format(name, params)
            if name not in found or m.start() < found[name][0]:
                found[name] = (m.start(), sig)
    defs = [(name, sig) for name, (_, sig) in sorted(found.items(), key=lambda kv: kv[1][0])]
    return defs, _refs_from_source(source)


_TSX_EXTS = {".tsx", ".jsx", ".js", ".mjs", ".cjs"}


def extract_js(source, ext):
    """ext quyết định dialect: .tsx/.jsx/.js/.mjs/.cjs dùng grammar tsx (bao JSX),
    .ts/.mts/.cts dùng grammar typescript thuần."""
    if TREE_SITTER_OK:
        try:
            variant = "tsx" if ext in _TSX_EXTS else "typescript"
            parser, query = _get_ts_lang(variant)
            src_bytes = source.encode("utf-8", "ignore")
            tree = parser.parse(src_bytes)
            matches = QueryCursor(query).matches(tree.root_node)
            defs = _ts_collect_defs(matches, src_bytes)
            return defs, _refs_from_source(source)
        except Exception:
            pass
    return _extract_js_regex(source)


_VUE_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def extract_vue(source, path):
    scripts = "\n".join(_VUE_SCRIPT_RE.findall(source))
    defs, refs = extract_js(scripts, ".ts")
    # Component name theo tên file (PascalCase) → tạo cạnh khi file khác import
    stem = os.path.splitext(os.path.basename(path))[0]
    comp = re.sub(r"[^A-Za-z0-9]", " ", stem).title().replace(" ", "")
    if comp and all(comp != n for n, _ in defs):
        defs.insert(0, (comp, f"component {comp}"))
    return defs, refs


# --- PHP (regex) ---
_PHP_PATTERNS = [
    (re.compile(r"(?:abstract\s+|final\s+)?class\s+([A-Za-z_][\w]*)"), "class {0}"),
    (re.compile(r"interface\s+([A-Za-z_][\w]*)"), "interface {0}"),
    (re.compile(r"trait\s+([A-Za-z_][\w]*)"), "trait {0}"),
    (re.compile(r"(?:public\s+|private\s+|protected\s+|static\s+)*function\s+"
                r"([A-Za-z_][\w]*)\s*\(([^)]*)\)"), "function {0}({1})"),
]


def _extract_php_regex(source):
    """Fallback khi không có tree-sitter: heuristic bằng regex."""
    found = {}
    for pattern, template in _PHP_PATTERNS:
        for m in pattern.finditer(source):
            name = m.group(1)
            params = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
            sig = template.format(name, re.sub(r"\s+", " ", params))
            if name not in found or m.start() < found[name][0]:
                found[name] = (m.start(), sig)
    defs = [(name, sig) for name, (_, sig) in sorted(found.items(), key=lambda kv: kv[1][0])]
    return defs, _refs_from_source(source)


def extract_php(source):
    if TREE_SITTER_OK:
        try:
            parser, query = _get_ts_lang("php")
            src_bytes = source.encode("utf-8", "ignore")
            tree = parser.parse(src_bytes)
            matches = QueryCursor(query).matches(tree.root_node)
            defs = _ts_collect_defs(matches, src_bytes, skip_kinds={"module", "field"})
            return defs, _refs_from_source(source)
        except Exception:
            pass
    return _extract_php_regex(source)


# --- Tree-sitter: lõi trích xuất chính xác (fallback quy về ast/regex ở trên) ---
_TS_TSX_QUERY_SRC = """
(class_declaration name: (type_identifier) @name) @definition.class
(interface_declaration name: (type_identifier) @name) @definition.interface
(type_alias_declaration name: (type_identifier) @name) @definition.type
(enum_declaration name: (identifier) @name) @definition.enum
(function_declaration name: (identifier) @name) @definition.function
(method_definition name: (property_identifier) @name) @definition.method
(variable_declarator name: (identifier) @name value: (arrow_function)) @definition.function
(variable_declarator name: (identifier) @name value: (function_expression)) @definition.function
(assignment_expression
  left: (member_expression property: (property_identifier) @name)
  right: [(function_expression) (arrow_function)]) @definition.method
(assignment_expression
  left: (identifier) @name
  right: [(function_expression) (arrow_function)]) @definition.function
"""

_TS_KIND_LABEL = {
    "class_declaration": "class", "class_definition": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "function_declaration": "function", "function_definition": "function",
    "method_definition": "method", "method_declaration": "method",
    "variable_declarator": "const",
}

_TS_LANG_CACHE = {}


def _get_ts_lang(name):
    """Trả về (parser, query) đã build sẵn, cache theo tên dialect."""
    if name in _TS_LANG_CACHE:
        return _TS_LANG_CACHE[name]

    if name == "python":
        lang = Language(_ts_python.language())
        query_src = _ts_python.TAGS_QUERY
    elif name == "php":
        lang = Language(_ts_php.language_php())
        query_src = _ts_php.TAGS_QUERY
    elif name == "typescript":
        lang = Language(_ts_typescript.language_typescript())
        query_src = _TS_TSX_QUERY_SRC
    elif name == "tsx":
        lang = Language(_ts_typescript.language_tsx())
        query_src = _TS_TSX_QUERY_SRC
    else:
        raise ValueError(name)

    parser = Parser(lang)
    query = Query(lang, query_src)
    _TS_LANG_CACHE[name] = (parser, query)
    return _TS_LANG_CACHE[name]


_TRAIL_RE = re.compile(r"[:=]\s*$")


def _ts_header(node, src_bytes):
    """Chữ ký 1 dòng: phần trước thân hàm/lớp (field 'body' nếu có)."""
    body = node.child_by_field_name("body")
    if body is None and node.type == "assignment_expression":
        rhs = node.child_by_field_name("right")
        if rhs is not None:
            body = rhs.child_by_field_name("body")
    end = body.start_byte if body else node.end_byte
    text = src_bytes[node.start_byte:end].decode("utf-8", "ignore").strip()
    if not text:
        text = src_bytes[node.start_byte:node.end_byte].decode("utf-8", "ignore").strip()
    line = text.splitlines()[0].strip()
    return _TRAIL_RE.sub("", line).strip()


def _ts_collect_defs(matches, src_bytes, skip_kinds=()):
    """Gom (name, signature) từ kết quả QueryCursor.matches, giữ thứ tự xuất hiện."""
    found = []
    for _, captures in matches:
        def_node = kind = None
        for cap, nodes in captures.items():
            if cap.startswith("definition."):
                def_node, kind = nodes[0], cap.split(".", 1)[1]
        name_nodes = captures.get("name")
        if def_node is None or not name_nodes:
            continue
        label = _TS_KIND_LABEL.get(def_node.type, kind)
        if label in skip_kinds:
            continue
        name = src_bytes[name_nodes[0].start_byte:name_nodes[0].end_byte].decode("utf-8", "ignore")
        sig = _ts_header(def_node, src_bytes)
        if def_node.type == "variable_declarator":
            sig = f"const {sig}"  # 'const'/'let'/'var' nằm ở node cha, không có trong node này
        found.append((def_node.start_byte, name, sig))
    found.sort(key=lambda x: x[0])
    return [(name, sig) for _, name, sig in found]


def extract_symbols(files):
    """Trả về (definitions, references, signatures)."""
    definitions = defaultdict(set)
    references = {}
    signatures = defaultdict(list)

    for path in files:
        lang = LANG_EXTS.get(os.path.splitext(path)[1])
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except OSError:
            continue

        if lang == 'python':
            defs, refs = extract_python(source)
        elif lang == 'vue':
            defs, refs = extract_vue(source, path)
        elif lang == 'php':
            defs, refs = extract_php(source)
        elif lang == 'js':
            defs, refs = extract_js(source, os.path.splitext(path)[1])
        else:
            continue

        for name, sig in defs:
            definitions[name].add(path)
            signatures[path].append(sig)
        references[path] = refs

    return definitions, references, signatures


# ---------- Bước 3: Đồ thị tham chiếu (references × IDF) ----------
def build_reference_graph(files, definitions, references):
    n = max(len(files), 1)
    idf = {
        sym: math.log(1 + n / len(defining))
        for sym, defining in definitions.items()
    }

    edges = defaultdict(float)
    for a in files:
        for sym, count in references.get(a, {}).items():
            defining = definitions.get(sym)
            if not defining:
                continue  # ký hiệu ngoài repo → bỏ qua
            weight = count * idf[sym]
            for b in defining:
                if b != a:
                    edges[(a, b)] += weight
    return edges


# ---------- Bước 4: PageRank ----------
def pagerank(files, edges, damping=0.85, iterations=60, tol=1e-6):
    """Ưu tiên networkx nếu có sẵn; nếu không thì rơi về cài đặt thuần Python."""
    if NETWORKX_OK:
        try:
            return _pagerank_networkx(files, edges, damping)
        except Exception:
            pass
    return _pagerank_pure(files, edges, damping, iterations, tol)


def _pagerank_networkx(files, edges, damping):
    graph = nx.DiGraph()
    graph.add_nodes_from(files)
    for (a, b), w in edges.items():
        graph.add_edge(a, b, weight=w)
    return nx.pagerank(graph, alpha=damping, weight="weight")


def _pagerank_pure(files, edges, damping=0.85, iterations=60, tol=1e-6):
    nodes = list(files)
    n = len(nodes)
    if n == 0:
        return {}

    out_weight = defaultdict(float)
    out_edges = defaultdict(list)
    for (a, b), w in edges.items():
        out_weight[a] += w
        out_edges[a].append((b, w))

    rank = {node: 1.0 / n for node in nodes}
    base = (1.0 - damping) / n

    for _ in range(iterations):
        new = {node: base for node in nodes}
        dangling = sum(rank[a] for a in nodes if out_weight[a] == 0.0)
        dangling_share = damping * dangling / n
        for a in nodes:
            if out_weight[a] > 0.0:
                for b, w in out_edges[a]:
                    new[b] += damping * rank[a] * w / out_weight[a]
        for node in nodes:
            new[node] += dangling_share
        delta = sum(abs(new[node] - rank[node]) for node in nodes)
        rank = new
        if delta < tol:
            break
    return rank


# ---------- Bước 5: Render, phân trang theo token budget ----------
def render_map_pages(root_dir, ranked, signatures, max_tokens=DEFAULT_TOKEN_BUDGET):
    """Chia bản đồ thành nhiều trang, mỗi trang <= max_tokens (ước lượng).

    Khi một trang đầy, mở trang mới thay vì cắt bớt nội dung — để không mất
    thông tin ở các dự án lớn/multi-site.
    """
    pages = []
    lines = ["# REPOSITORY MAP (xếp hạng theo PageRank)"]
    used = 0

    ordered = sorted(ranked.items(), key=lambda kv: kv[1], reverse=True)
    for path, score in ordered:
        syms = signatures.get(path, [])
        if not syms:
            continue
        rel = os.path.relpath(path, root_dir)
        shown = syms[:MAX_SIGS_PER_FILE]
        block = [f"\n### {rel}  (PR {score:.4f})"]
        block += [f"  - {s}" for s in shown]
        if len(syms) > MAX_SIGS_PER_FILE:
            block.append(f"  - … (+{len(syms) - MAX_SIGS_PER_FILE} ký hiệu)")
        cost = sum(len(x) for x in block) // 4

        if used + cost > max_tokens and used > 0:
            pages.append("\n".join(lines))
            lines = ["# REPOSITORY MAP (tiếp theo)"]
            used = 0

        lines.extend(block)
        used += cost

    pages.append("\n".join(lines))
    return pages


def scan_prefix(root_dir):
    """Tên tiền tố file output, suy ra từ tên thư mục được scan.

    './app/backend' -> 'backend'; '.' hoặc '/' -> tên thư mục hiện hành.
    """
    name = os.path.basename(os.path.normpath(os.path.abspath(root_dir)))
    name = re.sub(r"[^\w.-]+", "-", name).strip("-") or "repo"
    return name


def _clear_old_output(out_dir, prefix):
    for f in glob.glob(os.path.join(out_dir, f"{prefix}_repo_map.md")):
        os.remove(f)
    for f in glob.glob(os.path.join(out_dir, f"{prefix}_repo_map.part.*.md")):
        os.remove(f)


def write_pages(out_dir, prefix, pages, file_count, timestamp):
    """Ghi các trang vào out_dir (luôn là repo-map/ tại nơi lệnh được thực thi),
    đặt tên theo prefix của thư mục đã scan — không đụng tới output của prefix khác.
    """
    os.makedirs(out_dir, exist_ok=True)
    _clear_old_output(out_dir, prefix)

    total = len(pages)
    written = []

    for i, page in enumerate(pages, 1):
        if total == 1:
            name = f"{prefix}_repo_map.md"
        else:
            name = f"{prefix}_repo_map.part.{i}.md"
        header = f"<!-- generated {timestamp} · {file_count} files"
        if total > 1:
            header += f" · part {i}/{total}"
        header += " -->\n\n"
        out_path = os.path.join(out_dir, name)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(header + page + "\n")
        written.append(out_path)

    return written


def _load_index_state(out_dir):
    path = os.path.join(out_dir, ".index.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def update_index(out_dir, prefix, root_dir, file_count, written, timestamp):
    """Cập nhật repo-map/INDEX.md — mục lục các lần scan đã gom vào out_dir,
    để AI Coding Agent (Antigravity, Claude Code, Codex, Cursor...) biết trong
    repo-map/ có gì mà không cần tự liệt kê thư mục.
    """
    state = _load_index_state(out_dir)
    state[prefix] = {
        "root": os.path.relpath(os.path.abspath(root_dir), os.getcwd()),
        "file_count": file_count,
        "files": [os.path.basename(p) for p in written],
        "timestamp": timestamp,
    }
    with open(os.path.join(out_dir, ".index.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    lines = [
        "# INDEX — các lần scan đã gom vào repo-map/",
        "",
        "| Prefix | Sub-path đã scan | Số file | File output | Cập nhật |",
        "|---|---|---|---|---|",
    ]
    for pfx in sorted(state):
        info = state[pfx]
        files_md = ", ".join(f"[{name}]({name})" for name in info["files"])
        lines.append(f"| {pfx} | `{info['root']}` | {info['file_count']} | {files_md} | {info['timestamp']} |")

    with open(os.path.join(out_dir, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Repo Map — PageRank-ranked repository map cho AI Coding Agents (Antigravity, Claude Code, Codex, Cursor...)"
    )
    parser.add_argument("root", nargs="?", default=".", help="Thư mục gốc để quét")
    parser.add_argument("budget", nargs="?", type=int, default=DEFAULT_TOKEN_BUDGET,
                         help="Token budget mỗi trang (mặc định 2000)")
    parser.add_argument(
        "--exclude", "-e", nargs="+", action="extend", default=[],
        help="Sub-path loại trừ khỏi lần quét (có thể lặp lại nhiều lần). "
             "Nhận nhiều giá trị nếu wildcard bị shell tự expand trước khi "
             "vào Python. Ví dụ: --exclude ./app/vendor --exclude ./sites/*/storage",
    )
    parser.add_argument(
        "--output-dir", "--out", "-o", default=OUTPUT_DIR,
        help=f"Thư mục lưu kết quả (mặc định: {OUTPUT_DIR})",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    root_dir = args.root
    budget = args.budget
    excludes = normalize_excludes(args.exclude)

    files = get_source_files(root_dir, excludes)
    if not files:
        print("Không tìm thấy file mã nguồn hỗ trợ (.py/.ts/.tsx/.js/.jsx/.vue/.php).")
        return

    definitions, references, signatures = extract_symbols(files)
    edges = build_reference_graph(files, definitions, references)
    ranked = pagerank(files, edges)
    pages = render_map_pages(root_dir, ranked, signatures, budget)

    # Thư mục output mặc định là repo-map/ tại nơi lệnh được thực thi (cwd), không phải root_dir
    # đang scan — cho phép gom nhiều lần scan (nhiều sub-path) về cùng một chỗ,
    # phân biệt bằng prefix theo tên thư mục scan.
    out_dir = os.path.join(os.getcwd(), args.output_dir)
    prefix = scan_prefix(root_dir)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    written = write_pages(out_dir, prefix, pages, len(files), timestamp)
    update_index(out_dir, prefix, root_dir, len(files), written, timestamp)

    for page in pages:
        print(page)
        print()

    if len(written) == 1:
        print(f"✅ Đã lưu bản đồ vào: {written[0]}")
    else:
        print(f"✅ Đã lưu bản đồ thành {len(written)} phần:")
        for path in written:
            print(f"   - {path}")


if __name__ == "__main__":
    main()
