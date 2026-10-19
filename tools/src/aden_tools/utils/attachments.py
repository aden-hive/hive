"""Shared filename sanitization + collision disambiguation for the
session attachment directory.

Used by both:

- ``framework.server.routes_sessions.handle_upload_attachment`` (user→assistant
  uploads through the chat composer)
- ``aden_tools.tools.attach_file_tool.attach_file`` (assistant→user
  surface via the ``attach_file`` MCP tool)

Both write to ``{queen_session_dir}/data/attachments/<basename>``. Keeping
the sanitize + disambiguate logic in one place means filenames behave
identically regardless of which direction the file flows, and the
``hive-attachment://`` URLs the renderer resolves point at the same on-disk
shape in both cases.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

_INVALID_CHARS_RE = re.compile(r"[\x00-\x1f\\/:*?\"<>|]")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_BASENAME_LEN = 200

# Text-shaped formats the LLM should see inline as text. Broad allowlist
# covering code, markup, config, prose. Shared by:
#   - attach_file_tool (assistant→user direction)
#   - routes_execution.handle_chat (user→assistant chat attachments)
#   - routes_sessions.handle_upload_attachment (chip-preview extraction)
#   - the frontend composer's classifyAttachment (ChatPanel.tsx) mirrors
#     these extensions — keep the lists in sync when editing.
TEXT_EXT_TO_MIME: dict[str, str] = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".svg": "image/svg+xml",
    ".css": "text/css",
    ".scss": "text/x-scss",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".ts": "text/x-typescript",
    ".tsx": "text/x-typescript",
    ".jsx": "text/javascript",
    ".py": "text/x-python",
    ".rb": "text/x-ruby",
    ".go": "text/x-go",
    ".rs": "text/x-rust",
    ".java": "text/x-java",
    ".kt": "text/x-kotlin",
    ".swift": "text/x-swift",
    ".c": "text/x-c",
    ".cpp": "text/x-c++",
    ".cc": "text/x-c++",
    ".h": "text/x-c",
    ".hpp": "text/x-c++",
    ".cs": "text/x-csharp",
    ".sh": "text/x-shellscript",
    ".bash": "text/x-shellscript",
    ".zsh": "text/x-shellscript",
    ".fish": "text/x-shellscript",
    ".sql": "application/sql",
    ".ini": "text/x-ini",
    ".cfg": "text/x-ini",
    ".conf": "text/x-conf",
    ".log": "text/plain",
    ".rst": "text/x-rst",
    ".tex": "text/x-tex",
}


def looks_like_text(sample: bytes) -> bool:
    """Best-effort: a file 'looks text' if its first 4KB has no NUL byte
    and decodes cleanly as UTF-8. Used as a fallback for files with
    unknown extensions so an unrecognized but-still-readable file (a
    Dockerfile, a Makefile, a no-extension shell script) gets piped to
    the LLM as text instead of being treated as opaque."""
    if b"\0" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sanitize_attachment_basename(
    original_name: str,
    *,
    force_ext: str | None = None,
    fallback_stem: str = "upload",
) -> str:
    """Reduce an arbitrary filename to a safe basename for the attachments
    directory.

    - Strips any directory components (``..``/etc/passwd → passwd).
    - Replaces reserved + control characters with underscores.
    - Collapses whitespace.
    - When ``force_ext`` is given (e.g. ``".pdf"``), the suffix is forced —
      this is what protects against ``.jpg``-extension sniff tricks on the
      upload route (the server trusts its content-type detection over the
      user-provided suffix).
    - Caps the final basename at 200 characters by trimming the stem.
    """
    base = os.path.basename(original_name) or fallback_stem
    base = _INVALID_CHARS_RE.sub("_", base)
    base = _WHITESPACE_RE.sub(" ", base).strip() or fallback_stem
    stem, ext = os.path.splitext(base)
    if force_ext is not None and (not ext or ext.lower() != force_ext.lower()):
        ext = force_ext
        base = f"{stem or fallback_stem}{ext}"
    if len(base) > _MAX_BASENAME_LEN:
        stem, suffix = os.path.splitext(base)
        base = stem[: _MAX_BASENAME_LEN - len(suffix)] + suffix
    return base


def disambiguate_attachment_filename(directory: Path, basename: str) -> str:
    """If ``directory/basename`` already exists, suffix the stem with
    ``" (2)"``, ``" (3)"``, ... — same convention macOS/Finder + Windows
    Explorer use on file copy. Falls back to a millisecond-timestamped
    suffix if even ``(2)..(9999)`` collide (vanishingly unlikely in
    practice, but the fallback guarantees we never overwrite).
    """
    if not (directory / basename).exists():
        return basename
    stem, suffix = os.path.splitext(basename)
    for i in range(2, 10000):
        candidate = f"{stem} ({i}){suffix}"
        if not (directory / candidate).exists():
            return candidate
    return f"{stem}-{int(time.time() * 1000)}{suffix}"
