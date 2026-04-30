"""``shell_rg`` and ``shell_find`` — structured wrappers over ripgrep / find.

Distinct from ``files-tools.search_files`` (project-relative,
code-editor-tuned) — these accept arbitrary paths and surface the
underlying tool's full feature set. The foundational skill steers
agents to ``files-tools`` for in-project work and these tools for
``/var/log``, ``/etc``, archive contents, etc.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


_DEFAULT_TIMEOUT_SEC = 30
_MAX_OUTPUT_BYTES = 256 * 1024


def register_search_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def shell_rg(
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        type_filter: str | None = None,
        ignore_case: bool = False,
        context: int = 0,
        max_count: int | None = None,
        max_depth: int | None = None,
        hidden: bool = False,
        no_ignore: bool = False,
        extra_args: list[str] | None = None,
    ) -> dict:
        """Run ripgrep on `path` for `pattern`.

        For project-scoped code search use files-tools.search_files instead;
        this tool is for raw paths (system configs, /var/log, archive contents)
        and exposes the full rg flag surface.

        Args:
            pattern: Regex pattern.
            path: Directory or file to search. Default: current dir.
            glob: Filename glob (e.g. "*.py").
            type_filter: rg filetype shortcut (e.g. "py", "rust", "md").
            ignore_case: Case-insensitive search.
            context: Lines of context above and below each match.
            max_count: Stop after N matches per file.
            max_depth: Limit directory recursion depth.
            hidden: Include hidden files (rg ignores them by default).
            no_ignore: Don't respect .gitignore.
            extra_args: Raw flags to append (use sparingly — most needs are covered above).

        Returns: {matches: [...], total, truncated, command}
        """
        if not shutil.which("rg"):
            return {"error": "ripgrep (rg) is not installed on this host"}

        argv = ["rg", "--json", "--no-heading"]
        if ignore_case:
            argv.append("-i")
        if context > 0:
            argv.extend(["-C", str(context)])
        if max_count is not None:
            argv.extend(["-m", str(max_count)])
        if max_depth is not None:
            argv.extend(["--max-depth", str(max_depth)])
        if hidden:
            argv.append("--hidden")
        if no_ignore:
            argv.append("--no-ignore")
        if type_filter:
            argv.extend(["-t", type_filter])
        if glob:
            argv.extend(["-g", glob])
        if extra_args:
            argv.extend(str(a) for a in extra_args)
        argv.extend(["--", pattern, path])

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=_DEFAULT_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": "ripgrep timed out", "command": argv}
        except FileNotFoundError:
            return {"error": "ripgrep (rg) is not installed on this host"}

        # Parse JSON-line output: only "match" events are interesting for the
        # default surface. Errors land in stderr.
        import json

        matches: list[dict] = []
        truncated = False
        bytes_seen = 0
        for line in proc.stdout.splitlines():
            if not line:
                continue
            bytes_seen += len(line)
            if bytes_seen > _MAX_OUTPUT_BYTES:
                truncated = True
                break
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") != "match":
                continue
            data = evt.get("data", {})
            path_data = (data.get("path") or {}).get("text") or ""
            line_no = data.get("line_number")
            text = (data.get("lines") or {}).get("text") or ""
            matches.append({"path": path_data, "line": line_no, "text": text.rstrip("\n")})

        return {
            "matches": matches,
            "total": len(matches),
            "truncated": truncated,
            "exit_code": proc.returncode,
            "stderr": proc.stderr.decode("utf-8", errors="replace")[-2000:] if proc.stderr else "",
        }

    @mcp.tool()
    def shell_find(
        path: str,
        name: str | None = None,
        iname: str | None = None,
        type_filter: str | None = None,
        mtime_days: int | None = None,
        size_kb_min: int | None = None,
        size_kb_max: int | None = None,
        max_depth: int | None = None,
        max_results: int = 1000,
    ) -> dict:
        """Run `find` with structured predicates.

        For tree views or stat-like info on a single path, use shell_exec
        ("ls -la", "tree -L 2", "stat foo"). This tool is for predicate-driven
        searches (find me .log files modified in the last 7 days bigger than 1MB).

        Args:
            path: Directory to search under.
            name: Glob match (case-sensitive). e.g. "*.log".
            iname: Glob match (case-insensitive).
            type_filter: "f" file, "d" dir, "l" symlink.
            mtime_days: Modified within the last N days (negative or 0 means
                exact-day; we use -N for "within").
            size_kb_min, size_kb_max: Size bounds in KB.
            max_depth: Limit directory recursion.
            max_results: Cap on returned paths.

        Returns: {paths: [...], count, truncated, command}
        """
        if not shutil.which("find"):
            return {"error": "find is not installed on this host"}

        argv = ["find", path]
        if max_depth is not None:
            argv.extend(["-maxdepth", str(max_depth)])
        if type_filter in {"f", "d", "l"}:
            argv.extend(["-type", type_filter])
        if name:
            argv.extend(["-name", name])
        if iname:
            argv.extend(["-iname", iname])
        if mtime_days is not None:
            argv.extend(["-mtime", f"-{abs(mtime_days)}"])
        if size_kb_min is not None:
            argv.extend(["-size", f"+{int(size_kb_min)}k"])
        if size_kb_max is not None:
            argv.extend(["-size", f"-{int(size_kb_max)}k"])

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=_DEFAULT_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": "find timed out", "command": argv}

        all_paths = proc.stdout.decode("utf-8", errors="replace").splitlines()
        truncated = len(all_paths) > max_results
        paths = all_paths[:max_results]
        return {
            "paths": paths,
            "count": len(paths),
            "truncated": truncated,
            "total_seen": len(all_paths),
            "exit_code": proc.returncode,
            "stderr": proc.stderr.decode("utf-8", errors="replace")[-2000:] if proc.stderr else "",
            "command": argv,
        }


__all__ = ["register_search_tools"]
