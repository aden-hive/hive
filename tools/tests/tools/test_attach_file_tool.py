"""Tests for attach_file tool (FastMCP)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from aden_tools.tools.attach_file_tool import register_tools

# Smallest valid PDF (one blank page) — matches the upload-path probe fixture.
TINY_PDF_BYTES = base64.b64decode(
    "JVBERi0xLjQKJeLjz9MKMyAwIG9iago8PC9UeXBlIC9QYWdlCi9QYXJlbnQg"
    "MSAwIFIKL01lZGlhQm94IFswIDAgNjEyIDc5Ml0KL0NvbnRlbnRzIDQgMCBS"
    "Ci9SZXNvdXJjZXMgPDwvRm9udCA8PC9GMSAyIDAgUj4+Pj4+PgplbmRvYmoK"
    "NCAwIG9iago8PC9MZW5ndGggNDQ+PgpzdHJlYW0KQlQKL0YxIDI0IFRmCjEw"
    "MCA3MDAgVGQKKHRlc3QpIFRqCkVUCmVuZHN0cmVhbQplbmRvYmoKMiAwIG9i"
    "ago8PC9UeXBlIC9Gb250Ci9TdWJ0eXBlIC9UeXBlMQovQmFzZUZvbnQgL0hl"
    "bHZldGljYT4+CmVuZG9iagoxIDAgb2JqCjw8L1R5cGUgL1BhZ2VzCi9LaWRz"
    "IFszIDAgUl0KL0NvdW50IDE+PgplbmRvYmoKNSAwIG9iago8PC9UeXBlIC9D"
    "YXRhbG9nCi9QYWdlcyAxIDAgUj4+CmVuZG9iagp0cmFpbGVyCjw8L1NpemUg"
    "NgovUm9vdCA1IDAgUj4+CnN0YXJ0eHJlZgozMjQKJSVFT0Y="
)

# Smallest valid 1×1 PNG (8-bit grayscale).
TINY_PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


@pytest.fixture
def attach_file_fn(mcp: FastMCP):
    """Register and return the attach_file tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["attach_file"].fn


def _parse_summary(result: list) -> dict:
    """Pull the JSON summary out of the result's TextContent."""
    assert len(result) >= 1
    assert isinstance(result[0], TextContent)
    return json.loads(result[0].text)


class TestAttachFileSingle:
    """Single-path attach behavior."""

    def test_single_pdf(self, attach_file_fn, tmp_path: Path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(TINY_PDF_BYTES)

        result = attach_file_fn(paths=str(pdf))
        summary = _parse_summary(result)

        assert summary["errors"] == []
        assert len(summary["attached"]) == 1
        entry = summary["attached"][0]
        assert entry["kind"] == "pdf"
        assert entry["mime"] == "application/pdf"
        assert entry["filename"] == "doc.pdf"
        assert entry["bytes"] == len(TINY_PDF_BYTES)

        # One ImageContent block follows the summary.
        assert len(result) == 2
        img = result[1]
        assert isinstance(img, ImageContent)
        assert img.mimeType == "application/pdf"
        assert base64.b64decode(img.data) == TINY_PDF_BYTES

    def test_single_png(self, attach_file_fn, tmp_path: Path):
        png = tmp_path / "pic.png"
        png.write_bytes(TINY_PNG_BYTES)

        result = attach_file_fn(paths=str(png))
        summary = _parse_summary(result)

        assert summary["errors"] == []
        assert len(summary["attached"]) == 1
        entry = summary["attached"][0]
        assert entry["kind"] == "image"
        assert entry["mime"] == "image/png"

        assert len(result) == 2
        img = result[1]
        assert isinstance(img, ImageContent)
        assert img.mimeType == "image/png"
        assert base64.b64decode(img.data) == TINY_PNG_BYTES

    def test_jpg_and_jpeg_both_map_to_image_jpeg(self, attach_file_fn, tmp_path: Path):
        for ext in (".jpg", ".jpeg"):
            f = tmp_path / f"pic{ext}"
            f.write_bytes(b"\xff\xd8\xff")  # JPEG SOI marker — enough for the test
            summary = _parse_summary(attach_file_fn(paths=str(f)))
            assert summary["attached"][0]["mime"] == "image/jpeg"


class TestAttachFileMulti:
    """Multi-path behavior."""

    def test_multiple_files(self, attach_file_fn, tmp_path: Path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(TINY_PDF_BYTES)
        png = tmp_path / "b.png"
        png.write_bytes(TINY_PNG_BYTES)
        webp = tmp_path / "c.webp"
        webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")

        result = attach_file_fn(paths=[str(pdf), str(png), str(webp)])
        summary = _parse_summary(result)

        assert summary["errors"] == []
        assert len(summary["attached"]) == 3
        # One TextContent + three ImageContent blocks.
        assert len(result) == 4
        assert all(isinstance(b, ImageContent) for b in result[1:])
        mimes = [b.mimeType for b in result[1:]]
        assert mimes == ["application/pdf", "image/png", "image/webp"]

    def test_partial_failure_keeps_valid(self, attach_file_fn, tmp_path: Path):
        good = tmp_path / "good.pdf"
        good.write_bytes(TINY_PDF_BYTES)
        missing = tmp_path / "missing.pdf"

        result = attach_file_fn(paths=[str(good), str(missing)])
        summary = _parse_summary(result)

        assert len(summary["attached"]) == 1
        assert summary["attached"][0]["filename"] == "good.pdf"
        assert len(summary["errors"]) == 1
        assert summary["errors"][0]["path"] == str(missing)
        # Only one ImageContent (for the good file).
        assert len(result) == 2

    def test_too_many_paths_hard_fails(self, attach_file_fn, tmp_path: Path):
        f = tmp_path / "x.pdf"
        f.write_bytes(TINY_PDF_BYTES)
        result = attach_file_fn(paths=[str(f)] * 11)
        summary = _parse_summary(result)
        assert summary["attached"] == []
        assert any("Too many paths" in e["error"] for e in summary["errors"])

    def test_all_paths_invalid_returns_summary_only(self, attach_file_fn, tmp_path: Path):
        result = attach_file_fn(paths=[str(tmp_path / "a.pdf"), str(tmp_path / "b.png")])
        summary = _parse_summary(result)
        assert summary["attached"] == []
        assert len(summary["errors"]) == 2
        # No ImageContent appended when nothing attached.
        assert len(result) == 1


class TestAttachFileResolution:
    """Path-resolution rules."""

    def test_hive_storage_path_relative(self, attach_file_fn, tmp_path: Path, monkeypatch):
        """A path like ``data/attachments/X.pdf`` resolves against
        $HIVE_STORAGE_PATH, mirroring what the agent reads from the
        upload-path's attachments listing."""
        att_dir = tmp_path / "data" / "attachments"
        att_dir.mkdir(parents=True)
        pdf = att_dir / "from_chat.pdf"
        pdf.write_bytes(TINY_PDF_BYTES)

        monkeypatch.setenv("HIVE_STORAGE_PATH", str(tmp_path))
        summary = _parse_summary(attach_file_fn(paths="data/attachments/from_chat.pdf"))
        assert summary["errors"] == []
        assert summary["attached"][0]["filename"] == "from_chat.pdf"
        assert summary["attached"][0]["resolved"] == str(pdf.resolve())

    def test_absolute_path_always_wins(self, attach_file_fn, tmp_path: Path, monkeypatch):
        pdf = tmp_path / "absolute.pdf"
        pdf.write_bytes(TINY_PDF_BYTES)
        monkeypatch.setenv("HIVE_STORAGE_PATH", "/nonexistent/path")
        # Absolute path bypasses HIVE_STORAGE_PATH lookup.
        summary = _parse_summary(attach_file_fn(paths=str(pdf)))
        assert summary["errors"] == []
        assert summary["attached"][0]["resolved"] == str(pdf.resolve())


class TestAttachFileGuards:
    """Per-file guards: size, extension, type errors."""

    def test_oversize_file_rejected(self, attach_file_fn, tmp_path: Path):
        big = tmp_path / "huge.pdf"
        big.write_bytes(b"%PDF-1.4\n" + b"x" * (3 * 1024 * 1024))
        result = attach_file_fn(paths=str(big), max_bytes_mb=1.0)
        summary = _parse_summary(result)
        assert summary["attached"] == []
        assert any("max_bytes" in e["error"] for e in summary["errors"])

    def test_unknown_binary_extension_accepted_as_blob(self, attach_file_fn, tmp_path: Path):
        # Previously rejected outright. New contract: any file is
        # acceptable. Binary files the LLM can't consume directly are
        # surfaced to the user as a chip; the LLM gets only the summary
        # entry (kind="blob", no inline content block).
        weird = tmp_path / "file.bin"
        weird.write_bytes(b"\x00\x01\x02")
        summary = _parse_summary(attach_file_fn(paths=str(weird)))
        assert summary["errors"] == []
        assert len(summary["attached"]) == 1
        entry = summary["attached"][0]
        assert entry["kind"] == "blob"
        assert entry["mime"] == "application/octet-stream"
        assert entry["filename"] == "file.bin"

    def test_unknown_text_extension_accepted_as_text(self, attach_file_fn, tmp_path: Path):
        # No-extension text-shaped files (e.g. a Dockerfile) flow into
        # the text path via the utf-8 sniff heuristic, so the LLM can
        # read them inline.
        plain = tmp_path / "Dockerfile"
        plain.write_text("FROM python:3.12\nRUN echo hi\n")
        summary = _parse_summary(attach_file_fn(paths=str(plain)))
        assert summary["errors"] == []
        entry = summary["attached"][0]
        assert entry["kind"] == "text"
        assert entry["mime"] == "text/plain"

    def test_yaml_inlined_as_text(self, attach_file_fn, tmp_path: Path):
        spec = tmp_path / "openapi.yaml"
        spec.write_text("openapi: 3.0.0\ninfo:\n  title: Test\n")
        summary = _parse_summary(attach_file_fn(paths=str(spec)))
        assert summary["errors"] == []
        entry = summary["attached"][0]
        assert entry["kind"] == "text"
        assert entry["mime"] == "application/yaml"

    def test_directory_rejected(self, attach_file_fn, tmp_path: Path):
        summary = _parse_summary(attach_file_fn(paths=str(tmp_path)))
        # Directory → not found (we only resolve regular files).
        assert summary["attached"] == []
        assert summary["errors"][0]["error"] == "file not found"

    def test_paths_must_be_string_or_list(self, attach_file_fn):
        summary = _parse_summary(attach_file_fn(paths=123))  # type: ignore[arg-type]
        assert summary["attached"] == []
        assert "paths must be" in summary["errors"][0]["error"]

    def test_large_text_inline_is_capped_so_chip_survives(self, attach_file_fn, tmp_path: Path):
        """A big text file must NOT be inlined whole. If the result exceeds the
        agent loop's max_tool_result_chars (~30k) it gets spilled to disk and the
        leading JSON summary is replaced with a prose placeholder — which the
        renderer can't parse, so the attachment chip silently never renders.
        Regression for the 62KB-CSV chip-not-showing bug."""
        big = tmp_path / "engagers_export.csv"
        big.write_text("col_a,col_b\n" + ("x,y\n" * 30_000))  # ~120 KB
        assert big.stat().st_size > 100_000

        result = attach_file_fn(paths=str(big))
        summary = _parse_summary(result)
        assert summary["errors"] == []
        assert summary["attached"][0]["kind"] == "text"
        assert summary["attached"][0]["filename"] == "engagers_export.csv"

        # Total concatenated text must stay well under a typical
        # max_tool_result_chars (~30k) so the result isn't spilled.
        total_text = sum(len(b.text) for b in result if isinstance(b, TextContent))
        assert total_text < 30_000, f"attach_file result is {total_text} chars — it would be spilled and the chip would break"
        # The inline body is a capped preview, not the whole 120KB file.
        assert any(isinstance(b, TextContent) and "preview truncated" in b.text for b in result[1:])
