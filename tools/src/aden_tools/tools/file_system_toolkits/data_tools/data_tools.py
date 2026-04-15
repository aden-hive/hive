"""
Data Tools - Read and write files with data_dir sandboxing.

These tools let agents read and write files within their session's data directory
and access files in ~/.hive/ for cross-agent file sharing.

Uses context injection for data_dir - the parameter is auto-injected by the
framework and doesn't need to be provided by the LLM.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from aden_tools.file_state_cache import record_read

# ~/.hive/ is always allowed for cross-agent file access
HIVE_DIR = os.path.expanduser("~/.hive")


def _resolve_path(path: str, data_dir: str | None) -> str:
    """Resolve and validate a path against the allowed directories.

    Args:
        path: The path to resolve (can be relative or absolute)
        data_dir: The session's data directory from context

    Returns:
        The resolved absolute path

    Raises:
        ValueError: If path is outside allowed directories
    """
    if not data_dir:
        raise ValueError("data_dir is not configured")

    # Normalize path
    path = path.replace("/", os.sep)

    # Expand ~ to home directory
    if path.startswith("~"):
        path = os.path.expanduser(path)

    # Resolve to absolute path
    if os.path.isabs(path):
        resolved = os.path.abspath(path)
    else:
        resolved = os.path.abspath(os.path.join(data_dir, path))

    # Check against allowed paths
    allowed_paths = [data_dir, HIVE_DIR]
    for allowed in allowed_paths:
        try:
            if os.path.commonpath([resolved, allowed]) == allowed:
                return resolved
        except ValueError:
            continue

    # Block and remind
    allowed_str = ", ".join(f"'{p}'" for p in allowed_paths)
    raise ValueError(f"Access denied: '{path}' is not accessible. Allowed paths: {allowed_str}")


def register_tools(mcp: FastMCP) -> None:
    """Register file management tools with the MCP server."""

    @mcp.tool()
    def read_file(
        path: str,
        offset: int = 1,
        limit: int = 0,
        data_dir: str = "",
        agent_id: str = "",
    ) -> str:
        """Read file contents with line numbers.

        Files are read from the session's data directory or ~/.hive/.
        Large files are automatically truncated at 2000 lines or 50KB.
        Use offset and limit to paginate through large files.

        Args:
            path: File path to read. Can be relative to data_dir or absolute.
            offset: Starting line number, 1-indexed (default: 1).
            limit: Max lines to return, 0 = up to 2000 (default: 0).
            data_dir: Auto-injected - the session's data directory.
            agent_id: Auto-injected - the calling agent id, used to scope
                the file-state cache that powers stale-edit detection.
        """
        try:
            resolved = _resolve_path(path, data_dir)
        except ValueError as e:
            return f"Error: {e}"

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

        # Check for binary files
        try:
            with open(resolved, "rb") as f:
                chunk = f.read(4096)
            if b"\x00" in chunk:
                size = os.path.getsize(resolved)
                return f"Binary file: {path} ({size:,} bytes). Cannot display binary content."
        except OSError:
            pass

        try:
            # Read as bytes first so we can hash them for the state cache
            # without a second open, then decode for the line-formatted
            # return value the model sees.
            with open(resolved, "rb") as f:
                raw_bytes = f.read()
            content = raw_bytes.decode("utf-8", errors="replace")
            # Record this read in the per-agent state cache so a later
            # hashline_edit/write_file call can detect external writes
            # that happened between now and then. Scoped to agent_id so
            # two agents sharing the MCP server can't see each other.
            record_read(agent_id or None, resolved, content_bytes=raw_bytes)

            all_lines = content.splitlines()
            total_lines = len(all_lines)
            start_idx = max(0, offset - 1)
            effective_limit = limit if limit > 0 else 2000
            end_idx = min(start_idx + effective_limit, total_lines)

            max_bytes = 50 * 1024
            output_lines = []
            byte_count = 0

            for i in range(start_idx, end_idx):
                line = all_lines[i]
                if len(line) > 2000:
                    line = line[:2000] + "..."
                formatted = f"{i + 1:>6}\t{line}"
                line_bytes = len(formatted.encode("utf-8")) + 1
                if byte_count + line_bytes > max_bytes:
                    break
                output_lines.append(formatted)
                byte_count += line_bytes

            result = "\n".join(output_lines)
            lines_shown = len(output_lines)
            actual_end = start_idx + lines_shown

            if actual_end < total_lines:
                result += (
                    f"\n\n(Showing lines {start_idx + 1}-{actual_end}"
                    f" of {total_lines}."
                    f" Use offset={actual_end + 1} to continue reading.)"
                )

            return result
        except Exception as e:
            return f"Error reading file: {e}"

    @mcp.tool()
    def write_file(
        path: str,
        content: str,
        data_dir: str = "",
    ) -> str:
        """Create or overwrite a file with the given content.

        Automatically creates parent directories. Files are written to
        the session's data directory or ~/.hive/.

        Args:
            path: File path to write. Can be relative to data_dir or absolute.
            content: Complete file content to write.
            data_dir: Auto-injected - the session's data directory.
        """
        try:
            resolved = _resolve_path(path, data_dir)
        except ValueError as e:
            return f"Error: {e}"

        try:
            resolved_path = Path(resolved)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)

            existed = resolved_path.is_file()
            content_str = content if content is not None else ""
            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(content_str)
                f.flush()
                os.fsync(f.fileno())

            line_count = content_str.count("\n") + (
                1 if content_str and not content_str.endswith("\n") else 0
            )
            action = "Updated" if existed else "Created"
            return f"{action} {path} ({len(content_str):,} bytes, {line_count} lines)"
        except Exception as e:
            return f"Error writing file: {e}"

    @mcp.tool()
    def list_files(
        path: str = ".",
        recursive: bool = False,
        data_dir: str = "",
    ) -> str:
        """List directory contents with type indicators.

        Directories have a / suffix. Hidden files and common build directories
        are skipped.

        Args:
            path: Directory path (default: data_dir).
            recursive: List recursively (default: false).
            data_dir: Auto-injected - the session's data directory.
        """
        try:
            resolved = _resolve_path(path, data_dir)
        except ValueError as e:
            return f"Error: {e}"

        if not os.path.isdir(resolved):
            return f"Error: Directory not found: {path}"

        try:
            skip = {".git", "__pycache__", "node_modules", ".venv", ".tox"}
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
        pattern: str,
        path: str = ".",
        data_dir: str = "",
    ) -> str:
        """Search file contents using regex.

        Results sorted by file with line numbers. Searches within
        the session's data directory or ~/.hive/.

        Args:
            pattern: Regex pattern to search for.
            path: Directory path to search (default: data_dir).
            data_dir: Auto-injected - the session's data directory.
        """
        import re

        try:
            resolved = _resolve_path(path, data_dir)
        except ValueError as e:
            return f"Error: {e}"

        if not os.path.isdir(resolved):
            return f"Error: Directory not found: {path}"

        try:
            compiled = re.compile(pattern)
            matches: list[str] = []
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv"}

            for root, dirs, files in os.walk(resolved):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for fname in files:
                    fpath = os.path.join(root, fname)
                    display_path = os.path.relpath(fpath, resolved)
                    try:
                        with open(fpath, encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                stripped = line.rstrip()
                                if compiled.search(stripped):
                                    matches.append(f"{display_path}:{i}:{stripped[:2000]}")
                                    if len(matches) >= 100:
                                        return "\n".join(matches) + "\n... (truncated)"
                    except (OSError, UnicodeDecodeError):
                        continue

            return "\n".join(matches) if matches else "No matches found."
        except re.error as e:
            return f"Error: Invalid regex: {e}"
