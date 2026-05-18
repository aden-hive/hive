"""Unit tests for MCP client transport and reconnect behavior."""

import asyncio
import sys
import types
from types import SimpleNamespace

import httpx
import pytest

from framework.loader import mcp_client as mcp_client_module
from framework.loader.mcp_client import MCPClient, MCPServerConfig, MCPTool


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        """Pretend the request succeeded."""

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.get_calls: list[str] = []
        self.closed = False

    def get(self, path: str) -> _FakeResponse:
        self.get_calls.append(path)
        return _FakeResponse()

    def close(self) -> None:
        self.closed = True


def test_connect_unix_transport_uses_socket_path(monkeypatch):
    created = {}

    class FakeHTTPTransport:
        def __init__(self, *, uds: str):
            created["uds"] = uds
            self.uds = uds

    def fake_client_factory(**kwargs):
        client = _FakeHttpClient(**kwargs)
        created["client"] = client
        return client

    monkeypatch.setattr(mcp_client_module.httpx, "HTTPTransport", FakeHTTPTransport)
    monkeypatch.setattr(mcp_client_module.httpx, "Client", fake_client_factory)
    monkeypatch.setattr(MCPClient, "_discover_tools", lambda self: None)

    client = MCPClient(
        MCPServerConfig(
            name="unix-server",
            transport="unix",
            url="http://localhost",
            socket_path="/tmp/test.sock",
        )
    )

    client.connect()

    assert created["uds"] == "/tmp/test.sock"
    assert client._http_client is created["client"]  # noqa: SLF001 - direct unit test
    assert created["client"].kwargs["base_url"] == "http://localhost"
    assert created["client"].get_calls == ["/health"]

    client.disconnect()
    assert created["client"].closed is True


def test_connect_sse_and_list_tools(monkeypatch):
    pytest.importorskip("mcp")
    sse_module = pytest.importorskip("mcp.client.sse")
    import mcp

    contexts = []

    class FakeSSEContext:
        def __init__(self, url: str, headers: dict[str, str] | None, timeout: float):
            self.url = url
            self.headers = headers
            self.timeout = timeout
            self.exited = False

        async def __aenter__(self):
            return "read-stream", "write-stream"

        async def __aexit__(self, exc_type, exc, tb):
            self.exited = True

    class FakeSession:
        def __init__(self, read_stream, write_stream):
            self.read_stream = read_stream
            self.write_stream = write_stream
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self.closed = True

        async def initialize(self):
            """Pretend session initialization succeeded."""

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="search",
                        description="Search docs",
                        inputSchema={"type": "object"},
                    )
                ]
            )

    def fake_sse_client(url: str, headers=None, timeout=5, **_kwargs):
        context = FakeSSEContext(url=url, headers=headers, timeout=timeout)
        contexts.append(context)
        return context

    monkeypatch.setattr(sse_module, "sse_client", fake_sse_client)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)

    client = MCPClient(
        MCPServerConfig(
            name="sse-server",
            transport="sse",
            url="http://localhost/sse",
            headers={"Authorization": "Bearer token"},
        )
    )

    client.connect()
    tools = client.list_tools()

    assert [tool.name for tool in tools] == ["search"]
    assert tools[0].description == "Search docs"
    assert contexts[0].url == "http://localhost/sse"
    assert contexts[0].headers == {"Authorization": "Bearer token"}
    assert contexts[0].timeout == 30.0

    client.disconnect()
    assert contexts[0].exited is True


def test_call_tool_retries_once_on_connect_error_for_unix(monkeypatch):
    client = MCPClient(MCPServerConfig(name="unix-server", transport="unix"))
    client._connected = True  # noqa: SLF001 - direct unit test
    client._tools = {  # noqa: SLF001 - direct unit test
        "ping": MCPTool("ping", "Ping tool", {}, "unix-server")
    }

    first_error = httpx.ConnectError("first failure")
    calls = {"count": 0}
    reconnects = []

    def fake_call_tool_http(tool_name, arguments):
        calls["count"] += 1
        if calls["count"] == 1:
            raise first_error
        return [{"type": "text", "text": f"{tool_name}:{arguments['value']}"}]

    monkeypatch.setattr(client, "_call_tool_http", fake_call_tool_http)
    monkeypatch.setattr(client, "_reconnect", lambda: reconnects.append("reconnected"))

    result = client.call_tool("ping", {"value": "ok"})

    assert result == [{"type": "text", "text": "ping:ok"}]
    assert calls["count"] == 2
    assert reconnects == ["reconnected"]


def test_call_tool_retry_exhausted_raises_original_error_for_unix(monkeypatch):
    client = MCPClient(MCPServerConfig(name="unix-server", transport="unix"))
    client._connected = True  # noqa: SLF001 - direct unit test
    client._tools = {  # noqa: SLF001 - direct unit test
        "ping": MCPTool("ping", "Ping tool", {}, "unix-server")
    }

    first_error = httpx.ConnectError("first failure")
    second_error = httpx.ConnectError("second failure")
    calls = {"count": 0}
    reconnects = []

    def fake_call_tool_http(_tool_name, _arguments):
        calls["count"] += 1
        if calls["count"] == 1:
            raise first_error
        raise second_error

    monkeypatch.setattr(client, "_call_tool_http", fake_call_tool_http)
    monkeypatch.setattr(client, "_reconnect", lambda: reconnects.append("reconnected"))

    with pytest.raises(httpx.ConnectError) as exc_info:
        client.call_tool("ping", {"value": "ok"})

    assert exc_info.value is first_error
    assert calls["count"] == 2
    assert reconnects == ["reconnected"]


def test_call_tool_http_preserves_runtime_error_wrapping(monkeypatch):
    client = MCPClient(MCPServerConfig(name="http-server", transport="http"))
    client._connected = True  # noqa: SLF001 - direct unit test
    client._tools = {  # noqa: SLF001 - direct unit test
        "ping": MCPTool("ping", "Ping tool", {}, "http-server")
    }

    connect_error = httpx.ConnectError("first failure")

    class FailingHttpClient:
        def post(self, _path, json):
            raise connect_error

    client._http_client = FailingHttpClient()  # noqa: SLF001 - direct unit test
    reconnects = []
    monkeypatch.setattr(client, "_reconnect", lambda: reconnects.append("reconnected"))

    with pytest.raises(RuntimeError) as exc_info:
        client.call_tool("ping", {"value": "ok"})

    assert "Failed to call tool via HTTP" in str(exc_info.value)
    assert exc_info.value.__cause__ is connect_error
    assert reconnects == []


def test_connect_stdio_times_out_when_not_ready(monkeypatch):
    mcp = types.ModuleType("mcp")
    mcp_client = types.ModuleType("mcp.client")
    mcp_client_stdio = types.ModuleType("mcp.client.stdio")

    class StdioServerParameters:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class ClientSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self):
            return None

    class NeverEnterContext:
        async def __aenter__(self):
            await asyncio.Future()  # Simulate a hung handshake

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def stdio_client(_params):
        return NeverEnterContext()

    mcp.StdioServerParameters = StdioServerParameters
    mcp.ClientSession = ClientSession
    mcp_client_stdio.stdio_client = stdio_client

    monkeypatch.setitem(sys.modules, "mcp", mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", mcp_client_stdio)

    # Make the event loop start succeed, but the connection-ready event never set.
    class FakeEvent:
        _count = 0

        def __init__(self):
            type(self)._count += 1
            self._idx = type(self)._count
            self._set = False

        def set(self):
            self._set = True

        def wait(self, timeout=None):
            # First event (loop_started) reports ready immediately.
            # Second event (connection_ready) never becomes ready.
            return self._idx == 1

        def is_set(self):
            return self._set if self._idx == 1 else False

    class FakeLoop:
        def create_task(self, coro):
            # Avoid "coroutine was never awaited" warnings.
            coro.close()
            return None

        def run_forever(self):
            return None

    def fake_new_event_loop():
        return FakeLoop()

    def fake_set_event_loop(_loop):
        return None

    class FakeThread:
        def __init__(self, target, daemon=None):
            self._target = target
            self._alive = False

        def start(self):
            self._alive = True
            self._target()
            self._alive = False

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("threading.Event", FakeEvent)
    monkeypatch.setattr("threading.Thread", FakeThread)
    monkeypatch.setattr("asyncio.new_event_loop", fake_new_event_loop)
    monkeypatch.setattr("asyncio.set_event_loop", fake_set_event_loop)

    monkeypatch.setattr(MCPClient, "_discover_tools", lambda _self: None)

    client = MCPClient(MCPServerConfig(name="demo", transport="stdio", command="dummy"))

    with pytest.raises(RuntimeError, match="Timed out waiting for MCP stdio connection"):
        client.connect()
