"""
PDF Read Tool - Parse and extract text from PDF files.

Uses pypdf to read PDF documents and extract text content
along with metadata.

SECURITY & ROBUSTNESS IMPROVEMENTS:
- Path traversal protection
- Empty file validation  
- Large file rejection (50MB limit)
- Encrypted PDF graceful handling
- Better PyPDF2 exception specificity
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

from fastmcp import FastMCP
from pypdf import PdfReader
from pypdf.errors import (
    PdfReadError, 
    PdfStreamError, 
    PdfNoOutlinesError
)


def register_tools(mcp: FastMCP) -> None:
    """Register PDF read tools with the MCP server."""

    def parse_page_range(
        pages: str | None, total_pages: int, max_pages: int
    ) -> List[int] | dict:
        """
        Parse page range string into list of 0-indexed page numbers.

        Returns list of indices or error dict.
        """
        if pages is None or pages.lower() == "all":
            indices = list(range(min(total_pages, max_pages)))
            return indices

        try:
            # Single page: "5"
            if pages.isdigit():
                page_num = int(pages)
                if page_num < 1 or page_num > total_pages:
                    return {"error": f"Page {page_num} out of range. PDF has {total_pages} pages."}
                return [page_num - 1]

            # Range: "1-10"
            if "-" in pages and "," not in pages:
                start_str, end_str = pages.split("-", 1)
                start, end = int(start_str), int(end_str)
                if start > end:
                    return {"error": f"Invalid page range: {pages}. Start must be less than end."}
                if start < 1:
                    return {"error": f"Page numbers start at 1, got {start}."}
                if end > total_pages:
                    return {"error": f"Page {end} out of range. PDF has {total_pages} pages."}
                indices = list(range(start - 1, min(end, start - 1 + max_pages)))
                return indices

            # Comma-separated: "1,3,5"
            if "," in pages:
                page_nums = [int(p.strip()) for p in pages.split(",")]
                for p in page_nums:
                    if p < 1 or p > total_pages:
                        return {"error": f"Page {p} out of range. PDF has {total_pages} pages."}
                indices = [p - 1 for p in page_nums[:max_pages]]
                return indices

            return {"error": f"Invalid page format: '{pages}'. Use 'all', '5', '1-10', or '1,3,5'."}

        except ValueError as e:
            return {"error": f"Invalid page format: '{pages}'. {str(e)}"}

    def validate_path_security(path: Path) -> dict | None:
        """SECURITY: Prevent path traversal and validate working directory confinement."""
        try:
            # Resolve symlinks and check we're still in working directory
            resolved_path = path.resolve(strict=True)
            cwd = Path.cwd().resolve()
            
            # Path traversal check: must be relative to cwd
            if not resolved_path.is_relative_to(cwd):
                return {"error": f"Path traversal detected: {path}. Must be within working directory."}
            
            return None  # Valid
        except Exception:
            return {"error": f"Invalid path: {path}"}

    @mcp.tool()
    def pdf_read(
        file_path: str,
        pages: str | None = None,
        max_pages: int = 100,
        include_metadata: bool = True,
    ) -> dict:
        """
        Read and extract text content from a PDF file.

        Returns text content with page markers and optional metadata.
        Use for reading PDFs, reports, documents, or any PDF file.

        Args:
            file_path: Path to the PDF file to read (absolute or relative)
            pages: Page range to extract - 'all'/None for all, '5' for single, '1-10' for range, '1,3,5' for specific
            max_pages: Maximum number of pages to process (1-1000, memory safety)
            include_metadata: Include PDF metadata (author, title, creation date, etc.)

        Returns:
            Dict with extracted text and metadata, or error dict
        """
        try:
            path = Path(file_path)
            
            # SECURITY: Path traversal validation
            security_error = validate_path_security(path)
            if security_error:
                return security_error

            path = path.resolve()

            # Validate file exists
            if not path.exists():
                return {"error": f"PDF file not found: {file_path}"}

            if not path.is_file():
                return {"error": f"Not a file: {file_path}"}

            # NEW: Empty file check (fixes #269)
            if path.stat().st_size == 0:
                return {"error": "Empty PDF file (0 bytes)"}

            # NEW: Large file rejection (memory safety)
            if path.stat().st_size > 50 * 1024 * 1024:  # 50MB
                return {"error": "PDF too large (>50MB). Split document or use pdf_chunk tool."}

            # Check extension
            if path.suffix.lower() != ".pdf":
                return {"error": f"Not a PDF file (expected .pdf): {file_path}"}

            # Validate max_pages
            if max_pages < 1:
                max_pages = 1
            elif max_pages > 1000:
                max_pages = 1000

            # Open and read PDF with specific error handling
            try:
                reader = PdfReader(path)
            except PdfReadError as e:
                return {"error": f"Corrupted PDF structure: {str(e)[:100]}"}
            except PdfStreamError as e:
                return {"error": f"PDF stream error (malformed content): {str(e)[:100]}"}
            except Exception as e:
                return {"error": f"Failed to open PDF: {str(e)[:100]}"}

            # Check for encryption (already handled but more specific)
            if reader.is_encrypted:
                return {"error": "Encrypted PDF detected. Password support not implemented."}

            total_pages = len(reader.pages)
            if total_pages == 0:
                return {"error": "PDF contains no readable pages"}

            # Parse page range
            page_indices = parse_page_range(pages, total_pages, max_pages)
            if isinstance(page_indices, dict):  # Error dict
                return page_indices

            # Extract text from pages
            content_parts = []
            for i in page_indices:
                try:
                    page_text = reader.pages[i].extract_text() or ""
                    content_parts.append(f"--- Page {i + 1} ---\n{page_text}")
                except Exception as e:
                    content_parts.append(f"--- Page {i + 1} ---\n[ERROR extracting page: {str(e)[:50]}]")

            content = "\n\n".join(content_parts)

            result: dict[str, Any] = {
                "path": str(path),
                "name": path.name,
                "total_pages": total_pages,
                "pages_extracted": len(page_indices),
                "content": content,
                "char_count": len(content),
                "truncated": len(page_indices) < total_pages,
            }

            # Add metadata if requested (with safe handling)
            if include_metadata and reader.metadata:
                try:
                    meta = reader.metadata
                    result["metadata"] = {
                        "title": meta.get("/Title", "").strip() or None,
                        "author": meta.get("/Author", "").strip() or None,
                        "subject": meta.get("/Subject", "").strip() or None,
                        "creator": meta.get("/Creator", "").strip() or None,
                        "producer": meta.get("/Producer", "").strip() or None,
                        "created": str(meta.get("/CreationDate")).strip() if meta.get("/CreationDate") else None,
                        "modified": str(meta.get("/ModDate")).strip() if meta.get("/ModDate") else None,
                    }
                    # Clean None values
                    result["metadata"] = {k: v for k, v in result["metadata"].items() if v}
                except Exception:
                    result["metadata"] = {"error": "Failed to parse metadata"}

            return result

        except PermissionError:
            return {"error": f"Permission denied accessing: {file_path}"}
        except Exception as e:
            return {"error": f"Unexpected error reading PDF: {str(e)[:100]}"}
