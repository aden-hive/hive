"""
Shared file operation tools for MCP servers.

Provides 4 tools (read_file, write_file, search_files, edit_file)
plus supporting helpers. ``search_files`` is unified — it covers both
content grep (``target='content'``) and file listing
(``target='files'``), replacing the older ``list_directory`` tool and
the LLM's choice between grep/find/ls. ``edit_file`` is unified — it
covers single-file fuzzy find/replace (``mode='replace'``) and
multi-file structured edits with two-phase apply (``mode='patch'``).

Used by files_server.py (the MCP entry point that exposes these tools
to the queen and any other agent loading the files-tools server).

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
import threading as _threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from aden_tools.file_state_cache import Freshness, check_fresh, record_read
from aden_tools.hashline import compute_line_hash

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

# ── search_files anti-loop tracker ────────────────────────────────────────
#
# Process-level memory of the most recent search_files call per task. When
# the same query (target+pattern+path+glob+pagination+output) is repeated
# back-to-back, we warn the model on the 3rd hit and block on the 4th.
# Catches LLM loops where the same search is fired without acting on the
# previous result.

_SEARCH_TRACKER_LOCK = _threading.Lock()
_SEARCH_TRACKER: dict[str, dict] = {}

# Skip set shared by both search targets — common build/cache dirs that are
# almost never what the model wants to walk.
_SEARCH_SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", ".tox", ".mypy_cache", ".ruff_cache"})


def _relativize(path: str, root: str | None) -> str:
    """Best-effort relative path; falls back to the original on cross-volume."""
    if not root:
        return path
    try:
        norm_path = os.path.normpath(path.replace("/", os.sep))
        norm_root = os.path.normpath(root.replace("/", os.sep))
        return os.path.relpath(norm_path, norm_root)
    except ValueError:
        return path


def _do_search_files_target(
    pattern: str,
    resolved: str,
    display_root: str,
    limit: int,
    offset: int,
) -> str:
    """target='files': enumerate files matching a glob, mtime-sorted (newest first)."""
    if not os.path.isdir(resolved):
        return f"Error: Directory not found: {resolved}"

    glob = pattern or "*"
    files: list[tuple[float, str]] = []

    # Try ripgrep --files first; it respects .gitignore which is what we want.
    try:
        cmd = [
            "rg",
            "--files",
            "--no-messages",
            "--hidden",
            "--glob=!.git/*",
        ]
        if glob and glob != "*":
            cmd.extend(["--glob", glob])
        cmd.append(resolved)
        rg = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
        )
        if rg.returncode <= 1:
            for raw in rg.stdout.splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    files.append((os.path.getmtime(raw), raw))
                except OSError:
                    continue
        else:
            files = []
    except FileNotFoundError:
        # ripgrep absent — fall through to os.walk
        files = []
    except subprocess.TimeoutExpired:
        return "Error: file listing timed out after 30 seconds"

    # Python fallback (also runs when rg returned nothing on platforms where
    # rg.returncode reports >1 for "no files in glob").
    if not files:
        for root, dirs, fnames in os.walk(resolved):
            dirs[:] = [d for d in dirs if d not in _SEARCH_SKIP_DIRS and not d.startswith(".")]
            for fname in fnames:
                if fname.startswith("."):
                    continue
                if glob and glob != "*" and not fnmatch.fnmatch(fname, glob):
                    continue
                full = os.path.join(root, fname)
                try:
                    files.append((os.path.getmtime(full), full))
                except OSError:
                    continue

    files.sort(reverse=True)
    total = len(files)
    page = files[offset : offset + max(0, int(limit))]
    if not page:
        return "No files found." if total == 0 else f"No files at offset {offset} (total: {total})."

    lines = [_relativize(p, display_root) for _, p in page]
    out = "\n".join(lines)
    next_offset = offset + len(page)
    if total > next_offset:
        out += (
            f"\n\n[Hint: showing {len(page)} of {total} files. "
            f"Use offset={next_offset} for more, or narrow with a more specific glob.]"
        )
    return out


def _do_search_content_target(
    pattern: str,
    resolved: str,
    project_root: str | None,
    file_glob: str,
    limit: int,
    offset: int,
    output_mode: str,
    context: int,
    hashline: bool,
) -> str:
    """target='content': regex search across file contents (ripgrep + Python fallback)."""
    display_root = project_root or (resolved if os.path.isdir(resolved) else os.path.dirname(resolved))
    cap = max(1, int(limit))

    # Try ripgrep first.
    try:
        cmd = ["rg", "-nH", "--no-messages", "--hidden", "--glob=!.git/*"]
        if context and output_mode == "content":
            cmd.extend(["-C", str(int(context))])
        if file_glob:
            cmd.extend(["--glob", file_glob])
        if output_mode == "files_only":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        cmd.append(pattern)
        cmd.append(resolved)

        rg = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
        )
        if rg.returncode <= 1:
            raw_lines = [ln for ln in rg.stdout.splitlines() if ln]
            total = len(raw_lines)
            page = raw_lines[offset : offset + cap]
            if not page:
                return "No matches found." if total == 0 else f"No matches at offset {offset} (total: {total})."

            formatted: list[str] = []
            for line in page:
                # Relativize path prefix on every line.
                m = re.match(r"^(.+?):(\d+):(.*)$", line) if output_mode == "content" else None
                if m:
                    fpath, lineno, rest = m.group(1), m.group(2), m.group(3)
                    rel = _relativize(fpath, display_root)
                    if hashline:
                        h = compute_line_hash(rest)
                        line = f"{rel}:{lineno}:{h}|{rest}"
                    else:
                        line = f"{rel}:{lineno}:{rest}"
                else:
                    # files_only/count: single path (or path:count) per line
                    head, sep, tail = line.partition(":")
                    if sep and tail.isdigit():
                        line = f"{_relativize(head, display_root)}:{tail}"
                    else:
                        line = _relativize(line, display_root)
                if len(line) > MAX_LINE_LENGTH:
                    line = line[:MAX_LINE_LENGTH] + "..."
                formatted.append(line)

            out = "\n".join(formatted)
            next_offset = offset + len(page)
            if total > next_offset:
                out += (
                    f"\n\n[Hint: showing {len(page)} of {total} matches. "
                    f"Use offset={next_offset} for more, or narrow with file_glob/pattern.]"
                )
            return out
    except FileNotFoundError:
        pass  # ripgrep missing — Python fallback below
    except subprocess.TimeoutExpired:
        return "Error: search timed out after 30 seconds"

    # Python fallback (no ripgrep): regex over file contents.
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    if os.path.isfile(resolved):
        candidates = [resolved]
    else:
        candidates = []
        for root, dirs, fnames in os.walk(resolved):
            dirs[:] = [d for d in dirs if d not in _SEARCH_SKIP_DIRS and not d.startswith(".")]
            for fname in fnames:
                if file_glob and not fnmatch.fnmatch(fname, file_glob):
                    continue
                candidates.append(os.path.join(root, fname))

    # files_only / count modes need per-file aggregation.
    if output_mode in ("files_only", "count"):
        items: list[tuple[str, int]] = []
        for fpath in candidates:
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    n = sum(1 for line in f if compiled.search(line.rstrip()))
            except OSError:
                continue
            if n:
                items.append((fpath, n))
        total = len(items)
        page = items[offset : offset + cap]
        if not page:
            return "No matches found." if total == 0 else f"No matches at offset {offset} (total: {total})."
        if output_mode == "files_only":
            lines = [_relativize(p, display_root) for p, _ in page]
        else:
            lines = [f"{_relativize(p, display_root)}:{n}" for p, n in page]
        out = "\n".join(lines)
        next_offset = offset + len(page)
        if total > next_offset:
            out += f"\n\n[Hint: showing {len(page)} of {total}. Use offset={next_offset} for more.]"
        return out

    # output_mode == "content"
    matches: list[str] = []
    for fpath in candidates:
        rel = _relativize(fpath, display_root)
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                buf = f.readlines()
        except OSError:
            continue
        for i, raw in enumerate(buf, 1):
            stripped = raw.rstrip()
            if not compiled.search(stripped):
                continue
            if context > 0:
                lo = max(0, i - 1 - context)
                hi = min(len(buf), i + context)
                ctx = []
                for j in range(lo, hi):
                    marker = ":" if (j + 1) == i else "-"
                    ln = buf[j].rstrip()
                    ctx.append(f"{rel}:{j + 1}{marker}{ln[:MAX_LINE_LENGTH]}")
                matches.append("\n".join(ctx))
            elif hashline:
                h = compute_line_hash(stripped)
                matches.append(f"{rel}:{i}:{h}|{stripped}")
            else:
                matches.append(f"{rel}:{i}:{stripped[:MAX_LINE_LENGTH]}")

    total = len(matches)
    page = matches[offset : offset + cap]
    if not page:
        return "No matches found." if total == 0 else f"No matches at offset {offset} (total: {total})."
    out = "\n\n".join(page) if context > 0 else "\n".join(page)
    next_offset = offset + len(page)
    if total > next_offset:
        out += (
            f"\n\n[Hint: showing {len(page)} of {total} matches. "
            f"Use offset={next_offset} for more, or narrow with file_glob/pattern.]"
        )
    return out


# ── Path policy ──────────────────────────────────────────────────────────
#
# One model for every file tool:
#
#   - Relative path  → resolved under the agent's home directory.
#   - Absolute path  → used as-is, no silent rebasing.
#   - Tilde (~)      → expanded to the OS user home.
#
# Two deny lists. Reads ⊂ writes:
#
#   - Reads are blocked only for credential FILES (SSH keys, AWS creds,
#     /etc/shadow, etc.). System config like /etc/nginx/nginx.conf is
#     readable on purpose — agents need to inspect configs.
#   - Writes are blocked for system directories AND credential paths.
#
# An optional ``write_safe_root`` is a hard ceiling on writes for hosted
# deployments. Reads are not affected by it.

_HOME = os.path.expanduser("~")


def _norm(p: str) -> str:
    """Resolve ``~`` and symlinks; return canonical absolute path."""
    return os.path.realpath(os.path.expanduser(p))


# Anything under one of these prefixes is denied for writes.
#
# Notes on what's intentionally NOT here:
#   - /var, /private/var: macOS user tmpdirs live under /private/var/folders/,
#     so denying that prefix breaks every test using tmp_path. Sensitive
#     items under /var (sudoers.d, etc.) are listed individually below.
#   - /var/run: docker.sock is in the exact-files list, which is enough.
_WRITE_DENY_PREFIXES: tuple[str, ...] = tuple(
    _norm(p)
    for p in (
        "/etc",
        "/boot",
        "/usr/lib/systemd",
        "/private/etc",
        "/etc/sudoers.d",
        "/etc/systemd",
        "~/.ssh",
        "~/.aws",
        "~/.gnupg",
        "~/.kube",
        "~/.docker",
        "~/.azure",
        "~/.config/gh",
    )
)

# Exact files denied for writes (in addition to the prefix list).
_WRITE_DENY_FILES: frozenset[str] = frozenset(
    _norm(p)
    for p in (
        "/etc/sudoers",
        "/etc/passwd",
        "/etc/shadow",
        "/var/run/docker.sock",
        "/run/docker.sock",
        "~/.netrc",
        "~/.pypirc",
    )
)

# Reads are denied only for credential FILES — system dirs stay readable.
_READ_DENY_PREFIXES: tuple[str, ...] = tuple(
    _norm(p)
    for p in (
        "~/.ssh",
        "~/.aws",
        "~/.gnupg",
    )
)
_READ_DENY_FILES: frozenset[str] = frozenset(
    _norm(p)
    for p in (
        "/etc/shadow",
        "/etc/sudoers",
        "~/.netrc",
        "~/.pypirc",
    )
)


def _path_is_under(path: str, root: str) -> bool:
    """True iff ``path`` equals or sits under ``root`` (both absolute)."""
    if not root:
        return False
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False  # different drives on Windows


class _FilePolicy:
    """Path resolver and deny-list checker bound to an agent's home dir.

    One instance per ``register_file_tools`` call. All file tools route
    their path arg through ``read_path`` or ``write_path`` so the same
    rules apply across read_file/write_file/edit_file/search_files/etc.
    """

    def __init__(
        self,
        home: str | None = None,
        write_safe_root: str | list[str] | None = None,
    ) -> None:
        # ``home`` is the anchor for relative paths. Default to CWD so the
        # unsandboxed local server keeps working without explicit config.
        self.home = _norm(home) if home else os.path.abspath(os.getcwd())
        # ``write_safe_root`` is normalized to a list. None means "no ceiling
        # — only the deny list applies". A non-empty list means writes must
        # land under at least one of the listed roots.
        if write_safe_root is None:
            self.write_safe_roots: list[str] = []
        elif isinstance(write_safe_root, str):
            self.write_safe_roots = [_norm(write_safe_root)]
        else:
            self.write_safe_roots = [_norm(r) for r in write_safe_root if r]

    # ── public ─────────────────────────────────────────────────────────

    def read_path(self, path: str) -> str:
        """Resolve a read path; raise ValueError if denied."""
        resolved = self._resolve(path)
        self._check_read(resolved, path)
        return resolved

    def write_path(self, path: str) -> str:
        """Resolve a write path; raise ValueError if denied."""
        resolved = self._resolve(path)
        self._check_write(resolved, path)
        return resolved

    # ── internals ──────────────────────────────────────────────────────

    def _resolve(self, path: str) -> str:
        if not path:
            raise ValueError("path cannot be empty")
        # Normalize slashes for cross-platform robustness.
        p = path.replace("/", os.sep) if os.sep != "/" else path
        if p.startswith("~"):
            p = os.path.expanduser(p)
        if os.path.isabs(p):
            return os.path.realpath(p)
        return os.path.realpath(os.path.join(self.home, p))

    def _check_read(self, resolved: str, original: str) -> None:
        if resolved in _READ_DENY_FILES:
            raise ValueError(f"read denied: '{original}' is on the credential deny list")
        for prefix in _READ_DENY_PREFIXES:
            if _path_is_under(resolved, prefix):
                raise ValueError(f"read denied: '{original}' is under {prefix} (credential directory)")

    def _check_write(self, resolved: str, original: str) -> None:
        if resolved in _WRITE_DENY_FILES:
            raise ValueError(f"write denied: '{original}' is on the system/credential deny list")
        for prefix in _WRITE_DENY_PREFIXES:
            if _path_is_under(resolved, prefix):
                raise ValueError(f"write denied: '{original}' is under {prefix} (system or credential directory)")
        if self.write_safe_roots and not any(_path_is_under(resolved, r) for r in self.write_safe_roots):
            roots = ", ".join(self.write_safe_roots)
            raise ValueError(f"write denied: '{original}' is outside the configured write_safe_root(s) ({roots})")


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


# Unicode normalization map for fuzzy matching. LLMs frequently emit
# typographic variants (smart quotes, em-dashes, ellipsis, NBSP) when
# the source file uses ASCII — or vice versa.
_UNICODE_NORMALIZATIONS = (
    ("‘", "'"),  # left single quote
    ("’", "'"),  # right single quote
    ("“", '"'),  # left double quote
    ("”", '"'),  # right double quote
    ("—", "--"),  # em-dash
    ("–", "-"),  # en-dash
    ("…", "..."),  # ellipsis
    (" ", " "),  # NBSP
)


def _unicode_normalize(s: str) -> str:
    for src, dst in _UNICODE_NORMALIZATIONS:
        s = s.replace(src, dst)
    return s


def _fuzzy_find_candidates(content: str, old_text: str):
    """Yield candidate substrings from content that match old_text.

    Strategies are ordered as a safety gradient: strict and zero-false-
    positive first, similarity-based last. Callers stop at the first
    yielded candidate that they can act on, so an exact match never
    falls through to a heuristic match.

    Order: exact → line-trimmed → whitespace-normalized →
    indentation-flexible → escape-normalized → trimmed-boundary →
    unicode-normalized → block-anchor → context-aware.
    """
    # 1. Exact match
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

    # 2. Line-trimmed match
    for i in range(len(content_lines) - n_search + 1):
        window = content_lines[i : i + n_search]
        if all(cl.strip() == sl.strip() for cl, sl in zip(window, search_lines, strict=True)):
            yield "\n".join(window)

    # 3. Whitespace-normalized match (collapse runs of whitespace)
    normalized_search = re.sub(r"\s+", " ", old_text).strip()
    for i in range(len(content_lines) - n_search + 1):
        window = content_lines[i : i + n_search]
        normalized_block = re.sub(r"\s+", " ", "\n".join(window)).strip()
        if normalized_block == normalized_search:
            yield "\n".join(window)

    # 4. Indentation-flexible match (strip common leading indent)
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

    # 5. Escape-normalized match — agents sometimes paste literal "\n",
    # "\t", "\r" sequences instead of actual control chars.
    if "\\n" in old_text or "\\t" in old_text or "\\r" in old_text:
        unescaped = old_text.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
        if unescaped != old_text and unescaped in content:
            yield unescaped

    # 6. Trimmed-boundary match (only outer whitespace differs)
    trimmed = old_text.strip()
    if trimmed != old_text and trimmed in content:
        yield trimmed

    # 7. Unicode-normalized match (smart quotes, em/en-dashes, ellipsis,
    # NBSP). Walk the original content recovering the substring whose
    # normalization equals the normalized search term — replacement
    # happens in original space so length deltas don't corrupt the file.
    norm_search = _unicode_normalize(old_text)
    if norm_search != old_text:
        norm_content = _unicode_normalize(content)
        if norm_search in norm_content:
            # Build a per-original-char index → normalized-position map.
            pos_map = []
            np = 0
            for ch in content:
                pos_map.append(np)
                np += len(_unicode_normalize(ch))
            pos_map.append(np)
            target = norm_content.find(norm_search)
            if target >= 0:
                target_end = target + len(norm_search)
                # Locate boundaries in original space.
                try:
                    orig_start = pos_map.index(target)
                    orig_end = pos_map.index(target_end, orig_start)
                    yield content[orig_start:orig_end]
                except ValueError:
                    pass

    # 8. Block-anchor match — first and last lines match exactly (after
    # trim), middle is allowed to drift if similarity is high enough.
    # Thresholds (0.50 / 0.70) are deliberately tight; older 0.10/0.30
    # values silently matched unrelated blocks.
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
            threshold = 0.50 if len(candidates) == 1 else 0.70
            if candidates[0][0] >= threshold:
                yield candidates[0][1]

    # 9. Context-aware match — last resort. Per-line similarity with
    # 50% threshold per line for heavily mangled but recognizable blocks.
    if n_search >= 2:
        for i in range(len(content_lines) - n_search + 1):
            window = content_lines[i : i + n_search]
            sims = [_similarity(cl.strip(), sl.strip()) for cl, sl in zip(window, search_lines, strict=True)]
            if sims and min(sims) >= 0.50 and (sum(sims) / len(sims)) >= 0.65:
                yield "\n".join(window)
                break


def _compute_diff(old: str, new: str, path: str) -> str:
    """Compute a unified diff for display."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=path, tofile=path, n=3)
    result = "".join(diff)
    if len(result) > 2000:
        result = result[:2000] + "\n... (diff truncated)"
    return result


# ── Multi-file structured patch (V4A) ─────────────────────────────────────
#
# A small, lenient parser for the structured patch format. The grammar:
#
#     *** Begin Patch          (optional)
#     *** Update File: path
#     @@ optional context @@   (optional, per hunk)
#      context line             ← space prefix
#     -removed line
#     +added line
#     *** Add File: path
#     +line
#     +line
#     *** Delete File: path
#     *** Move File: src -> dst
#     *** End Patch            (optional)
#
# Two-phase apply: every operation is simulated against an in-memory
# copy of the touched files first; only when every op validates do we
# actually write to disk. This gives multi-file edits all-or-nothing
# semantics without needing a copy-aside / journal.

_BEGIN_RE = re.compile(r"^\*\*\*\s*Begin\s+Patch\s*$")
_END_RE = re.compile(r"^\*\*\*\s*End\s+Patch\s*$")
_OP_RE = re.compile(r"^\*\*\*\s+(Update|Add|Delete|Move)\s+File:\s*(.+)$")
_HUNK_HINT_RE = re.compile(r"^@@\s*(.*?)\s*@@\s*$")


@dataclass
class _Hunk:
    context_hint: str | None
    lines: list[tuple[str, str]]  # (prefix, content), prefix in {' ', '-', '+'}


@dataclass
class _PatchOp:
    kind: str  # "add" | "update" | "delete" | "move"
    path: str
    dest: str | None = None  # only for "move"
    hunks: list[_Hunk] = field(default_factory=list)  # only for "update"
    add_content: str = ""  # only for "add"


def _is_op_marker(line: str) -> bool:
    return bool(_OP_RE.match(line))


def _parse_v4a(text: str) -> tuple[list[_PatchOp], str | None]:
    """Parse V4A patch text into a list of operations.

    Returns ``(operations, error)``. On failure ``operations`` is empty
    and ``error`` describes why parsing stopped. Lenient about markers:
    ``Begin``/``End`` are optional, lines starting with ``\\`` (e.g. the
    ``\\ No newline at end of file`` git artifact) are skipped, and a
    line inside a hunk that lacks a ``+``/``-``/space prefix is treated
    as an implicit context line (a common LLM mistake).
    """
    lines = text.splitlines()
    i = 0
    # Skip until Begin marker or first op marker.
    while i < len(lines):
        if _BEGIN_RE.match(lines[i].strip()):
            i += 1
            break
        if _is_op_marker(lines[i]):
            break
        i += 1

    ops: list[_PatchOp] = []
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if _END_RE.match(stripped):
            break
        m = _OP_RE.match(raw)
        if not m:
            i += 1
            continue
        kind_word, rest = m.group(1), m.group(2).strip()
        i += 1
        if kind_word == "Update":
            hunks: list[_Hunk] = []
            while i < len(lines):
                if _is_op_marker(lines[i]) or _END_RE.match(lines[i].strip()):
                    break
                hunk, i = _parse_hunk(lines, i)
                if hunk is None:
                    break
                hunks.append(hunk)
            if not hunks:
                return [], f"Update {rest}: no hunks parsed"
            ops.append(_PatchOp(kind="update", path=rest, hunks=hunks))
        elif kind_word == "Add":
            content_lines: list[str] = []
            while i < len(lines):
                if _is_op_marker(lines[i]) or _END_RE.match(lines[i].strip()):
                    break
                if lines[i].startswith("+"):
                    content_lines.append(lines[i][1:])
                i += 1
            ops.append(_PatchOp(kind="add", path=rest, add_content="\n".join(content_lines)))
        elif kind_word == "Delete":
            ops.append(_PatchOp(kind="delete", path=rest))
        elif kind_word == "Move":
            mv = re.match(r"^(.+?)\s*->\s*(.+)$", rest)
            if not mv:
                return [], f"Move requires 'src -> dst', got: {rest}"
            ops.append(_PatchOp(kind="move", path=mv.group(1).strip(), dest=mv.group(2).strip()))

    if not ops:
        return [], "patch text contained no operations"

    errors: list[str] = []
    for op in ops:
        if not op.path:
            errors.append(f"{op.kind}: empty path")
        if op.kind == "move" and not op.dest:
            errors.append(f"move {op.path}: missing destination")
    if errors:
        return [], "; ".join(errors)
    return ops, None


def _parse_hunk(lines: list[str], start_idx: int) -> tuple[_Hunk | None, int]:
    """Parse one hunk. Returns ``(hunk_or_none, next_idx)``."""
    i = start_idx
    if i >= len(lines):
        return None, i
    context_hint: str | None = None
    m = _HUNK_HINT_RE.match(lines[i])
    if m:
        context_hint = m.group(1).strip() or None
        i += 1
    hunk_lines: list[tuple[str, str]] = []
    started = False
    while i < len(lines):
        line = lines[i]
        if _is_op_marker(line) or _END_RE.match(line.strip()) or _HUNK_HINT_RE.match(line):
            break
        if line.startswith("\\"):
            # Git-diff artifact like "\ No newline at end of file" — skip
            i += 1
            continue
        if line.startswith((" ", "-", "+")):
            hunk_lines.append((line[0], line[1:]))
            started = True
            i += 1
            continue
        if started:
            # Implicit context line — common LLM mistake of forgetting
            # the leading space. Treat it as context, not hunk-end.
            hunk_lines.append((" ", line))
            i += 1
            continue
        # Blank prelude before hunk content — stop trying.
        break
    if not hunk_lines:
        return None, i
    return _Hunk(context_hint=context_hint, lines=hunk_lines), i


def _apply_hunk(content: str, hunk: _Hunk) -> tuple[str, str | None]:
    """Apply one hunk to ``content``. Returns ``(new_content, error)``."""
    search_lines = [c for p, c in hunk.lines if p in (" ", "-")]
    replace_lines = [c for p, c in hunk.lines if p in (" ", "+")]

    # Pure addition (no - or context lines, only +). Insert at hint or
    # append to EOF if the hint is missing or unique.
    if not search_lines and replace_lines:
        addition = "\n".join(replace_lines)
        if hunk.context_hint:
            count = content.count(hunk.context_hint)
            if count > 1:
                return content, (
                    f"addition-only hunk: context hint '{hunk.context_hint}' is ambiguous ({count} occurrences)"
                )
            if count == 1:
                idx = content.find(hunk.context_hint)
                line_end = content.find("\n", idx)
                if line_end < 0:
                    new = content + "\n" + addition
                else:
                    new = content[: line_end + 1] + addition + "\n" + content[line_end + 1 :]
                return new, None
        # No hint, or hint not found: append to EOF.
        if content and not content.endswith("\n"):
            content += "\n"
        return content + addition + "\n", None

    search = "\n".join(search_lines)
    replace = "\n".join(replace_lines)
    if not search:
        return content, "hunk has neither context nor removed lines"

    # Try fuzzy match in the full content first.
    matched: str | None = None
    for candidate in _fuzzy_find_candidates(content, search):
        first = content.find(candidate)
        if first < 0:
            continue
        last = content.rfind(candidate)
        if first == last:
            matched = candidate
            break

    if matched is None and hunk.context_hint:
        # Asymmetric window around the hint. Hunks usually appear after
        # their identifying function/class signature, so we look further
        # forward than backward.
        hint_pos = content.find(hunk.context_hint)
        if hint_pos >= 0:
            wstart = max(0, hint_pos - 500)
            wend = min(len(content), hint_pos + 2000)
            window = content[wstart:wend]
            for candidate in _fuzzy_find_candidates(window, search):
                first = window.find(candidate)
                if first < 0:
                    continue
                last = window.rfind(candidate)
                if first == last:
                    new_window = window.replace(candidate, replace, 1)
                    return content[:wstart] + new_window + content[wend:], None

    if matched is None:
        return content, "could not find a unique match for hunk"

    return content.replace(matched, replace, 1), None


def _apply_v4a(
    ops: list[_PatchOp],
    policy,
    before_write: Callable[[], None] | None,
) -> tuple[str | None, str | None]:
    """Two-phase apply for a V4A operation list.

    Phase 1 simulates every op against an in-memory copy of the touched
    files. If anything fails, returns an error and writes nothing.
    Phase 2 commits the simulated state to disk; a failure there is
    annotated as potentially-partial and points the agent at git diff.
    """
    fs_state: dict[str, str] = {}
    fs_exists: dict[str, bool] = {}  # True = should exist post-apply, False = deleted
    original_existed: dict[str, bool] = {}

    def _ensure_loaded(resolved: str) -> str | None:
        if resolved in fs_state:
            return None
        if not os.path.isfile(resolved):
            return f"file not found: {resolved}"
        try:
            with open(resolved, encoding="utf-8") as f:
                fs_state[resolved] = f.read()
            fs_exists[resolved] = True
            original_existed[resolved] = True
        except Exception as e:
            return f"failed to read: {e}"
        return None

    errors: list[str] = []
    for op_idx, op in enumerate(ops):
        try:
            resolved = policy.write_path(op.path)
        except ValueError as e:
            errors.append(f"Op #{op_idx + 1} {op.kind} {op.path}: {e}")
            continue

        if op.kind == "add":
            if os.path.exists(resolved) and fs_exists.get(resolved, True):
                errors.append(f"Op #{op_idx + 1} add {op.path}: file already exists")
                continue
            content = op.add_content
            if content and not content.endswith("\n"):
                content += "\n"
            fs_state[resolved] = content
            fs_exists[resolved] = True
            original_existed.setdefault(resolved, os.path.exists(resolved))

        elif op.kind == "delete":
            err = _ensure_loaded(resolved)
            if err:
                errors.append(f"Op #{op_idx + 1} delete {op.path}: {err}")
                continue
            fs_exists[resolved] = False

        elif op.kind == "update":
            err = _ensure_loaded(resolved)
            if err:
                errors.append(f"Op #{op_idx + 1} update {op.path}: {err}")
                continue
            content = fs_state[resolved]
            for hunk_idx, hunk in enumerate(op.hunks):
                new_content, herr = _apply_hunk(content, hunk)
                if herr:
                    errors.append(f"Op #{op_idx + 1} update {op.path} hunk #{hunk_idx + 1}: {herr}")
                    break
                content = new_content
            fs_state[resolved] = content

        elif op.kind == "move":
            try:
                dst_resolved = policy.write_path(op.dest or "")
            except ValueError as e:
                errors.append(f"Op #{op_idx + 1} move {op.path}: {e}")
                continue
            err = _ensure_loaded(resolved)
            if err:
                errors.append(f"Op #{op_idx + 1} move {op.path}: {err}")
                continue
            if os.path.exists(dst_resolved) and fs_exists.get(dst_resolved, True):
                errors.append(f"Op #{op_idx + 1} move {op.path}: destination already exists")
                continue
            fs_state[dst_resolved] = fs_state[resolved]
            fs_exists[dst_resolved] = True
            fs_exists[resolved] = False
            original_existed.setdefault(dst_resolved, os.path.exists(dst_resolved))

    if errors:
        return None, "Patch validation failed (no files were modified):\n  " + "\n  ".join(errors)

    # Phase 2: commit
    files_modified: list[str] = []
    files_created: list[str] = []
    files_deleted: list[str] = []
    diffs: list[str] = []
    apply_errors: list[str] = []

    for resolved, will_exist in fs_exists.items():
        try:
            existed = original_existed.get(resolved, os.path.isfile(resolved))
            if will_exist:
                new_content = fs_state[resolved]
                old_content = ""
                if existed:
                    try:
                        with open(resolved, encoding="utf-8") as f:
                            old_content = f.read()
                    except Exception:
                        old_content = ""
                if before_write:
                    before_write()
                Path(resolved).parent.mkdir(parents=True, exist_ok=True)
                with open(resolved, "w", encoding="utf-8") as f:
                    f.write(new_content)
                try:
                    record_read(None, resolved, content_bytes=new_content.encode("utf-8"))
                except Exception:
                    pass
                if existed:
                    files_modified.append(resolved)
                    diff = _compute_diff(old_content, new_content, resolved)
                    if diff:
                        diffs.append(diff)
                else:
                    files_created.append(resolved)
            else:
                if before_write:
                    before_write()
                if os.path.isfile(resolved):
                    os.unlink(resolved)
                files_deleted.append(resolved)
        except Exception as e:
            apply_errors.append(f"{resolved}: {e}")

    if apply_errors:
        return None, (
            "Apply phase failed (state may be inconsistent — run `git diff` to assess):\n  " + "\n  ".join(apply_errors)
        )

    summary_parts: list[str] = []
    if files_modified:
        summary_parts.append(f"Modified {len(files_modified)} file(s): {', '.join(files_modified)}")
    if files_created:
        summary_parts.append(f"Created {len(files_created)} file(s): {', '.join(files_created)}")
    if files_deleted:
        summary_parts.append(f"Deleted {len(files_deleted)} file(s): {', '.join(files_deleted)}")
    summary = "\n".join(summary_parts) or "Patch applied (no files changed)"
    if diffs:
        summary += "\n\n" + "\n\n".join(diffs)
    return summary, None


# ── Patch tool implementations ────────────────────────────────────────────
#
# The two modes of the unified ``patch`` tool live as module-level
# functions so they're easy to test in isolation. Both honor the same
# ``policy`` (path resolution + deny lists) and ``before_write`` hook.


def _patch_replace(
    policy,
    before_write: Callable[[], None] | None,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> str:
    """Single-file fuzzy find-and-replace (the ``mode='replace'`` path)."""
    if not path:
        return "Error: replace mode requires a non-empty 'path'"
    if not old_string:
        return "Error: 'old_string' must not be empty"
    if old_string == new_string:
        return "Error: 'old_string' and 'new_string' are identical — nothing to do"
    try:
        resolved = policy.write_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not os.path.isfile(resolved):
        return f"Error: File not found: {path}"

    # Stale-edit guard: refuse unless a recent read is on record and the
    # file on disk still matches it. Prevents the model from overwriting
    # changes the user made between calling read_file and patch.
    _fresh = check_fresh(None, resolved)
    if _fresh.status is Freshness.UNREAD:
        return (
            f"Refusing to edit '{path}': call read_file('{path}') first so the "
            f"harness can track its state before you edit it."
        )
    if _fresh.status is Freshness.STALE:
        return f"Refusing to edit '{path}': {_fresh.detail}. Re-read the file with read_file before editing."

    try:
        with open(resolved, encoding="utf-8") as f:
            content = f.read()

        if before_write:
            before_write()

        strategies = [
            "exact",
            "line-trimmed",
            "whitespace-normalized",
            "indentation-flexible",
            "escape-normalized",
            "trimmed-boundary",
            "unicode-normalized",
            "block-anchor",
            "context-aware",
        ]
        matched: str | None = None
        strategy_used: str | None = None
        for i, candidate in enumerate(_fuzzy_find_candidates(content, old_string)):
            idx = content.find(candidate)
            if idx < 0:
                continue
            if replace_all:
                matched = candidate
                strategy_used = strategies[min(i, len(strategies) - 1)]
                break
            last_idx = content.rfind(candidate)
            if idx == last_idx:
                matched = candidate
                strategy_used = strategies[min(i, len(strategies) - 1)]
                break

        if matched is None:
            close = difflib.get_close_matches(old_string[:200], content.split("\n"), n=3, cutoff=0.4)
            msg = (
                f"Error: Could not find a unique match for old_string in {path}. "
                f"Use read_file to verify the current content, or search_files "
                f"to locate the text."
            )
            if close:
                suggestions = "\n".join(f"  {line}" for line in close)
                msg += f"\n\nDid you mean one of these lines?\n{suggestions}"
            return msg

        if replace_all:
            count = content.count(matched)
            new_content = content.replace(matched, new_string)
        else:
            count = 1
            new_content = content.replace(matched, new_string, 1)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        try:
            record_read(None, resolved, content_bytes=new_content.encode("utf-8"))
        except Exception:
            pass

        diff = _compute_diff(content, new_content, path)
        match_info = f" (matched via {strategy_used})" if strategy_used != "exact" else ""
        result = f"Replaced {count} occurrence(s) in {path}{match_info}"
        if diff:
            result += f"\n\n{diff}"
        return result
    except Exception as e:
        return f"Error editing file: {e}"


def _patch_apply(
    policy,
    before_write: Callable[[], None] | None,
    patch_text: str,
) -> str:
    """Multi-file structured patch (the ``mode='patch'`` path)."""
    if not patch_text:
        return "Error: patch mode requires a non-empty 'patch_text'"

    ops, parse_error = _parse_v4a(patch_text)
    if parse_error:
        return f"Error: {parse_error}"
    if not ops:
        return "Error: patch text contained no operations"

    summary, apply_error = _apply_v4a(ops, policy, before_write)
    if apply_error:
        return f"Error: {apply_error}"
    return summary or "Patch applied"


# ── Tool prompts ──────────────────────────────────────────────────────────
#
# Each tool's top-level description and per-parameter descriptions live in a
# co-located block here. The factory below references these constants from
# its tool registrations — descriptions never live inline in the function
# signatures. Module-level placement is required: ``from __future__ import
# annotations`` makes ``Annotated[..., Field(description=...)]`` resolve
# against module globals, not the factory's locals.

# ── read_file prompts ────────────────────────────────────────────

READ_FILE_DOC = (
    "Read file contents with line numbers. Use this instead of `cat`. "
    "Binary files are detected and rejected. Large files are auto-truncated "
    "at 2000 lines or 50KB — use offset/limit to paginate. Reading a "
    "directory returns its entries (use search_files for proper find/ls)."
)
READ_FILE_PARAMS = {
    "path": (
        "File path to read. Relative paths anchor to the agent's home; "
        "absolute paths used verbatim. Credential paths (~/.ssh, ~/.aws, "
        "etc.) are denied."
    ),
    "offset": "Starting line number, 1-indexed. Default 1.",
    "limit": "Max lines to return. 0 means up to 2000. Default 0.",
    "hashline": (
        "If True, return lines in N:hhhh|content format with content-hash "
        "anchors. Line truncation is disabled in this mode to preserve "
        "hash integrity. Default False."
    ),
}

# ── write_file prompts ───────────────────────────────────────────

WRITE_FILE_DOC = (
    "Create or overwrite a file with the given content. Parent directories "
    "are created automatically. Use this instead of `cat > file` or shell "
    "redirects. For targeted edits in an existing file, prefer edit_file "
    "(this tool overwrites the whole file). Existing files require a recent "
    "read_file call first; brand-new files don't."
)
WRITE_FILE_PARAMS = {
    "path": (
        "File path to write. Relative paths anchor to the agent's home; "
        "absolute paths used verbatim. System and credential paths are denied."
    ),
    "content": "Complete file content to write.",
}

# ── edit_file prompts ────────────────────────────────────────────

EDIT_FILE_DOC = (
    "Edit files: one string in one file (replace mode), or many edits "
    "across many files (patch mode). Use this instead of `sed`, `awk`, or "
    "shell redirects. Returns a unified diff. If old_string doesn't match "
    "in replace mode, re-read the file with read_file or use search_files "
    "to locate the exact text — don't retry blindly."
)
EDIT_FILE_PARAMS = {
    "mode": (
        "Edit mode. 'replace' (default) for single-file find-and-replace. "
        "'patch' for multi-file structured patches that can "
        "Update/Add/Delete/Move files atomically."
    ),
    "path": (
        "Replace mode only. File path to edit. Relative paths anchor to "
        "the agent's home; absolute paths used verbatim. Ignored in patch "
        "mode (paths live inside patch_text)."
    ),
    "old_string": (
        "Replace mode only. Text to find. Must be unique in the file "
        "unless replace_all=True; include surrounding context to "
        "disambiguate. Fuzzy matching tolerates whitespace/indent drift, "
        "tabs vs spaces, smart quotes vs ASCII, and literal \\n/\\t/\\r "
        "vs real control chars."
    ),
    "new_string": ("Replace mode only. Replacement text. Pass an empty string to delete the matched text."),
    "replace_all": ("Replace mode only. Replace every occurrence instead of requiring a unique match. Default False."),
    "patch_text": (
        "Patch mode only. Structured patch body. File paths are embedded "
        "inside the body via '*** Update File: <path>' / "
        "'*** Add File: <path>' / '*** Delete File: <path>' / "
        "'*** Move File: <src> -> <dst>' markers, so one call can touch "
        "many files. Hunks use unified-diff syntax: lines starting with "
        "' ' (space) are context, '-' lines are removed, '+' lines are "
        "added. Optional '@@ hint @@' before a hunk narrows fuzzy "
        "matching to a window around the hint. If any operation fails "
        "validation, no files are written. Example:\n"
        "*** Begin Patch\n"
        "*** Update File: a.py\n"
        "@@ def hello @@\n"
        " def hello():\n"
        "-    return 1\n"
        "+    return 42\n"
        "*** Add File: new.py\n"
        "+x = 1\n"
        "*** Delete File: old.py\n"
        "*** Move File: src.py -> dst.py\n"
        "*** End Patch"
    ),
}

# ── search_files prompts ─────────────────────────────────────────

SEARCH_FILES_DOC = (
    "Search file contents OR find files by name. Use this instead of "
    "grep, find, or ls. target='content' (default) regex-greps inside "
    "files; target='files' globs file names (mtime-sorted, newest first). "
    "Pagination via limit/offset; truncated responses include a hint with "
    "the next offset. Repeating the same exact query consecutively is "
    "warned at 3 calls and blocked at 4 — use the results you already have."
)
SEARCH_FILES_PARAMS = {
    "pattern": (
        "Regex (content mode) or glob (files mode, e.g. '*.py'). For an 'ls'-style listing pass '*' or '*.<ext>'."
    ),
    "target": (
        "'content' to grep inside files, 'files' to list/find files. "
        "Legacy aliases: 'grep' -> 'content', 'find'/'ls' -> 'files'. "
        "Default 'content'."
    ),
    "path": ("Directory (or, in content mode, a single file) to search. Default '.'."),
    "file_glob": (
        "Restrict content search to filenames matching this glob. "
        "Ignored in files mode (use the 'pattern' argument instead)."
    ),
    "limit": "Max results to return. Default 50.",
    "offset": "Skip first N results for pagination. Default 0.",
    "output_mode": (
        "Content-mode output shape: 'content' (lines + line numbers, "
        "default), 'files_only' (paths only), 'count' (per-file match "
        "counts)."
    ),
    "context": ("Lines of context before and after each match (content mode only). Default 0."),
    "hashline": ("Content mode: include N:hhhh hash anchors in matched lines. Default False."),
    "task_id": (
        "Optional anti-loop scope key. Defaults to a shared bucket; pass "
        "a per-task id when multiple agents share a process."
    ),
}


# ── Factory ───────────────────────────────────────────────────────────────


def register_file_tools(
    mcp: FastMCP,
    *,
    home: str | None = None,
    write_safe_root: str | list[str] | None = None,
    before_write: Callable[[], None] | None = None,
) -> None:
    """Register the canonical file tools on an MCP server.

    Path model (uniform across read_file, write_file, edit_file,
    hashline_edit, search_files, apply_patch):

      * Relative paths anchor to ``home``. ``home="my-folder"`` means
        ``path="notes.md"`` resolves to ``<home>/notes.md``.
      * Absolute paths are honored verbatim — no silent rebasing.
      * ``~`` expands to the OS user home.
      * A small deny list blocks writes to system + credential paths
        and reads of credential files. System config (e.g. /etc/nginx/)
        remains readable.
      * If ``write_safe_root`` is set, writes outside that subtree are
        denied. Reads are not restricted by it.

    Args:
        mcp: FastMCP instance to register tools on.
        home: Anchor for relative paths. Defaults to the process CWD when
            omitted, which is the right thing for the local unsandboxed
            server. Hosted contexts should always pass this explicitly.
        write_safe_root: Optional hard ceiling on writes. Either a single
            path or a list of allowed write roots — a write must land
            under at least one of them. Reads are unaffected.
        before_write: Hook called before any write/edit (e.g. git snapshot).
    """
    policy = _FilePolicy(home=home, write_safe_root=write_safe_root)

    @mcp.tool(description=READ_FILE_DOC)
    def read_file(
        path: Annotated[str, Field(description=READ_FILE_PARAMS["path"])],
        offset: Annotated[int, Field(description=READ_FILE_PARAMS["offset"])] = 1,
        limit: Annotated[int, Field(description=READ_FILE_PARAMS["limit"])] = 0,
        hashline: Annotated[bool, Field(description=READ_FILE_PARAMS["hashline"])] = False,
    ) -> str:
        try:
            resolved = policy.read_path(path)
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

        if _is_binary(resolved):
            size = os.path.getsize(resolved)
            return f"Binary file: {path} ({size:,} bytes). Cannot display binary content."

        try:
            # Read raw bytes once; use them both for the line-formatted
            # return value and to hash into the file-state cache so a
            # later edit can detect external writes without a second
            # open. Hash is computed even on partial/offset reads so the
            # guard still fires when the model only read the start of a
            # large file before editing deeper into it.
            with open(resolved, "rb") as fb:
                raw_bytes = fb.read()
            content = raw_bytes.decode("utf-8", errors="replace")
            record_read(None, resolved, content_bytes=raw_bytes)

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

    @mcp.tool(description=WRITE_FILE_DOC)
    def write_file(
        path: Annotated[str, Field(description=WRITE_FILE_PARAMS["path"])],
        content: Annotated[str, Field(description=WRITE_FILE_PARAMS["content"])],
    ) -> str:
        try:
            resolved = policy.write_path(path)
        except ValueError as e:
            return f"Error: {e}"
        resolved_path = Path(resolved)

        # Stale-edit guard: an existing file must have been read recently
        # and still match the on-disk content. Writing over a file the
        # model has never seen (or that changed since it last saw it)
        # risks clobbering the user's work.  Brand-new files are allowed
        # without a prior read - there's nothing to clobber.
        if resolved_path.is_file():
            _fresh = check_fresh(None, resolved)
            if _fresh.status is Freshness.UNREAD:
                return (
                    f"Refusing to overwrite '{path}': call read_file('{path}') "
                    f"first so the harness can track its state before you "
                    f"replace it. If you intend to discard the current "
                    f"contents, read it first to acknowledge what you are "
                    f"overwriting."
                )
            if _fresh.status is Freshness.STALE:
                return (
                    f"Refusing to overwrite '{path}': {_fresh.detail}. Re-read the file with read_file before writing."
                )

        try:
            # Create parent dirs first (before git snapshot) so structure exists
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            if before_write:
                try:
                    before_write()
                except Exception:
                    # Don't block the write if git snapshot fails. Do NOT log here —
                    # logging writes to stderr and can deadlock the MCP stdio pipe.
                    pass

            existed = resolved_path.is_file()
            content_str = content if content is not None else ""
            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(content_str)
                f.flush()
                os.fsync(f.fileno())

            # Record the post-write state so a later edit in the same
            # turn doesn't trip the stale-edit guard against the file
            # this call just created or overwrote.
            try:
                record_read(None, resolved, content_bytes=content_str.encode("utf-8"))
            except Exception:
                pass

            line_count = content_str.count("\n") + (1 if content_str and not content_str.endswith("\n") else 0)
            action = "Updated" if existed else "Created"
            return f"{action} {path} ({len(content_str):,} bytes, {line_count} lines)"
        except Exception as e:
            return f"Error writing file: {e}"

    @mcp.tool(description=EDIT_FILE_DOC)
    def edit_file(
        mode: Annotated[str, Field(description=EDIT_FILE_PARAMS["mode"])] = "replace",
        path: Annotated[str, Field(description=EDIT_FILE_PARAMS["path"])] = "",
        old_string: Annotated[str, Field(description=EDIT_FILE_PARAMS["old_string"])] = "",
        new_string: Annotated[str, Field(description=EDIT_FILE_PARAMS["new_string"])] = "",
        replace_all: Annotated[bool, Field(description=EDIT_FILE_PARAMS["replace_all"])] = False,
        patch_text: Annotated[str, Field(description=EDIT_FILE_PARAMS["patch_text"])] = "",
    ) -> str:
        if mode == "replace":
            return _patch_replace(
                policy,
                before_write,
                path,
                old_string,
                new_string,
                replace_all,
            )
        if mode == "patch":
            return _patch_apply(policy, before_write, patch_text)
        return f"Error: unknown mode '{mode}'. Use mode='replace' or mode='patch'."

    @mcp.tool(description=SEARCH_FILES_DOC)
    def search_files(
        pattern: Annotated[str, Field(description=SEARCH_FILES_PARAMS["pattern"])],
        target: Annotated[str, Field(description=SEARCH_FILES_PARAMS["target"])] = "content",
        path: Annotated[str, Field(description=SEARCH_FILES_PARAMS["path"])] = ".",
        file_glob: Annotated[str, Field(description=SEARCH_FILES_PARAMS["file_glob"])] = "",
        limit: Annotated[int, Field(description=SEARCH_FILES_PARAMS["limit"])] = 50,
        offset: Annotated[int, Field(description=SEARCH_FILES_PARAMS["offset"])] = 0,
        output_mode: Annotated[str, Field(description=SEARCH_FILES_PARAMS["output_mode"])] = "content",
        context: Annotated[int, Field(description=SEARCH_FILES_PARAMS["context"])] = 0,
        hashline: Annotated[bool, Field(description=SEARCH_FILES_PARAMS["hashline"])] = False,
        task_id: Annotated[str, Field(description=SEARCH_FILES_PARAMS["task_id"])] = "",
    ) -> str:
        # Legacy aliases — keep older prompts working.
        if target in ("grep",):
            target = "content"
        elif target in ("find", "ls"):
            target = "files"

        if target not in ("content", "files"):
            return f"Error: invalid target '{target}'. Use 'content' or 'files'."
        if output_mode not in ("content", "files_only", "count"):
            return f"Error: invalid output_mode '{output_mode}'. Use 'content', 'files_only', or 'count'."

        # Anti-loop guard. Key includes everything that would change results so
        # paginating through the same query doesn't trip the alarm.
        key = (target, pattern, str(path), file_glob, int(limit), int(offset), output_mode, int(context))
        bucket = task_id or "_default"
        with _SEARCH_TRACKER_LOCK:
            td = _SEARCH_TRACKER.setdefault(bucket, {"last_key": None, "consecutive": 0})
            if td["last_key"] == key:
                td["consecutive"] += 1
            else:
                td["last_key"] = key
                td["consecutive"] = 1
            consecutive = td["consecutive"]

        if consecutive >= 4:
            return (
                f"BLOCKED: this exact search has run {consecutive} times in a row. "
                "Results have NOT changed. Use the information you already have and proceed."
            )

        try:
            resolved = policy.read_path(path)
        except ValueError as e:
            return f"Error: {e}"

        # Output paths are relativized against home for readability —
        # e.g. ``src/foo.py`` instead of ``/Users/aden/<home>/src/foo.py``.
        display_root = policy.home

        if target == "files":
            result = _do_search_files_target(
                pattern=pattern,
                resolved=resolved,
                display_root=display_root,
                limit=limit,
                offset=offset,
            )
        else:
            # content mode allows a single file as path; the target=files mode does not
            if not os.path.isdir(resolved) and not os.path.isfile(resolved):
                return f"Error: Path not found: {path}"
            result = _do_search_content_target(
                pattern=pattern,
                resolved=resolved,
                project_root=display_root,
                file_glob=file_glob,
                limit=limit,
                offset=offset,
                output_mode=output_mode,
                context=context,
                hashline=hashline,
            )

        if consecutive == 3:
            result += (
                f"\n\n[Warning: this exact search has run {consecutive} times consecutively. "
                "Results have not changed — use what you have instead of re-searching.]"
            )
        return result
