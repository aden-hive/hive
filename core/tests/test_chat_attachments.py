"""What the queen receives when a chat message carries attachments.

Each attachment kind is parsed in a worker thread (PDF text, CSV rows, text
head, image size). Those workers take the attachment's bytes and path as
arguments, so these tests pin the text each kind contributes to the queen's
message.
"""

from __future__ import annotations

import base64
import io

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from framework.server.tests.test_api import _make_app_with_session, _make_session


def _data_uri(mime: str, data: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}


def _one_page_pdf(text: str) -> bytes:
    """A minimal single-page PDF whose page shows *text*."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height)).save(buf, format="PNG")
    return buf.getvalue()


async def _send(tmp_path, attachment: dict) -> str:
    """Post *attachment* to the chat route; return the message the queen got."""
    session = _make_session(tmp_dir=tmp_path)
    session.queen_dir = tmp_path / "queen"
    session.queen_dir.mkdir()
    # Grab the node first: shutting the test server down stops its sessions,
    # which clears queen_executor.
    node = session.queen_executor.node_registry["queen"]
    async with TestClient(TestServer(_make_app_with_session(session))) as client:
        resp = await client.post(f"/api/sessions/{session.id}/chat", json={"message": "see attached", "images": [attachment]})
        assert resp.status == 200
    return node.inject_event.await_args.args[0]


@pytest.mark.asyncio
async def test_pdf_page_text_reaches_the_queen(tmp_path):
    message = await _send(tmp_path, _data_uri("application/pdf", _one_page_pdf("Quarterly revenue grew")))

    assert "[PDF page 1]\nQuarterly revenue grew" in message


@pytest.mark.asyncio
async def test_csv_rows_reach_the_queen(tmp_path):
    message = await _send(tmp_path, _data_uri("text/csv", b"city,offset\nParis,+02:00\nLima,-05:00\n"))

    assert "2 rows, 2 columns]\ncity | offset\n--- | ---\nParis | +02:00\nLima | -05:00" in message


@pytest.mark.asyncio
async def test_text_file_body_reaches_the_queen(tmp_path):
    message = await _send(tmp_path, _data_uri("text/plain", b"deploy window: Tue 02:00-04:00 UTC"))

    assert "]\ndeploy window: Tue 02:00-04:00 UTC" in message


@pytest.mark.asyncio
async def test_image_dimensions_are_listed_for_the_queen(tmp_path):
    message = await _send(tmp_path, _data_uri("image/png", _png(7, 3)))

    assert "(7×3, image/png," in message
