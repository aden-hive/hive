import contextlib
import json
import os
import re
import tempfile

from mcp.server.fastmcp import FastMCP

from ..hashline import format_hashlines, parse_anchor, validate_anchor
from ..security import get_secure_path

_HASHLINE_PREFIX_RE = re.compile(r"^\d+:[0-9a-f]{4}\|")


def _strip_content_prefixes(lines: list[str]) -> list[str]:
    """Strip hashline prefixes from content lines when all have them.

    LLMs frequently copy hashline-formatted text (e.g. '5:a3b1|content') into
    their content fields. Only strips when 2+ non-empty lines all match the
    exact hashline prefix pattern (N:hhhh|). Single-line content is left alone
    to avoid false positives on literal text that happens to match the pattern.
    """
    if not lines:
        return lines
    non_empty = [ln for ln in lines if ln]
    if len(non_empty) < 2:
        return lines
    prefix_count = sum(1 for ln in non_empty if _HASHLINE_PREFIX_RE.match(ln))
    if prefix_count < len(non_empty):
        return lines
    return [_HASHLINE_PREFIX_RE.sub("", ln) for ln in lines]


def _whitespace_equal(a: str, b: str) -> bool:
    """Compare strings ignoring spaces and tabs."""
    return a.replace(" ", "").replace("\t", "") == b.replace(" ", "").replace("\t", "")


def _strip_insert_echo(
    anchor_line: str, new_lines: list[str], *, position: str = "first"
) -> list[str]:
    """Strip echoed anchor line from insert content.

    If the model echoes the anchor line in inserted content, remove it to
    avoid duplication. Only applies when content has 2+ lines and both the
    anchor and checked content line are non-blank.

    position="first" (insert_after): check first line, strip from front.
    position="last" (insert_before): check last line, strip from end.
    """
    if len(new_lines) <= 1:
        return new_lines
    if position == "last":
        if not anchor_line.strip() or not new_lines[-1].strip():
            return new_lines
        if _whitespace_equal(new_lines[-1], anchor_line):
            return new_lines[:-1]
    else:
        if not anchor_line.strip() or not new_lines[0].strip():
            return new_lines
        if _whitespace_equal(new_lines[0], anchor_line):
            return new_lines[1:]
    return new_lines


def _strip_boundary_echo(
    file_lines: list[str], start_1idx: int, end_1idx: int, new_lines: list[str]
) -> list[str]:
    """Strip echoed boundary context from replace_lines content.

    If the model includes the line before AND after the replaced range as part
    of the replacement content, strip those echoed boundary lines. Both
    boundaries must echo simultaneously before either is stripped (a single
    boundary match is too likely to be a coincidence with real content).
    Only applies when the replacement has more lines than the range being
    replaced, and both the boundary line and content line are non-blank.
    """
    range_count = end_1idx - start_1idx + 1
    if len(new_lines) <= 1 or len(new_lines) <= range_count:
        return new_lines

    # Check if leading boundary echoes
    before_idx = start_1idx - 2  # 0-indexed line before range
    leading_echoes = (
        before_idx >= 0
        and new_lines[0].strip()
        and file_lines[before_idx].strip()
        and _whitespace_equal(new_lines[0], file_lines[before_idx])
    )

    # Check if trailing boundary echoes
    after_idx = end_1idx  # 0-indexed line after range
    trailing_echoes = (
        after_idx < len(file_lines)
        and new_lines[-1].strip()
        and file_lines[after_idx].strip()
        and _whitespace_equal(new_lines[-1], file_lines[after_idx])
    )

    # Only strip if BOTH boundaries echo and there is content between them.
    # len < 3 means no real content between the two boundary lines, so
    # stripping would produce an empty list (accidental deletion).
    if not (leading_echoes and trailing_echoes) or len(new_lines) < 3:
        return new_lines

    return new_lines[1:-1]


def _maybe_strip(new_lines, strip_fn, action_name, auto_cleanup, cleanup_actions):
    """Apply a strip function if auto_cleanup is enabled, tracking actions."""
    if not auto_cleanup:
        return new_lines
    cleaned = strip_fn(new_lines)
    if cleaned != new_lines:
        if action_name not in cleanup_actions:
            cleanup_actions.append(action_name)
        return cleaned
    return new_lines


def register_tools(mcp: FastMCP) -> None:
    """Register hashline edit tools with the MCP server."""

    @mcp.tool()
    def hashline_edit(
        path: str,
        edits: str,
        workspace_id: str,
        agent_id: str,
        session_id: str,
        auto_cleanup: bool = True,
        encoding: str = "utf-8",
    ) -> dict:
        """
        Purpose
            Edit a file using anchor-based line references (N:hash) for precise edits.

        When to use
            After reading a file with view_file(hashline=True), use the anchors to make
            targeted edits without reproducing exact file content.

        Rules & Constraints
            Anchors must match the current file content (hash validation).
            All edits in a batch are validated before any are applied (atomic).
            Overlapping line ranges within a single call are rejected.

        Args:
            path: The path to the file (relative to session root)
            edits: JSON string containing a list of edit operations.
                Each op is a dict with:
                - set_line: anchor, content
                - replace_lines: start_anchor, end_anchor, content
                - insert_after: anchor, content
                - insert_before: anchor, content
                - replace: old_content, new_content, allow_multiple
                - append: content
            workspace_id: The ID of workspace
            agent_id: The ID of agent
            session_id: The ID of the current session
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
            secure_path = get_secure_path(path, workspace_id, agent_id, session_id)
            if not os.path.exists(secure_path):
                return {"error": f"File not found at {path}"}
            if not os.path.isfile(secure_path):
                return {"error": f"Path is not a file: {path}"}

            with open(secure_path, "rb") as f:
                raw_head = f.read(8192)
            eol = "\r\n" if b"\r\n" in raw_head else "\n"

            with open(secure_path, encoding=encoding) as f:
                content = f.read()
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        content_bytes = len(content.encode(encoding))
        if content_bytes > 10 * 1024 * 1024:
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

            op_type = op.get("op")

            if op_type == "set_line":
                anchor = op.get("anchor", "")
                err = validate_anchor(anchor, lines)
                if err:
                    return {"error": f"Edit #{i + 1} (set_line): {err}"}
                if "content" not in op:
                    return {"error": f"Edit #{i + 1} (set_line): missing required field 'content'"}
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
                new_lines = new_content.splitlines() if new_content else []
                new_lines = _maybe_strip(
                    new_lines,
                    _strip_content_prefixes,
                    "prefix_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                splices.append((idx, idx, new_lines, i))

            elif op_type == "replace_lines":
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
                        "error": f"Edit #{i + 1} (replace_lines): missing required field 'content'"
                    }
                if not isinstance(op["content"], str):
                    return {"error": f"Edit #{i + 1} (replace_lines): content must be a string"}
                new_content = op["content"]
                new_lines = new_content.splitlines() if new_content else []
                new_lines = _maybe_strip(
                    new_lines,
                    _strip_content_prefixes,
                    "prefix_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                new_lines = _maybe_strip(
                    new_lines,
                    lambda nl, s=start_num, e=end_num: _strip_boundary_echo(lines, s, e, nl),
                    "boundary_echo_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                splices.append((start_num - 1, end_num - 1, new_lines, i))

            elif op_type == "insert_after":
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
                new_lines = _maybe_strip(
                    new_lines,
                    _strip_content_prefixes,
                    "prefix_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                new_lines = _maybe_strip(
                    new_lines,
                    lambda nl, _idx=idx: _strip_insert_echo(lines[_idx], nl),
                    "insert_echo_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                # Insert after = splice at (idx+1, idx, new_lines)
                # start > end means pure insertion at that point
                splices.append((idx + 1, idx, new_lines, i))

            elif op_type == "insert_before":
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
                new_lines = _maybe_strip(
                    new_lines,
                    _strip_content_prefixes,
                    "prefix_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                new_lines = _maybe_strip(
                    new_lines,
                    lambda nl, _idx=idx: _strip_insert_echo(lines[_idx], nl, position="last"),
                    "insert_echo_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                # Insert before = splice at (idx, idx - 1, new_lines)
                # end < start signals a pure insertion (no lines removed).
                # For insert_before line 1, idx=0 so end=-1.
                splices.append((idx, idx - 1, new_lines, i))

            elif op_type == "replace":
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
                    return {"error": f"Edit #{i + 1} (replace): allow_multiple must be a boolean"}
                replaces.append((old_content, new_content, i, allow_multiple))

            elif op_type == "append":
                new_content = op.get("content")
                if new_content is None:
                    return {"error": f"Edit #{i + 1} (append): missing content"}
                if not isinstance(new_content, str):
                    return {"error": f"Edit #{i + 1} (append): content must be a string"}
                if not new_content:
                    return {"error": f"Edit #{i + 1} (append): content must not be empty"}
                new_lines = new_content.splitlines()
                new_lines = _maybe_strip(
                    new_lines,
                    _strip_content_prefixes,
                    "prefix_strip",
                    auto_cleanup,
                    cleanup_actions,
                )
                insert_point = len(lines)
                splices.append((insert_point, insert_point - 1, new_lines, i))

            else:
                return {"error": f"Edit #{i + 1}: unknown op '{op_type}'"}

        # 4. Check for overlapping splice ranges
        # Each splice is (start_0idx, end_0idx, new_lines, op_index).
        # Pure insertions have start > end (e.g. insert_after line 2 = (3, 2, ...)).
        # Two insertions at the same point are allowed.
        # An insertion inside a replace range is NOT allowed.
        for j in range(len(splices)):
            for k in range(j + 1, len(splices)):
                s_a, e_a, _, idx_a = splices[j]
                s_b, e_b, _, idx_b = splices[k]
                is_insert_a = s_a > e_a
                is_insert_b = s_b > e_b

                # Two insertions at the same point: allowed
                if is_insert_a and is_insert_b:
                    continue

                # Insertion vs replace range: check if insertion point is inside range
                if is_insert_a and not is_insert_b:
                    # insert point is s_a; replace covers [s_b, e_b]
                    if s_b <= s_a <= e_b + 1:
                        return {
                            "error": (
                                f"Overlapping edits: edit #{idx_a + 1} "
                                f"and edit #{idx_b + 1} affect overlapping line ranges"
                            )
                        }
                    continue

                if is_insert_b and not is_insert_a:
                    # insert point is s_b; replace covers [s_a, e_a]
                    if s_a <= s_b <= e_a + 1:
                        return {
                            "error": (
                                f"Overlapping edits: edit #{idx_a + 1} "
                                f"and edit #{idx_b + 1} affect overlapping line ranges"
                            )
                        }
                    continue

                # Two replace ranges: check for intersection
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
                # Pure insertion always counts as a change
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

        # 8. Restore original EOL style
        if eol == "\r\n":
            joined = joined.replace("\n", "\r\n")

        # 9. Atomic write (write-to-tmp + os.replace)
        try:
            original_mode = os.stat(secure_path).st_mode
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(secure_path))
            fd_open = True
            try:
                os.fchmod(fd, original_mode)
                with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                    fd_open = False
                    f.write(joined)
                os.replace(tmp_path, secure_path)
            except BaseException:
                if fd_open:
                    os.close(fd)
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except Exception as e:
            return {"error": f"Failed to write file: {e}"}

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
