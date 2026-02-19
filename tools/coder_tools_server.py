#!/usr/bin/env python3
"""
Coder Tools MCP Server — OpenCode-inspired coding tools.

Provides rich file I/O, fuzzy-match editing, git snapshots, and shell execution
for the hive_coder agent. Modeled after opencode's tool architecture.

All paths scoped to a configurable project root for safety.

Usage:
    python coder_tools_server.py --stdio --project-root /path/to/project
    python coder_tools_server.py --port 4002 --project-root /path/to/project
"""

import argparse
import difflib
import fnmatch
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants (inspired by opencode) ──────────────────────────────────────

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
        ".o",
        ".a",
        ".lib",
    }
)


def setup_logger():
    if not logger.handlers:
        stream = sys.stderr if "--stdio" in sys.argv else sys.stdout
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter("[coder-tools] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


setup_logger()

if "--stdio" in sys.argv:
    import rich.console

    _original_console_init = rich.console.Console.__init__

    def _patched_console_init(self, *args, **kwargs):
        kwargs["file"] = sys.stderr
        _original_console_init(self, *args, **kwargs)

    rich.console.Console.__init__ = _patched_console_init


from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("coder-tools")

PROJECT_ROOT: str = ""
SNAPSHOT_DIR: str = ""


# ── Path resolution ───────────────────────────────────────────────────────


def _find_project_root() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    while current != os.path.dirname(current):
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        current = os.path.dirname(current)
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_path(path: str) -> str:
    """Resolve path relative to PROJECT_ROOT. Raises ValueError if outside."""
    if os.path.isabs(path):
        resolved = os.path.abspath(path)
    else:
        resolved = os.path.abspath(os.path.join(PROJECT_ROOT, path))
    try:
        common = os.path.commonpath([resolved, PROJECT_ROOT])
    except ValueError as err:
        raise ValueError(f"Access denied: '{path}' is outside the project root.") from err
    if common != PROJECT_ROOT:
        raise ValueError(f"Access denied: '{path}' is outside the project root.")
    return resolved


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


# ── Fuzzy edit strategies (ported from opencode's 9-strategy cascade) ─────


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
    """
    Yield candidate substrings from content that match old_text,
    using a cascade of increasingly fuzzy strategies.
    Ported from opencode's edit.ts replace() cascade.
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
    # Each line trimmed; yields original content substring preserving indentation
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
                    # Score middle lines
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


# ── Git snapshot system (ported from opencode's shadow git) ───────────────


def _snapshot_git(*args: str) -> str:
    """Run a git command with the snapshot GIT_DIR and PROJECT_ROOT worktree."""
    cmd = ["git", "--git-dir", SNAPSHOT_DIR, "--work-tree", PROJECT_ROOT, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def _ensure_snapshot_repo():
    """Initialize the shadow git repo if needed."""
    if not SNAPSHOT_DIR:
        return
    if not os.path.isdir(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", SNAPSHOT_DIR],
            capture_output=True,
            timeout=10,
        )
        _snapshot_git("config", "core.autocrlf", "false")


# ── Tool: read_file ──────────────────────────────────────────────────────


@mcp.tool()
def read_file(path: str, offset: int = 1, limit: int = 0) -> str:
    """Read file contents with line numbers and byte-budget truncation.

    Returns numbered lines. Binary files are detected and rejected.
    Large files are automatically truncated at 2000 lines or 50KB.

    Args:
        path: File path (relative to project root or absolute within project)
        offset: Starting line number, 1-indexed (default: 1)
        limit: Max lines to return, 0 = up to 2000 (default: 0)

    Returns:
        File contents with line numbers, or error message
    """
    resolved = _resolve_path(path)

    if os.path.isdir(resolved):
        # List directory contents instead
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
        start_idx = max(0, offset - 1)  # Convert 1-indexed to 0-indexed
        effective_limit = limit if limit > 0 else MAX_READ_LINES
        end_idx = min(start_idx + effective_limit, total_lines)

        # Apply byte budget (like opencode)
        output_lines = []
        byte_count = 0
        truncated_by_bytes = False
        for i in range(start_idx, end_idx):
            line = all_lines[i].rstrip("\n\r")
            if len(line) > MAX_LINE_LENGTH:
                line = line[:MAX_LINE_LENGTH] + "..."
            formatted = f"{i + 1:>6}\t{line}"
            line_bytes = len(formatted.encode("utf-8")) + 1  # +1 for newline
            if byte_count + line_bytes > MAX_OUTPUT_BYTES:
                truncated_by_bytes = True
                break
            output_lines.append(formatted)
            byte_count += line_bytes

        result = "\n".join(output_lines)

        # Truncation notices
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


# ── Tool: write_file ─────────────────────────────────────────────────────


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file. Automatically creates parent directories.

    Takes a snapshot before writing for undo capability.

    Args:
        path: File path relative to project root
        content: Complete file content

    Returns:
        Success message with file stats, or error
    """
    resolved = _resolve_path(path)

    try:
        # Snapshot before write
        _take_snapshot()

        existed = os.path.isfile(resolved)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        action = "Updated" if existed else "Created"
        return f"{action} {path} ({len(content):,} bytes, {line_count} lines)"
    except Exception as e:
        return f"Error writing file: {e}"


# ── Tool: edit_file (fuzzy-match cascade) ─────────────────────────────────


@mcp.tool()
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """Replace text in a file using a fuzzy-match cascade.

    Tries exact match first, then falls back through increasingly fuzzy
    strategies: line-trimmed, block-anchor, whitespace-normalized,
    indentation-flexible, and trimmed-boundary matching.

    Inspired by opencode's 9-strategy edit tool.

    Args:
        path: File path relative to project root
        old_text: Text to find (fuzzy matching applied if exact fails)
        new_text: Replacement text
        replace_all: Replace all occurrences (default: first only)

    Returns:
        Success message with diff preview, or error with suggestions
    """
    resolved = _resolve_path(path)
    if not os.path.isfile(resolved):
        return f"Error: File not found: {path}"

    try:
        with open(resolved, encoding="utf-8") as f:
            content = f.read()

        # Snapshot before edit
        _take_snapshot()

        # Try fuzzy cascade
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

            # Check uniqueness
            last_idx = content.rfind(candidate)
            if idx == last_idx:
                matched_text = candidate
                strategy_used = strategies[min(i, len(strategies) - 1)]
                break
            # Multiple matches — continue to next strategy

        if matched_text is None:
            # Generate helpful error
            close = difflib.get_close_matches(old_text[:200], content.split("\n"), n=3, cutoff=0.4)
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

        # Write
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Build response with diff preview
        diff = _compute_diff(content, new_content, path)
        match_info = f" (matched via {strategy_used})" if strategy_used != "exact" else ""
        result = f"Replaced {count} occurrence(s) in {path}{match_info}"
        if diff:
            result += f"\n\n{diff}"
        return result
    except Exception as e:
        return f"Error editing file: {e}"


# ── Tool: list_directory ──────────────────────────────────────────────────


@mcp.tool()
def list_directory(path: str = ".", recursive: bool = False) -> str:
    """List directory contents with type indicators.

    Args:
        path: Directory path (relative to project root, default: root)
        recursive: List recursively (default: False)

    Returns:
        Sorted directory listing with / suffix for directories
    """
    resolved = _resolve_path(path)
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
        entries = []
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


# ── Tool: search_files ───────────────────────────────────────────────────


@mcp.tool()
def search_files(pattern: str, path: str = ".", include: str = "") -> str:
    """Search file contents using regex. Results sorted by modification time.

    Uses ripgrep when available, falls back to Python regex.

    Args:
        pattern: Regex pattern to search for
        path: Directory to search (relative to project root)
        include: File glob filter (e.g. '*.py')

    Returns:
        Matching lines grouped by file with line numbers
    """
    resolved = _resolve_path(path)
    if not os.path.isdir(resolved):
        return f"Error: Directory not found: {path}"

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

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode <= 1:
            output = result.stdout.strip()
            if not output:
                return "No matches found."

            # Group by file, make paths relative
            lines = []
            for line in output.split("\n")[:SEARCH_RESULT_LIMIT]:
                line = line.replace(PROJECT_ROOT + "/", "")
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
        pass
    except subprocess.TimeoutExpired:
        return "Error: Search timed out after 30 seconds"

    # Fallback: Python regex
    try:
        compiled = re.compile(pattern)
        matches = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", ".tox"}

        for root, dirs, files in os.walk(resolved):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, PROJECT_ROOT)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if compiled.search(line):
                                matches.append(f"{rel}:{i}:{line.rstrip()[:MAX_LINE_LENGTH]}")
                                if len(matches) >= SEARCH_RESULT_LIMIT:
                                    return "\n".join(matches) + "\n... (truncated)"
                except (OSError, UnicodeDecodeError):
                    continue

        return "\n".join(matches) if matches else "No matches found."
    except re.error as e:
        return f"Error: Invalid regex: {e}"


# ── Tool: run_command ─────────────────────────────────────────────────────


@mcp.tool()
def run_command(command: str, cwd: str = "", timeout: int = 120) -> str:
    """Execute a shell command in the project context.

    PYTHONPATH is automatically set to include core/ and exports/.
    Output is truncated at 30K chars with a notice.

    Args:
        command: Shell command to execute
        cwd: Working directory (relative to project root)
        timeout: Timeout in seconds (default: 120, max: 300)

    Returns:
        Combined stdout/stderr with exit code
    """
    timeout = min(timeout, 300)  # Cap at 5 minutes
    work_dir = _resolve_path(cwd) if cwd else PROJECT_ROOT

    try:
        start = time.monotonic()
        result = subprocess.run(
            command,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                **os.environ,
                "PYTHONPATH": (
                    f"{PROJECT_ROOT}/core:{PROJECT_ROOT}/exports"
                    f":{PROJECT_ROOT}/core/framework/agents"
                ),
            },
        )
        elapsed = time.monotonic() - start

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")

        output = "\n".join(parts)

        # Truncate large output (like opencode's MAX_METADATA_LENGTH)
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


# ── Tool: snapshot (git-based undo) ───────────────────────────────────────


def _take_snapshot() -> str:
    """Take a git snapshot and return the tree hash. Silent on failure."""
    if not SNAPSHOT_DIR:
        return ""
    try:
        _ensure_snapshot_repo()
        _snapshot_git("add", ".")
        return _snapshot_git("write-tree")
    except Exception:
        return ""


@mcp.tool()
def undo_changes(path: str = "") -> str:
    """Undo file changes by restoring from the last git snapshot.

    Uses a shadow git repository to track changes. If path is empty,
    restores ALL changed files. If path is specified, restores only that file.

    Args:
        path: Specific file to restore (empty = restore all changes)

    Returns:
        List of restored files, or error
    """
    if not SNAPSHOT_DIR:
        return "Error: Snapshot system not available (no project root detected)"

    try:
        _ensure_snapshot_repo()

        if path:
            resolved = _resolve_path(path)
            rel = os.path.relpath(resolved, PROJECT_ROOT)
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    SNAPSHOT_DIR,
                    "--work-tree",
                    PROJECT_ROOT,
                    "checkout",
                    "HEAD",
                    "--",
                    rel,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return f"Restored: {path}"
        else:
            # Get list of changed files
            diff_out = _snapshot_git("diff", "--name-only")
            if not diff_out.strip():
                return "No changes to undo."

            _snapshot_git("checkout", ".")
            changed = diff_out.strip().split("\n")
            return f"Restored {len(changed)} file(s):\n" + "\n".join(f"  {f}" for f in changed)
    except Exception as e:
        return f"Error restoring files: {e}"


# ── Meta-agent: Tool discovery ────────────────────────────────────────────


@mcp.tool()
def discover_mcp_tools(server_config_path: str = "") -> str:
    """Discover available MCP tools by connecting to servers defined in a config file.

    Connects to each MCP server, lists all tools with full schemas, then
    disconnects. Use this to see what tools are available before designing
    an agent — never rely on static documentation.

    Args:
        server_config_path: Path to mcp_servers.json (relative to project root).
            Default: the hive-tools server config at tools/mcp_servers.json.
            Can also point to any agent's mcp_servers.json.

    Returns:
        JSON listing of all tools with names, descriptions, and input schemas
    """
    # Resolve config path
    if not server_config_path:
        # Default: look for the main hive-tools mcp_servers.json
        candidates = [
            os.path.join(PROJECT_ROOT, "tools", "mcp_servers.json"),
            os.path.join(PROJECT_ROOT, "mcp_servers.json"),
        ]
        config_path = None
        for c in candidates:
            if os.path.isfile(c):
                config_path = c
                break
        if not config_path:
            return "Error: No mcp_servers.json found. Provide server_config_path."
    else:
        config_path = _resolve_path(server_config_path)
        if not os.path.isfile(config_path):
            return f"Error: Config file not found: {server_config_path}"

    try:
        with open(config_path, encoding="utf-8") as f:
            servers_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return f"Error reading config: {e}"

    # Import MCPClient (deferred — needs PYTHONPATH to include core/)
    try:
        from framework.runner.mcp_client import MCPClient, MCPServerConfig
    except ImportError:
        return "Error: Cannot import MCPClient. Ensure PYTHONPATH includes the core/ directory."

    all_tools = []
    errors = []
    config_dir = os.path.dirname(config_path)

    for server_name, server_conf in servers_config.items():
        # Resolve cwd relative to config file location
        cwd = server_conf.get("cwd", "")
        if cwd and not os.path.isabs(cwd):
            cwd = os.path.abspath(os.path.join(config_dir, cwd))

        try:
            config = MCPServerConfig(
                name=server_name,
                transport=server_conf.get("transport", "stdio"),
                command=server_conf.get("command"),
                args=server_conf.get("args", []),
                env=server_conf.get("env", {}),
                cwd=cwd or None,
                url=server_conf.get("url"),
                headers=server_conf.get("headers", {}),
            )
            client = MCPClient(config)
            client.connect()
            tools = client.list_tools()

            for tool in tools:
                all_tools.append(
                    {
                        "server": server_name,
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                )

            client.disconnect()
        except Exception as e:
            errors.append({"server": server_name, "error": str(e)})

    result = {
        "tools": all_tools,
        "total": len(all_tools),
        "servers_queried": len(servers_config),
    }
    if errors:
        result["errors"] = errors

    return json.dumps(result, indent=2, default=str)


# ── Meta-agent: Agent inventory ───────────────────────────────────────────


@mcp.tool()
def list_agents() -> str:
    """List all Hive agent packages with runtime session info.

    Scans exports/ for user agents and core/framework/agents/ for framework
    agents. Checks ~/.hive/agents/ for runtime data (session counts).

    Returns:
        JSON list of agents with names, descriptions, source, and session counts
    """
    hive_agents_dir = Path.home() / ".hive" / "agents"
    agents = []
    skip = {"__pycache__", "__init__.py", ".git"}

    # Agent sources: (directory, source_label)
    scan_dirs = [
        (os.path.join(PROJECT_ROOT, "core", "framework", "agents"), "framework"),
        (os.path.join(PROJECT_ROOT, "exports"), "user"),
    ]

    for scan_dir, source in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue

        for entry in sorted(os.listdir(scan_dir)):
            if entry in skip or entry.startswith("."):
                continue
            agent_dir = os.path.join(scan_dir, entry)
            if not os.path.isdir(agent_dir):
                continue

            # Must have agent.py to be considered an agent package
            if not os.path.isfile(os.path.join(agent_dir, "agent.py")):
                continue

            info = {
                "name": entry,
                "path": os.path.relpath(agent_dir, PROJECT_ROOT),
                "source": source,
                "has_nodes": os.path.isdir(os.path.join(agent_dir, "nodes")),
                "has_tests": os.path.isdir(os.path.join(agent_dir, "tests")),
                "has_mcp_config": os.path.isfile(os.path.join(agent_dir, "mcp_servers.json")),
            }

            # Read description from __init__.py docstring
            init_path = os.path.join(agent_dir, "__init__.py")
            if os.path.isfile(init_path):
                try:
                    with open(init_path, encoding="utf-8") as f:
                        content = f.read(2000)
                    # Extract module docstring
                    for quote in ['"""', "'''"]:
                        start = content.find(quote)
                        if start != -1:
                            end = content.find(quote, start + 3)
                            if end != -1:
                                info["description"] = (
                                    content[start + 3 : end].strip().split("\n")[0]
                                )
                                break
                except OSError:
                    pass

            # Check runtime data
            runtime_dir = hive_agents_dir / entry
            if runtime_dir.is_dir():
                sessions_dir = runtime_dir / "sessions"
                if sessions_dir.is_dir():
                    session_count = sum(
                        1
                        for d in sessions_dir.iterdir()
                        if d.is_dir() and d.name.startswith("session_")
                    )
                    info["session_count"] = session_count
                else:
                    info["session_count"] = 0
            else:
                info["session_count"] = 0

            agents.append(info)

    return json.dumps({"agents": agents, "total": len(agents)}, indent=2)


# ── Meta-agent: Session & checkpoint inspection ───────────────────────────

_MAX_TRUNCATE_LEN = 500


def _resolve_hive_agent_path(agent_name: str) -> Path:
    """Resolve agent_name to ~/.hive/agents/{agent_name}/."""
    return Path.home() / ".hive" / "agents" / agent_name


def _read_session_json(path: Path) -> dict | None:
    """Read a JSON file, returning None on failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _scan_agent_sessions(agent_dir: Path) -> list[tuple[str, Path]]:
    """Find session directories with state.json, sorted most-recent-first."""
    sessions: list[tuple[str, Path]] = []
    sessions_dir = agent_dir / "sessions"
    if not sessions_dir.exists():
        return sessions
    for session_dir in sessions_dir.iterdir():
        if session_dir.is_dir() and session_dir.name.startswith("session_"):
            state_path = session_dir / "state.json"
            if state_path.exists():
                sessions.append((session_dir.name, state_path))
    sessions.sort(key=lambda t: t[0], reverse=True)
    return sessions


def _truncate_value(value: object, max_len: int = _MAX_TRUNCATE_LEN) -> object:
    """Truncate a value's JSON representation if too long."""
    s = json.dumps(value, default=str)
    if len(s) <= max_len:
        return value
    return {"_truncated": True, "_preview": s[:max_len] + "...", "_length": len(s)}


@mcp.tool()
def list_agent_sessions(
    agent_name: str,
    status: str = "",
    limit: int = 20,
) -> str:
    """List sessions for an agent, with optional status filter.

    Use this to see what sessions exist for a built agent, find
    failed sessions for debugging, or check execution history.

    Args:
        agent_name: Agent package name (e.g. 'deep_research_agent')
        status: Filter by status: 'active', 'paused', 'completed',
            'failed', 'cancelled'. Empty for all.
        limit: Maximum results (default 20)

    Returns:
        JSON with session summaries sorted most-recent-first
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    all_sessions = _scan_agent_sessions(agent_dir)

    if not all_sessions:
        return json.dumps(
            {
                "agent_name": agent_name,
                "sessions": [],
                "total": 0,
                "hint": (
                    f"No sessions found at {agent_dir}/sessions/. Has this agent been run yet?"
                ),
            }
        )

    summaries = []
    for session_id, state_path in all_sessions:
        data = _read_session_json(state_path)
        if data is None:
            continue

        session_status = data.get("status", "")
        if status and session_status != status:
            continue

        timestamps = data.get("timestamps", {})
        progress = data.get("progress", {})
        checkpoint_dir = state_path.parent / "checkpoints"

        summaries.append(
            {
                "session_id": session_id,
                "status": session_status,
                "goal_id": data.get("goal_id", ""),
                "started_at": timestamps.get("started_at", ""),
                "updated_at": timestamps.get("updated_at", ""),
                "completed_at": timestamps.get("completed_at"),
                "current_node": progress.get("current_node"),
                "steps_executed": progress.get("steps_executed", 0),
                "execution_quality": progress.get("execution_quality", ""),
                "has_checkpoints": (
                    checkpoint_dir.exists() and any(checkpoint_dir.glob("cp_*.json"))
                ),
            }
        )

    total = len(summaries)
    page = summaries[:limit]
    return json.dumps(
        {
            "agent_name": agent_name,
            "sessions": page,
            "total": total,
        },
        indent=2,
    )


@mcp.tool()
def get_agent_session_state(agent_name: str, session_id: str) -> str:
    """Load full session state (excluding memory to prevent context bloat).

    Returns status, progress, result, metrics, and checkpoint info.
    Use get_agent_session_memory to read memory contents separately.

    Args:
        agent_name: Agent package name (e.g. 'deep_research_agent')
        session_id: Session ID (e.g. 'session_20260208_143022_abc12345')

    Returns:
        JSON with full session state
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    state_path = agent_dir / "sessions" / session_id / "state.json"
    data = _read_session_json(state_path)
    if data is None:
        return json.dumps({"error": f"Session not found: {session_id}"})

    # Exclude memory values but show keys
    memory = data.get("memory", {})
    data["memory_keys"] = list(memory.keys()) if isinstance(memory, dict) else []
    data["memory_size"] = len(memory) if isinstance(memory, dict) else 0
    data.pop("memory", None)

    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_agent_session_memory(
    agent_name: str,
    session_id: str,
    key: str = "",
) -> str:
    """Read memory contents from a session.

    Memory stores intermediate results passed between nodes. Use this
    to inspect what data was produced during execution.

    Args:
        agent_name: Agent package name
        session_id: Session ID
        key: Specific memory key to retrieve. Empty for all keys.

    Returns:
        JSON with memory contents
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    state_path = agent_dir / "sessions" / session_id / "state.json"
    data = _read_session_json(state_path)
    if data is None:
        return json.dumps({"error": f"Session not found: {session_id}"})

    memory = data.get("memory", {})
    if not isinstance(memory, dict):
        memory = {}

    if key:
        if key not in memory:
            return json.dumps(
                {
                    "error": f"Memory key not found: '{key}'",
                    "available_keys": list(memory.keys()),
                }
            )
        return json.dumps(
            {
                "session_id": session_id,
                "key": key,
                "value": memory[key],
                "value_type": type(memory[key]).__name__,
            },
            indent=2,
            default=str,
        )

    return json.dumps(
        {
            "session_id": session_id,
            "memory": memory,
            "total_keys": len(memory),
        },
        indent=2,
        default=str,
    )


@mcp.tool()
def list_agent_checkpoints(
    agent_name: str,
    session_id: str,
) -> str:
    """List checkpoints for a session.

    Checkpoints capture execution state at node boundaries. Use this
    to find recovery points or understand execution flow.

    Args:
        agent_name: Agent package name
        session_id: Session ID

    Returns:
        JSON with checkpoint summaries
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    session_dir = agent_dir / "sessions" / session_id
    checkpoint_dir = session_dir / "checkpoints"

    if not session_dir.exists():
        return json.dumps({"error": f"Session not found: {session_id}"})

    if not checkpoint_dir.exists():
        return json.dumps(
            {
                "session_id": session_id,
                "checkpoints": [],
                "total": 0,
            }
        )

    # Try index.json first
    index_data = _read_session_json(checkpoint_dir / "index.json")
    if index_data and "checkpoints" in index_data:
        checkpoints = index_data["checkpoints"]
    else:
        # Fallback: scan individual checkpoint files
        checkpoints = []
        for cp_file in sorted(checkpoint_dir.glob("cp_*.json")):
            cp_data = _read_session_json(cp_file)
            if cp_data:
                checkpoints.append(
                    {
                        "checkpoint_id": cp_data.get("checkpoint_id", cp_file.stem),
                        "checkpoint_type": cp_data.get("checkpoint_type", ""),
                        "created_at": cp_data.get("created_at", ""),
                        "current_node": cp_data.get("current_node"),
                        "next_node": cp_data.get("next_node"),
                        "is_clean": cp_data.get("is_clean", True),
                        "description": cp_data.get("description", ""),
                    }
                )

    latest_id = None
    if index_data:
        latest_id = index_data.get("latest_checkpoint_id")
    elif checkpoints:
        latest_id = checkpoints[-1].get("checkpoint_id")

    return json.dumps(
        {
            "session_id": session_id,
            "checkpoints": checkpoints,
            "total": len(checkpoints),
            "latest_checkpoint_id": latest_id,
        },
        indent=2,
    )


@mcp.tool()
def get_agent_checkpoint(
    agent_name: str,
    session_id: str,
    checkpoint_id: str = "",
) -> str:
    """Load a specific checkpoint's full state.

    Returns shared memory snapshot, execution path, outputs, and metrics.
    If checkpoint_id is empty, loads the latest checkpoint.

    Args:
        agent_name: Agent package name
        session_id: Session ID
        checkpoint_id: Specific checkpoint ID, or empty for latest

    Returns:
        JSON with full checkpoint data
    """
    agent_dir = _resolve_hive_agent_path(agent_name)
    checkpoint_dir = agent_dir / "sessions" / session_id / "checkpoints"

    if not checkpoint_dir.exists():
        return json.dumps({"error": f"No checkpoints for session: {session_id}"})

    if not checkpoint_id:
        index_data = _read_session_json(checkpoint_dir / "index.json")
        if index_data and index_data.get("latest_checkpoint_id"):
            checkpoint_id = index_data["latest_checkpoint_id"]
        else:
            cp_files = sorted(checkpoint_dir.glob("cp_*.json"))
            if not cp_files:
                return json.dumps({"error": f"No checkpoints for session: {session_id}"})
            checkpoint_id = cp_files[-1].stem

    cp_path = checkpoint_dir / f"{checkpoint_id}.json"
    data = _read_session_json(cp_path)
    if data is None:
        return json.dumps({"error": f"Checkpoint not found: {checkpoint_id}"})

    return json.dumps(data, indent=2, default=str)


# ── Meta-agent: Test execution ────────────────────────────────────────────


@mcp.tool()
def run_agent_tests(
    agent_name: str,
    test_types: str = "all",
    fail_fast: bool = False,
) -> str:
    """Run pytest on an agent's test suite with structured result parsing.

    Automatically sets PYTHONPATH so framework and agent packages are
    importable. Parses pytest output into structured pass/fail results.

    Args:
        agent_name: Agent package name (e.g. 'deep_research_agent')
        test_types: Comma-separated test types: 'constraint', 'success',
            'edge_case', 'all' (default: 'all')
        fail_fast: Stop on first failure (default: False)

    Returns:
        JSON with summary counts, per-test results, and failure details
    """
    agent_path = Path(PROJECT_ROOT) / "exports" / agent_name
    if not agent_path.is_dir():
        # Fall back to framework agents
        agent_path = Path(PROJECT_ROOT) / "core" / "framework" / "agents" / agent_name
    tests_dir = agent_path / "tests"

    if not agent_path.is_dir():
        return json.dumps(
            {
                "error": f"Agent not found: {agent_name}",
                "hint": "Use list_agents() to see available agents.",
            }
        )

    if not tests_dir.exists():
        return json.dumps(
            {
                "error": f"No tests directory: exports/{agent_name}/tests/",
                "hint": "Create test files in the tests/ directory first.",
            }
        )

    # Parse test types
    types_list = [t.strip() for t in test_types.split(",")]

    # Build pytest command
    cmd = ["pytest"]

    if "all" in types_list:
        cmd.append(str(tests_dir))
    else:
        type_to_file = {
            "constraint": "test_constraints.py",
            "success": "test_success_criteria.py",
            "edge_case": "test_edge_cases.py",
        }
        for t in types_list:
            if t in type_to_file:
                test_file = tests_dir / type_to_file[t]
                if test_file.exists():
                    cmd.append(str(test_file))

    cmd.append("-v")
    if fail_fast:
        cmd.append("-x")
    cmd.append("--tb=short")

    # Set PYTHONPATH
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    core_path = os.path.join(PROJECT_ROOT, "core")
    exports_path = os.path.join(PROJECT_ROOT, "exports")
    fw_agents_path = os.path.join(PROJECT_ROOT, "core", "framework", "agents")
    env["PYTHONPATH"] = f"{core_path}:{exports_path}:{fw_agents_path}:{PROJECT_ROOT}:{pythonpath}"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "error": "Tests timed out after 120 seconds. A test may be hanging "
                "(e.g. a client-facing node waiting for stdin). Use mock mode "
                "or add timeouts to async tests.",
                "command": " ".join(cmd),
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to run pytest: {e}",
                "command": " ".join(cmd),
            }
        )

    output = result.stdout + "\n" + result.stderr

    # Parse summary line (e.g. "5 passed, 2 failed in 1.23s")
    summary_match = re.search(r"=+ ([\d\w,\s]+) in [\d.]+s =+", output)
    summary_text = summary_match.group(1) if summary_match else "unknown"

    passed = failed = skipped = errors = 0
    for label, pattern in [
        ("passed", r"(\d+) passed"),
        ("failed", r"(\d+) failed"),
        ("skipped", r"(\d+) skipped"),
        ("errors", r"(\d+) error"),
    ]:
        m = re.search(pattern, summary_text)
        if m:
            if label == "passed":
                passed = int(m.group(1))
            elif label == "failed":
                failed = int(m.group(1))
            elif label == "skipped":
                skipped = int(m.group(1))
            elif label == "errors":
                errors = int(m.group(1))

    total = passed + failed + skipped + errors

    # Extract per-test results
    test_results = []
    test_pattern = re.compile(r"([\w/]+\.py)::(\w+)\s+(PASSED|FAILED|SKIPPED|ERROR)")
    for m in test_pattern.finditer(output):
        test_results.append(
            {
                "file": m.group(1),
                "test_name": m.group(2),
                "status": m.group(3).lower(),
            }
        )

    # Extract failure details
    failures = []
    failure_section = re.search(
        r"=+ FAILURES =+(.+?)(?:=+ (?:short test summary|ERRORS|warnings) =+|$)",
        output,
        re.DOTALL,
    )
    if failure_section:
        failure_text = failure_section.group(1)
        failure_blocks = re.split(r"_+ (test_\w+) _+", failure_text)
        for i in range(1, len(failure_blocks), 2):
            if i + 1 < len(failure_blocks):
                detail = failure_blocks[i + 1].strip()
                if len(detail) > 2000:
                    detail = detail[:2000] + "\n... (truncated)"
                failures.append(
                    {
                        "test_name": failure_blocks[i],
                        "detail": detail,
                    }
                )

    return json.dumps(
        {
            "agent_name": agent_name,
            "summary": summary_text,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "total": total,
            "test_results": test_results,
            "failures": failures,
            "exit_code": result.returncode,
        },
        indent=2,
    )


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    global PROJECT_ROOT, SNAPSHOT_DIR

    parser = argparse.ArgumentParser(description="Coder Tools MCP Server")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--port", type=int, default=int(os.getenv("CODER_TOOLS_PORT", "4002")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    PROJECT_ROOT = os.path.abspath(args.project_root) if args.project_root else _find_project_root()
    SNAPSHOT_DIR = os.path.join(
        os.path.expanduser("~"),
        ".hive",
        "snapshots",
        os.path.basename(PROJECT_ROOT),
    )
    logger.info(f"Project root: {PROJECT_ROOT}")
    logger.info(f"Snapshot dir: {SNAPSHOT_DIR}")

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        logger.info(f"Starting HTTP server on {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
