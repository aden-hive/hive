"""
Shared file operation tools for MCP servers.

Provides 7 tools (read_file, write_file, edit_file, hashline_edit,
list_directory, search_files, run_command) plus supporting helpers.
Used by both files_server.py (unsandboxed) and coder_tools_server.py
(project-root sandboxed with git snapshots).

Usage:
    from aden_tools.file_ops import register_file_tools

    mcp = FastMCP("my-server")
    register_file_tools(mcp)                       # unsandboxed defaults
    register_file_tools(mcp, resolve_path=fn, ...)  # sandboxed with hooks
"""

from __future__ import annotations

import contextlib
import difflib
import fnmatch
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastmcp import FastMCP

from aden_tools.hashline import (
    compute_line_hash,
    format_hashlines,
    maybe_strip,
    parse_anchor,
    strip_boundary_echo,
    strip_content_prefixes,
    strip_insert_echo,
    validate_anchor,
)

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
    def read_file(path: str, offset: int = 1, limit: int = 0, hashline: bool = False) -> str:
        """Read file contents with line numbers and byte-budget truncation.

        Binary files are detected and rejected. Large files are automatically
        truncated at 2000 lines or 50KB. Use offset and limit to paginate.

        Set hashline=True to get N:hhhh|content format with content-hash
        anchors for use with hashline_edit. Line truncation is disabled in
        hashline mode to preserve hash integrity.

        Args:
            path: Absolute file path to read.
            offset: Starting line number, 1-indexed (default: 1).
            limit: Max lines to return, 0 = up to 2000 (default: 0).
            hashline: If True, return N:hhhh|content anchors (default: False).
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
                content = f.read()

            # Use splitlines() for consistent line splitting with hashline module
            all_lines = content.splitlines()
            total_lines = len(all_lines)
            start_idx = max(0, offset - 1)
            effective_limit = limit if limit > 0 else MAX_READ_LINES
            end_idx = min(start_idx + effective_limit, total_lines)

            output_lines = []
            byte_count = 0
            truncated_by_bytes = False
            for i in range(start_idx, end_idx):
                line = all_lines[i]
                if hashline:
                    # No line truncation in hashline mode (would corrupt hashes)
                    h = compute_line_hash(line)
                    formatted = f"{i + 1}:{h}|{line}"
                else:
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
    def search_files(
        pattern: str, path: str = ".", include: str = "", hashline: bool = False
    ) -> str:
        """Search file contents using regex. Uses ripgrep if available.

        Results sorted by file with line numbers. Set hashline=True to include
        content-hash anchors (N:hhhh) for use with hashline_edit.

        Args:
            pattern: Regex pattern to search for.
            path: Absolute directory path to search (default: current directory).
            include: File glob filter (e.g. '*.py').
            hashline: If True, include hash anchors in results (default: False).
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

            rg_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
            )
            if rg_result.returncode <= 1:
                output = rg_result.stdout.strip()
                if not output:
                    return "No matches found."

                lines = []
                for line in output.split("\n")[:SEARCH_RESULT_LIMIT]:
                    if project_root:
                        line = line.replace(project_root + "/", "")
                    if hashline:
                        # Parse file:linenum:content and insert hash anchor
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            content = parts[2]
                            h = compute_line_hash(content)
                            line = f"{parts[0]}:{parts[1]}:{h}|{content}"
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
                    display_path = os.path.relpath(fpath, project_root) if project_root else fpath
                    try:
                        with open(fpath, encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                stripped = line.rstrip()
                                if compiled.search(stripped):
                                    if hashline:
                                        h = compute_line_hash(stripped)
                                        matches.append(
                                            f"{display_path}:{i}:{h}|{stripped}"
                                        )
                                    else:
                                        matches.append(
                                            f"{display_path}:{i}:{stripped[:MAX_LINE_LENGTH]}"
                                        )
                                    if len(matches) >= SEARCH_RESULT_LIMIT:
                                        return "\n".join(matches) + "\n... (truncated)"
                    except (OSError, UnicodeDecodeError):
                        continue

            return "\n".join(matches) if matches else "No matches found."
        except re.error as e:
            return f"Error: Invalid regex: {e}"

    @mcp.tool()
    def hashline_edit(
        path: str,
        edits: str,
        auto_cleanup: bool = True,
        encoding: str = "utf-8",
    ) -> str:
        """Edit a file using anchor-based line references (N:hash) for precise edits.

        After reading a file with read_file(hashline=True), use the anchors to make
        targeted edits without reproducing exact file content.

        Anchors must match current file content (hash validation). All edits in a
        batch are validated before any are applied (atomic). Overlapping line ranges
        within a single call are rejected.

        Args:
            path: Absolute file path to edit.
            edits: JSON string containing a list of edit operations. Each op is a
                dict with "op" key and operation-specific fields:
                - set_line: anchor, content (single line replacement)
                - replace_lines: start_anchor, end_anchor, content (multi-line)
                - insert_after: anchor, content
                - insert_before: anchor, content
                - replace: old_content, new_content, allow_multiple
                - append: content
            auto_cleanup: Strip hashline prefixes and echoed context from edit
                content (default: True).
            encoding: File encoding (default: "utf-8").
        """
        # 1. Parse JSON
        try:
            edit_ops = json.loads(edits)
        except (json.JSONDecodeError, TypeError) as e:
            return f"Error: Invalid JSON in edits: {e}"

        if not isinstance(edit_ops, list):
            return "Error: edits must be a JSON array of operations"
        if not edit_ops:
            return "Error: edits array is empty"
        if len(edit_ops) > 100:
            return "Error: Too many edits in one call (max 100). Split into multiple calls."

        # 2. Read file
        resolved = _resolve(path)
        if not os.path.isfile(resolved):
            return f"Error: File not found: {path}"

        try:
            with open(resolved, "rb") as f:
                raw_head = f.read(8192)
            eol = "\r\n" if b"\r\n" in raw_head else "\n"

            with open(resolved, encoding=encoding) as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        content_bytes = len(content.encode(encoding))
        if content_bytes > 10 * 1024 * 1024:
            return f"Error: File too large for hashline_edit ({content_bytes} bytes, max 10MB)"

        trailing_newline = content.endswith("\n")
        lines = content.splitlines()

        # 3. Categorize and validate ops
        splices = []  # (start_0idx, end_0idx, new_lines, op_index)
        replaces = []  # (old_content, new_content, op_index, allow_multiple)
        cleanup_actions: list[str] = []

        for i, op in enumerate(edit_ops):
            if not isinstance(op, dict):
                return f"Error: Edit #{i + 1}: operation must be a dict"

            match op.get("op"):
                case "set_line":
                    anchor = op.get("anchor", "")
                    err = validate_anchor(anchor, lines)
                    if err:
                        return f"Error: Edit #{i + 1} (set_line): {err}"
                    if "content" not in op:
                        return f"Error: Edit #{i + 1} (set_line): missing required field 'content'"
                    if not isinstance(op["content"], str):
                        return f"Error: Edit #{i + 1} (set_line): content must be a string"
                    if "\n" in op["content"] or "\r" in op["content"]:
                        return (
                            f"Error: Edit #{i + 1} (set_line): content must be a single line. "
                            f"Use replace_lines for multi-line replacement."
                        )
                    line_num, _ = parse_anchor(anchor)
                    idx = line_num - 1
                    new_content = op["content"]
                    new_lines = [new_content] if new_content else []
                    new_lines = maybe_strip(
                        new_lines, strip_content_prefixes, "prefix_strip",
                        auto_cleanup, cleanup_actions,
                    )
                    splices.append((idx, idx, new_lines, i))

                case "replace_lines":
                    start_anchor = op.get("start_anchor", "")
                    end_anchor = op.get("end_anchor", "")
                    err = validate_anchor(start_anchor, lines)
                    if err:
                        return f"Error: Edit #{i + 1} (replace_lines start): {err}"
                    err = validate_anchor(end_anchor, lines)
                    if err:
                        return f"Error: Edit #{i + 1} (replace_lines end): {err}"
                    start_num, _ = parse_anchor(start_anchor)
                    end_num, _ = parse_anchor(end_anchor)
                    if start_num > end_num:
                        return (
                            f"Error: Edit #{i + 1} (replace_lines): "
                            f"start line {start_num} > end line {end_num}"
                        )
                    if "content" not in op:
                        return (
                            f"Error: Edit #{i + 1} (replace_lines): "
                            f"missing required field 'content'"
                        )
                    if not isinstance(op["content"], str):
                        return f"Error: Edit #{i + 1} (replace_lines): content must be a string"
                    new_content = op["content"]
                    new_lines = new_content.splitlines() if new_content else []
                    new_lines = maybe_strip(
                        new_lines, strip_content_prefixes, "prefix_strip",
                        auto_cleanup, cleanup_actions,
                    )
                    new_lines = maybe_strip(
                        new_lines,
                        lambda nl, s=start_num, e=end_num: strip_boundary_echo(lines, s, e, nl),
                        "boundary_echo_strip", auto_cleanup, cleanup_actions,
                    )
                    splices.append((start_num - 1, end_num - 1, new_lines, i))

                case "insert_after":
                    anchor = op.get("anchor", "")
                    err = validate_anchor(anchor, lines)
                    if err:
                        return f"Error: Edit #{i + 1} (insert_after): {err}"
                    line_num, _ = parse_anchor(anchor)
                    idx = line_num - 1
                    new_content = op.get("content", "")
                    if not isinstance(new_content, str):
                        return f"Error: Edit #{i + 1} (insert_after): content must be a string"
                    if not new_content:
                        return f"Error: Edit #{i + 1} (insert_after): content is empty"
                    new_lines = new_content.splitlines()
                    new_lines = maybe_strip(
                        new_lines, strip_content_prefixes, "prefix_strip",
                        auto_cleanup, cleanup_actions,
                    )
                    new_lines = maybe_strip(
                        new_lines,
                        lambda nl, _idx=idx: strip_insert_echo(lines[_idx], nl),
                        "insert_echo_strip", auto_cleanup, cleanup_actions,
                    )
                    splices.append((idx + 1, idx, new_lines, i))

                case "insert_before":
                    anchor = op.get("anchor", "")
                    err = validate_anchor(anchor, lines)
                    if err:
                        return f"Error: Edit #{i + 1} (insert_before): {err}"
                    line_num, _ = parse_anchor(anchor)
                    idx = line_num - 1
                    new_content = op.get("content", "")
                    if not isinstance(new_content, str):
                        return f"Error: Edit #{i + 1} (insert_before): content must be a string"
                    if not new_content:
                        return f"Error: Edit #{i + 1} (insert_before): content is empty"
                    new_lines = new_content.splitlines()
                    new_lines = maybe_strip(
                        new_lines, strip_content_prefixes, "prefix_strip",
                        auto_cleanup, cleanup_actions,
                    )
                    new_lines = maybe_strip(
                        new_lines,
                        lambda nl, _idx=idx: strip_insert_echo(lines[_idx], nl, position="last"),
                        "insert_echo_strip", auto_cleanup, cleanup_actions,
                    )
                    splices.append((idx, idx - 1, new_lines, i))

                case "replace":
                    old_content = op.get("old_content")
                    new_content = op.get("new_content")
                    if old_content is None:
                        return f"Error: Edit #{i + 1} (replace): missing old_content"
                    if not isinstance(old_content, str):
                        return f"Error: Edit #{i + 1} (replace): old_content must be a string"
                    if not old_content:
                        return f"Error: Edit #{i + 1} (replace): old_content must not be empty"
                    if new_content is None:
                        return f"Error: Edit #{i + 1} (replace): missing new_content"
                    if not isinstance(new_content, str):
                        return f"Error: Edit #{i + 1} (replace): new_content must be a string"
                    allow_multiple = op.get("allow_multiple", False)
                    if not isinstance(allow_multiple, bool):
                        return f"Error: Edit #{i + 1} (replace): allow_multiple must be a boolean"
                    replaces.append((old_content, new_content, i, allow_multiple))

                case "append":
                    new_content = op.get("content")
                    if new_content is None:
                        return f"Error: Edit #{i + 1} (append): missing content"
                    if not isinstance(new_content, str):
                        return f"Error: Edit #{i + 1} (append): content must be a string"
                    if not new_content:
                        return f"Error: Edit #{i + 1} (append): content must not be empty"
                    new_lines = new_content.splitlines()
                    new_lines = maybe_strip(
                        new_lines, strip_content_prefixes, "prefix_strip",
                        auto_cleanup, cleanup_actions,
                    )
                    insert_point = len(lines)
                    splices.append((insert_point, insert_point - 1, new_lines, i))

                case unknown:
                    return f"Error: Edit #{i + 1}: unknown op '{unknown}'"

        # 4. Check for overlapping splice ranges
        for j in range(len(splices)):
            for k in range(j + 1, len(splices)):
                s_a, e_a, _, idx_a = splices[j]
                s_b, e_b, _, idx_b = splices[k]
                is_insert_a = s_a > e_a
                is_insert_b = s_b > e_b

                if is_insert_a and is_insert_b:
                    continue
                if is_insert_a and not is_insert_b:
                    if s_b <= s_a <= e_b + 1:
                        return (
                            f"Error: Overlapping edits: edit #{idx_a + 1} "
                            f"and edit #{idx_b + 1} affect overlapping line ranges"
                        )
                    continue
                if is_insert_b and not is_insert_a:
                    if s_a <= s_b <= e_a + 1:
                        return (
                            f"Error: Overlapping edits: edit #{idx_a + 1} "
                            f"and edit #{idx_b + 1} affect overlapping line ranges"
                        )
                    continue
                if not (e_a < s_b or e_b < s_a):
                    return (
                        f"Error: Overlapping edits: edit #{idx_a + 1} "
                        f"and edit #{idx_b + 1} affect overlapping line ranges"
                    )

        # 5. Apply splices bottom-up
        changes_made = 0
        working = list(lines)
        for start, end, new_lines, _ in sorted(
            splices, key=lambda s: (s[0], s[3]), reverse=True
        ):
            if start > end:
                changes_made += 1
                for k, nl in enumerate(new_lines):
                    working.insert(start + k, nl)
            else:
                old_slice = working[start : end + 1]
                if old_slice != new_lines:
                    changes_made += 1
                working[start : end + 1] = new_lines

        # 6. Apply str_replace ops
        joined = "\n".join(working)
        replace_counts = []
        for old_content, new_content, op_idx, allow_multiple in replaces:
            count = joined.count(old_content)
            if count == 0:
                return (
                    f"Error: Edit #{op_idx + 1} (replace): "
                    f"old_content not found "
                    f"(note: anchor-based edits in this batch are applied first)"
                )
            if count > 1 and not allow_multiple:
                return (
                    f"Error: Edit #{op_idx + 1} (replace): "
                    f"old_content found {count} times (must be unique). "
                    f"Include more surrounding context to make it unique, "
                    f"or use anchor-based ops instead."
                )
            if allow_multiple:
                joined = joined.replace(old_content, new_content)
                replace_counts.append((op_idx, count))
            else:
                joined = joined.replace(old_content, new_content, 1)
            if count > 0 and old_content != new_content:
                changes_made += 1

        # 7. Restore trailing newline
        if trailing_newline and joined and not joined.endswith("\n"):
            joined += "\n"

        # 8. Restore original EOL style
        if eol == "\r\n":
            joined = joined.replace("\n", "\r\n")

        # 9. Snapshot + atomic write
        try:
            if before_write:
                before_write()
            original_mode = os.stat(resolved).st_mode
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(resolved))
            fd_open = True
            try:
                os.fchmod(fd, original_mode)
                with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                    fd_open = False
                    f.write(joined)
                os.replace(tmp_path, resolved)
            except BaseException:
                if fd_open:
                    os.close(fd)
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except Exception as e:
            return f"Error: Failed to write file: {e}"

        # 10. Build response
        updated_lines = joined.splitlines()
        total_lines = len(updated_lines)

        # Limit returned content to first 200 lines
        preview_limit = 200
        hashline_content = format_hashlines(updated_lines, limit=preview_limit)

        parts = [f"Applied {changes_made} edit(s) to {path}"]
        if changes_made == 0:
            parts.append("(content unchanged after applying edits)")
        if cleanup_actions:
            parts.append(f"Auto-cleanup: {', '.join(cleanup_actions)}")
        if replace_counts:
            for op_idx, count in replace_counts:
                parts.append(f"Edit #{op_idx + 1} replaced {count} occurrence(s)")
        parts.append("")
        parts.append(hashline_content)
        if total_lines > preview_limit:
            parts.append(
                f"\n(Showing first {preview_limit} of {total_lines} lines. "
                f"Use read_file with offset to see more.)"
            )
        return "\n".join(parts)
