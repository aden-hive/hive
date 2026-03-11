"""Session file uploads: validation, storage, and text extraction for chat attachments."""

import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Allowed MIME types and extensions for chat attachments
ALLOWED_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".txt"})
ALLOWED_MIMES = frozenset({
    "application/pdf",
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "text/plain",
})
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILES_PER_UPLOAD = 5

# Safe filename: alphanumeric, dash, underscore, one dot for extension
SAFE_FNAME = re.compile(r"^[a-zA-Z0-9_\-]+(\.[a-zA-Z0-9]+)?$")


def _safe_file_id(name: str) -> str:
    """Return a safe storage file id (no path separators)."""
    return str(uuid.uuid4())[:12] + "_" + "".join(c if c.isalnum() or c in "._-" else "_" for c in name[:30])


def validate_file(
    filename: str,
    content_type: str | None,
    size: int,
) -> None:
    """Validate a single file. Raises ValueError with user-facing message on failure."""
    if size <= 0:
        raise ValueError("File is empty")
    if size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File too large (max {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB)")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type not allowed. Use one of: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    if content_type and content_type.lower().split(";")[0].strip() not in ALLOWED_MIMES:
        # Allow by extension if MIME is wrong but extension is allowed
        pass


def extract_text(path: Path, filename: str, content_type: str | None) -> str:
    """Extract plain text from a stored file. Returns a string for inclusion in the chat message."""
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".txt":
            return path.read_text(encoding="utf-8", errors="replace").strip()
        if ext == ".pdf":
            return _extract_pdf(path)
        if ext in (".doc", ".docx"):
            return _extract_docx(path, ext)
    except Exception as e:
        logger.warning("Text extraction failed for %s: %s", filename, e)
        return f"[Attachment: {filename} — could not extract text: {e}]"
    return f"[Attachment: {filename} — unsupported type]"


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "[Attachment: PDF — install server extra with pypdf for text extraction]"
    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        try:
            text = page.extract_text()
            if text:
                parts.append(text.strip())
        except Exception:
            pass
    return "\n\n".join(parts) if parts else "[Attachment: PDF — no text content]"


def _extract_docx(path: Path, ext: str) -> str:
    """Extract text from .docx (and optionally .doc if supported)."""
    if ext == ".doc":
        return "[Attachment: .doc (binary Word) — use .docx for text extraction]"
    try:
        from docx import Document
    except ImportError:
        return "[Attachment: DOCX — install server extra with python-docx for text extraction]"
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text).strip() or "[Attachment: DOCX — no text content]"


def save_upload(uploads_dir: Path, filename: str, data: bytes) -> tuple[str, Path]:
    """Save uploaded bytes to uploads_dir under a safe file_id. Returns (file_id, path)."""
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = filename if SAFE_FNAME.match(filename) else "attachment"
    file_id = _safe_file_id(safe_name)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".bin"
    dest = uploads_dir / f"{file_id}{ext}"
    dest.write_bytes(data)
    return file_id, dest


def read_attachment(uploads_dir: Path, file_id: str) -> tuple[str, str] | None:
    """Read an attachment by file_id. Returns (filename, extracted_text) or None if not found.

    Filename is taken from a sidecar meta file or derived from file_id.
    """
    # file_id is like "abc123_resume" or "abc123"; we store as abc123_resume.pdf
    candidates = list(uploads_dir.glob(f"{file_id}*"))
    if not candidates:
        return None
    path = candidates[0]
    if not path.is_file():
        return None
    filename = path.name
    content_type = None
    if path.suffix.lower() == ".pdf":
        content_type = "application/pdf"
    elif path.suffix.lower() in (".doc", ".docx"):
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    text = extract_text(path, filename, content_type)
    return filename, text


def build_message_with_attachments(
    message: str,
    uploads_dir: Path,
    attachment_ids: list[str],
) -> str:
    """Build the final message string to inject: optional attachment blocks then user message."""
    parts: list[str] = []
    for fid in attachment_ids:
        rec = read_attachment(uploads_dir, fid)
        if rec:
            name, text = rec
            parts.append(f"[Attached file: {name}]\n```\n{text}\n```")
        else:
            parts.append(f"[Attached file: {fid} — not found]")
    if message.strip():
        if parts:
            parts.append("")
        parts.append(message)
    return "\n".join(parts)
