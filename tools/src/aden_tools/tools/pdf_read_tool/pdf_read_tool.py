"""
PDF Read Tool - Parse and extract text from PDF files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pypdf import PdfReader


logger = logging.getLogger(__name__)


# ============================================================
# Core Business Logic (Framework Independent)
# ============================================================

def pdf_read_logic(
    file_path: str,
    pages: str | None = None,
    max_pages: int = 100,
    include_metadata: bool = True,
) -> dict[str, Any]:
    """
    Core PDF reading logic independent of FastMCP.
    """

    try:
        path = Path(file_path).resolve()

        if not path.exists():
            return {"error": f"PDF file not found: {file_path}"}

        if not path.is_file():
            return {"error": f"Not a file: {file_path}"}

        if path.suffix.lower() != ".pdf":
            return {"error": f"Not a PDF file (expected .pdf): {file_path}"}

        # File size protection (50MB)
        max_file_size_mb = 50
        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > max_file_size_mb:
            return {
                "error": (
                    f"PDF too large ({file_size_mb:.2f}MB). "
                    f"Maximum allowed size is {max_file_size_mb}MB."
                )
            }

        reader = PdfReader(path)

        if reader.is_encrypted:
            return {"error": "Cannot read encrypted PDF. Password required."}

        total_pages = len(reader.pages)

        if total_pages == 0:
            return {"error": "PDF has no pages."}

        # Safety for max_pages
        max_pages = max(1, min(max_pages, 1000))

        page_indices = list(range(min(total_pages, max_pages)))

        content_parts = []

        for i in page_indices:
            try:
                page = reader.pages[i]
                page_text = page.extract_text()

                if not page_text:
                    page_text = "[No extractable text on this page]"

                content_parts.append(
                    f"--- Page {i + 1} ---\n{page_text.strip()}"
                )

            except Exception:
                content_parts.append(
                    f"--- Page {i + 1} ---\n[Error extracting text from this page]"
                )

        content = "\n\n".join(content_parts)

        result: dict[str, Any] = {
            "path": str(path),
            "name": path.name,
            "total_pages": total_pages,
            "pages_extracted": len(page_indices),
            "content": content,
            "char_count": len(content),
        }

        if include_metadata and reader.metadata:
            result["metadata"] = dict(reader.metadata)

        return result

    except Exception as e:
        logger.exception("Error reading PDF")
        return {"error": str(e)}


# ============================================================
# FastMCP Registration Layer
# ============================================================

def register_tools(mcp: FastMCP) -> None:
    """Register PDF read tool with FastMCP."""

    @mcp.tool()
    def pdf_read(
        file_path: str,
        pages: str | None = None,
        max_pages: int = 100,
        include_metadata: bool = True,
    ) -> dict:
        return pdf_read_logic(
            file_path=file_path,
            pages=pages,
            max_pages=max_pages,
            include_metadata=include_metadata,
        )
