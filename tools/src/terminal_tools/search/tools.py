"""``terminal_rg`` and ``terminal_glob`` — structured wrappers over ripgrep.

These are the canonical content/name search tools. They accept
arbitrary paths, resolve relative paths against the session workdir,
and surface the underlying tool's full feature set — use them for
in-project search as well as ``/var/log``, ``/etc``, archive contents, etc.

``terminal_glob`` lists files by name/glob. For mtime/size/type predicate
queries (find's specialty) the skill steers agents to ``terminal_exec("find ...")``.
"""

from __future__ import annotations

import fnmatch
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from terminal_tools.common.ring_buffer import RingBuffer
from terminal_tools.common.ripgrep import installation_hint, resolve_ripgrep as _resolve_rg
from terminal_tools.search.glob_match import path_matcher

if TYPE_CHECKING:
    from fastmcp import FastMCP


_DEFAULT_TIMEOUT_SEC = 30
_MAX_OUTPUT_BYTES = 256 * 1024

# Build/cache dirs that are almost never what the model wants to walk. Mirrors
# files-tools' _SEARCH_SKIP_DIRS so both finders prune the same noise. Only used
# by the os.walk fallback — ``rg --files`` prunes via .gitignore on its own.
_SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", ".tox", ".mypy_cache", ".ruff_cache"})

_GLOB_META_RE = re.compile(r"[*?\[{]")


def _expand_glob_pattern(pattern: str) -> str:
    """Normalize a user glob so bare stems and non-recursive globs Just Work.

    `find -name`/`fnmatch` require an exact basename glob, so a model that
    passes a bare filename stem gets a silent zero — the trap this tool was
    rebuilt to close. We widen pragmatically:

      - no glob metachar at all -> ``**/*pattern*`` (recursive substring)
      - has a metachar but no '/' -> ``**/pattern`` (recursive by default)
      - contains '/' -> verbatim (the caller is being explicit)
    """
    if "/" in pattern:
        return pattern
    if not _GLOB_META_RE.search(pattern):
        return f"**/*{pattern}*"
    return f"**/{pattern}"


def _terminate(proc: subprocess.Popen) -> None:
    """Best-effort kill of a still-running child (we stopped reading early)."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _stream_paths(argv: list[str], max_results: int, accept: Callable[[str], bool] | None = None) -> tuple[list[str], bool, bool, str]:
    """Run `argv`, reading stdout until `max_results` paths or the deadline.

    Streaming + early termination means the cap bounds real work (the child is
    killed once we have enough) and a slow tree still yields partial results
    instead of the old timeout-returns-nothing cliff.

    Returns (paths, truncated, timed_out, stderr_tail).
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + _DEFAULT_TIMEOUT_SEC
    chunks: queue.Queue[bytes] = queue.Queue(maxsize=8)
    stopped = threading.Event()
    errors = RingBuffer(2000)

    # Windows select() accepts sockets only. Reader threads also drain stderr
    # concurrently, so a noisy rg cannot block before producing any paths.
    def pump(stream, *, stderr=False):
        try:
            while stderr or not stopped.is_set():
                chunk = os.read(stream.fileno(), 65536)
                if stderr:
                    errors.write(chunk)
                else:
                    while not stopped.is_set():
                        try:
                            chunks.put(chunk, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                if not chunk:
                    break
        except (OSError, ValueError):
            stopped.set()

    readers = [
        threading.Thread(target=pump, args=(proc.stdout,), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr,), kwargs={"stderr": True}, daemon=True),
    ]
    for reader in readers:
        reader.start()
    paths: list[str] = []
    truncated = False
    timed_out = False
    pending = b""

    def record(raw: bytes) -> None:
        path = raw.rstrip(b"\r").decode("utf-8", "replace")
        if path and (accept is None or accept(path)):
            paths.append(path)

    try:
        while True:
            if len(paths) >= max_results:
                truncated = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                chunk = chunks.get(timeout=remaining)
            except queue.Empty:
                timed_out = True
                break
            if not chunk:
                if pending:
                    record(pending)
                break  # EOF
            pending += chunk
            parts = pending.split(b"\n")
            pending = parts.pop()  # trailing partial line
            for raw in parts:
                if raw:
                    record(raw)
                    if len(paths) >= max_results:
                        break
    finally:
        stopped.set()
        _terminate(proc)
        for reader in readers:
            reader.join(timeout=2)
        proc.stdout.close()
        proc.stderr.close()
        stderr_tail = errors.tail(2000).data.decode("utf-8", "replace")
    if len(paths) > max_results:
        truncated = True
        paths = paths[:max_results]
    return paths, truncated, timed_out, stderr_tail


def _walk_paths(pattern: str, path: str, max_results: int, include_ignored: bool) -> tuple[list[str], bool]:
    """os.walk fallback for hosts without ripgrep. Best-effort, no .gitignore."""
    matches = path_matcher(pattern)

    paths: list[str] = []
    for root_dir, dirs, fnames in os.walk(path):
        if not include_ignored:
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in fnames:
            if not include_ignored and fname.startswith("."):
                continue
            full = os.path.join(root_dir, fname)
            rel = os.path.relpath(full, path)
            if matches(rel.replace(os.sep, "/")):
                paths.append(full)
                if len(paths) > max_results:
                    return paths[:max_results], True
    return paths, False


# Minimal rg filetype -> extension map for the os.walk content fallback.
# Covers common shortcuts. Reject unknown types rather than searching all files.
_TYPE_FILTER_EXTS: dict[str, tuple[str, ...]] = {
    "py": (".py", ".pyi"),
    "js": (".js", ".jsx", ".mjs", ".cjs"),
    "ts": (".ts", ".tsx"),
    "rust": (".rs",),
    "go": (".go",),
    "java": (".java",),
    "c": (".c", ".h"),
    "cpp": (".cpp", ".cc", ".cxx", ".hpp", ".hh"),
    "md": (".md", ".markdown"),
    "json": (".json",),
    "yaml": (".yaml", ".yml"),
    "toml": (".toml",),
    "sh": (".sh", ".bash"),
    "html": (".html", ".htm"),
    "css": (".css",),
    "txt": (".txt",),
}


def _walk_grep(
    pattern: str,
    path: str,
    *,
    glob: str | None,
    type_filter: str | None,
    ignore_case: bool,
    max_count: int | None,
    max_depth: int | None,
    hidden: bool,
    no_ignore: bool,
    context: int = 0,
    extra_args: list[str] | None = None,
    allow_fallback: bool = False,
) -> dict:
    """Opt-in approximate search; never silently discard requested flags."""
    limitations = ["No .gitignore awareness", "Python regex syntax", "Basename globs and a limited filetype table"]
    unsupported = []
    if context:
        unsupported.append("context")
    if extra_args:
        unsupported.append("extra_args")
    if type_filter and type_filter not in _TYPE_FILTER_EXTS:
        unsupported.append("type_filter")
    if glob and (any(c in glob for c in "/\\{}") or glob.startswith("!")):
        unsupported.append("glob")
    if not allow_fallback or unsupported:
        return {
            "error": (
                "ripgrep is unavailable; requested parameters require ripgrep: " + ", ".join(unsupported)
                if unsupported
                else "ripgrep is unavailable; approximate Python search requires allow_fallback=True."
            ),
            "code": "ripgrep_required",
            "unsupported_parameters": unsupported,
            "fallback_limitations": limitations,
            "hint": installation_hint(),
        }
    try:
        compiled = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return {"error": f"invalid regex: {e}", "fallback": "python-walk"}

    exts = _TYPE_FILTER_EXTS.get(type_filter) if type_filter else None

    def _included(fname: str) -> bool:
        if not hidden and fname.startswith("."):
            return False
        if glob and not fnmatch.fnmatch(fname, glob):
            return False
        if exts and not fname.endswith(exts):
            return False
        return True

    matches: list[dict] = []
    truncated = False
    bytes_seen = 0

    def _scan(fpath: str) -> bool:
        """Search one file, appending matches. Return False once the output
        byte cap is hit so the whole walk stops."""
        nonlocal truncated, bytes_seen
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as fh:
                file_lines = fh.readlines()
        except OSError:
            return True
        hits = 0
        for idx, raw in enumerate(file_lines):
            if not compiled.search(raw):
                continue
            text = raw.rstrip("\n")
            bytes_seen += len(text)
            if bytes_seen > _MAX_OUTPUT_BYTES:
                truncated = True
                return False
            matches.append({"path": fpath, "line": idx + 1, "text": text})
            hits += 1
            if max_count is not None and hits >= max_count:
                break
        return True

    if os.path.isfile(path):
        _scan(path)
    elif os.path.isdir(path):
        base_depth = path.rstrip(os.sep).count(os.sep)
        for root_dir, dirs, fnames in os.walk(path):
            # Prune build/cache dirs (unless no_ignore) and hidden dirs
            # (unless hidden) — approximates what .gitignore would skip.
            dirs[:] = [d for d in dirs if (hidden or not d.startswith(".")) and (no_ignore or d not in _SKIP_DIRS)]
            if max_depth is not None:
                depth = root_dir.rstrip(os.sep).count(os.sep) - base_depth
                if depth >= max_depth - 1:
                    dirs[:] = []  # at the depth limit — don't descend further
            stop = False
            for fname in fnames:
                if _included(fname) and not _scan(os.path.join(root_dir, fname)):
                    stop = True
                    break
            if stop:
                break

    return {
        "matches": matches,
        "context": [],
        "total": len(matches),
        "truncated": truncated,
        "exit_code": 0,
        "stderr": "",
        "fallback": "python-walk",
        "fallback_limitations": limitations,
        "note": "ripgrep unavailable; explicitly requested approximate Python search without .gitignore support.",
    }


def register_search_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def terminal_rg(
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
        session_cwd: str | None = None,
        allow_fallback: bool = False,
    ) -> dict:
        """Run ripgrep on `path` for `pattern` — the content-search tool.

        Use this for all content (regex) search, whether project code or raw
        paths (system configs, /var/log, archive contents); it exposes the full
        rg flag surface. Relative paths resolve against the session workdir.

        Args:
            pattern: Regex pattern.
            path: Directory or file to search. Relative paths resolve against
                the session workdir; default is the session workdir itself.
            glob: Filename glob (e.g. "*.py").
            type_filter: rg filetype shortcut (e.g. "py", "rust", "md").
            ignore_case: Case-insensitive search.
            context: Lines of context above and below each match.
            max_count: Stop after N matches per file.
            max_depth: Limit directory recursion depth.
            hidden: Include hidden files (rg ignores them by default).
            no_ignore: Don't respect .gitignore.
            extra_args: Raw flags to append (use sparingly — most needs are covered above).
            allow_fallback: If rg is missing, explicitly accept approximate Python
                search without .gitignore support and with Python regex syntax.
                Context, extra_args, unknown filetypes and complex globs still
                require rg; unsupported parameters return an error without searching.

        Returns: {matches: [...], context: [...], total, truncated, exit_code, stderr}.
            Context entries have the same path/line/text shape as matches;
            total counts only matches. Missing rg returns ripgrep_required by default.
        """
        # Loose default: resolve a relative path (incl. the "." default) against
        # the framework-injected session workdir.
        if session_cwd and not os.path.isabs(path):
            path = os.path.join(session_cwd, path)
        rg_bin = _resolve_rg()
        if not rg_bin:
            return _walk_grep(
                pattern,
                path,
                glob=glob,
                type_filter=type_filter,
                ignore_case=ignore_case,
                max_count=max_count,
                max_depth=max_depth,
                hidden=hidden,
                no_ignore=no_ignore,
                context=context,
                extra_args=extra_args,
                allow_fallback=allow_fallback,
            )

        argv = [rg_bin, "--json", "--no-heading"]
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
            # Apply the same fallback policy if rg disappears after discovery.
            return _walk_grep(
                pattern,
                path,
                glob=glob,
                type_filter=type_filter,
                ignore_case=ignore_case,
                max_count=max_count,
                max_depth=max_depth,
                hidden=hidden,
                no_ignore=no_ignore,
                context=context,
                extra_args=extra_args,
                allow_fallback=allow_fallback,
            )

        # Keep requested context separate so it does not inflate the match count.
        import json

        matches: list[dict] = []
        context_lines: list[dict] = []
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
            event_type = evt.get("type")
            if event_type not in {"match", "context"}:
                continue
            data = evt.get("data", {})
            path_data = (data.get("path") or {}).get("text") or ""
            line_no = data.get("line_number")
            text = (data.get("lines") or {}).get("text") or ""
            target = matches if event_type == "match" else context_lines
            target.append({"path": path_data, "line": line_no, "text": text.rstrip("\r\n")})

        return {
            "matches": matches,
            "context": context_lines,
            "total": len(matches),
            "truncated": truncated,
            "exit_code": proc.returncode,
            "stderr": proc.stderr.decode("utf-8", errors="replace")[-2000:] if proc.stderr else "",
        }

    @mcp.tool()
    def terminal_glob(
        pattern: str,
        path: str = ".",
        max_results: int = 1000,
        include_ignored: bool = False,
        session_cwd: str | None = None,
    ) -> dict:
        """Find files by name/glob under `path` — the Glob tool.

        Use this to locate files by name, in the project tree or raw/arbitrary
        paths (/var/log, /etc, archive contents). Relative paths resolve against
        the session workdir. For mtime/size/type predicate queries, drop to
        terminal_exec("find ...") — see references/find_predicates.md.

        Pattern handling (so bare stems Just Work):
            "lk_scan_post_reactors" -> matched as **/*lk_scan_post_reactors*
            "*.py"                  -> matched as **/*.py (recursive)
            "src/**/*.py"           -> used verbatim
        The glob actually run is returned as `expanded_pattern`.

        Args:
            pattern: Filename glob or bare substring.
            path: Directory to search under. Relative paths resolve against the
                session workdir; default is the session workdir itself.
            max_results: Cap on returned paths (search stops early at the cap).
            include_ignored: Include .gitignored / hidden / build-cache files.

        Returns: {paths, count, truncated, timed_out, expanded_pattern, command}
            Without rg, returns fallback="python-walk" and a note: the
            approximate filename walk does not honor .gitignore.
        """
        # Loose default: resolve a relative path (incl. the "." default) against
        # the framework-injected session workdir.
        if session_cwd and not os.path.isabs(path):
            path = os.path.join(session_cwd, path)
        expanded = _expand_glob_pattern(pattern)
        try:
            matches = path_matcher(expanded)
        except ValueError as exc:
            return {"error": str(exc), "expanded_pattern": expanded}

        rg_bin = _resolve_rg()
        if not rg_bin:
            # No ripgrep — best-effort os.walk (no .gitignore awareness).
            paths, truncated = _walk_paths(expanded, path, max_results, include_ignored)
            return {
                "paths": paths,
                "count": len(paths),
                "truncated": truncated,
                "timed_out": False,
                "expanded_pattern": expanded,
                "command": ["os.walk", path, expanded],
                "fallback": "python-walk",
                "note": "ripgrep unavailable; approximate filename walk does not honor .gitignore.",
            }

        argv = [rg_bin, "--files", "--no-messages"]
        if include_ignored:
            argv.extend(["-uu", "--hidden"])
        # Positive rg --glob rules override .gitignore. Filter the eligible
        # file stream instead, before applying the result cap.
        argv.extend(["--", path])
        base = path if os.path.isdir(path) else os.path.dirname(path) or "."

        def accept(candidate: str) -> bool:
            return matches(os.path.relpath(candidate, base).replace(os.sep, "/"))

        try:
            paths, truncated, timed_out, stderr_tail = _stream_paths(argv, max_results, accept=accept)
        except FileNotFoundError:
            return {"error": "ripgrep (rg) is not installed on this host"}

        return {
            "paths": paths,
            "count": len(paths),
            "truncated": truncated,
            "timed_out": timed_out,
            "expanded_pattern": expanded,
            "stderr": stderr_tail,
            "command": argv,
        }


__all__ = ["register_search_tools"]
