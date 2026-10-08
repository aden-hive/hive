"""Tests for the image_generate tool (FastMCP).

The tool routes through the Hive LLM proxy, so every test mocks ``httpx.post``
to stand in for the proxy and asserts on the request body and the saved output.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from aden_tools.tools.image_gen_tool import image_gen_tool, register_tools

# Smallest valid 1×1 PNG (8-bit grayscale) — reused as both the generated
# output bytes and a reference-image fixture.
TINY_PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
TINY_PNG_B64 = base64.b64encode(TINY_PNG_BYTES).decode("utf-8")


class DummyResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code: int, payload: dict | None = None, *, text: str = "", headers: dict | None = None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.content = content

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _ok_payload(n: int = 1) -> dict:
    return {
        "data": [{"b64_json": TINY_PNG_B64} for _ in range(n)],
        # The Hive proxy injects `credits` into usage; the tool echoes it
        # verbatim so the UI can show the per-image cost.
        "usage": {"input_tokens": 12, "output_tokens": 300, "total_tokens": 312, "credits": 8.5},
    }


@pytest.fixture
def mcp() -> FastMCP:
    return FastMCP("test-server")


@pytest.fixture
def image_generate_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["image_generate"].fn


@pytest.fixture(autouse=True)
def _proxy_env(monkeypatch, tmp_path: Path):
    """Provide the proxy token + a temp artifact dir for every test."""
    monkeypatch.setenv("HIVE_API_KEY", "stream-token")
    monkeypatch.setenv("HIVE_STORAGE_PATH", str(tmp_path))
    monkeypatch.delenv("HIVE_LLM_BASE_URL", raising=False)


def _summary(result: list) -> dict:
    assert isinstance(result, list) and result
    assert isinstance(result[0], TextContent)
    return json.loads(result[0].text)


def test_missing_token_returns_error(image_generate_fn, monkeypatch):
    monkeypatch.delenv("HIVE_API_KEY", raising=False)
    result = image_generate_fn(prompt="a cat")
    assert "error" in _summary(result)


def test_generation_success_saves_and_previews(image_generate_fn, monkeypatch, tmp_path: Path):
    captured: dict = {}

    def mock_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return DummyResponse(200, _ok_payload())

    monkeypatch.setattr(httpx, "post", mock_post)
    # Bypass the Pillow re-encode (provenance/watermark strip) so this test can
    # assert the exact bytes flow through the save/preview plumbing unchanged;
    # _postprocess_image has its own coverage.
    monkeypatch.setattr(image_gen_tool, "_postprocess_image", lambda raw, fmt: raw)

    result = image_generate_fn(prompt="a friendly robot logo")
    summary = _summary(result)

    # Request shape: defaults applied, no reference image.
    assert captured["url"].endswith("/v1/images/generations")
    assert captured["headers"]["Authorization"] == "Bearer stream-token"
    body = captured["json"]
    assert body["model"] == "gpt-image-2"
    assert body["quality"] == "low"
    assert body["size"] == "1024x1024"
    assert body["n"] == 1
    assert "image" not in body

    # Output: one saved file under the temp storage dir + one inline preview.
    assert summary["model"] == "gpt-image-2"
    assert summary["n"] == 1
    assert summary["usage"]["output_tokens"] == 300
    # Proxy-injected per-image credit cost is echoed through for the UI.
    assert summary["usage"]["credits"] == 8.5
    saved_path = Path(summary["images"][0]["path"])
    assert saved_path.exists()
    assert str(saved_path).startswith(str(tmp_path))
    assert saved_path.read_bytes() == TINY_PNG_BYTES

    assert len(result) == 2
    assert isinstance(result[1], ImageContent)
    assert base64.b64decode(result[1].data) == TINY_PNG_BYTES


def test_reference_image_sent_as_base64(image_generate_fn, monkeypatch, tmp_path: Path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(TINY_PNG_BYTES)

    captured: dict = {}

    def mock_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return DummyResponse(200, _ok_payload())

    monkeypatch.setattr(httpx, "post", mock_post)

    result = image_generate_fn(prompt="restyle this", reference_images=[str(ref)])
    assert "error" not in _summary(result)
    assert captured["json"]["image"] == [TINY_PNG_B64]


def test_n_and_quality_are_clamped(image_generate_fn, monkeypatch):
    captured: dict = {}

    def mock_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return DummyResponse(200, _ok_payload(n=4))

    monkeypatch.setattr(httpx, "post", mock_post)

    image_generate_fn(prompt="variations", n=99, quality="ultra", output_format="bmp")
    assert captured["json"]["n"] == 4
    assert captured["json"]["quality"] == "low"
    assert captured["json"]["output_format"] == "png"


def test_only_low_quality_is_enabled(image_generate_fn, monkeypatch):
    captured: list = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured.append(json["quality"])
        return DummyResponse(200, _ok_payload())

    monkeypatch.setattr(httpx, "post", mock_post)

    # medium/high/auto are all disabled and forced down to low; only low passes.
    for requested in ("high", "auto", "medium", "low"):
        image_generate_fn(prompt="x", quality=requested)
    assert captured == ["low", "low", "low", "low"]


@pytest.mark.parametrize(
    "status,needle",
    [
        (402, "credit"),
        (403, "unavailable"),
        (429, "rate-limited"),
        (400, "rejected"),
        (500, "error"),
    ],
)
def test_error_status_mapping(image_generate_fn, monkeypatch, status, needle):
    def mock_post(url, json=None, headers=None, timeout=None):
        return DummyResponse(status, {"error": {"message": "boom"}}, text="boom")

    monkeypatch.setattr(httpx, "post", mock_post)

    result = image_generate_fn(prompt="x")
    summary = _summary(result)
    assert "error" in summary
    assert needle.lower() in summary["error"].lower()
    assert summary.get("status") == status


def test_timeout_maps_to_error_without_raising(image_generate_fn, monkeypatch):
    def mock_post(url, json=None, headers=None, timeout=None):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx, "post", mock_post)

    result = image_generate_fn(prompt="x")
    assert "timed out" in _summary(result)["error"].lower()


def test_too_many_reference_images(image_generate_fn):
    result = image_generate_fn(prompt="x", reference_images=[f"/tmp/{i}.png" for i in range(11)])
    assert "Too many reference images" in _summary(result)["error"]


def test_url_reference_image_fetched(image_generate_fn, monkeypatch):
    """A public image URL is fetched, base64'd, and placed in the body."""
    captured: dict = {}

    def mock_get(url, timeout=None, follow_redirects=None):
        return DummyResponse(200, headers={"content-type": "image/png"}, content=TINY_PNG_BYTES)

    def mock_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return DummyResponse(200, _ok_payload())

    # Treat the URL host as public so the SSRF guard passes.
    monkeypatch.setattr(image_gen_tool, "_url_target_is_public", lambda url: True)
    monkeypatch.setattr(httpx, "get", mock_get)
    monkeypatch.setattr(httpx, "post", mock_post)

    result = image_generate_fn(prompt="edit", reference_images=["https://cdn.example.com/a.png"])
    assert "error" not in _summary(result)
    assert captured["json"]["image"] == [TINY_PNG_B64]
