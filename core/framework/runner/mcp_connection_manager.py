"""Shared MCP client connection management."""

import threading
from typing import Any

import httpx

from framework.runner.mcp_client import MCPClient, MCPServerConfig


class MCPConnectionManager:
    """Process-wide MCP client pool keyed by server name."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._pool: dict[str, MCPClient] = {}
        self._refcounts: dict[str, int] = {}
        self._configs: dict[str, MCPServerConfig] = {}
        self._pool_lock = threading.Lock()
        # Transition events keep callers from racing a connect/reconnect/disconnect.
        self._transitions: dict[str, threading.Event] = {}

    @classmethod
    def get_instance(cls) -> "MCPConnectionManager":
        """Return the process-level singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _is_connected(client: MCPClient | None) -> bool:
        return bool(client and getattr(client, "_connected", False))

    def acquire(self, config: MCPServerConfig) -> MCPClient:
        """Get or create a shared connection and increment its refcount."""
        server_name = config.name

        while True:
            should_connect = False
            transition_event: threading.Event | None = None

            with self._pool_lock:
                client = self._pool.get(server_name)
                if self._is_connected(client) and server_name not in self._transitions:
                    self._refcounts[server_name] = self._refcounts.get(server_name, 0) + 1
                    self._configs[server_name] = config
                    return client

                transition_event = self._transitions.get(server_name)
                if transition_event is None:
                    transition_event = threading.Event()
                    self._transitions[server_name] = transition_event
                    self._configs[server_name] = config
                    should_connect = True

            if not should_connect:
                transition_event.wait()
                continue

            client = MCPClient(config)
            try:
                client.connect()
            except Exception:
                with self._pool_lock:
                    current = self._transitions.get(server_name)
                    if current is transition_event:
                        self._transitions.pop(server_name, None)
                        if (
                            server_name not in self._pool
                            and self._refcounts.get(server_name, 0) <= 0
                        ):
                            self._configs.pop(server_name, None)
                        transition_event.set()
                raise

            with self._pool_lock:
                current = self._transitions.get(server_name)
                if current is transition_event:
                    self._pool[server_name] = client
                    self._refcounts[server_name] = self._refcounts.get(server_name, 0) + 1
                    self._configs[server_name] = config
                    self._transitions.pop(server_name, None)
                    transition_event.set()
                    return client

            client.disconnect()

    def release(self, server_name: str) -> None:
        """Decrement refcount and disconnect when the last user releases."""
        while True:
            disconnect_client: MCPClient | None = None
            transition_event: threading.Event | None = None
            should_disconnect = False

            with self._pool_lock:
                transition_event = self._transitions.get(server_name)
                if transition_event is None:
                    refcount = self._refcounts.get(server_name, 0)
                    if refcount <= 0:
                        return
                    if refcount > 1:
                        self._refcounts[server_name] = refcount - 1
                        return

                    disconnect_client = self._pool.pop(server_name, None)
                    self._refcounts.pop(server_name, None)
                    transition_event = threading.Event()
                    self._transitions[server_name] = transition_event
                    should_disconnect = True

            if not should_disconnect:
                transition_event.wait()
                continue

            try:
                if disconnect_client is not None:
                    disconnect_client.disconnect()
            finally:
                with self._pool_lock:
                    current = self._transitions.get(server_name)
                    if current is transition_event:
                        self._transitions.pop(server_name, None)
                        transition_event.set()
            return

    def health_check(self, server_name: str) -> bool:
        """Return True when the pooled connection appears healthy."""
        while True:
            with self._pool_lock:
                transition_event = self._transitions.get(server_name)
                if transition_event is None:
                    client = self._pool.get(server_name)
                    config = self._configs.get(server_name)
                    break

            transition_event.wait()

        if client is None or config is None:
            return False

        try:
            if config.transport == "stdio":
                client.list_tools()
                return True

            if not config.url:
                return False

            client_kwargs: dict[str, Any] = {
                "base_url": config.url,
                "headers": config.headers,
                "timeout": 5.0,
            }
            if config.transport == "unix":
                if not config.socket_path:
                    return False
                client_kwargs["transport"] = httpx.HTTPTransport(uds=config.socket_path)

            with httpx.Client(**client_kwargs) as http_client:
                response = http_client.get("/health")
                response.raise_for_status()
            return True
        except Exception:
            return False

    def reconnect(self, server_name: str) -> MCPClient:
        """Force a disconnect and replace the pooled client with a fresh one."""
        while True:
            transition_event: threading.Event | None = None
            old_client: MCPClient | None = None

            with self._pool_lock:
                transition_event = self._transitions.get(server_name)
                if transition_event is None:
                    config = self._configs.get(server_name)
                    if config is None:
                        raise KeyError(f"Unknown MCP server: {server_name}")
                    old_client = self._pool.get(server_name)
                    refcount = self._refcounts.get(server_name, 0)
                    transition_event = threading.Event()
                    self._transitions[server_name] = transition_event
                    break

            transition_event.wait()

        if old_client is not None:
            old_client.disconnect()

        new_client = MCPClient(config)
        try:
            new_client.connect()
        except Exception:
            with self._pool_lock:
                current = self._transitions.get(server_name)
                if current is transition_event:
                    self._pool.pop(server_name, None)
                    self._transitions.pop(server_name, None)
                    transition_event.set()
            raise

        with self._pool_lock:
            current = self._transitions.get(server_name)
            if current is transition_event:
                self._pool[server_name] = new_client
                self._refcounts[server_name] = max(refcount, 1)
                self._transitions.pop(server_name, None)
                transition_event.set()
                return new_client

        new_client.disconnect()
        return self.acquire(config)

    def cleanup_all(self) -> None:
        """Disconnect all pooled clients and clear manager state."""
        while True:
            with self._pool_lock:
                if self._transitions:
                    pending = list(self._transitions.values())
                else:
                    cleanup_events = {name: threading.Event() for name in self._pool}
                    clients = list(self._pool.items())
                    self._transitions.update(cleanup_events)
                    self._pool.clear()
                    self._refcounts.clear()
                    self._configs.clear()
                    break

            for event in pending:
                event.wait()

        for _server_name, client in clients:
            try:
                client.disconnect()
            except Exception:
                pass

        with self._pool_lock:
            for server_name, event in cleanup_events.items():
                current = self._transitions.get(server_name)
                if current is event:
                    self._transitions.pop(server_name, None)
                    event.set()
