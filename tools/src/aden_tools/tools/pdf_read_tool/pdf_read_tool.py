"""PDF read tool — extract text and metadata from PDFs.

Reads local or HTTP(S)-hosted PDFs via pdfplumber (better text + table
extraction than pypdf), supports single- or multi-file batching, page-range
filtering, optional decryption, and a byte cap on URL downloads. Each page's
text length is checked against a minimum threshold; pages below it are flagged
``needs_vision`` so a downstream caller knows the page is probably scanned and
should be reprocessed via the vision-fallback sidecar (or rasterized).

Stays strictly a text extractor — no LLM calls, no image rendering. Vision
needs are signalled, not handled.
"""

from __future__ import annotations

import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
import pdfplumber
from fastmcp import FastMCP

# Caps and thresholds — match the upload-path defaults so a PDF that's
# accepted via chat upload is also accepted via direct tool call.
_MAX_PDFS = 10
_DEFAULT_MAX_PAGES = 100
_HARD_MAX_PAGES = 1000
_DEFAULT_MAX_BYTES_MB = 25.0
# pdfminer (pdfplumber's backend) returns short strings on scanned/empty
# pages — anything under this means the agent should treat the page as
# vision-needed rather than as having "extracted nothing useful."
_VISION_TEXT_THRESHOLD = 200
# Fail-fast budget for pdfplumber. The framework's tool-call ceiling is
# 60s; we leave ~40s of headroom so a stuck pdfplumber can't burn the
# whole tool slot. On expiry pdf_read yields a structured response that
# steers the agent toward terminal_exec + pdftotext/pdfinfo as a fallback.
_PDF_EXTRACT_TIMEOUT_SECONDS = 20.0

# Cheatsheet of fallback terminal commands for the yield response. Kept
# in one constant so the agent sees the same text whether it timed out,
# the PDF was scanned, or pdfplumber failed to open at all.
_TERMINAL_HINT = (
    "pdfplumber couldn't extract this PDF — fall through to terminal_exec "
    "for one of these (poppler-utils is installed on the desktop runtime):\n"
    "  pdftotext '<path>' - | head -200        text extraction (whole file)\n"
    "  pdftotext -f 5 -l 10 '<path>' -          specific page range\n"
    "  pdfinfo '<path>'                        page count + metadata\n"
    "  pdfimages -list '<path>'                image inventory (scanned docs)\n"
    "  pdfgrep -p '<pattern>' '<path>'         pattern search\n"
    "Pipe to head/grep to keep tool-result size bounded."
)


def _terminal_next_step(reason: str, path: Path | str) -> str:
    """Single most-promising next call for the agent based on failure reason."""
    p = str(path)
    if reason == "pdf_extract_timeout":
        return f"terminal_exec: pdftotext '{p}' - | head -200"
    if reason == "pdf_open_failed":
        # pdfinfo probes the file structurally and prints the real error.
        return f"terminal_exec: pdfinfo '{p}'"
    if reason == "pdf_encrypted":
        return f"terminal_exec: qpdf --decrypt --password=<pw> '{p}' /tmp/decrypted.pdf (then call pdf_read again on /tmp/decrypted.pdf)"
    if reason == "pdf_extract_empty":
        return f"attach_file(paths='{p}') — scanned PDFs read directly on vision models. For non-vision: terminal_exec pdfimages + tesseract."
    return f"terminal_exec: pdfinfo '{p}'"


def _yield_to_terminal(
    path: Path | str,
    *,
    reason: str,
    elapsed_s: float | None = None,
    page_count: int | None = None,
) -> dict[str, Any]:
    """Structured fallback response — pdf_read couldn't get a quick win,
    so it yields with terminal-tool hints so the agent can route through
    `terminal_exec`. The agent's next_step is one concrete call to try.
    """
    out: dict[str, Any] = {
        "error": reason,
        "path": str(path),
        "next_step": _terminal_next_step(reason, path),
        "terminal_hint": _TERMINAL_HINT,
    }
    if elapsed_s is not None:
        out["elapsed_seconds"] = round(elapsed_s, 1)
    if page_count is not None:
        out["page_count"] = page_count
    return out


# SSRF deny-list. pdf_read is callable by an agent with an arbitrary URL,
# so we refuse to fetch from loopback / link-local / RFC1918 ranges to
# avoid being used to probe internal services. Best-effort string match —
# DNS rebinding is out of scope (we'd need to resolve once and pin the
# IP, which is heavier than this tool warrants).
_PRIVATE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_PRIVATE_PREFIXES = (
    "127.",
    "10.",
    "192.168.",
    "169.254.",
    *(f"172.{i}." for i in range(16, 32)),
)


def _is_private_url(url: str) -> bool:
    """Reject URLs that resolve obviously to private/loopback hosts."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in _PRIVATE_HOSTS:
        return True
    return any(host.startswith(p) for p in _PRIVATE_PREFIXES)


def parse_page_range(
    pages: str | None,
    total_pages: int,
    max_pages: int,
) -> dict[str, Any]:
    """Parse page-range string into 0-indexed page numbers.

    Returns one of:
      {"indices": [...], "truncated": bool, "requested_pages": int}
      {"error": "..."}
    """
    if pages is None or pages.lower() == "all":
        requested = total_pages
        limited = min(total_pages, max_pages)
        return {
            "indices": list(range(limited)),
            "truncated": requested > max_pages,
            "requested_pages": requested,
        }

    try:
        if pages.isdigit():
            n = int(pages)
            if n < 1 or n > total_pages:
                return {"error": f"Page {n} out of range. PDF has {total_pages} pages."}
            return {"indices": [n - 1], "truncated": False, "requested_pages": 1}

        if "-" in pages and "," not in pages:
            start_str, end_str = pages.split("-", 1)
            start, end = int(start_str), int(end_str)
            if start > end:
                return {"error": f"Invalid page range: {pages}. Start must be less than end."}
            if start < 1:
                return {"error": f"Page numbers start at 1, got {start}."}
            if end > total_pages:
                return {"error": f"Page {end} out of range. PDF has {total_pages} pages."}
            requested = end - start + 1
            limited_end = min(end, start - 1 + max_pages)
            return {
                "indices": list(range(start - 1, limited_end)),
                "truncated": requested > max_pages,
                "requested_pages": requested,
            }

        if "," in pages:
            nums = [int(p.strip()) for p in pages.split(",")]
            for n in nums:
                if n < 1 or n > total_pages:
                    return {"error": f"Page {n} out of range. PDF has {total_pages} pages."}
            return {
                "indices": [n - 1 for n in nums[:max_pages]],
                "truncated": len(nums) > max_pages,
                "requested_pages": len(nums),
            }

        return {"error": f"Invalid page format: '{pages}'. Use 'all', '5', '1-10', or '1,3,5'."}

    except ValueError as e:
        return {"error": f"Invalid page format: '{pages}'. {e!s}"}


def _download_pdf(url: str, max_bytes: int) -> tuple[Path | None, dict | None]:
    """Download a PDF URL to a temp file. Returns (path, None) on success
    or (None, error_dict) on failure. Caller is responsible for unlinking
    the returned path.
    """
    if _is_private_url(url):
        return None, {"error": f"URL refused (private/loopback host): {url}"}

    try:
        response = httpx.get(
            url,
            headers={"User-Agent": "AdenBot/1.0 (PDF Reader)"},
            follow_redirects=True,
            timeout=60.0,
        )
    except httpx.TimeoutException:
        return None, {"error": "PDF download timed out"}
    except httpx.RequestError as e:
        return None, {"error": f"Failed to download PDF: {e!s}"}

    if response.status_code != 200:
        return None, {"error": f"Failed to download PDF: HTTP {response.status_code}"}

    content_type = (response.headers.get("content-type") or "").lower()
    if "application/pdf" not in content_type:
        return None, {
            "error": f"URL does not point to a PDF file. Content-Type: {content_type}",
            "content_type": content_type,
            "url": url,
        }

    # Header check (when present) lets us reject huge files without
    # touching the body — but httpx already downloaded into memory by
    # this point, so the post-check on response.content is the real cap.
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        return None, {
            "error": (f"PDF exceeds max_bytes ({int(declared)} > {max_bytes}). Increase max_bytes_mb or use a smaller PDF."),
        }
    if len(response.content) > max_bytes:
        return None, {
            "error": (f"PDF exceeds max_bytes ({len(response.content)} > {max_bytes}). Increase max_bytes_mb or use a smaller PDF."),
        }

    temp = tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", delete=False)
    try:
        temp.write(response.content)
    finally:
        temp.close()
    return Path(temp.name), None


def _resolve_local_path(file_path: str) -> tuple[Path | None, dict | None]:
    """Resolve a local PDF path. Returns (path, None) or (None, error_dict)."""
    path = Path(file_path).resolve()
    if not path.exists():
        return None, {"error": f"PDF file not found: {file_path}"}
    if not path.is_file():
        return None, {"error": f"Not a file: {file_path}"}
    if path.suffix.lower() != ".pdf":
        return None, {"error": f"Not a PDF file (expected .pdf): {file_path}"}
    return path, None


def _read_single_pdf(
    file_ref: str,
    pages: str | None,
    max_pages: int,
    max_bytes: int,
    password: str | None,
    include_metadata: bool,
) -> dict[str, Any]:
    """Read one PDF (local path or URL) and return the result dict.

    On any error, returns a dict containing an ``error`` key. Otherwise
    returns the full per-PDF shape (see ``pdf_read`` docstring).
    """
    temp_path: Path | None = None
    is_url = file_ref.startswith(("http://", "https://"))

    if is_url:
        path, err = _download_pdf(file_ref, max_bytes=max_bytes)
        if err is not None:
            return err
        assert path is not None
        temp_path = path
    else:
        resolved, err = _resolve_local_path(file_ref)
        if err is not None:
            return err
        assert resolved is not None
        path = resolved

    # The pdfplumber.open + page iteration is the part that can hang on
    # a malformed/complex PDF. Run it in a daemon thread with a join
    # timeout so we never tie up the 60s framework tool slot — yield
    # back to terminal_exec hints instead. Bounded leak: the thread
    # eventually returns when pdfplumber gives up (or the MCP subprocess
    # recycles); daemon=True so it never blocks process shutdown.
    holder: dict[str, Any] = {}

    def _worker() -> None:
        try:
            holder["value"] = _extract_with_pdfplumber(
                path=path,
                file_ref=file_ref,
                is_url=is_url,
                pages=pages,
                max_pages=max_pages,
                password=password,
                include_metadata=include_metadata,
            )
        except BaseException as exc:  # noqa: BLE001 - caught + classified
            holder["exc"] = exc

    import time as _time

    started = _time.monotonic()
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=_PDF_EXTRACT_TIMEOUT_SECONDS)
    try:
        if t.is_alive():
            return _yield_to_terminal(
                path,
                reason="pdf_extract_timeout",
                elapsed_s=_time.monotonic() - started,
            )
        if "exc" in holder:
            exc = holder["exc"]
            if isinstance(exc, PermissionError):
                return {"error": f"Permission denied: {file_ref}"}
            msg = str(exc).lower()
            if "password" in msg or "encrypt" in msg:
                # Keep the legacy error message for backwards compat with
                # existing callers that pattern-match on it; layer in the
                # terminal-hint fields so the agent still gets a path
                # forward via qpdf.
                yielded = _yield_to_terminal(path, reason="pdf_encrypted")
                yielded["error"] = "Cannot read encrypted PDF: wrong password or no password supplied."
                return yielded
            yielded = _yield_to_terminal(path, reason="pdf_open_failed")
            yielded["error"] = f"Failed to open PDF: {exc!s}"
            return yielded
        return holder.get("value") or _yield_to_terminal(path, reason="pdf_open_failed")
    finally:
        if temp_path is not None:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _extract_with_pdfplumber(
    *,
    path: Path,
    file_ref: str,
    is_url: bool,
    pages: str | None,
    max_pages: int,
    password: str | None,
    include_metadata: bool,
) -> dict[str, Any]:
    """The pdfplumber-bound body of ``_read_single_pdf``. Pulled out so the
    parent can run it in a worker thread with an internal timeout. May
    raise — caller catches and classifies into the yield-to-terminal
    shape. Returns the success-shape dict on a clean extract.
    """
    pdf_ctx = pdfplumber.open(path, password=password or "")
    with pdf_ctx as pdf:
        total_pages = len(pdf.pages)
        page_info = parse_page_range(pages, total_pages, max_pages)
        if "error" in page_info:
            return page_info
        indices: list[int] = page_info["indices"]

        page_entries: list[dict[str, Any]] = []
        needs_vision: list[int] = []
        content_parts: list[str] = []
        for i in indices:
            # pdfplumber.extract_text() returns None for pages with
            # no text layer (scans). Coerce to "" so downstream length
            # checks behave consistently.
            text = (pdf.pages[i].extract_text() or "").strip()
            page_number = i + 1
            page_needs_vision = len(text) < _VISION_TEXT_THRESHOLD
            if page_needs_vision:
                needs_vision.append(page_number)
            page_entries.append(
                {
                    "number": page_number,
                    "text": text,
                    "needs_vision": page_needs_vision,
                }
            )
            content_parts.append(f"--- Page {page_number} ---\n{text}")

        content = "\n\n".join(content_parts)
        result: dict[str, Any] = {
            "path": str(path) if not is_url else file_ref,
            "name": path.name,
            "total_pages": total_pages,
            "pages_extracted": len(indices),
            "content": content,
            "char_count": len(content),
            "pages": page_entries,
        }
        if needs_vision:
            result["needs_vision_pages"] = needs_vision
            # Primary path: attach_file → vision model reads scanned PDFs
            # natively. Secondary: terminal_hint for non-vision setups
            # (pdfimages + tesseract, etc.) — Layer G adds the hint so
            # the agent has a fallback when the active model can't see.
            result["next_step"] = (
                "This PDF is scanned (no extractable text). "
                "Call attach_file(file_path) on the original PDF to send "
                "the pages as ImageContent for vision reading — no OCR or "
                "image rendering needed."
            )
            result["terminal_hint"] = _TERMINAL_HINT

        if page_info.get("truncated"):
            requested = page_info.get("requested_pages", len(indices))
            result["truncated"] = True
            result["truncation_warning"] = (
                f"Requested {requested} page(s), but max_pages={max_pages}. Only the first {len(indices)} page(s) were processed."
            )

        if include_metadata:
            # pdfplumber.metadata is a dict-like with raw PDF keys
            # (``/Title``, ``/Author``, ...). Map to the same keys
            # the previous pypdf-backed implementation exposed so
            # callers don't have to branch on the library.
            meta = pdf.metadata or {}
            result["metadata"] = {
                "title": meta.get("Title") or meta.get("/Title"),
                "author": meta.get("Author") or meta.get("/Author"),
                "subject": meta.get("Subject") or meta.get("/Subject"),
                "creator": meta.get("Creator") or meta.get("/Creator"),
                "producer": meta.get("Producer") or meta.get("/Producer"),
                "created": (
                    str(meta.get("CreationDate") or meta.get("/CreationDate")) if (meta.get("CreationDate") or meta.get("/CreationDate")) else None
                ),
                "modified": (str(meta.get("ModDate") or meta.get("/ModDate")) if (meta.get("ModDate") or meta.get("/ModDate")) else None),
            }

        return result


def register_tools(mcp: FastMCP) -> None:
    """Register the PDF read tool with the MCP server."""

    @mcp.tool()
    def pdf_read(
        file_path: str | None = None,
        files: list[str] | None = None,
        pages: str | None = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
        max_bytes_mb: float = _DEFAULT_MAX_BYTES_MB,
        password: str | None = None,
        include_metadata: bool = True,
    ) -> dict:
        """Read and extract text from one or many PDF files.

        Single-file mode (``file_path``) returns a flat result:
        ``{path, name, total_pages, pages_extracted, content, char_count,
        pages: [{number, text, needs_vision}], needs_vision_pages?, metadata?}``.

        Multi-file mode (``files``, up to 10) returns ``{pdfs: [...]}`` with
        each entry in the single-file shape. Pages below 200 chars of
        extracted text are flagged ``needs_vision: true``; the result also
        carries a ``next_step`` field telling the caller to use
        ``attach_file`` on the original PDF — it sends the pages as
        ImageContent so vision reads them directly (no OCR, no per-page
        image rendering).

        Args:
            file_path: One PDF (local path or http(s):// URL). Back-compat.
            files: Up to 10 PDFs. Mutually-exclusive with ``file_path``.
            pages: ``"all"``/None, ``"5"``, ``"1-10"``, or ``"1,3,5"``.
            max_pages: Per-PDF cap on parsed pages (1-1000).
            max_bytes_mb: Per-PDF download cap for URL inputs.
            password: Decrypt password for encrypted PDFs.
            include_metadata: Include title/author/dates if available.
        """
        # Clamp max_pages first — used by every path.
        max_pages = max(1, min(_HARD_MAX_PAGES, int(max_pages)))
        max_bytes = max(1, int(max_bytes_mb * 1024 * 1024))

        # Resolve which mode we're in.
        targets: list[str] = []
        if files:
            if file_path:
                return {
                    "error": "Pass either file_path or files, not both.",
                }
            if len(files) > _MAX_PDFS:
                return {
                    "error": f"Too many PDFs: {len(files)} provided, max {_MAX_PDFS}.",
                }
            targets = list(files)
            multi_mode = True
        elif file_path:
            targets = [file_path]
            multi_mode = False
        else:
            return {"error": "Provide file_path (single PDF) or files (list, up to 10)."}

        results = [
            _read_single_pdf(
                ref,
                pages=pages,
                max_pages=max_pages,
                max_bytes=max_bytes,
                password=password,
                include_metadata=include_metadata,
            )
            for ref in targets
        ]

        if multi_mode:
            return {"pdfs": results}
        # Back-compat: single-file mode returns the result dict directly
        # (with the new fields layered in additively).
        return results[0]
