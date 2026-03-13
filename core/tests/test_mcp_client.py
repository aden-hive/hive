import asyncio
import sys
import types

import pytest

from framework.runner.mcp_client import MCPClient, MCPServerConfig


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
