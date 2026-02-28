"""
Shared file operation tools for MCP servers.

Provides 6 tools (read_file, write_file, edit_file, list_directory, search_files,
run_command) plus supporting helpers. Used by both files_server.py (unsandboxed)
and coder_tools_server.py (project-root sandboxed with git snapshots).

Usage:
    from aden_tools.file_ops import register_file_tools

    mcp = FastMCP("my-server")
    register_file_tools(mcp)                       # unsandboxed defaults
    register_file_tools(mcp, resolve_path=fn, ...)  # sandboxed with hooks
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from fastmcp import FastMCP

# ── Constants ─────────────────────────────────────────────────────────────

MAX_READ_LINES = 2000
MAX_LINE_LENGTH = 2000
MAX_OUTPUT_BYTES = 50 * 1024  # 50KB byte budget for read output
MAX_COMMAND_OUTPUT = 30_000  # chars before truncation
SEARCH_RESULT_LIMIT = 100

BINARY_EXTENSIONS = frozenset(
    {
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".class",
        ".jar",
        ".war",
        ".pyc",
        ".pyo",
        ".wasm",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".wav",
        ".flac",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".sqlite",
        ".db",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        ".o",
        ".a",
        ".lib",
        ".obj",
    }
)

# ── Private helpers ───────────────────────────────────────────────────────


def _default_resolve_path(p: str) -> str:
    """Default path resolver — just resolves to absolute."""
    return str(Path(p).resolve())


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


# ── Factory ───────────────────────────────────────────────────────────────


def register_file_tools(
    mcp: FastMCP,
    *,
    resolve_path: Callable[[str], str] | None = None,
    before_write: Callable[[], None] | None = None,
    project_root: str | None = None,
) -> None:
    """Register the 5 shared file tools on an MCP server.

    Args:
        mcp: FastMCP instance to register tools on.
        resolve_path: Path resolver. Default: resolve to absolute path.
            Raise ValueError to reject paths (e.g. outside sandbox).
        before_write: Hook called before write/edit operations (e.g. git snapshot).
        project_root: If set, search_files relativizes output paths to this root.
    """
    _resolve = resolve_path or _default_resolve_path

    @mcp.tool()
    def read_file(path: str, offset: int = 1, limit: int = 0) -> str:
        """Read file contents with line numbers and byte-budget truncation.

        Binary files are detected and rejected. Large files are automatically
        truncated at 2000 lines or 50KB. Use offset and limit to paginate.

        Args:
            path: Absolute file path to read.
            offset: Starting line number, 1-indexed (default: 1).
            limit: Max lines to return, 0 = up to 2000 (default: 0).
        """
        resolved = _resolve(path)

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

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file with the given content.

        Automatically creates parent directories.

        Args:
            path: Absolute file path to write.
            content: Complete file content to write.
        """
        resolved = _resolve(path)

        try:
            if before_write:
                before_write()

            existed = os.path.isfile(resolved)
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            action = "Updated" if existed else "Created"
            return f"{action} {path} ({len(content):,} bytes, {line_count} lines)"
        except Exception as e:
            return f"Error writing file: {e}"

    @mcp.tool()
    def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        """Replace text in a file using a fuzzy-match cascade.

        Tries exact match first, then falls back through increasingly fuzzy
        strategies: line-trimmed, block-anchor, whitespace-normalized,
        indentation-flexible, and trimmed-boundary matching.

        Args:
            path: Absolute file path to edit.
            old_text: Text to find (fuzzy matching applied if exact fails).
            new_text: Replacement text.
            replace_all: Replace all occurrences (default: first only).
        """
        resolved = _resolve(path)
        if not os.path.isfile(resolved):
            return f"Error: File not found: {path}"

        try:
            with open(resolved, encoding="utf-8") as f:
                content = f.read()

            if before_write:
                before_write()

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

    @mcp.tool()
    def list_directory(path: str = ".", recursive: bool = False) -> str:
        """List directory contents with type indicators.

        Directories have a / suffix. Hidden files and common build directories
        are skipped.

        Args:
            path: Absolute directory path (default: current directory).
            recursive: List recursively (default: false). Truncates at 500 entries.
        """
        resolved = _resolve(path)
        if not os.path.isdir(resolved):
            return f"Error: Directory not found: {path}"

        try:
            skip = {
                ".git",
                "__pycache__",
                "node_modules",
                ".venv",
                ".tox",
                ".mypy_cache",
                ".ruff_cache",
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

    @mcp.tool()
    def search_files(pattern: str, path: str = ".", include: str = "") -> str:
        """Search file contents using regex. Uses ripgrep when available, falls back to Python regex.

        Results sorted by file with line numbers.

        Args:
            pattern: Regex pattern to search for.
            path: Absolute directory path to search (default: current directory).
            include: File glob filter (e.g. '*.py').
        """
        resolved = _resolve(path)
        if not os.path.isdir(resolved):
            return f"Error: Directory not found: {path}"

        # Try ripgrep first
        try:
            cmd = [
                "rg",
                "-nH",
                "--no-messages",
                "--hidden",
                "--max-count=20",
                "--glob=!.git/*",
                pattern,
            ]
            if include:
                cmd.extend(["--glob", include])
            cmd.append(resolved)

            rg_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if rg_result.returncode <= 1:
                output = rg_result.stdout.strip()
                if not output:
                    return "No matches found."

                lines = []
                for line in output.split("\n")[:SEARCH_RESULT_LIMIT]:
                    if project_root:
                        line = line.replace(project_root + "/", "")
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
                    display_path = (
                        os.path.relpath(fpath, project_root) if project_root else fpath
                    )
                    try:
                        with open(fpath, encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                if compiled.search(line):
                                    matches.append(
                                        f"{display_path}:{i}:{line.rstrip()[:MAX_LINE_LENGTH]}"
                                    )
                                    if len(matches) >= SEARCH_RESULT_LIMIT:
                                        return "\n".join(matches) + "\n... (truncated)"
                    except (OSError, UnicodeDecodeError):
                        continue

            return "\n".join(matches) if matches else "No matches found."
        except re.error as e:
            return f"Error: Invalid regex: {e}"
