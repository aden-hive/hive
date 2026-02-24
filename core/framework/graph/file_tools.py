"""Built-in file and command tools for EventLoopNode.

Provides 6 tools (read_file, write_file, edit_file, list_directory,
search_files, run_command) that are always available when spillover is
configured.  Adapted from tools/coder_tools_server.py with PROJECT_ROOT
scoping removed — all paths are absolute.

Public API:
    build_file_tools() -> list[Tool]   — 6 Tool schema objects
    is_file_tool(name) -> bool         — membership check
    execute_file_tool(name, inputs)    — dispatch + catch exceptions
"""

from __future__ import annotations

import difflib
import fnmatch
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from framework.llm.provider import Tool, ToolResult

logger = logging.getLogger(__name__)

# ── Constants (matching coder_tools_server.py) ────────────────────────────

MAX_READ_LINES = 2000
MAX_LINE_LENGTH = 2000
MAX_OUTPUT_BYTES = 50 * 1024  # 50KB byte budget for read output
MAX_COMMAND_OUTPUT = 30_000  # chars before truncation
SEARCH_RESULT_LIMIT = 100

BINARY_EXTENSIONS = frozenset(
    {
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".class",
        ".jar", ".war", ".pyc", ".pyo", ".wasm",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
        ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        ".o", ".a", ".lib", ".obj",
    }
)

FILE_TOOL_NAMES = frozenset({
    "read_file", "write_file", "edit_file",
    "list_directory", "search_files", "run_command",
})

# ── Public API ────────────────────────────────────────────────────────────


def build_file_tools() -> list[Tool]:
    """Return 6 Tool schema objects for the built-in file tools."""
    return [
        Tool(
            name="read_file",
            description=(
                "Read file contents with line numbers and byte-budget truncation. "
                "Binary files are detected and rejected. Large files are automatically "
                "truncated at 2000 lines or 50KB. Use offset and limit to paginate."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path to read.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Starting line number, 1-indexed (default: 1).",
                        "default": 1,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lines to return, 0 = up to 2000 (default: 0).",
                        "default": 0,
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="write_file",
            description=(
                "Create or overwrite a file with the given content. "
                "Automatically creates parent directories."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content to write.",
                    },
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="edit_file",
            description=(
                "Replace text in a file using a fuzzy-match cascade. "
                "Tries exact match first, then falls back through increasingly "
                "fuzzy strategies: line-trimmed, block-anchor, whitespace-normalized, "
                "indentation-flexible, and trimmed-boundary matching."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path to edit.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Text to find (fuzzy matching applied if exact fails).",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences (default: first only).",
                        "default": False,
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        ),
        Tool(
            name="list_directory",
            description=(
                "List directory contents with type indicators. "
                "Directories have a / suffix. Hidden files and common "
                "build directories are skipped."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute directory path (default: current directory).",
                        "default": ".",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively (default: false). Truncates at 500 entries.",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="search_files",
            description=(
                "Search file contents using regex. Uses ripgrep when available, "
                "falls back to Python regex. Results sorted by file with line numbers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute directory path to search (default: current directory).",
                        "default": ".",
                    },
                    "include": {
                        "type": "string",
                        "description": "File glob filter (e.g. '*.py').",
                        "default": "",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="run_command",
            description=(
                "Execute a shell command. Output is truncated at 30K chars. "
                "Timeout defaults to 120s, max 300s."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory (absolute path). Defaults to current directory.",
                        "default": "",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 120, max: 300).",
                        "default": 120,
                    },
                },
                "required": ["command"],
            },
        ),
    ]


def is_file_tool(name: str) -> bool:
    """Check if *name* is a built-in file tool."""
    return name in FILE_TOOL_NAMES


def execute_file_tool(name: str, inputs: dict, tool_use_id: str = "") -> ToolResult:
    """Dispatch to the appropriate handler, catch exceptions.

    Returns a ToolResult. On exception the result has ``is_error=True``.
    """
    handlers = {
        "read_file": _handle_read_file,
        "write_file": _handle_write_file,
        "edit_file": _handle_edit_file,
        "list_directory": _handle_list_directory,
        "search_files": _handle_search_files,
        "run_command": _handle_run_command,
    }
    handler = handlers.get(name)
    if handler is None:
        return ToolResult(
            tool_use_id=tool_use_id,
            content=f"Unknown file tool: {name}",
            is_error=True,
        )
    try:
        content = handler(**inputs)
        return ToolResult(tool_use_id=tool_use_id, content=content, is_error=False)
    except Exception as e:
        logger.warning("file_tool %s raised: %s", name, e, exc_info=True)
        return ToolResult(
            tool_use_id=tool_use_id,
            content=f"Error in {name}: {e}",
            is_error=True,
        )


# ── Private helpers ───────────────────────────────────────────────────────


def _is_binary(filepath: str) -> bool:
    """Detect binary files by extension and content sampling."""
    _, ext = os.path.splitext(filepath)
    if ext.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(4096)
        if b"\x00" in chunk:
            return True
        non_printable = sum(1 for b in chunk if b < 9 or (13 < b < 32) or b > 126)
        return non_printable / max(len(chunk), 1) > 0.3
    except OSError:
        return False


def _levenshtein(a: str, b: str) -> int:
    """Standard Levenshtein distance."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _similarity(a: str, b: str) -> float:
    maxlen = max(len(a), len(b))
    if maxlen == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / maxlen


def _fuzzy_find_candidates(content: str, old_text: str):
    """Yield candidate substrings from content that match old_text,
    using a cascade of increasingly fuzzy strategies.
    """
    # Strategy 1: Exact match
    if old_text in content:
        yield old_text

    content_lines = content.split("\n")
    search_lines = old_text.split("\n")
    # Strip trailing empty line from search (common copy-paste artifact)
    while search_lines and not search_lines[-1].strip():
        search_lines = search_lines[:-1]
    if not search_lines:
        return

    n_search = len(search_lines)

    # Strategy 2: Line-trimmed match
    for i in range(len(content_lines) - n_search + 1):
        window = content_lines[i : i + n_search]
        if all(cl.strip() == sl.strip() for cl, sl in zip(window, search_lines, strict=True)):
            yield "\n".join(window)

    # Strategy 3: Block-anchor match (first/last line as anchors, fuzzy middle)
    if n_search >= 3:
        first_trimmed = search_lines[0].strip()
        last_trimmed = search_lines[-1].strip()
        candidates = []
        for i, line in enumerate(content_lines):
            if line.strip() == first_trimmed:
                end = i + n_search
                if end <= len(content_lines) and content_lines[end - 1].strip() == last_trimmed:
                    block = content_lines[i:end]
                    middle_content = "\n".join(block[1:-1])
                    middle_search = "\n".join(search_lines[1:-1])
                    sim = _similarity(middle_content, middle_search)
                    candidates.append((sim, "\n".join(block)))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            if candidates[0][0] > 0.3:
                yield candidates[0][1]

    # Strategy 4: Whitespace-normalized match
    normalized_search = re.sub(r"\s+", " ", old_text).strip()
    for i in range(len(content_lines) - n_search + 1):
        window = content_lines[i : i + n_search]
        normalized_block = re.sub(r"\s+", " ", "\n".join(window)).strip()
        if normalized_block == normalized_search:
            yield "\n".join(window)

    # Strategy 5: Indentation-flexible match
    def _strip_indent(lines):
        non_empty = [ln for ln in lines if ln.strip()]
        if not non_empty:
            return "\n".join(lines)
        min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
        return "\n".join(ln[min_indent:] for ln in lines)

    stripped_search = _strip_indent(search_lines)
    for i in range(len(content_lines) - n_search + 1):
        block = content_lines[i : i + n_search]
        if _strip_indent(block) == stripped_search:
            yield "\n".join(block)

    # Strategy 6: Trimmed-boundary match
    trimmed = old_text.strip()
    if trimmed != old_text and trimmed in content:
        yield trimmed


def _compute_diff(old: str, new: str, path: str) -> str:
    """Compute a unified diff for display."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=path, tofile=path, n=3)
    result = "".join(diff)
    if len(result) > 2000:
        result = result[:2000] + "\n... (diff truncated)"
    return result


# ── Handlers ──────────────────────────────────────────────────────────────


def _handle_read_file(path: str, offset: int = 1, limit: int = 0, **_kw) -> str:
    """Read file contents with line numbers and byte-budget truncation."""
    resolved = str(Path(path).resolve())

    if os.path.isdir(resolved):
        entries = []
        for entry in sorted(os.listdir(resolved)):
            full = os.path.join(resolved, entry)
            suffix = "/" if os.path.isdir(full) else ""
            entries.append(f"  {entry}{suffix}")
        total = len(entries)
        return f"Directory: {path} ({total} entries)\n" + "\n".join(entries[:200])

    if not os.path.isfile(resolved):
        return f"Error: File not found: {path}"

    if _is_binary(resolved):
        size = os.path.getsize(resolved)
        return f"Binary file: {path} ({size:,} bytes). Cannot display binary content."

    try:
        with open(resolved, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        start_idx = max(0, offset - 1)
        effective_limit = limit if limit > 0 else MAX_READ_LINES
        end_idx = min(start_idx + effective_limit, total_lines)

        output_lines = []
        byte_count = 0
        truncated_by_bytes = False
        for i in range(start_idx, end_idx):
            line = all_lines[i].rstrip("\n\r")
            if len(line) > MAX_LINE_LENGTH:
                line = line[:MAX_LINE_LENGTH] + "..."
            formatted = f"{i + 1:>6}\t{line}"
            line_bytes = len(formatted.encode("utf-8")) + 1
            if byte_count + line_bytes > MAX_OUTPUT_BYTES:
                truncated_by_bytes = True
                break
            output_lines.append(formatted)
            byte_count += line_bytes

        result = "\n".join(output_lines)

        lines_shown = len(output_lines)
        actual_end = start_idx + lines_shown
        if actual_end < total_lines or truncated_by_bytes:
            result += f"\n\n(Showing lines {start_idx + 1}-{actual_end} of {total_lines}."
            if truncated_by_bytes:
                result += " Truncated by byte budget."
            result += f" Use offset={actual_end + 1} to continue reading.)"

        return result
    except Exception as e:
        return f"Error reading file: {e}"


def _handle_write_file(path: str, content: str, **_kw) -> str:
    """Create or overwrite a file."""
    resolved = str(Path(path).resolve())

    try:
        existed = os.path.isfile(resolved)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        action = "Updated" if existed else "Created"
        return f"{action} {path} ({len(content):,} bytes, {line_count} lines)"
    except Exception as e:
        return f"Error writing file: {e}"


def _handle_edit_file(
    path: str, old_text: str, new_text: str, replace_all: bool = False, **_kw
) -> str:
    """Replace text in a file using a fuzzy-match cascade."""
    resolved = str(Path(path).resolve())
    if not os.path.isfile(resolved):
        return f"Error: File not found: {path}"

    try:
        with open(resolved, encoding="utf-8") as f:
            content = f.read()

        matched_text = None
        strategy_used = None
        strategies = [
            "exact",
            "line-trimmed",
            "block-anchor",
            "whitespace-normalized",
            "indentation-flexible",
            "trimmed-boundary",
        ]

        for i, candidate in enumerate(_fuzzy_find_candidates(content, old_text)):
            idx = content.find(candidate)
            if idx == -1:
                continue

            if replace_all:
                matched_text = candidate
                strategy_used = strategies[min(i, len(strategies) - 1)]
                break

            last_idx = content.rfind(candidate)
            if idx == last_idx:
                matched_text = candidate
                strategy_used = strategies[min(i, len(strategies) - 1)]
                break

        if matched_text is None:
            close = difflib.get_close_matches(
                old_text[:200], content.split("\n"), n=3, cutoff=0.4
            )
            msg = f"Error: Could not find a unique match for old_text in {path}."
            if close:
                suggestions = "\n".join(f"  {line}" for line in close)
                msg += f"\n\nDid you mean one of these lines?\n{suggestions}"
            return msg

        if replace_all:
            count = content.count(matched_text)
            new_content = content.replace(matched_text, new_text)
        else:
            count = 1
            new_content = content.replace(matched_text, new_text, 1)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        diff = _compute_diff(content, new_content, path)
        match_info = f" (matched via {strategy_used})" if strategy_used != "exact" else ""
        result = f"Replaced {count} occurrence(s) in {path}{match_info}"
        if diff:
            result += f"\n\n{diff}"
        return result
    except Exception as e:
        return f"Error editing file: {e}"


def _handle_list_directory(path: str = ".", recursive: bool = False, **_kw) -> str:
    """List directory contents with type indicators."""
    resolved = str(Path(path).resolve())
    if not os.path.isdir(resolved):
        return f"Error: Directory not found: {path}"

    try:
        skip = {
            ".git", "__pycache__", "node_modules", ".venv",
            ".tox", ".mypy_cache", ".ruff_cache",
        }
        entries: list[str] = []
        if recursive:
            for root, dirs, files in os.walk(resolved):
                dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith("."))
                rel_root = os.path.relpath(root, resolved)
                if rel_root == ".":
                    rel_root = ""
                for f in sorted(files):
                    if f.startswith("."):
                        continue
                    entries.append(os.path.join(rel_root, f) if rel_root else f)
                    if len(entries) >= 500:
                        entries.append("... (truncated at 500 entries)")
                        return "\n".join(entries)
        else:
            for entry in sorted(os.listdir(resolved)):
                if entry.startswith(".") or entry in skip:
                    continue
                full = os.path.join(resolved, entry)
                suffix = "/" if os.path.isdir(full) else ""
                entries.append(f"{entry}{suffix}")

        return "\n".join(entries) if entries else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


def _handle_search_files(pattern: str, path: str = ".", include: str = "", **_kw) -> str:
    """Search file contents using regex. Ripgrep with Python fallback."""
    resolved = str(Path(path).resolve())
    if not os.path.isdir(resolved):
        return f"Error: Directory not found: {path}"

    # Try ripgrep first
    try:
        cmd = [
            "rg", "-nH", "--no-messages", "--hidden",
            "--max-count=20", "--glob=!.git/*",
            pattern,
        ]
        if include:
            cmd.extend(["--glob", include])
        cmd.append(resolved)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode <= 1:
            output = result.stdout.strip()
            if not output:
                return "No matches found."

            lines = []
            for line in output.split("\n")[:SEARCH_RESULT_LIMIT]:
                if len(line) > MAX_LINE_LENGTH:
                    line = line[:MAX_LINE_LENGTH] + "..."
                lines.append(line)
            total = output.count("\n") + 1
            result_str = "\n".join(lines)
            if total > SEARCH_RESULT_LIMIT:
                result_str += (
                    f"\n\n... ({total} total matches, showing first {SEARCH_RESULT_LIMIT})"
                )
            return result_str
    except FileNotFoundError:
        pass  # ripgrep not installed — fall through to Python
    except subprocess.TimeoutExpired:
        return "Error: Search timed out after 30 seconds"

    # Fallback: Python regex
    try:
        compiled = re.compile(pattern)
        matches: list[str] = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", ".tox"}

        for root, dirs, files in os.walk(resolved):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if compiled.search(line):
                                matches.append(
                                    f"{fpath}:{i}:{line.rstrip()[:MAX_LINE_LENGTH]}"
                                )
                                if len(matches) >= SEARCH_RESULT_LIMIT:
                                    return "\n".join(matches) + "\n... (truncated)"
                except (OSError, UnicodeDecodeError):
                    continue

        return "\n".join(matches) if matches else "No matches found."
    except re.error as e:
        return f"Error: Invalid regex: {e}"


def _handle_run_command(command: str, cwd: str = "", timeout: int = 120, **_kw) -> str:
    """Execute a shell command."""
    timeout = min(timeout, 300)
    work_dir = cwd if cwd else None

    try:
        start = time.monotonic()
        result = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")

        output = "\n".join(parts)

        if len(output) > MAX_COMMAND_OUTPUT:
            output = (
                output[:MAX_COMMAND_OUTPUT]
                + f"\n\n... (output truncated at {MAX_COMMAND_OUTPUT:,} chars)"
            )

        code = result.returncode
        output += f"\n\n[exit code: {code}, {elapsed:.1f}s]"
        return output
    except subprocess.TimeoutExpired:
        return (
            f"Error: Command timed out after {timeout}s. "
            "Consider breaking it into smaller operations."
        )
    except Exception as e:
        return f"Error executing command: {e}"
