import contextlib
import json
import os
import re
import sys
import tempfile

from mcp.server.fastmcp import FastMCP

from aden_tools.hashline import (
    HASHLINE_MAX_FILE_BYTES,
    format_hashlines,
    maybe_strip,
    parse_anchor,
    strip_boundary_echo,
    strip_content_prefixes,
    strip_insert_echo,
    validate_anchor,
)

from aden_tools.file_state_cache import Freshness, check_fresh, record_read

from ..security import get_sandboxed_path


def register_tools(mcp: FastMCP) -> None:
    """Register hashline edit tools with the MCP server."""

    @mcp.tool()
    def hashline_edit(
        path: str,
        edits: str,
        agent_id: str,
        auto_cleanup: bool = True,
        encoding: str = "utf-8",
    ) -> dict:
        """
        Purpose
            Edit a file using anchor-based line references (N:hash) for precise edits.

        When to use
            After reading a file with read_file(hashline=True), use the anchors to make
            targeted edits without reproducing exact file content.

        Rules & Constraints
            Anchors must match the current file content (hash validation).
            All edits in a batch are validated before any are applied (atomic).
            Overlapping line ranges within a single call are rejected.

        Args:
            path: The path to the file (relative to agent sandbox)
            edits: JSON string containing a list of edit operations.
                Each op is a dict with:
                - set_line: anchor, content
                - replace_lines: start_anchor, end_anchor, content
                - insert_after: anchor, content
                - insert_before: anchor, content
                - replace: old_content, new_content, allow_multiple
                - append: content
            agent_id: The ID of the agent
            auto_cleanup: If True (default), automatically strip hashline prefixes and
                echoed context from edit content. Set to False to write content exactly
                as provided.
            encoding: File encoding (default "utf-8"). Must match the file's actual encoding.

        Returns:
            Dict with success status, updated hashline content, and edit count, or error dict
        """
        # 1. Parse JSON
        try:
            edit_ops = json.loads(edits)
        except (json.JSONDecodeError, TypeError) as e:
            return {"error": f"Invalid JSON in edits: {e}"}

        if not isinstance(edit_ops, list):
            return {"error": "edits must be a JSON array of operations"}

        if not edit_ops:
            return {"error": "edits array is empty"}

        if len(edit_ops) > 100:
            return {"error": "Too many edits in one call (max 100). Split into multiple calls."}

        # 2. Read file
        try:
            secure_path = get_sandboxed_path(path, agent_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}
            if not os.path.isfile(secure_path):
                return {"error": f"Path is not a file: {path}"}

            # Stale-edit guard: refuse to edit unless we have a recent
            # read recorded in the file-state cache and the file on disk
            # still matches it. This catches the case where the user
            # saved the file in their editor between the model's Read
            # and Edit, which would otherwise cause the model to write
            # against a stale mental model.
            fresh = check_fresh(agent_id, secure_path)
            if fresh.status is Freshness.UNREAD:
                return {
                    "error": (
                        f"Refusing to edit '{path}': you must call "
                        f"read_file('{path}') first so the harness can "
                        f"track its state before you edit it."
                    )
                }
            if fresh.status is Freshness.STALE:
                return {
                    "error": (
                        f"Refusing to edit '{path}': {fresh.detail}. "
                        f"Re-read the file with read_file before editing."
                    )
                }

            with open(secure_path, "rb") as f:
                raw_head = f.read(8192)
            eol = "\r\n" if b"\r\n" in raw_head else "\n"

            with open(secure_path, encoding=encoding) as f:
                content = f.read()
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        content_bytes = len(content.encode(encoding))
        if content_bytes > HASHLINE_MAX_FILE_BYTES:
            return {"error": f"File too large for hashline_edit ({content_bytes} bytes, max 10MB)"}

        trailing_newline = content.endswith("\n")
        lines = content.splitlines()

        # 3. Categorize and validate ops
        splices = []  # (start_0idx, end_0idx, new_lines, op_index)
        replaces = []  # (old_content, new_content, op_index, allow_multiple)
        cleanup_actions = []

        for i, op in enumerate(edit_ops):
            if not isinstance(op, dict):
                return {"error": f"Edit #{i + 1}: operation must be a dict"}

            match op.get("op"):
                case "set_line":
                    anchor = op.get("anchor", "")
                    err = validate_anchor(anchor, lines)
                    if err:
                        return {"error": f"Edit #{i + 1} (set_line): {err}"}
                    if "content" not in op:
                        return {
                            "error": f"Edit #{i + 1} (set_line): missing required field 'content'"
                        }
                    if not isinstance(op["content"], str):
                        return {"error": f"Edit #{i + 1} (set_line): content must be a string"}
                    if "\n" in op["content"] or "\r" in op["content"]:
                        return {
                            "error": f"Edit #{i + 1} (set_line): content must be a single line. "
                            f"Use replace_lines for multi-line replacement."
                        }
                    line_num, _ = parse_anchor(anchor)
                    idx = line_num - 1
                    new_content = op["content"]
                    new_lines = [new_content] if new_content else []
                    new_lines = maybe_strip(
                        new_lines,
                        strip_content_prefixes,
                        "prefix_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    splices.append((idx, idx, new_lines, i))

                case "replace_lines":
                    start_anchor = op.get("start_anchor", "")
                    end_anchor = op.get("end_anchor", "")
                    err = validate_anchor(start_anchor, lines)
                    if err:
                        return {"error": f"Edit #{i + 1} (replace_lines start): {err}"}
                    err = validate_anchor(end_anchor, lines)
                    if err:
                        return {"error": f"Edit #{i + 1} (replace_lines end): {err}"}
                    start_num, _ = parse_anchor(start_anchor)
                    end_num, _ = parse_anchor(end_anchor)
                    if start_num > end_num:
                        return {
                            "error": f"Edit #{i + 1} (replace_lines): "
                            f"start line {start_num} > end line {end_num}"
                        }
                    if "content" not in op:
                        return {
                            "error": (
                                f"Edit #{i + 1} (replace_lines): missing required field 'content'"
                            )
                        }
                    if not isinstance(op["content"], str):
                        return {"error": f"Edit #{i + 1} (replace_lines): content must be a string"}
                    new_content = op["content"]
                    new_lines = new_content.splitlines() if new_content else []
                    new_lines = maybe_strip(
                        new_lines,
                        strip_content_prefixes,
                        "prefix_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    new_lines = maybe_strip(
                        new_lines,
                        lambda nl, s=start_num, e=end_num: strip_boundary_echo(lines, s, e, nl),
                        "boundary_echo_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    splices.append((start_num - 1, end_num - 1, new_lines, i))

                case "insert_after":
                    anchor = op.get("anchor", "")
                    err = validate_anchor(anchor, lines)
                    if err:
                        return {"error": f"Edit #{i + 1} (insert_after): {err}"}
                    line_num, _ = parse_anchor(anchor)
                    idx = line_num - 1
                    new_content = op.get("content", "")
                    if not isinstance(new_content, str):
                        return {"error": f"Edit #{i + 1} (insert_after): content must be a string"}
                    if not new_content:
                        return {"error": f"Edit #{i + 1} (insert_after): content is empty"}
                    new_lines = new_content.splitlines()
                    new_lines = maybe_strip(
                        new_lines,
                        strip_content_prefixes,
                        "prefix_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    new_lines = maybe_strip(
                        new_lines,
                        lambda nl, _idx=idx: strip_insert_echo(lines[_idx], nl),
                        "insert_echo_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    splices.append((idx + 1, idx, new_lines, i))

                case "insert_before":
                    anchor = op.get("anchor", "")
                    err = validate_anchor(anchor, lines)
                    if err:
                        return {"error": f"Edit #{i + 1} (insert_before): {err}"}
                    line_num, _ = parse_anchor(anchor)
                    idx = line_num - 1
                    new_content = op.get("content", "")
                    if not isinstance(new_content, str):
                        return {"error": f"Edit #{i + 1} (insert_before): content must be a string"}
                    if not new_content:
                        return {"error": f"Edit #{i + 1} (insert_before): content is empty"}
                    new_lines = new_content.splitlines()
                    new_lines = maybe_strip(
                        new_lines,
                        strip_content_prefixes,
                        "prefix_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    new_lines = maybe_strip(
                        new_lines,
                        lambda nl, _idx=idx: strip_insert_echo(lines[_idx], nl, position="last"),
                        "insert_echo_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    splices.append((idx, idx - 1, new_lines, i))

                case "replace":
                    old_content = op.get("old_content")
                    new_content = op.get("new_content")
                    if old_content is None:
                        return {"error": f"Edit #{i + 1} (replace): missing old_content"}
                    if not isinstance(old_content, str):
                        return {"error": f"Edit #{i + 1} (replace): old_content must be a string"}
                    if not old_content:
                        return {"error": f"Edit #{i + 1} (replace): old_content must not be empty"}
                    if new_content is None:
                        return {"error": f"Edit #{i + 1} (replace): missing new_content"}
                    if not isinstance(new_content, str):
                        return {"error": f"Edit #{i + 1} (replace): new_content must be a string"}
                    allow_multiple = op.get("allow_multiple", False)
                    if not isinstance(allow_multiple, bool):
                        return {
                            "error": f"Edit #{i + 1} (replace): allow_multiple must be a boolean"
                        }
                    replaces.append((old_content, new_content, i, allow_multiple))

                case "append":
                    new_content = op.get("content")
                    if new_content is None:
                        return {"error": f"Edit #{i + 1} (append): missing content"}
                    if not isinstance(new_content, str):
                        return {"error": f"Edit #{i + 1} (append): content must be a string"}
                    if not new_content:
                        return {"error": f"Edit #{i + 1} (append): content must not be empty"}
                    new_lines = new_content.splitlines()
                    new_lines = maybe_strip(
                        new_lines,
                        strip_content_prefixes,
                        "prefix_strip",
                        auto_cleanup,
                        cleanup_actions,
                    )
                    insert_point = len(lines)
                    splices.append((insert_point, insert_point - 1, new_lines, i))

                case unknown:
                    return {"error": f"Edit #{i + 1}: unknown op '{unknown}'"}

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
                        return {
                            "error": (
                                f"Overlapping edits: edit #{idx_a + 1} "
                                f"and edit #{idx_b + 1} affect overlapping line ranges"
                            )
                        }
                    continue

                if is_insert_b and not is_insert_a:
                    if s_a <= s_b <= e_a + 1:
                        return {
                            "error": (
                                f"Overlapping edits: edit #{idx_a + 1} "
                                f"and edit #{idx_b + 1} affect overlapping line ranges"
                            )
                        }
                    continue

                if not (e_a < s_b or e_b < s_a):
                    return {
                        "error": (
                            f"Overlapping edits: edit #{idx_a + 1} "
                            f"and edit #{idx_b + 1} affect overlapping line ranges"
                        )
                    }

        # 5. Apply splices bottom-up
        changes_made = 0
        working = list(lines)
        for start, end, new_lines, _ in sorted(splices, key=lambda s: (s[0], s[3]), reverse=True):
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
                return {
                    "error": (
                        f"Edit #{op_idx + 1} (replace): "
                        f"old_content not found "
                        f"(note: anchor-based edits in this batch are applied first)"
                    )
                }
            if count > 1 and not allow_multiple:
                return {
                    "error": (
                        f"Edit #{op_idx + 1} (replace): "
                        f"old_content found {count} times (must be unique). "
                        f"Include more surrounding context to make it unique, "
                        f"or use anchor-based ops instead."
                    )
                }
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

        # 8. Restore original EOL style (only convert bare \n, not existing \r\n)
        if eol == "\r\n":
            joined = re.sub(r"(?<!\r)\n", "\r\n", joined)

        # 9. Atomic write (write-to-tmp + os.replace)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(secure_path))
            fd_open = True
            try:
                match sys.platform:
                    case "win32":
                        pass  # ACL preservation handled by atomic_replace below
                    case _:
                        original_mode = os.stat(secure_path).st_mode
                        os.fchmod(fd, original_mode)
                with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                    fd_open = False
                    f.write(joined)
                match sys.platform:
                    case "win32":
                        from aden_tools._win32_atomic import atomic_replace

                        atomic_replace(secure_path, tmp_path)
                    case _:
                        os.replace(tmp_path, secure_path)
            except BaseException:
                if fd_open:
                    os.close(fd)
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except Exception as e:
            return {"error": f"Failed to write file: {e}"}

        # Re-record the new file state so a second edit in the same turn
        # sees the post-write hash instead of tripping the stale guard.
        try:
            record_read(agent_id, secure_path, content_bytes=joined.encode(encoding))
        except Exception:
            # Hash record is best-effort; a failure here must not break
            # the edit that already succeeded on disk.
            pass

        # 10. Build response
        updated_lines = joined.splitlines()
        hashline_content = format_hashlines(updated_lines)

        result = {
            "success": True,
            "path": path,
            "edits_applied": changes_made,
            "content": hashline_content,
        }
        if changes_made == 0:
            result["note"] = "Content unchanged after applying edits"
        if cleanup_actions:
            result["cleanup_applied"] = cleanup_actions
        if replace_counts:
            result["replacements"] = {
                f"edit_{op_idx + 1}": count for op_idx, count in replace_counts
            }
        return result
