from __future__ import annotations

from typing import Any

import pytest

from framework.mcp.models import MCPServerConfig
from framework.mcp.transport.http import HttpMCPTransport


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
        json_data: dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(
        self,
        *,
        get_response: _FakeResponse | None = None,
        post_responses: list[_FakeResponse] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.headers = headers or {}
        self._get_response = get_response or _FakeResponse(status_code=200)
        self._post_responses = post_responses or []
        self._post_index = 0

    def get(self, path: str):
        _ = path
        return self._get_response

    def post(self, path: str, json: dict[str, Any], headers: dict[str, str] | None = None):
        _ = (path, json, headers)
        if self._post_index >= len(self._post_responses):
            return _FakeResponse(status_code=404)
        response = self._post_responses[self._post_index]
        self._post_index += 1
        return response

    def close(self):
        return None


def _config(url: str = "https://example.com/mcp") -> MCPServerConfig:
    return MCPServerConfig(name="TestMCP", transport="http", url=url)


def test_parse_sse_payload_extracts_json_result(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeClient(
        get_response=_FakeResponse(status_code=200),
        post_responses=[
            _FakeResponse(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                text=(
                    "event: message\n"
                    "data: "
                    '{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"SearchFastMcp"}]}}'
                    "\n\n"
                ),
            )
        ],
    )

    def _fake_client_factory(*, base_url: str, headers: dict[str, str], timeout: float):
        _ = (base_url, headers, timeout)
        return fake_client

    monkeypatch.setattr("framework.mcp.transport.http.httpx.Client", _fake_client_factory)

    transport = HttpMCPTransport(_config("https://example.com/mcp",))
    transport.connect()
    tools = transport.list_tools()
    transport.disconnect()

    assert tools[0]["name"] == "SearchFastMcp"


def test_connect_sets_mcp_accept_header(monkeypatch: pytest.MonkeyPatch):
    captured_headers: dict[str, str] = {}

    def _fake_client_factory(*, base_url: str, headers: dict[str, str], timeout: float):
        _ = (base_url, timeout)
        captured_headers.update(headers)
        return _FakeClient(get_response=_FakeResponse(status_code=200), headers=headers)

    monkeypatch.setattr("framework.mcp.transport.http.httpx.Client", _fake_client_factory)

    transport = HttpMCPTransport(_config())
    transport.connect()

    assert "application/json" in captured_headers["Accept"]
    assert "text/event-stream" in captured_headers["Accept"]
    transport.disconnect()


def test_rpc_falls_back_and_parses_sse_payload(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeClient(
        headers={"Accept": "application/json, text/event-stream"},
        post_responses=[
            _FakeResponse(status_code=406),
            _FakeResponse(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'event: message\n'
                    "data: "
                    '{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"SearchFastMcp"}]}}'
                    "\n\n"
                ),
            ),
        ],
    )

    def _fake_client_factory(*, base_url: str, headers: dict[str, str], timeout: float):
        _ = (base_url, headers, timeout)
        return fake_client

    monkeypatch.setattr("framework.mcp.transport.http.httpx.Client", _fake_client_factory)

    transport = HttpMCPTransport(_config("https://example.com/mcp"))
    transport.config.rpc_paths = ["/mcp/v1", "/mcp"]
    transport.connect()
    tools = transport.list_tools()
    transport.disconnect()

    assert tools[0]["name"] == "SearchFastMcp"
