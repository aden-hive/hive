"""Execution control routes — chat, queen-context, cancel-queen, fork."""

import asyncio
import json
import logging
from datetime import UTC
from typing import Any

from aiohttp import web

from framework.server.app import resolve_session
from framework.utils.text import humanize_slug

logger = logging.getLogger(__name__)

# Strong refs to background fork-finalize tasks (compaction + worker-conv
# copy) so asyncio doesn't GC them mid-run. fork_session_into_colony
# schedules into this set and the done-callback evicts on completion.
_BACKGROUND_FORK_TASKS: set[asyncio.Task[None]] = set()


# Tool names the worker SHOULD inherit when a colony is forked. These are
# the "work-doing" primitives — anything else in a queen phase tool list is
# queen-lifecycle and must not flow into worker.json.
_WORKER_INHERITED_TOOLS: frozenset[str] = frozenset(
    {
        # File I/O is done via the terminal tools below (terminal_exec /
        # terminal_rg / terminal_glob); the dedicated file tools were removed.
        # Terminal (basics — exec + ripgrep + glob)
        "terminal_exec",
        "terminal_rg",
        "terminal_glob",
        # Framework synthetics (always available to any AgentLoop node)
        "set_output",
        # ``report_to_parent`` is the worker's terminal channel: it
        # publishes a SUBAGENT_REPORT and ends the run. Workers use it
        # for both success and failure (status='failed' with a clear
        # reason) — there is no queen-side escalation/reply loop. The
        # queen reads the failure and either re-dispatches with new
        # parameters or takes over herself.
        "report_to_parent",
        # Tracker reads + writes — workers fill rows in the queen's
        # tracker.db (tracker_upsert) and read their assignment context
        # via SELECT (tracker_query). The queen-only ``tracker_sql`` and
        # ``tracker_register_writable`` are stripped automatically by
        # _resolve_queen_only_tools because they're in the queen phase
        # lists but NOT here.
        "tracker_upsert",
        "tracker_query",
        # Session task tools. ``colony_runtime._apply_pipeline_results``
        # registers these on the colony pipeline registry "so the colony's
        # `_tools` snapshot includes them" and every worker gets its own
        # ``session_id`` (``colony_runtime.spawn``). They must therefore
        # survive the queen-only strip — without these four entries the
        # tools appear in the queen phase lists, get classified
        # queen-only, and are stripped from every parallel worker even
        # though the colony explicitly registered them for worker use.
        # ``WORKER_SYSTEM_PROMPT``'s ``## Task tracking`` section depends
        # on workers actually having these.
        "task_create",
        "task_update",
        "task_list",
        "task_get",
    }
)


# Queen-lifecycle tools that are registered into the queen's tool registry
# but NOT listed in any _QUEEN_*_TOOLS phase list (they're reachable only via
# explicit registration or as frontend-visible helpers, not phase-based
# gating). These must still be stripped from forked / parallel-spawned
# worker tool inventories.
_QUEEN_LIFECYCLE_EXTRAS: frozenset[str] = frozenset(
    {
        # Phase-transition wrappers (method variants are on QueenPhaseState
        # but the queen also sees them as tools).
        "switch_to_independent",
        # Frontend helpers that live outside phase lists.
        "list_credentials",
        "get_worker_health_summary",
    }
)


def _resolve_queen_only_tools() -> frozenset[str]:
    """Compute the set of queen-lifecycle tool names to strip on fork.

    Derived from the queen phase tool lists in ``agents.queen.nodes``:
    any tool listed in any ``_QUEEN_*_TOOLS`` set that is NOT in
    :data:`_WORKER_INHERITED_TOOLS` is a queen-only tool. Browser and MCP
    tools are not in the queen phase lists (they're added dynamically),
    so they pass through untouched. Supplemented by
    :data:`_QUEEN_LIFECYCLE_EXTRAS` for tools registered without phase
    gating.

    Computed lazily so this module can be imported before the queen
    nodes package is loaded.
    """
    from framework.agents.queen.nodes import (
        _QUEEN_COLONY_TOOLS,
        _QUEEN_INDEPENDENT_TOOLS,
    )

    union: set[str] = set()
    for tool_list in (
        _QUEEN_INDEPENDENT_TOOLS,
        _QUEEN_COLONY_TOOLS,
    ):
        union.update(tool_list)
    derived = union - _WORKER_INHERITED_TOOLS
    return frozenset(derived | _QUEEN_LIFECYCLE_EXTRAS)


async def handle_chat(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/chat — send a message to the queen.

    The input box is permanently connected to the queen agent, including
    replies to worker-originated questions. The queen decides whether to
    relay the user's answer back into the worker via inject_message().

    Body: {"message": "hello", "images": [{"type": "image_url", "image_url": {"url": "data:..."}}]}

    The optional ``images`` field accepts a list of OpenAI-format image_url
    content blocks.  The frontend encodes images as base64 data URIs.
    """
    session, err = resolve_session(request)
    if err:
        logger.debug("[handle_chat] Session resolution failed: %s", err)
        return err

    # Sessions that have spawned a colony are locked: the user must compact +
    # fork into a fresh session before continuing the conversation. Frontend
    # surfaces this as a button instead of the textarea, but enforce server-
    # side too so the lock can't be bypassed by a stale tab or scripted call.
    if getattr(session, "colony_spawned", False):
        return web.json_response(
            {
                "error": "session_locked",
                "reason": "colony_spawned",
                "spawned_colony_id": getattr(session, "spawned_colony_id", None),
                "message": (
                    "This session is locked because a colony has been "
                    "spawned from it. Compact and start a new session "
                    "with the same queen to continue."
                ),
            },
            status=409,
        )

    # Sessions forked away via task_create(new_session=true) are retired:
    # the conversation continues in the successor session. Lock the old
    # one so a stale tab can't write to a session that is being stopped.
    if getattr(session, "superseded_by", None):
        return web.json_response(
            {
                "error": "session_locked",
                "reason": "superseded",
                "superseded_by": session.superseded_by,
                "message": ("This session has been forked into a fresh one. Continue in the successor session."),
            },
            status=409,
        )

    # A genuine user message re-arms new_session on a freshly-forked
    # session: the kickoff turn is over, and any pivot the user makes
    # from here is a real one the queen may legitimately fork on.
    if getattr(session, "fork_kickoff_pending", False):
        session.fork_kickoff_pending = False

    body = await request.json()
    message = body.get("message", "")
    display_message = body.get("display_message")
    image_content = body.get("images") or None  # list[dict] | None

    # Persist uploaded attachments to disk and separate PDFs from images.
    # PDFs are emitted as OpenAI-native `file` blocks so LiteLLM auto-remaps
    # them per provider (Anthropic document, Gemini inline_data, OpenAI
    # native file). Their text is also extracted and prepended to the user
    # message as a belt-and-braces fallback. Non-vision primaries still get
    # the PDF — the vision-fallback sidecar accepts `file` blocks too.
    saved_image_paths: list[str] = []
    if image_content and session.queen_dir:
        import base64
        import io
        import time

        # Save under data/ so MCP tools can reach files via
        # $HIVE_STORAGE_PATH/data/attachments/... (the convention web_scrape_tool
        # and other tools follow). Old sessions keep their files at the prior
        # top-level attachments/ location; only new uploads land here.
        attachments_dir = session.queen_dir / "data" / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)

        # Each saved attachment: (kind, rel_path, abs_path, meta_str) used by the
        # path-injection block appended to the user's message below.
        saved_attachment_info: list[tuple[str, str, str, str]] = []

        images_only: list[dict] = []
        # Per-attachment extracted text the backend prepends to the user
        # message (one place, one owner — Layer F1). PDFs, CSVs and
        # text-shaped files land here; images contribute nothing. Frontend
        # NEVER prepends text any more; the upload-endpoint's
        # `extracted_text` is for chip preview only, not for queen context.
        attachment_text_parts: list[str] = []

        from aden_tools.utils.attachments import TEXT_EXT_TO_MIME

        # Lookup of allowed MIME types by extension — used both for
        # data:-URI emission and for resolving hive-attachment:// references
        # back to a block shape. Text-shaped extensions come from the shared
        # attach_file allowlist (mirrored by the frontend composer's
        # classifyAttachment). `.svg` is excluded: the composer sends SVGs
        # as data:image/* URIs, and svg bytes can't go into an image block.
        _EXT_TO_MIME = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".csv": "text/csv",
            **{e: m for e, m in TEXT_EXT_TO_MIME.items() if e != ".svg"},
        }
        # MIMEs that take the inline-text branch below. text/csv is handled
        # by its own table-formatting branch first; image/svg+xml excluded
        # with .svg above.
        _TEXT_MIMES = frozenset(TEXT_EXT_TO_MIME.values()) - {"text/csv", "image/svg+xml"}
        _MIME_TO_EXT = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }

        # Size threshold: above this, a PDF is treated as a "large agentic
        # attachment" — the bytes don't go into the LLM message at all, only
        # a path pointer that instructs the agent to load pages partially
        # via pdf_read. Prevents the calculus-textbook scenario where a 100 MB
        # PDF blew Claude's input-token count to 900% and triggered a
        # compaction storm.
        LARGE_PDF_THRESHOLD_BYTES = 10 * 1024 * 1024

        # Text extraction is CPU-bound per page; a dense 1000-page PDF under
        # the size threshold used to burn minutes. Beyond this cap the agent
        # reads further pages selectively via pdf_read.
        _PDF_EXTRACT_MAX_PAGES = 200

        # Same idea for text files: above this, only a truncated head is
        # prepended and the agent reads the rest from disk via terminal
        # tools. 256 KB of text is already ~64k tokens — enough to be
        # useful inline without risking a compaction storm.
        LARGE_TEXT_THRESHOLD_BYTES = 256 * 1024
        LARGE_TEXT_HEAD_CHARS = 8 * 1024

        def _fmt_size(n: int) -> str:
            """Human-friendly size for the [Attachments] block hint."""
            if n >= 1024 * 1024:
                return f"{n / (1024 * 1024):.1f} MB"
            if n >= 1024:
                return f"{n / 1024:.1f} KB"
            return f"{n} bytes"

        for idx, img in enumerate(image_content):
            url = img.get("image_url", {}).get("url", "")

            # hive-attachment://<rel-path-from-queen-dir> — the file is
            # already on disk (multipart upload saved it). Skips the
            # body-size cost of re-sending the bytes inline; chat body
            # stays small even for big PDFs.
            if url.startswith("hive-attachment://"):
                rel_path_in_url = url[len("hive-attachment://") :].lstrip("/")
                target = (session.queen_dir / rel_path_in_url).resolve()
                # Path-traversal guard: target must be inside queen_dir.
                try:
                    target.relative_to(session.queen_dir.resolve())
                except ValueError:
                    logger.warning(
                        "[handle_chat] rejecting attachment ref outside queen_dir: %s",
                        url,
                    )
                    continue
                if not target.exists() or not target.is_file():
                    logger.warning("[handle_chat] attachment ref not found on disk: %s", url)
                    continue
                ext = target.suffix.lower()
                mime = _EXT_TO_MIME.get(ext)
                if mime is None:
                    # Unknown/binary type (e.g. .docx, .xlsx, archives) — no
                    # inline block exists for it, but the file IS on disk and
                    # the agent has terminal tools. Surface it instead of
                    # silently dropping the user's attachment.
                    try:
                        _size = target.stat().st_size
                    except OSError:
                        _size = 0
                    rel = url[len("hive-attachment://") :].lstrip("/")
                    saved_image_paths.append(rel)
                    attachment_text_parts.append(
                        f"[Attachment saved to disk: {rel} ({_fmt_size(_size)}) — "
                        f"no inline preview for '{ext or 'unknown'}' files; read/convert "
                        f"it from disk with terminal tools]"
                    )
                    continue
                # Defer the byte read — for a large PDF we won't emit a block
                # and reading 100 MB into memory for nothing is wasteful.
                try:
                    attachment_size = target.stat().st_size
                except OSError as exc:
                    logger.warning("[handle_chat] attachment ref stat failed (%s): %s", exc, url)
                    continue
                raw_bytes = None
                b64data = None
                rel_path = rel_path_in_url
                saved_image_paths.append(rel_path)
                resolved_path = target
                # Fall through into the same per-mime branches below.
                is_attachment_ref = True
            elif url.startswith("data:"):
                try:
                    header, b64data = url.split(",", 1)
                    mime = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
                    # Off-loop: a 20 MB body means ~27 MB of base64 — CPU
                    # work that would stall every SSE stream if run inline.
                    raw_bytes = await asyncio.to_thread(base64.b64decode, b64data)
                except Exception:
                    logger.debug("[handle_chat] failed to decode attachment %d", idx)
                    continue
                attachment_size = len(raw_bytes)
                rel_path = ""  # filled in per-mime below
                resolved_path = None  # filled in per-mime below
                is_attachment_ref = False
            else:
                images_only.append(img)
                continue

            if mime == "application/pdf":
                if not is_attachment_ref:
                    # data: URI path — save the bytes to disk now.
                    pdf_filename = f"{ts}_{idx}.pdf"
                    pdf_filepath = attachments_dir / pdf_filename
                    await asyncio.to_thread(pdf_filepath.write_bytes, raw_bytes)
                    rel_path = f"data/attachments/{pdf_filename}"
                    saved_image_paths.append(rel_path)
                else:
                    # hive-attachment:// path — file is already on disk.
                    pdf_filename = resolved_path.name
                    pdf_filepath = resolved_path

                is_large = attachment_size > LARGE_PDF_THRESHOLD_BYTES

                # Page count + (for small PDFs) text extraction. Runs in a
                # worker thread: extract_text() on a dense sub-10MB PDF is
                # pure CPU that used to freeze the whole server for up to
                # minutes. Page cap bounds the extraction (a 9.9 MB
                # 1000-page PDF is still megabytes of text otherwise).
                _pdf_bytes = raw_bytes

                def _inspect_pdf() -> tuple[int, list[str]]:
                    page_count = 0
                    parts: list[str] = []
                    try:
                        import pdfplumber

                        # Use the file path for hive-attachment so we don't
                        # have to load bytes into memory just to count pages.
                        pdf_src: Any = io.BytesIO(_pdf_bytes) if _pdf_bytes is not None else pdf_filepath
                        with pdfplumber.open(pdf_src) as pdf:
                            page_count = len(pdf.pages)
                            if not is_large:
                                for page_num, page in enumerate(pdf.pages):
                                    if page_num >= _PDF_EXTRACT_MAX_PAGES:
                                        parts.append(
                                            f"[PDF text extraction stopped at page {_PDF_EXTRACT_MAX_PAGES} "
                                            f"of {page_count} — read the rest via pdf_read]"
                                        )
                                        break
                                    page_text = page.extract_text()
                                    if page_text and page_text.strip():
                                        parts.append(f"[PDF page {page_num + 1}]\n{page_text.strip()}")
                    except ImportError:
                        logger.warning("[handle_chat] pdfplumber not installed; PDF page count + text prepend skipped")
                    except Exception:
                        logger.debug("[handle_chat] PDF inspection failed", exc_info=True)
                    return page_count, parts

                pdf_page_count, _pdf_parts = await asyncio.to_thread(_inspect_pdf)
                attachment_text_parts.extend(_pdf_parts)

                if not is_large:
                    # Small PDF — load bytes if we deferred earlier, then
                    # emit the native OpenAI `file` block. LiteLLM 1.83.4
                    # auto-remaps to each provider's native PDF shape
                    # (Anthropic `document`, Gemini `inline_data`, OpenAI
                    # native `file`). Sidecar also accepts this shape.
                    if raw_bytes is None:
                        try:
                            raw_bytes = await asyncio.to_thread(pdf_filepath.read_bytes)
                        except OSError as exc:
                            logger.warning(
                                "[handle_chat] small PDF byte-read failed (%s): %s",
                                exc,
                                pdf_filepath,
                            )
                            continue
                        b64data = (await asyncio.to_thread(base64.b64encode, raw_bytes)).decode()
                    images_only.append(
                        {
                            "type": "file",
                            "file": {
                                "file_data": f"data:application/pdf;base64,{b64data}",
                                "filename": pdf_filename,
                            },
                        }
                    )
                    logger.info(
                        "[handle_chat] PDF attached: %d pages, %d chars extracted (file block + text prepend)",
                        pdf_page_count,
                        sum(len(p) for p in attachment_text_parts),
                    )
                else:
                    # Large PDF — agentic path. Don't inline; the agent
                    # will load pages selectively via pdf_read using the
                    # path in the [Attachments] block below.
                    logger.info(
                        "[handle_chat] Large PDF (%s, %d pages) — path-only mode, agent must call pdf_read to access content",
                        _fmt_size(attachment_size),
                        pdf_page_count,
                    )

                if is_large:
                    pages_label = f"{pdf_page_count} pages" if pdf_page_count else "unknown page count"
                    # Pick a starting range that scales with size — small
                    # enough to fit in any model's context, large enough
                    # that the agent gets enough to navigate the TOC.
                    suggest_to = min(50, pdf_page_count) if pdf_page_count else 10
                    meta = (
                        f"{pages_label}, {_fmt_size(attachment_size)} — "
                        f"LARGE: load partially via "
                        f"pdf_read(file_path='{rel_path}', pages='1-{suggest_to}')"
                    )
                else:
                    meta = (
                        f"{pdf_page_count} page{'s' if pdf_page_count != 1 else ''}, {_fmt_size(attachment_size)}"
                        if pdf_page_count
                        else _fmt_size(attachment_size)
                    )
                saved_attachment_info.append(("PDF", rel_path, str(pdf_filepath.resolve()), meta))
            elif mime == "text/csv":
                # CSV — no LLM block (it's tabular text, not vision content).
                # Extract first 200 rows as a pipe-delimited table and feed
                # the existing text-prepend path. Layer F1 moved this from
                # the multipart-upload endpoint so backend now owns ALL
                # attachment→queen-text conversion in one place.
                if not is_attachment_ref:
                    # data: URI path — save bytes to disk now.
                    csv_filename = f"{ts}_{idx}.csv"
                    csv_filepath = attachments_dir / csv_filename
                    await asyncio.to_thread(csv_filepath.write_bytes, raw_bytes)
                    rel_path = f"data/attachments/{csv_filename}"
                    saved_image_paths.append(rel_path)
                else:
                    csv_filename = resolved_path.name
                    csv_filepath = resolved_path

                # Bounded parse — the cap matches PDFs (100 MB) so the file
                # must NOT be list()'d into memory. Materialize header +
                # first 200 rows, count the rest row-by-row (O(1) memory).
                # Runs in a worker thread: the full-file row count over a
                # 100 MB CSV is seconds of loop-stalling work otherwise.
                _csv_bytes = raw_bytes

                def _parse_csv() -> tuple[int, str | None]:
                    row_count = 0
                    text_part: str | None = None
                    try:
                        import csv as _csv_mod
                        from itertools import islice

                        if _csv_bytes is not None:
                            src_fh: Any = io.StringIO(_csv_bytes.decode("utf-8", errors="replace"))
                        else:
                            src_fh = open(csv_filepath, newline="", encoding="utf-8", errors="replace")
                        try:
                            reader = _csv_mod.reader(src_fh)
                            header = next(reader, None)
                            if header is not None:
                                data_rows = list(islice(reader, 200))
                                row_count = len(data_rows) + sum(1 for _ in reader)
                                lines = [
                                    f"[CSV file: {csv_filename}, {row_count} rows, {len(header)} columns]",
                                    " | ".join(header),
                                    " | ".join("---" for _ in header),
                                ]
                                for r in data_rows:
                                    lines.append(" | ".join(r))
                                if row_count > 200:
                                    lines.append(f"... ({row_count - 200} more rows truncated)")
                                text_part = "\n".join(lines)
                        finally:
                            src_fh.close()
                    except Exception:
                        logger.debug("[handle_chat] CSV parse failed", exc_info=True)
                    return row_count, text_part

                csv_row_count, _csv_part = await asyncio.to_thread(_parse_csv)
                if _csv_part is not None:
                    attachment_text_parts.append(_csv_part)

                logger.info(
                    "[handle_chat] CSV attached: %d rows, %d bytes (text prepend, no LLM block)",
                    csv_row_count,
                    attachment_size,
                )
                meta = f"{csv_row_count} rows, {_fmt_size(attachment_size)}" if csv_row_count else _fmt_size(attachment_size)
                saved_attachment_info.append(("CSV", rel_path, str(csv_filepath.resolve()), meta))
            elif mime in _TEXT_MIMES or mime.startswith("text/"):
                # Text-shaped file (txt/md/json/code/config/...) — no LLM
                # block; content rides the same text-prepend path as CSV.
                if not is_attachment_ref:
                    # data: URI path — save bytes to disk now. The composer
                    # always multiparts text files, so this only serves
                    # programmatic clients; ".txt" is a safe default ext.
                    text_filename = f"{ts}_{idx}.txt"
                    text_filepath = attachments_dir / text_filename
                    await asyncio.to_thread(text_filepath.write_bytes, raw_bytes)
                    rel_path = f"data/attachments/{text_filename}"
                    saved_image_paths.append(rel_path)
                else:
                    text_filename = resolved_path.name
                    text_filepath = resolved_path

                # Bounded read — the cap matches PDFs (100 MB), so a large
                # file is never loaded fully into memory: only the inlined
                # head is decoded, and the line count streams in chunks.
                # Runs in a worker thread (chunked newline count over a
                # 100 MB file is loop-stalling work).
                is_large = attachment_size > LARGE_TEXT_THRESHOLD_BYTES
                _text_bytes = raw_bytes

                def _read_text_attachment() -> tuple[str, int]:
                    if _text_bytes is not None:
                        t = _text_bytes.decode("utf-8", errors="replace")
                        return t, (t.count("\n") + 1 if t else 0)
                    if is_large:
                        with open(text_filepath, "rb") as fh:
                            # ×4: worst-case UTF-8 bytes per char, so the
                            # decoded head always covers LARGE_TEXT_HEAD_CHARS.
                            head_bytes = fh.read(LARGE_TEXT_HEAD_CHARS * 4)
                            newlines = head_bytes.count(b"\n")
                            while chunk := fh.read(1024 * 1024):
                                newlines += chunk.count(b"\n")
                        return head_bytes.decode("utf-8", errors="replace"), newlines + 1
                    t = text_filepath.read_text(encoding="utf-8", errors="replace")
                    return t, (t.count("\n") + 1 if t else 0)

                try:
                    text, line_count = await asyncio.to_thread(_read_text_attachment)
                except OSError as exc:
                    logger.warning(
                        "[handle_chat] text attachment read failed (%s): %s",
                        exc,
                        text_filepath,
                    )
                    continue

                if is_large:
                    attachment_text_parts.append(
                        f"[Text file: {text_filename} — first {_fmt_size(LARGE_TEXT_HEAD_CHARS)} "
                        f"of {_fmt_size(attachment_size)}; read the full file at {rel_path}]\n"
                        f"{text[:LARGE_TEXT_HEAD_CHARS]}"
                    )
                else:
                    attachment_text_parts.append(f"[Text file: {text_filename}]\n{text}")

                logger.info(
                    "[handle_chat] text file attached: %s, %d lines, %d bytes (text prepend%s, no LLM block)",
                    text_filename,
                    line_count,
                    attachment_size,
                    " truncated" if is_large else "",
                )
                meta = f"{line_count} lines, {_fmt_size(attachment_size)}"
                if is_large:
                    meta += " — LARGE: only the head was inlined; read the full file from disk"
                saved_attachment_info.append(("Text", rel_path, str(text_filepath.resolve()), meta))
            else:
                # Regular image. Always inlined (frontend caps images at
                # 10 MB so no context-blow risk). For hive-attachment refs
                # we deferred the byte read upstream; load it now.
                if is_attachment_ref and raw_bytes is None:
                    try:
                        raw_bytes = await asyncio.to_thread(resolved_path.read_bytes)
                    except OSError as exc:
                        logger.warning(
                            "[handle_chat] image attachment-ref read failed (%s): %s",
                            exc,
                            resolved_path,
                        )
                        continue
                    b64data = (await asyncio.to_thread(base64.b64encode, raw_bytes)).decode()
                if not is_attachment_ref:
                    ext_choice = _MIME_TO_EXT.get(mime, ".bin")
                    filename = f"{ts}_{idx}{ext_choice}"
                    filepath = attachments_dir / filename
                    await asyncio.to_thread(filepath.write_bytes, raw_bytes)
                    rel_path = f"data/attachments/{filename}"
                    saved_image_paths.append(rel_path)
                    images_only.append(img)
                else:
                    # File already on disk; build a data-URI image_url block
                    # so downstream filters (drain, sidecar) see a normal
                    # image attachment instead of the hive-attachment scheme.
                    filename = resolved_path.name
                    filepath = resolved_path
                    images_only.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64data}"},
                        }
                    )

                # Best-effort dimensions for the path-injection block. PIL ships
                # with pdfplumber so it's always available; degrade silently if
                # an image is malformed.
                dims_str = ""
                try:
                    from PIL import Image

                    _img_bytes = raw_bytes

                    def _probe_dims() -> str:
                        with Image.open(io.BytesIO(_img_bytes)) as im:
                            return f"{im.size[0]}×{im.size[1]}, "

                    dims_str = await asyncio.to_thread(_probe_dims)
                except Exception:
                    pass
                saved_attachment_info.append(
                    (
                        "Image",
                        rel_path,
                        str(filepath.resolve()),
                        f"{dims_str}{mime}, {len(raw_bytes)} bytes",
                    )
                )

        # Prepend extracted attachment text to the user's message. Single
        # owner (Layer F1) — the frontend no longer prepends. Covers PDFs
        # (per-page extraction, small-PDF only — Layer E gate), CSVs
        # (first 200 rows formatted above) and text files (full content,
        # head-only when large).
        if attachment_text_parts:
            attached_text = "\n\n".join(attachment_text_parts)
            message = f"{message}\n\n--- Attached file content ---\n{attached_text}" if message else f"--- Attached file content ---\n{attached_text}"

        # Append a structured listing of saved attachments so the agent learns
        # the on-disk paths and can re-read or re-attach them later — the
        # image_content data URIs get evicted from history to save tokens,
        # but this text block persists. Two paths per file: relative (for
        # portable reasoning, matches frontend replay) + absolute (so any
        # path-taking tool works without HIVE_STORAGE_PATH resolution).
        if saved_attachment_info:
            # Wrapped in <system-reminder> so the LLM reads it as a framework
            # instruction (Claude / modern models treat these tags as
            # high-priority context) while the chat UI strips the block from
            # the rendered user-message body — the human shouldn't see their
            # message bloated with paths and pdf_read tutorials.
            lines = ["[Attachments saved to disk (re-read via pdf_read for text, or attach_file to put back into context)]"]
            large_count = 0
            for kind, rel_path, abs_path, meta in saved_attachment_info:
                lines.append(f"- {kind}: {rel_path} ({meta})")
                lines.append(f"  abs: {abs_path}")
                if "LARGE:" in meta:
                    large_count += 1
            if large_count > 0:
                # Make the constraint plain to the agent — the large
                # attachments are referenced by path only, not loaded.
                lines.append(
                    f"NOTE: {large_count} large attachment"
                    f"{'s were' if large_count != 1 else ' was'} not fully loaded "
                    "into context — use pdf_read (PDFs) or terminal tools "
                    "(text files) to read the rest selectively."
                )
            attachments_block = "<system-reminder>\n" + "\n".join(lines) + "\n</system-reminder>"
            message = f"{message}\n\n{attachments_block}" if message else attachments_block

        # Replace image_content with the processed list (PDFs are now native
        # `file` blocks rather than rendered page images).
        image_content = images_only if images_only else None

    logger.debug(
        "[handle_chat] session_id=%s, message_len=%d, has_images=%s",
        session.id,
        len(message),
        bool(image_content),
    )
    logger.debug("[handle_chat] session.queen_executor=%s", session.queen_executor)

    if not message and not image_content:
        return web.json_response({"error": "message is required"}, status=400)

    queen_executor = session.queen_executor
    if queen_executor is not None:
        logger.debug("[handle_chat] Queen executor exists, looking for 'queen' node...")
        logger.debug(
            "[handle_chat] node_registry type=%s, id=%s",
            type(queen_executor.node_registry),
            id(queen_executor.node_registry),
        )
        logger.debug("[handle_chat] node_registry keys: %s", list(queen_executor.node_registry.keys()))
        node = queen_executor.node_registry.get("queen")
        logger.debug("[handle_chat] node=%s, node_type=%s", node, type(node).__name__ if node else None)
        logger.debug("[handle_chat] has_inject_event=%s", hasattr(node, "inject_event") if node else False)

        # Race condition: executor exists but node not created yet (still initializing)
        if node is None and session.queen_task is not None and not session.queen_task.done():
            logger.warning("[handle_chat] Queen executor exists but node not ready yet (initializing). Waiting...")
            # Wait a short time for initialization to progress
            for _ in range(50):  # Max 5 seconds
                await asyncio.sleep(0.1)
                node = queen_executor.node_registry.get("queen")
                if node is not None:
                    logger.debug("[handle_chat] Node appeared after waiting")
                    break
            else:
                logger.error("[handle_chat] Node still not available after 5s wait")

        if node is not None and hasattr(node, "inject_event"):
            # A real user message re-opens worker dispatch. A Stop blocks it (so
            # a still-unwinding turn can't spawn workers into the middle of the
            # sweep), and this is the moment that block is lifted — the same
            # moment `inject_event` clears the loop's `_user_stopped`. Without
            # this the colony would stay permanently unable to spawn workers
            # after its first Stop.
            colony = getattr(session, "colony", None)
            if colony is not None and hasattr(colony, "resume_dispatch"):
                colony.resume_dispatch()

            # Publish BEFORE inject_event so handlers (e.g. memory recall)
            # complete before the event loop unblocks and starts the LLM turn.
            # Correlate the received event with the later CLIENT_INPUT_COMMITTED
            # the drain emits, so the UI can re-stamp this bubble to its true
            # injection time once the message actually enters the conversation.
            import uuid

            from framework.host.event_bus import AgentEvent, EventType

            input_correlation_id = uuid.uuid4().hex

            await session.event_bus.publish(
                AgentEvent(
                    type=EventType.CLIENT_INPUT_RECEIVED,
                    stream_id="queen",
                    node_id="queen",
                    execution_id=session.id,
                    correlation_id=input_correlation_id,
                    data={
                        # Allow the UI to display a user-friendly echo while
                        # the queen receives a richer relay wrapper.
                        "content": display_message if display_message is not None else message,
                        "image_count": len(image_content) if image_content else 0,
                        # Paths to saved attachment files (relative to session dir)
                        # so the frontend can reconstruct images on replay.
                        **({"image_paths": saved_image_paths} if saved_image_paths else {}),
                    },
                )
            )
            try:
                logger.debug("[handle_chat] Calling node.inject_event()...")
                await node.inject_event(
                    message,
                    is_client_input=True,
                    image_content=image_content,
                    correlation_id=input_correlation_id,
                )
                logger.debug("[handle_chat] inject_event() completed successfully")
            except Exception as e:
                logger.exception("[handle_chat] inject_event() failed: %s", e)
                raise
            return web.json_response(
                {
                    "status": "queen",
                    "delivered": True,
                }
            )
        else:
            if node is None:
                logger.error(
                    "[handle_chat] CRITICAL: Queen node is None! node_registry has %d keys: %s, queen_task=%s, queen_task_done=%s",
                    len(queen_executor.node_registry),
                    list(queen_executor.node_registry.keys()),
                    session.queen_task,
                    session.queen_task.done() if session.queen_task else None,
                )
            else:
                logger.error(
                    "[handle_chat] CRITICAL: Queen node exists but missing inject_event! node_attrs=%s",
                    [a for a in dir(node) if not a.startswith("_")],
                )

    # Queen is dead — try to revive her
    logger.warning("[handle_chat] Queen is dead for session '%s', reviving on /chat request", session.id)
    manager: Any = request.app["manager"]
    try:
        logger.debug("[handle_chat] Calling manager.revive_queen()...")
        await manager.revive_queen(session)
        logger.debug("[handle_chat] revive_queen() completed successfully")
        # Inject the user's message into the revived queen's queue so the
        # event loop drains it and clears any restored pending_input_state.
        _revived_executor = session.queen_executor
        _revived_node = _revived_executor.node_registry.get("queen") if _revived_executor else None
        if _revived_node is not None and hasattr(_revived_node, "inject_event"):
            await _revived_node.inject_event(message, is_client_input=True, image_content=image_content)
        return web.json_response(
            {
                "status": "queen_revived",
                "delivered": True,
            }
        )
    except Exception as e:
        logger.exception("[handle_chat] Failed to revive queen: %s", e)
        return web.json_response({"error": "Queen not available"}, status=503)


async def handle_queen_context(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/queen-context — queue context for the queen.

    Unlike /chat, this does NOT trigger an LLM response. The message is
    queued in the queen's injection queue and will be drained on her next
    natural iteration (prefixed with [External event]:).

    Body: {"message": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    body = await request.json()
    message = body.get("message", "")

    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    queen_executor = session.queen_executor
    if queen_executor is not None:
        node = queen_executor.node_registry.get("queen")
        if node is not None and hasattr(node, "inject_event"):
            await node.inject_event(message, is_client_input=False)
            return web.json_response({"status": "queued", "delivered": True})

    # Queen is dead — try to revive her
    logger.warning(
        "Queen is dead for session '%s', reviving on /queen-context request",
        session.id,
    )
    manager: Any = request.app["manager"]
    try:
        await manager.revive_queen(session)
        # After revival, deliver the message
        queen_executor = session.queen_executor
        if queen_executor is not None:
            node = queen_executor.node_registry.get("queen")
            if node is not None and hasattr(node, "inject_event"):
                await node.inject_event(message, is_client_input=False)
                return web.json_response({"status": "queued_revived", "delivered": True})
    except Exception as e:
        logger.error("Failed to revive queen for context: %s", e)

    return web.json_response({"error": "Queen not available"}, status=503)


async def handle_record_user_message(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/record-message — persist a user message
    to the on-disk transcript WITHOUT booting or running the queen.

    For a free/unpaid user answering a queen's question in a read-only,
    never-booted session: the pick must survive reload and be picked up when the
    queen resumes after the user upgrades — but we must spend ZERO compute now.
    Unlike /chat (runs the queen; needs a live session + active plan) and
    /queen-context (queues in-memory; revives the queen), this writes straight
    to disk:

      * appends a user ``Message`` part to ``conversations/parts/`` — what the
        queen replays on resume,
      * appends a ``client_input_received`` line to ``events.jsonl`` — what the
        chat UI renders on reload, and
      * clears ``cursor.pending_input`` so the resumed queen consumes the answer
        (runs a turn on it) instead of re-parking on the same question.

    No live ``Session`` is required: the dir is resolved from disk exactly like
    GET /events/history does, so it works when the queen was never booted.

    Body: {"message": "..."}
    """
    from framework.agent_loop.conversation import (
        Message,
        get_cursor_next_seq,
        update_cursor_next_seq,
    )
    from framework.host.event_bus import AgentEvent, EventType
    from framework.server.session_manager import _find_queen_session_dir
    from framework.storage.conversation_store import FileConversationStore

    session_id = request.match_info["session_id"]
    body = await request.json()
    message = body.get("message", "")
    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    session_dir = _find_queen_session_dir(session_id)
    if not session_dir.exists():
        return web.json_response({"error": "session not found"}, status=404)

    # 1. Append the user message part — what the queen replays on resume.
    convs = session_dir / "conversations"
    await asyncio.to_thread(lambda: convs.mkdir(parents=True, exist_ok=True))
    store = FileConversationStore(convs)

    cursor = await store.read_cursor() or {}
    next_seq = get_cursor_next_seq(cursor)
    if next_seq is None:
        parts = await store.read_parts()
        next_seq = (max(p.get("seq", -1) for p in parts) + 1) if parts else 0

    msg = Message(seq=next_seq, role="user", content=message, is_client_input=True)
    await store.write_part(next_seq, msg.to_storage_dict())

    # Advance next_seq and clear the parked-input wait so the resumed queen
    # answers this message instead of re-asking. agent_loop re-parks only while
    # cursor.pending_input is set with nothing drained; None makes it fall
    # through to a normal turn on the restored conversation (ending in this msg).
    new_cursor = update_cursor_next_seq(cursor, next_seq + 1)
    new_cursor["pending_input"] = None
    await store.write_cursor(new_cursor)

    # 2. Append the UI event — what the chat renders on reload. No live EventBus
    # exists (queen never booted), so write the JSONL line ourselves.
    events_path = session_dir / "events.jsonl"

    def _append_event() -> None:
        # The event seq must exceed every existing one (the renderer sorts and
        # dedupes by seq). File order is NOT seq order, so scan for the max.
        max_seq = -1
        if events_path.exists():
            with open(events_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        seq = json.loads(line).get("seq")
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(seq, int) and seq > max_seq:
                        max_seq = seq
        event = AgentEvent(
            type=EventType.CLIENT_INPUT_RECEIVED,
            stream_id="queen",
            node_id="queen",
            execution_id=session_id,
            data={"content": message, "image_count": 0},
            seq=max_seq + 1,
        )
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    await asyncio.to_thread(_append_event)

    return web.json_response({"status": "recorded", "seq": next_seq})


async def handle_cancel_queen(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/cancel-queen — cancel the queen's current LLM turn.

    Returns 200 in every case (including "no queen to cancel") with
    ``{"cancelled": bool, "error"?: str}``. The frontend treats
    ``cancelled: false`` as a user-facing failure and surfaces the reason;
    keeping a 200 means the client never has to special-case HTTP errors
    that are really application-level signals.
    """
    session, err = resolve_session(request)
    if err:
        return err
    queen_executor = session.queen_executor
    if queen_executor is None:
        return web.json_response({"cancelled": False, "error": "Queen not active"})
    node = queen_executor.node_registry.get("queen")
    if node is None or not hasattr(node, "cancel_current_turn"):
        return web.json_response({"cancelled": False, "error": "Queen node not found"})
    # Mark the user-stop BEFORE issuing the cancel — there's a tiny race
    # where the cancelled stream task can park the loop in USER_STOPPED
    # (firing LOOP_STATE_CHANGED) before this flag flips. Setting it first
    # guarantees the idle-nudge gate sees the flag from the very first
    # tick after the state transition.
    if hasattr(node, "mark_user_stopped"):
        node.mark_user_stopped()
    cancelled_tasks = node.cancel_current_turn()
    # Brief await so the cancellation has actually fired before we respond.
    # Without this, ``cancelled: true`` could return while the LLM HTTP
    # stream is still emitting a token or two. Half a second is plenty;
    # if it takes longer than that, fall through — subsequent events
    # (client_input_requested) will tell the client the queen really stopped.
    if cancelled_tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*cancelled_tasks, return_exceptions=True),
                timeout=0.5,
            )
        except TimeoutError:
            pass

    # Cascade to the colony. Stop means stop: cancelling only the queen's turn
    # used to leave every worker it had dispatched running — burning credits and
    # taking real actions after the user believed everything had halted. Asking
    # the queen to stop them instead can't work either: that runs as a tool call
    # *inside* the very turn we just cancelled. So the stop has to happen here,
    # on the control plane.
    #
    # block_dispatch=True: the queen's turn may still be unwinding and could
    # otherwise spawn workers into the middle of the sweep. Re-opened when the
    # user sends their next message (see Session.resume_dispatch / inject).
    workers: dict[str, Any] = {}
    colony = getattr(session, "colony", None)
    if colony is not None:
        try:
            workers = await colony.stop_workers(block_dispatch=True)
        except Exception as exc:  # never fail the cancel because a worker misbehaved
            logger.exception("cancel-queen: worker cascade failed")
            workers = {"error": str(exc)}

    return web.json_response({"cancelled": True, "workers": workers})


async def handle_session_presence(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/presence — chat re-entry signal.

    Historically lifted an explicit user-stop on re-entry; that contract
    has been removed. A user-cancelled agent now persists its INTERRUPTED
    state until the user sends a real message (``inject_event`` clears
    ``_user_stopped`` server-side). The route is kept for backwards
    compatibility but no longer mutates loop state.
    """
    session, err = resolve_session(request)
    if err:
        return err
    return web.json_response({"ok": True, "resumed": False})


def persist_colony_spawn_lock(session: Any, colony_id: str) -> None:
    """Persist the colony-spawned lock on a queen session.

    Writes ``colony_spawned: true`` + ``spawned_colony_id`` + a timestamp
    into the queen session's ``meta.json`` and mirrors the same fields onto
    the live ``Session`` object so subsequent ``/chat`` calls in this
    process are rejected immediately without disk I/O.

    Shared by the HTTP route ``handle_mark_colony_spawned`` (frontend
    click on the colony-link card) and the source-session lock path
    that runs inside POST /api/sessions when the frontend confirms
    the Create Colony popup.

    Raises ``OSError`` if the meta.json write fails. Callers should catch
    and respond/log appropriately.
    """
    from datetime import datetime as _dt

    queen_dir = getattr(session, "queen_dir", None)
    if queen_dir is None:
        # Tool-side callers may invoke before the queen dir is available.
        # Still mirror onto the session so the in-process /chat guard
        # works; the meta.json write is just deferred until the next
        # session start writes the file (rare path).
        session.colony_spawned = True
        session.spawned_colony_id = colony_id
        return

    meta_path = queen_dir / "meta.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}

    meta["colony_spawned"] = True
    meta["spawned_colony_id"] = colony_id
    meta["spawned_colony_at"] = _dt.now(UTC).isoformat()

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    session.colony_spawned = True
    session.spawned_colony_id = colony_id


async def handle_mark_colony_spawned(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/mark-colony-spawned -- lock the queen DM.

    Called by the frontend the first time the user clicks the
    COLONY_CREATED system message. Thin wrapper around
    :func:`persist_colony_spawn_lock` — the heavy lifting (meta.json
    merge + Session cache) lives in the helper so the source-session
    fork path inside POST /api/sessions can reuse it without
    re-issuing an HTTP call.

    Body: ``{"colony_id": "..."}``
    """
    session, err = resolve_session(request)
    if err:
        return err

    body = await request.json() if request.can_read_body else {}
    colony_id = (body.get("colony_id") or "").strip()
    if not colony_id:
        return web.json_response({"error": "colony_id is required"}, status=400)

    try:
        persist_colony_spawn_lock(session, colony_id)
    except OSError as exc:
        logger.exception("mark_colony_spawned: failed to persist meta.json")
        return web.json_response({"error": f"failed to persist: {exc}"}, status=500)

    return web.json_response(
        {
            "session_id": session.id,
            "colony_spawned": True,
            "spawned_colony_id": colony_id,
        }
    )


async def _compact_queen_conversation_in_place(
    *,
    queen_dir: Any,
    queen_ctx: Any,
    queen_loop: Any,
    inherited_from: str | None = None,
    dest_dir: Any | None = None,
) -> tuple[int, int, str] | None:
    """Compact ``queen_dir/conversations`` into one summary message.

    Reads ``parts/`` via :class:`FileConversationStore`, runs
    :func:`llm_compact` with ``preserve_user_messages=True``, and writes a
    single ``user``-role :class:`Message` (seq 0) tagged with
    ``inherited_from`` when provided, then resets ``cursor.json`` to
    ``next_seq=1``.

    ``dest_dir`` — when None, compacts **in place**: the source
    ``parts/`` + ``partials/`` are wiped and the summary replaces them.
    When given, the source is left untouched and the summary is written
    into ``dest_dir/conversations`` instead — used by the fork path to
    build a fresh session containing ONLY the compacted summary, with no
    raw parts or events copied across.

    ``events.jsonl`` is never touched here.

    Returns ``(messages_compacted, summary_chars, summary_text)`` on
    success, or ``None`` when there is nothing to do (no LLM ctx, no
    conversation directory, or no messages on disk).  Raises on LLM or
    filesystem failure so the caller can decide between user-facing
    error response (compact-and-fork) and silent fall-through (colony
    fork keeps the raw transcript).
    """
    import shutil as _shutil

    from framework.agent_loop.conversation import Message
    from framework.agent_loop.internals.compaction import llm_compact
    from framework.storage.conversation_store import FileConversationStore

    if queen_ctx is None or getattr(queen_ctx, "llm", None) is None:
        return None

    convs_dir = queen_dir / "conversations"
    if not convs_dir.exists():
        return None

    src_store = FileConversationStore(convs_dir)
    raw_parts = await src_store.read_parts()
    messages: list[Message] = []
    for part in raw_parts:
        try:
            messages.append(Message.from_storage_dict(part))
        except (KeyError, TypeError):
            # Skip malformed parts; the summary still covers everything else.
            logger.warning("compact_in_place: skipping malformed part %r", part)
            continue
    if not messages:
        return None

    max_ctx_tokens = 180_000
    loop_cfg = getattr(queen_loop, "_config", None)
    if loop_cfg is not None and getattr(loop_cfg, "max_context_tokens", None):
        max_ctx_tokens = int(loop_cfg.max_context_tokens)

    summary = await llm_compact(
        queen_ctx,
        messages,
        accumulator=None,
        max_context_tokens=max_ctx_tokens,
        preserve_user_messages=True,
    )

    summary_msg = Message(
        seq=0,
        role="user",
        content=summary,
        inherited_from=inherited_from,
    )

    if dest_dir is None:
        # In-place: write the summary FIRST so the store is never empty,
        # then remove stale data. If we crash between these steps the
        # summary survives and restore succeeds.
        target_convs = convs_dir
        dest_store = FileConversationStore(target_convs)
        await dest_store.write_part(0, summary_msg.to_storage_dict())
        await dest_store.write_cursor({"next_seq": 1})
        await dest_store.write_meta({"system_prompt": "", "max_context_tokens": max_ctx_tokens})

        parts_dir = convs_dir / "parts"
        partials_dir = convs_dir / "partials"

        def _cleanup_stale() -> None:
            if parts_dir.exists():
                for f in parts_dir.glob("*.json"):
                    if f.name != "0000000000.json":
                        f.unlink(missing_ok=True)
            if partials_dir.exists():
                _shutil.rmtree(partials_dir)

        await asyncio.to_thread(_cleanup_stale)
    else:
        # Out-of-place: the source is left intact; the summary is the
        # only thing written into the fresh destination.
        target_convs = dest_dir / "conversations"
        await asyncio.to_thread(lambda: target_convs.mkdir(parents=True, exist_ok=True))
        dest_store = FileConversationStore(target_convs)
        await dest_store.write_part(0, summary_msg.to_storage_dict())
        await dest_store.write_cursor({"next_seq": 1})
        await dest_store.write_meta({"system_prompt": "", "max_context_tokens": max_ctx_tokens})

    return (len(messages), len(summary), summary)


async def _write_seed_message(session_dir: Any, content: str) -> None:
    """Write a single seq-0 conversation message into a fresh session dir.

    Used by the fork path to seed the new session with the queen-authored
    handoff brief — its only inherited context. No LLM involved.
    """
    from framework.agent_loop.conversation import Message
    from framework.storage.conversation_store import FileConversationStore

    convs = session_dir / "conversations"
    await asyncio.to_thread(lambda: convs.mkdir(parents=True, exist_ok=True))
    store = FileConversationStore(convs)
    msg = Message(seq=0, role="user", content=content)
    await store.write_part(0, msg.to_storage_dict())
    await store.write_cursor({"next_seq": 1})
    # meta.json is required for NodeConversation.restore() to succeed;
    # without it, the agent loop treats the session as empty and clear()s
    # the seed data before the queen ever reads it.
    await store.write_meta({"system_prompt": "", "max_context_tokens": 180_000})


class ForkSessionError(Exception):
    """Raised by fork_queen_session_for_split when the fork can't proceed.

    Carries an HTTP-compatible status code so the route can map straight
    to web.json_response, while the queen-tool path can read .args[0] as
    a queen-readable error string.
    """

    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.status = status


async def _retire_superseded_session(manager: Any, old_session: Any, new_id: str) -> None:
    """Stop a session's queen loop once it has been forked away from.

    The fork runs synchronously inside the old session's ``task_create``
    tool call, so the queen task must not be cancelled while that call
    is still in flight. We wait for the fork tool's ``TOOL_CALL_COMPLETED``
    — the precise moment the queen task has returned from the fork — then
    stop the session immediately. Stopping here, rather than waiting for
    the whole turn to end (``EXECUTION_COMPLETED``), also skips the
    wasteful post-fork LLM iteration the retired queen would otherwise
    run. A short timeout guards against a missed event.
    """
    from framework.host.event_bus import EventType

    bus = getattr(old_session, "event_bus", None)
    if bus is not None:
        done = asyncio.Event()

        async def _on_tool_done(_ev: Any) -> None:
            done.set()

        sub_id = bus.subscribe([EventType.TOOL_CALL_COMPLETED], _on_tool_done)
        try:
            await asyncio.wait_for(done.wait(), timeout=15.0)
        except TimeoutError:
            logger.warning(
                "retire_superseded_session: %s — no tool-completion within 15s; stopping anyway",
                getattr(old_session, "id", "?"),
            )
        finally:
            try:
                bus.unsubscribe(sub_id)
            except Exception:
                pass

    try:
        await manager.stop_session(old_session.id)
        logger.info("Session '%s' retired (superseded by '%s')", old_session.id, new_id)
    except Exception:
        logger.warning(
            "retire_superseded_session: failed to stop %s",
            getattr(old_session, "id", "?"),
            exc_info=True,
        )


async def fork_queen_session_for_split(
    *,
    session: Any,
    manager: Any,
    publish_event: bool = False,
    tasks: list[dict[str, Any]] | None = None,
    handoff: str | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Fork the queen's current session into a fresh one.

    The new session directory is built from scratch — **nothing is
    copied from the old session**: no raw ``parts/``, no ``events.jsonl``.

    Two modes, discriminated by ``tasks``:

    * ``new_session`` tool path (``tasks`` provided) — the new session
      carries only the queen-authored ``handoff`` brief (one message in
      ``parts/``) plus the seeded task plan. NO LLM compaction runs: the
      handoff is the queen's own distillation, written for free in the
      turn it planned. This keeps the fork fast enough to stay inside a
      tool call's time budget.

    * HTTP ``compact-and-fork`` path (no ``tasks``) — continuing the
      SAME work in a fresh session, so the old conversation IS carried:
      it is compacted via an LLM call and the summary written into the
      new dir. Needs a live queen context with an LLM stamped.

    When ``publish_event=True`` SESSION_FORKED is emitted on the OLD
    session's bus so the frontend swaps silently; the HTTP route passes
    False (its response already carries new_session_id).

    Returns ``{new_session_id, queen_id, compacted_from, summary_chars,
    messages_compacted, task_ids}``. Raises ForkSessionError on failure.
    """
    import time as _time
    from datetime import datetime as _dt

    from framework.agent_loop.types import AgentContext
    from framework.host.event_bus import AgentEvent, EventType
    from framework.server.session_manager import (
        _generate_session_id,
        _queen_session_dir,
    )

    queen_dir = getattr(session, "queen_dir", None)
    if queen_dir is None or not queen_dir.exists():
        raise ForkSessionError("queen session directory not found", status=404)

    # ``tasks`` discriminates the two modes: the new_session tool path
    # always carries a plan; the HTTP compact-and-fork path never does.
    handoff_mode = bool(tasks)

    # The queen context (and its LLM) is only needed to compact — i.e.
    # the HTTP path. The handoff path writes a queen-authored brief and
    # never touches an LLM, so it does not require a running queen ctx.
    queen_node = None
    queen_ctx: AgentContext | None = None
    if not handoff_mode:
        queen_executor = getattr(session, "queen_executor", None)
        if queen_executor is None:
            raise ForkSessionError("queen is not running", status=503)
        queen_node = queen_executor.node_registry.get("queen") if queen_executor else None
        queen_ctx = getattr(queen_node, "_last_ctx", None) if queen_node else None
        if queen_ctx is None or queen_ctx.llm is None:
            raise ForkSessionError(
                ("queen context not yet stamped (no LLM available for compaction). Send a message to the queen and retry."),
                status=503,
            )

    queen_name = session.queen_name or "default"

    new_session_id = _generate_session_id()
    new_dir = _queen_session_dir(new_session_id, queen_name)
    if new_dir.exists():
        # Same-second collision would clobber another session.
        raise ForkSessionError(f"new session dir collision: {new_dir}", status=500)

    # Build the new session dir from scratch — copy NOTHING from the old
    # session. The collision check above already ruled out an existing
    # dir; create it empty.
    try:
        await asyncio.to_thread(lambda: new_dir.mkdir(parents=True, exist_ok=False))
    except OSError as exc:
        logger.exception("fork_queen_session: failed to create new session dir")
        raise ForkSessionError(f"failed to create forked session dir: {exc}", status=500) from exc

    messages_compacted = 0
    summary_chars = 0
    if handoff_mode:
        # No LLM. The new session opens on the queen-authored handoff
        # brief alone — written for free in the turn the queen planned.
        # If none was provided it opens with just the seeded task plan.
        if handoff and handoff.strip():
            await _write_seed_message(new_dir, f"[Session handoff]\n{handoff.strip()}")
    else:
        # HTTP compact-and-fork: continuing the SAME work, so carry the
        # old conversation across as an LLM-compacted summary.
        try:
            result = await _compact_queen_conversation_in_place(
                queen_dir=queen_dir,
                queen_ctx=queen_ctx,
                queen_loop=queen_node,
                dest_dir=new_dir,
            )
        except Exception as exc:
            logger.exception("fork_queen_session: compaction failed")
            raise ForkSessionError(f"compaction failed: {exc}", status=500) from exc
        if result is None:
            raise ForkSessionError(
                "queen conversation is empty -- nothing to compact",
                status=400,
            )
        messages_compacted, summary_chars, _summary_text = result

    # Write a fresh meta.json — provenance only, no old-session state.
    new_meta: dict = {
        "queen_id": queen_name,
        "compacted_from": session.id,
        "created_at": _time.time(),
    }
    if not handoff_mode:
        new_meta["compacted_at"] = _dt.now(UTC).isoformat()
    # Provenance is meta["compacted_from"]; the handoff brief itself is
    # the new session's seq-0 conversation message — no need to also
    # stash it in meta.
    try:
        (new_dir / "meta.json").write_text(json.dumps(new_meta), encoding="utf-8")
    except OSError:
        logger.warning("fork_queen_session: failed to write new meta.json", exc_info=True)

    # Seed the carried task plan into the forked session's list before it
    # goes live, so the new queen resumes onto an existing plan. The dir
    # is fresh — no inherited task list — so ids start at #1. The kickoff
    # prompt takes the resumed session out of restore-mode so the queen
    # works the plan immediately instead of idling; the HTTP
    # compact-and-fork path passes no tasks and keeps restore semantics.
    forked_task_records: list[Any] = []
    kickoff_prompt: str | None = None
    if tasks:
        from framework.tasks import get_task_store

        try:
            forked_task_records = await get_task_store().create_tasks_batch(new_session_id, tasks, goal=goal)
        except Exception as exc:
            logger.exception("fork_queen_session: failed to seed task plan")
            raise ForkSessionError(f"failed to seed task plan: {exc}", status=500) from exc
        # The <hive-internal> tag marks this as a backend-injected
        # directive, not a user message: the queen acts on it, but the
        # frontend (chat-helpers.ts) skips rendering it as a "You" bubble.
        kickoff_prompt = (
            "<hive-internal>\n"
            "This is a fresh session created to carry out a task plan "
            "that has ALREADY been set up for you — call task_list to "
            "see it. Do NOT call task_create, and do NOT start another "
            "new session: the plan already exists and this IS the new "
            "session. Begin immediately — task_update the first task to "
            "in_progress and work straight through the list."
        )

    try:
        new_session = await manager.create_session(
            session_id=None,
            queen_resume_from=new_session_id,
            queen_name=queen_name,
            initial_phase="independent",
            initial_prompt=kickoff_prompt,
        )
    except Exception as exc:
        logger.exception("fork_queen_session: create_session failed for forked id %s", new_session_id)
        raise ForkSessionError(f"failed to start forked session: {exc}", status=500) from exc

    # Retire the OLD session — only on the seeded-plan new_session path
    # (``tasks`` present). The HTTP compact-and-fork route keeps its
    # documented "old session stays alive but locked" contract.
    # Stamp meta.json so restart-resolution skips it, mirror onto the
    # live Session so the /chat guard locks it, and schedule its queen
    # loop to stop once the in-flight turn finishes.
    if tasks:
        # Disarm new_session on the freshly-forked session until its
        # first genuine user message — the synthetic kickoff turn must
        # not fork again (the pivot was already consumed here).
        new_session.fork_kickoff_pending = True

        session.superseded_by = new_session.id
        old_meta_path = queen_dir / "meta.json"
        try:
            old_meta: dict = {}
            if old_meta_path.exists():
                old_meta = json.loads(old_meta_path.read_text(encoding="utf-8"))
            old_meta["superseded_by"] = new_session.id
            old_meta["superseded_at"] = _dt.now(UTC).isoformat()
            old_meta_path.write_text(json.dumps(old_meta), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            logger.warning("fork_queen_session: failed to mark old session superseded", exc_info=True)

        try:
            stop_task = asyncio.create_task(
                _retire_superseded_session(manager, session, new_session.id),
                name=f"retire-{session.id}",
            )
            bg = getattr(manager, "_background_tasks", None)
            if bg is not None:
                bg.add(stop_task)
                stop_task.add_done_callback(bg.discard)
        except RuntimeError:
            logger.warning("fork_queen_session: could not schedule old-session stop", exc_info=True)

        # Announce the seeded plan on the NEW session's bus. The tasks
        # were written straight to tasks.json (before the session went
        # live) so no task_created events fired — without these the
        # Action Plan panel only learns the plan via a REST snapshot and
        # the forked session's plan never propagates live. Emitting here,
        # after the bus exists, lands them in the new session's
        # events.jsonl; with TASK_* in the SSE replay set the panel
        # populates the moment the user is swapped over.
        if forked_task_records:
            from framework.tasks.events import emit_task_created

            new_bus = getattr(new_session, "event_bus", None)
            for rec in forked_task_records:
                try:
                    await emit_task_created(
                        session_id=new_session_id,
                        record=rec,
                        bus=new_bus,
                    )
                except Exception:
                    logger.warning(
                        "fork_queen_session: failed to emit seeded task_created",
                        exc_info=True,
                    )

    if publish_event:
        # Fire on the OLD session's bus — that's the bus the desktop is
        # currently subscribed to. The handler in queen-dm.tsx flips the
        # URL ?session= param, which silently reconnects SSE to the new id.
        try:
            old_bus = getattr(session, "event_bus", None)
            if old_bus is not None:
                await old_bus.publish(
                    AgentEvent(
                        type=EventType.SESSION_FORKED,
                        stream_id="queen",
                        data={
                            "new_session_id": new_session.id,
                            "queen_id": queen_name,
                            "from_session_id": session.id,
                            "handoff": (handoff or "").strip(),
                        },
                    )
                )
        except Exception:
            # Event publish is best-effort — the new session exists and
            # the queen tool will still report success. The user just
            # won't see the silent swap, which is degraded UX but not
            # a correctness bug.
            logger.warning("fork_queen_session: failed to publish SESSION_FORKED", exc_info=True)

    return {
        "new_session_id": new_session.id,
        "queen_id": queen_name,
        "compacted_from": session.id,
        "summary_chars": summary_chars,
        "messages_compacted": messages_compacted,
        "task_ids": [r.id for r in forked_task_records],
    }


async def handle_compact_and_fork(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/compact-and-fork -- compact + new session.

    The locked-by-colony-spawn UI calls this when the user clicks "compact
    + start a new session with the same queen". Delegates to the shared
    ``fork_queen_session_for_split`` helper. The HTTP response already
    carries ``new_session_id`` so the frontend handler calls setSearchParams
    directly — we do NOT publish SESSION_FORKED here to avoid double-firing
    the UI swap.

    The OLD session stays alive but locked; the user navigates to the
    new session via the response.
    """
    session, err = resolve_session(request)
    if err:
        return err

    manager: Any = request.app["manager"]
    try:
        result = await fork_queen_session_for_split(
            session=session,
            manager=manager,
            publish_event=False,
        )
    except ForkSessionError as exc:
        return web.json_response({"error": str(exc)}, status=exc.status)

    return web.json_response(result)


async def _compact_inherited_conversation(
    *,
    dest_queen_dir: Any,
    queen_ctx: Any,
    queen_loop: Any,
    source_session_id: str,
) -> None:
    """Compact a freshly-forked colony's inherited transcript in place.

    Thin wrapper over :func:`_compact_queen_conversation_in_place` that
    tags the resulting summary message with ``inherited_from`` and
    appends a ``colony_fork_marker`` event to the colony's
    ``events.jsonl`` so the frontend can group + collapse everything
    that preceded the fork.

    Called from ``fork_session_into_colony`` after the parent queen
    session directory has been copied into the colony's queue dir.

    Fail-soft: any exception (compaction, write, marker append) logs a
    warning and leaves the directory as the raw copytree wrote it.  The
    colony still works; it just inherits the full DM transcript instead
    of the summary.
    """
    import json as _json
    from datetime import UTC as _UTC, datetime as _datetime

    try:
        result = await _compact_queen_conversation_in_place(
            queen_dir=dest_queen_dir,
            queen_ctx=queen_ctx,
            queen_loop=queen_loop,
            inherited_from=source_session_id,
        )
    except Exception:
        logger.warning(
            "compact_inherited: compaction failed; leaving raw transcript",
            exc_info=True,
        )
        return

    if result is None:
        # No queen ctx, no parts on disk, or empty conversation. Nothing
        # to compact and nothing to mark — the colony will just open with
        # an empty chat (or whatever raw state was copied).
        logger.info(
            "compact_inherited: nothing to compact for colony forked from %s",
            source_session_id,
        )
        return

    messages_compacted, summary_chars, summary_text = result

    # Append the boundary marker to the colony's events.jsonl so the
    # frontend can group + collapse everything that came before.  The
    # marker carries the parent session id and a short summary preview
    # so the collapsed widget has something to label itself with even
    # before the user expands it.
    fork_iso = _datetime.now(_UTC).isoformat()
    marker = {
        "type": "colony_fork_marker",
        "stream_id": "queen",
        "data": {
            "parent_session_id": source_session_id,
            "fork_time": fork_iso,
            "summary_preview": summary_text[:240],
            "inherited_message_count": messages_compacted,
        },
        "timestamp": fork_iso,
    }
    events_path = dest_queen_dir / "events.jsonl"

    def _append_marker() -> None:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(marker) + "\n")

    try:
        await asyncio.to_thread(_append_marker)
    except OSError:
        logger.warning("compact_inherited: failed to append fork marker", exc_info=True)

    logger.info(
        "compact_inherited: compacted %d parent message(s) -> 1 summary (%d chars) for colony forked from %s",
        messages_compacted,
        summary_chars,
        source_session_id,
    )


async def fork_session_into_colony(
    *,
    session: Any,
    colony_id: str,
    task: str,
    tasks: list[dict] | None = None,
    concurrency_hint: int | None = None,
    worker_profiles: list[dict] | None = None,
) -> dict:
    """Fork a queen session into a colony directory.

    Driven by ``_create_colony_from_source`` in routes_sessions.py, which
    is invoked by POST /api/sessions when the frontend's "Create Colony"
    popup confirms a fork (triggered by the queen's ``suggest_colony``
    tool). The caller is responsible for validating ``colony_id``
    against the lowercase-alphanumeric regex.

    The fork:
    1. Creates a colony directory with a single worker config (``worker.json``)
       holding the queen's current tools, prompts, skills, and loop config.
    2. Duplicates the queen's full session (conversations + events) into a new
       queen-session directory assigned to the colony so that cold-restoring
       the colony resumes with the queen's entire conversation history.
    3. Multiple independent sessions can be created against the same colony,
       giving parallel execution capacity without separate worker configs.
    4. Initializes (or ensures) ``tracker/tracker.db`` — the colony's
       SQLite tracker. The :class:`ColonyBinding` for this colony is threaded
       into the worker's ``input_data`` so spawned workers see it in
       their first user message; the queen's own execution context is
       also re-stamped with the binding so her tracker tools target the
       real DB from this point on.

    Returns ``{"colony_path", "colony_id", "queen_session_id",
              "is_new", "compaction_status"}``.
    """
    import asyncio
    import json
    import shutil
    from datetime import datetime

    from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
    from framework.agent_loop.types import AgentContext
    from framework.host.tracker_db import ensure_tracker_db
    from framework.server.session_manager import _queen_session_dir

    # Diagnostic capture: when the fork fails here we want to know which
    # piece of queen state was missing (executor cleared vs. node missing
    # vs. _last_ctx never stamped). Without this, callers only see
    # "'NoneType' object has no attribute 'node_registry'" with no hint
    # whether the queen loop exited, is mid-revive, or ran a different
    # path that never ran AgentLoop._execute_impl.
    queen_executor = getattr(session, "queen_executor", None)
    queen_task = getattr(session, "queen_task", None)
    phase_state_dbg = getattr(session, "phase_state", None)
    logger.info(
        "[fork_session_into_colony] session=%s colony=%s queen_executor=%s queen_task=%s queen_task_done=%s phase=%s queen_name=%s",
        session.id,
        colony_id,
        queen_executor,
        queen_task,
        queen_task.done() if queen_task is not None else None,
        getattr(phase_state_dbg, "phase", None),
        getattr(session, "queen_name", None),
    )

    if queen_executor is None:
        raise RuntimeError(
            f"queen_executor is None for session {session.id!r} — the "
            "queen loop isn't running right now. Wait for the queen to "
            "come back (or send her a chat message to revive her) and "
            "retry the colony fork."
        )

    node_registry = getattr(queen_executor, "node_registry", None)
    if not isinstance(node_registry, dict) or "queen" not in node_registry:
        raise RuntimeError(
            f"queen node is missing from the executor's registry for "
            f"session {session.id!r} (registry keys="
            f"{list(node_registry.keys()) if isinstance(node_registry, dict) else type(node_registry).__name__}"
            "). The queen loop is in an initialization or teardown "
            "window; retry after a moment."
        )

    queen_loop: AgentLoop = node_registry["queen"]
    queen_ctx: AgentContext = getattr(queen_loop, "_last_ctx", None)
    if queen_ctx is None:
        logger.warning(
            "[fork_session_into_colony] queen_loop has no _last_ctx yet "
            "(session=%s) — falling back to empty tool/skill snapshot; "
            "the forked worker will inherit no tools.",
            session.id,
        )

    # "is_new" keys off worker.json, not bare dir existence: callers may
    # have pre-created colony_dir to materialize colony-scoped artefacts
    # (skill folder, etc.) BEFORE the fork, which would wrongly flag
    # every fresh colony as "already-exists" if we used
    # ``not colony_dir.exists()``. A colony is "new" until its worker
    # config has actually been written.
    from framework.config import COLONIES_DIR

    colony_dir = COLONIES_DIR / colony_id
    worker_name = "worker"
    worker_config_path = colony_dir / f"{worker_name}.json"
    is_new = not worker_config_path.exists()
    colony_dir.mkdir(parents=True, exist_ok=True)

    # ── 0. Ensure the colony's tracker DB exists ──────────────────────
    # Runs before worker.json is written so the DB path can be threaded
    # into input_data. Idempotent on reruns of the same colony name.
    tracker_db_path = await asyncio.to_thread(ensure_tracker_db, colony_dir)

    # Fixed worker name and config path are already computed above so
    # ``is_new`` can be derived from worker.json rather than the colony
    # directory (see comment on the ``is_new`` block).

    # ── 1. Gather queen state ─────────────────────────────────────
    # Queen-lifecycle + agent-management tools are registered ONLY against
    # the queen's runtime (they need a live session + phase_state to
    # operate). Forking them into a worker config makes the worker fail
    # tool validation when its own runtime loads because those tools
    # aren't registered there. Strip them out of the snapshot.
    #
    # The blacklist is derived from the queen phase tool lists: any tool
    # that appears in any _QUEEN_*_TOOLS list but is NOT in the worker's
    # "work-doing" whitelist (file I/O + shell + undo) is queen-only.
    # This stays in sync automatically when new queen tools are added.
    queen_only_tools = _resolve_queen_only_tools()
    queen_tools: list = queen_ctx.available_tools if queen_ctx else []
    tool_names = [t.name for t in queen_tools if t.name not in queen_only_tools]

    phase_state = getattr(session, "phase_state", None)

    # Skills + protocols ARE inherited by the worker so it knows how to
    # use tools and follow operational conventions. These are NOT queen
    # identity data -- they are runtime-neutral guides.
    queen_skills_catalog = queen_ctx.skills_catalog_prompt if queen_ctx else ""
    queen_protocols = queen_ctx.protocols_prompt if queen_ctx else ""
    queen_skill_dirs = queen_ctx.skill_dirs if queen_ctx else []

    # ── 2. Build + write worker.json ────────────────────────────
    # The worker spec lives in ``agents.queen.worker_definition`` —
    # that module is the single source of truth for both the runtime
    # identity (Goal, prompt, loop config defaults) and the on-disk
    # serialization format (worker.json dict). Per-profile clones
    # below build off ``dict(worker_meta)`` so any future field
    # addition lands once. identity_prompt + memory_prompt are
    # intentionally empty (worker is a task executor, not the queen)
    # and the system prompt teaches report_to_parent / fail-fast /
    # attached-skills / tracker conventions inside
    # ``worker_definition.build_system_prompt``.
    from framework.agents.queen.worker_definition import (
        build_input_data,
        build_meta,
    )
    from framework.host.colony_binding import ColonyBinding

    binding = ColonyBinding(
        name=colony_id,
        dir=colony_dir,
        tracker_db=tracker_db_path,
    )
    _worker_input_data = build_input_data(binding=binding)

    queen_config: LoopConfig | None = getattr(queen_loop, "_config", None)
    worker_task = task or "Continue the work from the queen's current session."

    worker_meta = build_meta(
        worker_name=worker_name,
        source_session_id=session.id,
        task=task,
        tool_names=tool_names,
        skills_catalog_prompt=queen_skills_catalog,
        protocols_prompt=queen_protocols,
        skill_dirs=list(queen_skill_dirs),
        queen_loop_config=queen_config,
        queen_phase=phase_state.phase if phase_state else "",
        queen_id=getattr(phase_state, "queen_id", "") if phase_state else "",
        input_data=_worker_input_data,
        concurrency_hint=concurrency_hint,
    )
    worker_config_path.write_text(json.dumps(worker_meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 2a. Materialize named worker profiles ────────────────────
    # Each named profile gets its own ``profiles/<name>/worker.json``
    # cloned from the base worker_meta with profile-specific overrides
    # (task, system_prompt, tool_filter, concurrency_hint). The base
    # ``worker.json`` above acts as the implicit "default" profile.
    persisted_profiles: list[dict] = []
    if worker_profiles:
        from framework.host.worker_profiles import (
            DEFAULT_PROFILE_NAME,
            WorkerProfile,
            validate_profile_name,
            worker_spec_path,
        )

        for raw in worker_profiles:
            if not isinstance(raw, dict):
                continue
            profile = WorkerProfile.from_dict(raw)
            err = validate_profile_name(profile.name)
            if err is not None:
                logger.warning("fork_session_into_colony: invalid profile name %r: %s", profile.name, err)
                continue
            profile_meta = dict(worker_meta)
            profile_meta["profile_name"] = profile.name
            if profile.task:
                profile_meta["goal"] = {
                    **profile_meta.get("goal", {}),
                    "description": profile.task,
                }
            if profile.prompt_override:
                profile_meta["system_prompt"] = f"{worker_meta['system_prompt']}\n\n{profile.prompt_override}"
            if profile.tool_filter:
                profile_meta["tools"] = [t for t in worker_meta["tools"] if t in set(profile.tool_filter)]
            if isinstance(profile.concurrency_hint, int) and profile.concurrency_hint > 0:
                profile_meta["concurrency_hint"] = profile.concurrency_hint
            if profile.integrations:
                profile_meta["integrations"] = dict(profile.integrations)

            target = worker_spec_path(colony_id, profile.name)
            if profile.name == DEFAULT_PROFILE_NAME:
                # Skip — the legacy file already written above is the
                # canonical default.
                persisted_profiles.append(profile.to_dict())
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(profile_meta, indent=2, ensure_ascii=False), encoding="utf-8")
            persisted_profiles.append(profile.to_dict())

    # ── 3. Duplicate queen session into colony ───────────────────
    # Copy the queen's full session directory (conversations, events,
    # meta) into a new queen-session dir assigned to this colony.
    # This is the "brain fork" -- the colony queen starts with the
    # full conversation history from the originating session.
    #
    # session.queen_dir is authoritative -- queen_orchestrator relocates
    # it from default/ to the selected queen's dir on identity selection.
    source_queen_dir = session.queen_dir
    # Extract queen identity from the dir path: .../queens/{name}/sessions/xxx
    queen_name = source_queen_dir.parent.parent.name if source_queen_dir and source_queen_dir.exists() else (session.queen_name or "default")

    # Generate a colony-specific session ID so the colony has its own
    # session identity while preserving the full conversation.
    from framework.server.session_manager import _generate_session_id

    colony_session_id = _generate_session_id()
    # Write the forked overseer session to its canonical colony-tree home
    # (colonies/<c>/queens/<q>/sessions/<sid>/). Passing colony_id here
    # ensures the fork copy, downstream in-place compaction, and the later
    # _start_queen write all target the same directory — so one session_id
    # never maps to two physical dirs.
    dest_queen_dir = _queen_session_dir(colony_session_id, queen_name, colony_id=colony_id)

    if source_queen_dir.exists():
        await asyncio.to_thread(shutil.copytree, source_queen_dir, dest_queen_dir, dirs_exist_ok=True)
        # Update the duplicated meta.json to point to the colony
        dest_meta_path = dest_queen_dir / "meta.json"
        dest_meta: dict = {}
        if dest_meta_path.exists():
            try:
                dest_meta = json.loads(dest_meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        dest_meta["agent_path"] = str(colony_dir)
        dest_meta["agent_name"] = humanize_slug(colony_id)
        dest_meta["queen_id"] = queen_name
        dest_meta["forked_from"] = session.id
        dest_meta["colony_fork"] = True  # exclude from queen DM history
        # Clear any colony_spawned lock that came over from the parent meta —
        # it was the PARENT session that locked, not this freshly-forked one.
        dest_meta.pop("colony_spawned", None)
        dest_meta.pop("spawned_colony_id", None)
        dest_meta.pop("spawned_colony_at", None)
        dest_meta_path.write_text(json.dumps(dest_meta, ensure_ascii=False), encoding="utf-8")
        logger.info(
            "Duplicated queen session %s -> %s for colony '%s'",
            session.id,
            colony_session_id,
            colony_id,
        )

        # ── 3a. Compact the inherited conversation (fire-and-forget) ──
        # The colony queen doesn't need the full DM transcript — that
        # transcript was about REACHING the decision to fork, which is
        # now settled. Compaction replaces the copied parts with a
        # single summary message tagged ``inherited_from``.
        #
        # Compaction issues an LLM call that can legitimately exceed
        # the 60s tool-call timeout, so we schedule it (plus the
        # downstream worker-storage copy) as a background task and
        # return immediately. A compaction_status.json marker in
        # dest_queen_dir lets a subsequent colony session-load await
        # completion before reading the conversation files (see
        # session_manager.create_session_with_worker_colony).
        #
        # Fail-soft: any exception is logged and recorded in the
        # marker; the colony still works with the raw transcript.
        from framework.server import compaction_status

        compaction_status.mark_in_progress(dest_queen_dir)

        # v3: seed conversation lives next to the colony, not under a
        # parallel ``agents/<colony>/worker/`` tree.
        from framework.config import colony_seed_conversation_dir

        _seed_conv_dir = colony_seed_conversation_dir(colony_id)
        _dest_queen_dir = dest_queen_dir
        _queen_ctx = queen_ctx
        _queen_loop = queen_loop
        _source_session_id = session.id

        # Wall-clock cap on the background compaction's LLM call.
        # Without this a hung/misbehaving model (seen with local
        # endpoints) leaves compaction_status="in_progress" forever and
        # the colony-open await_completion waste its full poll window
        # before giving up. When this fires we still fall through to
        # the worker-storage copy below so the colony opens with the
        # raw transcript instead of empty state.
        _COMPACTION_TIMEOUT_SECONDS = 180.0

        async def _finalize_fork() -> None:
            compaction_error: str | None = None
            try:
                await asyncio.wait_for(
                    _compact_inherited_conversation(
                        dest_queen_dir=_dest_queen_dir,
                        queen_ctx=_queen_ctx,
                        queen_loop=_queen_loop,
                        source_session_id=_source_session_id,
                    ),
                    timeout=_COMPACTION_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                compaction_error = f"compaction timed out after {_COMPACTION_TIMEOUT_SECONDS:.0f}s (falling back to raw transcript)"
                logger.warning(
                    "fork_session_into_colony: %s for %s",
                    compaction_error,
                    _dest_queen_dir,
                )
            except Exception as exc:
                compaction_error = f"compaction failed: {exc}"
                logger.warning(
                    "fork_session_into_colony: %s for %s (falling back to raw transcript)",
                    compaction_error,
                    _dest_queen_dir,
                    exc_info=True,
                )

            # Seed-conversation copy runs regardless of the compaction
            # outcome. If compaction succeeded, the worker gets the
            # summary; if it failed / timed out, dest_queen_dir still
            # has the raw transcript from the earlier copytree and the
            # worker gets that. Without this copy-on-failure the worker
            # would open to empty state on every compaction hiccup.
            try:
                _seed_conv_dir.mkdir(parents=True, exist_ok=True)
                source_conv_dir = _dest_queen_dir / "conversations"
                if source_conv_dir.exists():
                    await asyncio.to_thread(
                        shutil.copytree,
                        source_conv_dir,
                        _seed_conv_dir,
                        dirs_exist_ok=True,
                    )
                    logger.info(
                        "Copied queen conversations to colony seed_conversation %s",
                        _seed_conv_dir,
                    )
            except Exception:
                logger.warning(
                    "fork_session_into_colony: seed-conversation copy failed for %s",
                    _seed_conv_dir,
                    exc_info=True,
                )

            if compaction_error:
                compaction_status.mark_failed(_dest_queen_dir, compaction_error)
            else:
                compaction_status.mark_done(_dest_queen_dir)

        _bg_task = asyncio.create_task(_finalize_fork())
        _BACKGROUND_FORK_TASKS.add(_bg_task)
        _bg_task.add_done_callback(_BACKGROUND_FORK_TASKS.discard)
    else:
        logger.warning(
            "Queen session dir %s not found, colony will start fresh",
            source_queen_dir,
        )

    # ── 4. Write metadata.json (queen provenance) ────────────────
    metadata_path = colony_dir / "metadata.json"
    metadata: dict = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    metadata["colony_id"] = colony_id
    metadata["queen_name"] = queen_name
    metadata["queen_session_id"] = colony_session_id
    metadata["source_session_id"] = session.id
    metadata.setdefault("created_at", datetime.now(UTC).isoformat())
    metadata["updated_at"] = datetime.now(UTC).isoformat()
    # Concurrency cap chosen at fork time. Promoted from the per-worker
    # advisory metadata to a colony-level setting because the runtime
    # uses it as the actual semaphore for parallel-worker scheduling.
    # ColonyRuntime reads ``max_concurrent_workers`` on session start;
    # values are clamped to a safety range to prevent a misconfigured
    # colony saturating resources. Default (None / not set) falls back
    # to the framework default in ColonyConfig.
    if isinstance(concurrency_hint, int) and concurrency_hint > 0:
        # Clamp to [1, 32]. Above 32 is almost certainly a configuration
        # mistake on a single-machine deployment; users who actually need
        # more should bump the env-controlled framework default.
        clamped = max(1, min(32, concurrency_hint))
        metadata["max_concurrent_workers"] = clamped
        if clamped != concurrency_hint:
            logger.info(
                "fork_session_into_colony: clamped concurrency_hint %d → %d for colony '%s'",
                concurrency_hint,
                clamped,
                colony_id,
            )
    metadata.setdefault("workers", {})
    metadata["workers"][worker_name] = {
        "task": worker_task[:100],
        "spawned_at": datetime.now(UTC).isoformat(),
    }
    if persisted_profiles:
        # Persist the canonical profile roster so dispatch + UI can read
        # back what the queen declared at create_colony time. Merge with
        # any existing list so a later update_worker_profile call doesn't
        # erase profiles created in an earlier fork.
        existing_profiles = metadata.get("worker_profiles") or []
        if not isinstance(existing_profiles, list):
            existing_profiles = []
        seen = {p["name"] for p in persisted_profiles if isinstance(p, dict) and p.get("name")}
        merged = list(persisted_profiles) + [p for p in existing_profiles if isinstance(p, dict) and p.get("name") and p["name"] not in seen]
        metadata["worker_profiles"] = merged
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 4a. Inherit the queen's tool allowlist into the colony ───
    # A colony forked from a curated queen should start with the same
    # tool surface (otherwise the colony silently falls back to its own
    # "allow every MCP tool" default, undoing the parent's curation).
    # We copy the queen's LIVE effective allowlist so the snapshot
    # reflects whatever was in force the moment the user clicked "Create
    # Colony". Users can further narrow the colony via the Tool Library.
    # Skip the write when the queen is on allow-all (None) so the colony
    # keeps the same semantics without creating an inert sidecar.
    try:
        queen_enabled = getattr(
            getattr(session, "phase_state", None),
            "enabled_mcp_tools",
            None,
        )
        if isinstance(queen_enabled, list):
            from framework.host.colony_tools_config import update_colony_tools_config

            update_colony_tools_config(colony_id, list(queen_enabled))
            logger.info(
                "Inherited queen allowlist into colony '%s' (%d tools)",
                colony_id,
                len(queen_enabled),
            )
    except Exception:
        # Inheritance is best-effort — don't let a tools.json hiccup
        # abort colony creation.
        logger.warning(
            "Failed to inherit queen allowlist into colony '%s'",
            colony_id,
            exc_info=True,
        )

    # ── 5. Update source queen session meta.json ─────────────────
    # Link the originating session back to the colony for discovery.
    source_meta_path = source_queen_dir / "meta.json"
    if source_meta_path.exists():
        try:
            qmeta = json.loads(source_meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            qmeta = {}
    else:
        qmeta = {}
    qmeta["agent_path"] = str(colony_dir)
    qmeta["agent_name"] = humanize_slug(colony_id)
    try:
        source_meta_path.parent.mkdir(parents=True, exist_ok=True)
        source_meta_path.write_text(json.dumps(qmeta, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

    # ── 6. Re-stamp the queen's execution context with the colony binding ──
    # Up to this point in the queen's life she has no binding (her DM
    # session is not a colony). Now that the on-disk colony exists, any
    # subsequent ``tracker_*`` call from the queen must target the
    # colony's DB. When ``fork_session_into_colony`` is invoked from the
    # queen's own ``create_colony`` tool (the common path), this function
    # runs inside the queen's asyncio task, so the ContextVar update
    # persists for the rest of the queen's life. The HTTP-driven path
    # also stamps ``session.binding`` so the queen's loop picks it up on
    # next start.
    from framework.loader.tool_registry import ToolRegistry

    ToolRegistry.set_execution_context(binding=binding)
    session.binding = binding
    session.colony_id = colony_id

    logger.info(
        "Forked queen to colony '%s' (new=%s, tools=%d, session=%s)",
        colony_id,
        is_new,
        len(queen_tools),
        colony_session_id,
    )
    return {
        "colony_path": str(colony_dir),
        "colony_id": colony_id,
        "queen_session_id": colony_session_id,
        "is_new": is_new,
        # "in_progress" when a background compactor was scheduled above,
        # "skipped" when the source queen dir was missing (nothing to
        # compact). Frontend uses this to decide whether to display a
        # "preparing colony…" state while session-load blocks on the
        # compaction marker.
        "compaction_status": ("in_progress" if source_queen_dir.exists() else "skipped"),
    }


def register_routes(app: web.Application) -> None:
    """Register execution control routes."""
    # Session-primary routes
    app.router.add_post("/api/sessions/{session_id}/chat", handle_chat)
    app.router.add_post("/api/sessions/{session_id}/queen-context", handle_queen_context)
    app.router.add_post("/api/sessions/{session_id}/record-message", handle_record_user_message)
    app.router.add_post("/api/sessions/{session_id}/cancel-queen", handle_cancel_queen)
    app.router.add_post("/api/sessions/{session_id}/presence", handle_session_presence)
    app.router.add_post(
        "/api/sessions/{session_id}/mark-colony-spawned",
        handle_mark_colony_spawned,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/compact-and-fork",
        handle_compact_and_fork,
    )
