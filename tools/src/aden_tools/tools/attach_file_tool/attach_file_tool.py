"""Attach file tool — make a local file appear in the user's chat AND
re-inject its content into the agent's next LLM turn.

Two simultaneous jobs:

1. **Re-inject for the model.** PDFs + images become MCP ``ImageContent``
   blocks; text-shaped files become ``TextContent`` blocks. mcp_client
   maps PDF mimeType → OpenAI ``file`` block; the rest become
   ``image_url`` / inline text. This is what lets the agent re-read
   bytes after they've aged out of context.

2. **Surface to the user as a clickable chip.** The chip copy
   (source → ``{session}/data/attachments/<basename>``) and the
   ``hive_attachment_url`` field are added by the framework's
   ``_publish_attach_file_result`` post-processor in agent_loop, NOT
   by this tool. The MCP subprocess this tool runs in is pooled at
   process boot and queen-agnostic, so it can't see
   ``$HIVE_STORAGE_PATH`` for the current session. Doing the copy in
   the framework gives us exactly one publish path that always has
   the session dir via ``conversation_store._base``.

Accepts one or many paths (absolute, CWD-relative, or
``$HIVE_STORAGE_PATH``-relative like ``data/attachments/X.pdf``).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from aden_tools.utils.attachments import (
    TEXT_EXT_TO_MIME as _TEXT_EXT_TO_MIME,
    looks_like_text as _looks_like_text,
)

logger = logging.getLogger("aden_tools.attach_file")

_MAX_PATHS = 10
_DEFAULT_MAX_BYTES_MB = 25.0
# Cap the inline text body SMALL. This is not just context economy: the inline
# body is concatenated into the tool result, and if the result exceeds the agent
# loop's ``max_tool_result_chars`` (~30k) it gets spilled to disk and replaced
# with a prose placeholder — which destroys the leading JSON summary the renderer
# parses to draw the attachment chip, so the chip silently never appears. Keeping
# the body well under that threshold keeps the result JSON-first and the chip
# always publishes. The full file is always copied to disk + downloadable via the
# chip; the LLM gets a preview here and can read the rest with a terminal tool.
_TEXT_INLINE_CAP_BYTES = 8 * 1024  # 8 KiB preview (must stay << max_tool_result_chars)

# Binary formats the LLM can directly consume — base64'd into ImageContent
# (mcp_client emits image_url for images, native `file` block for PDFs).
_BINARY_PREVIEW_EXT_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Text-shaped formats the LLM should see inline as TextContent — the shared
# allowlist lives in aden_tools.utils.attachments (imported above). Anything
# not on it that LOOKS text (no NUL bytes, decodable as utf-8) also falls
# through into the text path via the heuristic in `_classify_file`.


def _classify_file(ext: str, raw_bytes: bytes) -> tuple[str, str]:
    """Decide how to surface a file to the LLM. Returns ``(kind, mime)``:

    ``("pdf",   "application/pdf")``    → binary PDF preview block
    ``("image", "<image/*>")``          → image block
    ``("text",  "<text/* or similar>")``→ inline text block
    ``("blob",  "application/octet-stream")``
                                        → user-facing chip only; the LLM
                                          sees just a summary entry, not
                                          the bytes (e.g. zip, docx, mp3).
    """
    if ext in _BINARY_PREVIEW_EXT_TO_MIME:
        mime = _BINARY_PREVIEW_EXT_TO_MIME[ext]
        return ("pdf" if mime == "application/pdf" else "image", mime)
    if ext in _TEXT_EXT_TO_MIME:
        return ("text", _TEXT_EXT_TO_MIME[ext])
    # Unknown extension — sniff for text-shape.
    if _looks_like_text(raw_bytes[:4096]):
        return ("text", "text/plain")
    return ("blob", "application/octet-stream")


def _resolve_path(raw: str) -> Path | None:
    """Resolve a path string to an absolute Path, trying in order:

    1. As-is if absolute.
    2. ``$HIVE_STORAGE_PATH / raw`` if that env var is set (so the
       agent's typical ``data/attachments/X.pdf`` works out of the box).
    3. CWD-relative as a last resort.

    Returns the first candidate that exists, or None.
    """
    candidates: list[Path] = []
    p = Path(raw)
    if p.is_absolute():
        candidates.append(p)
    else:
        storage = os.environ.get("HIVE_STORAGE_PATH")
        if storage:
            candidates.append(Path(storage) / raw)
        candidates.append(Path.cwd() / raw)

    for c in candidates:
        try:
            if c.exists() and c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def register_tools(mcp: FastMCP) -> None:
    """Register the attach_file tool with the MCP server."""

    @mcp.tool()
    def attach_file(
        paths: str | list[str],
        max_bytes_mb: float = _DEFAULT_MAX_BYTES_MB,
    ) -> list:
        """Surface one or more local files to the user as clickable chips
        in chat. **Any file type is accepted.**

        Use this whenever the user has asked for a file — a report, a
        spreadsheet, a config, a zip, anything. Never rename, zip, or
        paste the contents inline as a workaround "because the tool
        doesn't support this format" — it does.

        Use this on a PDF that ``pdf_read`` returned with
        ``needs_vision_pages`` (scanned / image-based) — the PDF is sent
        as ImageContent so vision can read the rendered pages directly.
        Do NOT reach for tesseract / pdftoppm first; ``attach_file`` on
        the original PDF replaces that whole pipeline.

        Args:
            paths: One path or a list of up to 10 paths. Each may be
                absolute, CWD-relative, or relative to ``$HIVE_STORAGE_PATH``
                (so ``data/attachments/X.pdf`` works as the agent reads
                it from the user message).
            max_bytes_mb: Per-file cap. Files larger than this are
                reported in the ``errors`` list instead of being attached.

        How each file type is handled:
            - **PDFs + images** (.pdf, .png, .jpg, .jpeg, .webp, .gif) —
              base64-encoded into ImageContent so you can re-read the
              bytes, AND surfaced as a chip the user can open.
            - **Text formats** (.md, .txt, .csv, .json, .yaml, .py, .ts,
              .sh, .xml, .html, source code, configs, logs, ...) — read
              as text and inlined as TextContent so you can read them
              directly, AND surfaced as a chip.
            - **Anything else** (.zip, .docx, .xlsx, .mp3, .mp4, .wav,
              .exe, ...) — published as a chip the user can download.
              You receive only the metadata summary, not the bytes.
              The chip opens in a new browser tab; the browser previews
              the file when it can and downloads it otherwise.

        Returns:
            An MCP content list: a TextContent JSON summary plus zero or
            more content blocks per file (one for preview/text kinds;
            none for opaque blobs). Each ``attached`` entry includes
            ``kind`` ∈ {pdf, image, text, blob}, ``mime``, ``filename``,
            and ``resolved`` (absolute path). The framework injects
            ``hive_attachment_url`` (the renderer's chip URL) into each
            entry post-hoc once the chip copy is in place.
        """
        # Normalize input.
        if isinstance(paths, str):
            paths_list = [paths]
        elif isinstance(paths, list):
            paths_list = [str(p) for p in paths]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "attached": [],
                            "errors": [{"error": f"paths must be a string or list, got {type(paths).__name__}"}],
                        }
                    ),
                )
            ]

        if len(paths_list) > _MAX_PATHS:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "attached": [],
                            "errors": [{"error": (f"Too many paths: {len(paths_list)} provided, max {_MAX_PATHS} per call.")}],
                        }
                    ),
                )
            ]

        max_bytes = max(1, int(max_bytes_mb * 1024 * 1024))

        attached: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        content_blocks: list[Any] = []

        for raw_path in paths_list:
            resolved = _resolve_path(raw_path)
            if resolved is None:
                errors.append({"path": raw_path, "error": "file not found"})
                continue

            try:
                size = resolved.stat().st_size
            except OSError as exc:
                errors.append({"path": raw_path, "error": f"stat failed: {exc}"})
                continue

            if size > max_bytes:
                errors.append(
                    {
                        "path": raw_path,
                        "error": (f"file exceeds max_bytes ({size} > {max_bytes}); raise max_bytes_mb or shrink the file."),
                    }
                )
                continue

            try:
                raw_bytes = resolved.read_bytes()
            except OSError as exc:
                errors.append({"path": raw_path, "error": f"read failed: {exc}"})
                continue

            ext = resolved.suffix.lower()
            kind, mime = _classify_file(ext, raw_bytes)

            inline_block: Any | None
            if kind == "text":
                try:
                    text_body = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    # Fall back to latin-1 so we never lose bytes; rare
                    # since we only land here for text-shaped files.
                    text_body = raw_bytes.decode("latin-1", errors="replace")
                # Keep the inline body small so the result is never spilled
                # (a spilled result loses the leading JSON summary and the chip
                # never renders — see _TEXT_INLINE_CAP_BYTES). The on-disk copy +
                # chip always have the full file.
                if len(raw_bytes) > _TEXT_INLINE_CAP_BYTES:
                    text_body = (
                        text_body[:_TEXT_INLINE_CAP_BYTES] + f"\n\n…[preview truncated at {_TEXT_INLINE_CAP_BYTES} bytes — download the full file"
                        " via the chip, or read it with a terminal tool]"
                    )
                inline_block = TextContent(
                    type="text",
                    text=f"[attached {resolved.name} ({mime})]\n\n{text_body}",
                )
            elif kind in ("pdf", "image"):
                b64 = base64.b64encode(raw_bytes).decode()
                inline_block = ImageContent(type="image", data=b64, mimeType=mime)
            else:
                # ``blob`` — the file is binary and not one of the formats
                # the LLM can directly consume (zip, docx, mp3, exe, …).
                # We still publish a chip for the user; the LLM gets only
                # the summary entry below so it knows the user has the file.
                inline_block = None

            entry: dict[str, Any] = {
                "path": raw_path,
                "resolved": str(resolved),
                "kind": kind,
                "mime": mime,
                "bytes": size,
                "filename": resolved.name,
            }
            # NOTE: `hive_attachment_url` is added by the framework's
            # `_publish_attach_file_result` in agent_loop.py (queen and
            # non-queen paths alike). We can't publish it here because
            # this MCP subprocess is pooled at boot and doesn't carry a
            # per-session `$HIVE_STORAGE_PATH`.
            attached.append(entry)
            if inline_block is not None:
                content_blocks.append(inline_block)

        # If nothing got attached, surface a single hard error so the
        # agent doesn't quietly send an empty re-attach into context.
        if not attached:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"attached": [], "errors": errors}),
                )
            ]

        summary = TextContent(
            type="text",
            text=json.dumps({"attached": attached, "errors": errors}),
        )
        return [summary, *content_blocks]
