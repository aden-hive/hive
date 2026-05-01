"""End-to-end smoke for chart-tools: spec → PNG file on disk.

Tests run with ``asyncio_mode=auto`` (see tools/pyproject.toml), so any
``async def test_*`` is automatically run via the pytest-asyncio plugin.
chart_render is async because FastMCP runs tool handlers inside the
running event loop; we await it the same way the framework does.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

EXPECTED_TOOLS = {"chart_render"}


def test_register_chart_tools_lands_all(mcp):
    from chart_tools import register_chart_tools

    names = register_chart_tools(mcp)
    assert set(names) == EXPECTED_TOOLS, (
        f"missing: {EXPECTED_TOOLS - set(names)}, extra: {set(names) - EXPECTED_TOOLS}"
    )


def test_all_tools_have_chart_prefix(mcp):
    from chart_tools import register_chart_tools

    for n in register_chart_tools(mcp):
        assert n.startswith("chart_"), f"{n!r} missing chart_ prefix"


@pytest.fixture
def chart_tool(mcp, tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    from chart_tools.tools import register_tools

    register_tools(mcp)
    return mcp._tool_manager._tools["chart_render"].fn


def _is_png(b: bytes) -> bool:
    """Verify the magic bytes + at least one IHDR chunk."""
    return b[:8] == b"\x89PNG\r\n\x1a\n" and b"IHDR" in b[:32]


def _png_dims(path: Path) -> tuple[int, int]:
    """Read width/height from the IHDR chunk so we can assert the
    screenshot honored the requested dpi/scale."""
    data = path.read_bytes()
    # IHDR is at offset 16 (after 8-byte signature + 4-byte length + 4-byte 'IHDR')
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height


async def test_render_echarts_bar_chart(chart_tool, tmp_path):
    """The flagship test: agent calls chart_render with an ECharts spec
    → file lands on disk, returns a non-empty envelope including the
    spec echo so the chat can render it live."""
    spec = {
        "title": {"text": "Smoke test"},
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [12, 24, 6]}],
    }
    result = await chart_tool(
        kind="echarts",
        spec=spec,
        title="smoke",
        width=600,
        height=400,
        dpi=96,  # keep test fast: 1x scale
    )
    assert "error" not in result, result
    assert result["kind"] == "echarts"
    assert result["spec"] == spec, "spec must be echoed back so the chat can re-render"
    assert result["width"] == 600 and result["height"] == 400
    assert result["bytes"] > 1000, "PNG should be at least 1KB"

    path = Path(result["file_path"])
    assert path.exists(), f"file not written: {path}"
    assert _is_png(path.read_bytes()), "file is not a valid PNG"
    w, h = _png_dims(path)
    # At dpi=96 (1x), the PNG should be roughly viewport-sized.
    assert 500 <= w <= 700, f"unexpected PNG width {w}"
    assert 300 <= h <= 500, f"unexpected PNG height {h}"

    # File should land under HIVE_HOME/charts/
    assert path.parent.name == "charts"
    assert "smoke" in path.name


async def test_render_echarts_invalid_kind_returns_error(chart_tool):
    result = await chart_tool(kind="bogus", spec={}, title="x")
    assert "error" in result
    assert result["kind"] == "bogus"  # echoed for the chat to surface


async def test_render_echarts_accepts_string_spec(chart_tool):
    """Regression: agent sometimes passes the spec as a JSON STRING
    instead of a dict (the actual failure shown to the user on
    2026-05-01: 'Cannot create property \"series\" on string ...').

    chart_render must parse string specs transparently.
    """
    import json as _json

    spec_dict = {
        "title": {"text": "String-spec regression"},
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2, 3]}],
    }
    result = await chart_tool(
        kind="echarts",
        spec=_json.dumps(spec_dict),  # ← STRING not dict
        title="string-spec",
        width=600,
        height=400,
        dpi=96,
    )
    assert "error" not in result, result
    assert result["bytes"] > 1000
    # Spec should be echoed back as the parsed dict, not the original string.
    assert isinstance(result["spec"], dict)
    assert result["spec"] == spec_dict


async def test_render_mermaid_flowchart(chart_tool, tmp_path):
    """Mermaid path: agent passes raw mermaid source as the spec str."""
    src = """flowchart LR
A[Start] --> B{ok?}
B -- yes --> C[Done]
B -- no --> D[Retry]
"""
    result = await chart_tool(
        kind="mermaid",
        spec=src,
        title="flow",
        width=600,
        height=400,
        dpi=96,
    )
    assert "error" not in result, result
    assert result["spec"] == src
    path = Path(result["file_path"])
    assert path.exists() and _is_png(path.read_bytes())
