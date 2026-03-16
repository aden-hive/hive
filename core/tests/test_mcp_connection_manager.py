"""Tests for the shared MCP connection manager."""

import threading

import httpx
import pytest

from framework.runner.mcp_client import MCPServerConfig, MCPTool
from framework.runner.mcp_connection_manager import MCPConnectionManager


class FakeMCPClient:
    """Minimal fake MCP client for connection manager tests."""

    instances: list["FakeMCPClient"] = []

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.list_tools_calls = 0
        self.list_tools_error: Exception | None = None
        FakeMCPClient.instances.append(self)

    def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    def list_tools(self) -> list[MCPTool]:
        self.list_tools_calls += 1
        if self.list_tools_error is not None:
            raise self.list_tools_error
        return [MCPTool("ping", "Ping", {"type": "object"}, self.config.name)]


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr("framework.runner.mcp_connection_manager.MCPClient", FakeMCPClient)
    monkeypatch.setattr(MCPConnectionManager, "_instance", None)
    FakeMCPClient.instances.clear()
    manager = MCPConnectionManager.get_instance()
    yield manager
    manager.cleanup_all()
    monkeypatch.setattr(MCPConnectionManager, "_instance", None)
    FakeMCPClient.instances.clear()


def test_acquire_returns_same_client_for_same_server_name(manager):
    config = MCPServerConfig(name="shared", transport="stdio", command="echo")

    client_one = manager.acquire(config)
    client_two = manager.acquire(config)

    assert client_one is client_two
    assert manager._refcounts["shared"] == 2  # noqa: SLF001 - state assertion for unit test
    assert len(FakeMCPClient.instances) == 1


def test_release_with_refcount_above_one_keeps_connection_open(manager):
    config = MCPServerConfig(name="shared", transport="stdio", command="echo")
    client = manager.acquire(config)
    manager.acquire(config)

    manager.release("shared")

    assert client.disconnect_calls == 0
    assert manager._pool["shared"] is client  # noqa: SLF001 - state assertion for unit test
    assert manager._refcounts["shared"] == 1  # noqa: SLF001 - state assertion for unit test


def test_release_last_reference_disconnects_and_removes_from_pool(manager):
    config = MCPServerConfig(name="shared", transport="stdio", command="echo")
    client = manager.acquire(config)

    manager.release("shared")

    assert client.disconnect_calls == 1
    assert "shared" not in manager._pool  # noqa: SLF001 - state assertion for unit test
    assert "shared" not in manager._refcounts  # noqa: SLF001 - state assertion for unit test


def test_concurrent_acquire_and_release_keeps_state_consistent(manager):
    config = MCPServerConfig(name="shared", transport="stdio", command="echo")
    worker_count = 8
    acquire_barrier = threading.Barrier(worker_count + 1)
    release_barrier = threading.Barrier(worker_count)
    acquired_clients: list[FakeMCPClient] = []
    acquired_lock = threading.Lock()

    def worker() -> None:
        acquire_barrier.wait()
        client = manager.acquire(config)
        with acquired_lock:
            acquired_clients.append(client)
        release_barrier.wait()
        manager.release("shared")

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for thread in threads:
        thread.start()

    acquire_barrier.wait()

    for thread in threads:
        thread.join()

    assert len({id(client) for client in acquired_clients}) == 1
    assert len(FakeMCPClient.instances) == 1
    assert FakeMCPClient.instances[0].disconnect_calls == 1
    assert manager._pool == {}  # noqa: SLF001 - state assertion for unit test
    assert manager._refcounts == {}  # noqa: SLF001 - state assertion for unit test


def test_cleanup_all_disconnects_every_pooled_client(manager):
    manager.acquire(MCPServerConfig(name="one", transport="stdio", command="echo"))
    manager.acquire(MCPServerConfig(name="two", transport="stdio", command="echo"))

    manager.cleanup_all()

    assert len(FakeMCPClient.instances) == 2
    assert all(client.disconnect_calls == 1 for client in FakeMCPClient.instances)
    assert manager._pool == {}  # noqa: SLF001 - state assertion for unit test
    assert manager._refcounts == {}  # noqa: SLF001 - state assertion for unit test
    assert manager._configs == {}  # noqa: SLF001 - state assertion for unit test


def test_reconnect_replaces_client_even_with_existing_refcount(manager):
    config = MCPServerConfig(name="shared", transport="stdio", command="echo")
    original_client = manager.acquire(config)
    manager.acquire(config)

    replacement = manager.reconnect("shared")

    assert replacement is not original_client
    assert original_client.disconnect_calls == 1
    assert manager._pool["shared"] is replacement  # noqa: SLF001 - state assertion for unit test
    assert manager._refcounts["shared"] == 2  # noqa: SLF001 - state assertion for unit test


def test_health_check_returns_false_when_server_is_unreachable(manager, monkeypatch):
    config = MCPServerConfig(name="shared", transport="http", url="http://localhost:9")
    manager.acquire(config)

    class FailingHttpClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, _path: str):
            raise httpx.ConnectError("unreachable")

    monkeypatch.setattr("framework.runner.mcp_connection_manager.httpx.Client", FailingHttpClient)

    assert manager.health_check("shared") is False


def test_health_check_for_stdio_returns_false_on_tools_list_error(manager):
    config = MCPServerConfig(name="shared", transport="stdio", command="echo")
    client = manager.acquire(config)
    client.list_tools_error = RuntimeError("broken")

    assert manager.health_check("shared") is False
