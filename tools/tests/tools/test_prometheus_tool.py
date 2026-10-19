from __future__ import annotations

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.prometheus_tool import register_tools


@pytest.fixture
def mcp() -> FastMCP:
    server = FastMCP("test")
    register_tools(server)
    return server


def test_prometheus_query_validation(mcp: FastMCP) -> None:
    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    result = tool_fn(query="")

    assert "error" in result


def test_prometheus_query_success(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://fake-prometheus:9090")
    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "status": "success",
                "data": {"result": [{"metric": {}, "value": [123, "1"]}]},
            }

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("aden_tools.tools.prometheus_tool.prometheus_tool.httpx.get", mock_get)

    result = tool_fn(query="up")

    assert result["success"] is True
    assert "result" in result


def test_prometheus_query_range_success(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://fake-prometheus:9090")
    tool_fn = mcp._tool_manager._tools["prometheus_query_range"].fn

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "status": "success",
                "data": {"result": [{"values": [[123, "1"]]}]},
            }

    monkeypatch.setattr("aden_tools.tools.prometheus_tool.prometheus_tool.httpx.get", lambda *a, **k: MockResponse())

    result = tool_fn(
        query="up",
        start="2026-01-01T00:00:00Z",
        end="2026-01-01T01:00:00Z",
    )

    assert result["success"] is True


def test_prometheus_non_200(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://fake-prometheus:9090")
    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    class MockResponse:
        status_code = 500
        text = "Internal error"

        def json(self):
            return {}

    monkeypatch.setattr("aden_tools.tools.prometheus_tool.prometheus_tool.httpx.get", lambda *a, **k: MockResponse())

    result = tool_fn(query="up")

    assert "error" in result


def test_timeout(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://fake-prometheus:9090")
    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    def mock_query(*args, **kwargs):
        raise httpx.TimeoutException("Request timed out")

    monkeypatch.setattr(
        "aden_tools.tools.prometheus_tool.prometheus_tool.httpx.get",
        mock_query,
    )

    result = tool_fn(query="up")

    assert "error" in result
    assert "timed out" in result["error"].lower()


def test_prometheus_connection_error(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://fake-prometheus:9090")
    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    def mock_get(*args, **kwargs):
        raise Exception("Connection failed")

    monkeypatch.setattr("aden_tools.tools.prometheus_tool.prometheus_tool.httpx.get", mock_get)

    result = tool_fn(query="up")

    assert "error" in result


def test_missing_base_url(mcp: FastMCP, monkeypatch: pytest.MonkeyPatch) -> None:
    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    monkeypatch.delenv("PROMETHEUS_BASE_URL", raising=False)

    result = tool_fn(query="up")

    assert result["success"] is False
    assert "Missing required credential" in result["error"]


def test_base_url_credentials_priority_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMETHEUS_BASE_URL", "http://fake-prometheus:9090")

    class FakeCredentialStore:
        def get(self, key: str):
            return "http://cred-prometheus:9090"

    mcp = FastMCP("test-cred-override")
    register_tools(mcp, credentials=FakeCredentialStore())

    called_urls = []

    def fake_get(url, *args, **kwargs):
        called_urls.append(url)

        class Resp:
            status_code = 200

            def json(self):
                return {"status": "success", "data": {"result": []}}

        return Resp()

    monkeypatch.setattr("aden_tools.tools.prometheus_tool.prometheus_tool.httpx.get", fake_get)

    tool_fn = mcp._tool_manager._tools["prometheus_query"].fn

    result = tool_fn(query="up")

    assert result["success"] is True
    assert result["query"] == "up"
    assert "cred-prometheus:9090" in called_urls[0]
