"""Shared MCP client connection management."""

import logging
import threading

import httpx

from framework.runner.mcp_client import MCPClient, MCPServerConfig

logger = logging.getLogger(__name__)

_TRANSITION_TIMEOUT = 30.0


class MCPConnectionManager:
    """Process-wide MCP client pool keyed by server name."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._pool: dict[str, MCPClient] = {}
        self._refcounts: dict[str, int] = {}
        self._configs: dict[str, MCPServerConfig] = {}
        self._pool_lock = threading.Lock()
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

    def has_connection(self, server_name: str) -> bool:
        """Return True when a live pooled connection exists for ``server_name``."""
        with self._pool_lock:
            return self._is_connected(self._pool.get(server_name))

    def acquire(self, config: MCPServerConfig) -> MCPClient:
        """Get or create a shared connection and increment its refcount."""
        server_name = config.name

        while True:
            should_connect = False
            transition_event: threading.Event | None = None

            with self._pool_lock:
                client = self._pool.get(server_name)
                if self._is_connected(client) and server_name not in self._transitions:
                    new_refcount = self._refcounts.get(server_name, 0) + 1
                    self._refcounts[server_name] = new_refcount
                    self._configs[server_name] = config
                    logger.debug(
                        "Reusing pooled connection for MCP server '%s' (refcount=%d)",
                        server_name,
                        new_refcount,
                    )
                    return client

                transition_event = self._transitions.get(server_name)
                if transition_event is None:
                    transition_event = threading.Event()
                    self._transitions[server_name] = transition_event
                    self._configs[server_name] = config
                    should_connect = True

            if not should_connect:
                if not transition_event.wait(timeout=_TRANSITION_TIMEOUT):
                    logger.warning(
                        "Timed out waiting for transition on MCP server '%s', "
                        "forcing cleanup and retrying",
                        server_name,
                    )
                    with self._pool_lock:
                        stuck = self._transitions.get(server_name)
                        if stuck is transition_event:
                            self._transitions.pop(server_name, None)
                            transition_event.set()
                continue

            logger.info("Connecting to MCP server '%s'", server_name)
            client = MCPClient(config)
            try:
                client.connect()
            except Exception:
                logger.warning(
                    "Failed to connect to MCP server '%s'",
                    server_name,
                    exc_info=True,
                )
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
                    logger.info(
                        "Connected to MCP server '%s' (refcount=1)",
                        server_name,
                    )
                    return client

            # Lost the transition race, clean up and retry
            try:
                client.disconnect()
            except Exception:
                logger.debug(
                    "Error disconnecting stale client for '%s'",
                    server_name,
                    exc_info=True,
                )

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
                        logger.debug(
                            "Released MCP server '%s' (refcount=%d)",
                            server_name,
                            refcount - 1,
                        )
                        return

                    disconnect_client = self._pool.pop(server_name, None)
                    self._refcounts.pop(server_name, None)
                    self._configs.pop(server_name, None)
                    transition_event = threading.Event()
                    self._transitions[server_name] = transition_event
                    should_disconnect = True

            if not should_disconnect:
                if not transition_event.wait(timeout=_TRANSITION_TIMEOUT):
                    logger.warning(
                        "Timed out waiting for transition on '%s' during release, forcing cleanup",
                        server_name,
                    )
                    with self._pool_lock:
                        stuck = self._transitions.get(server_name)
                        if stuck is transition_event:
                            self._transitions.pop(server_name, None)
                            transition_event.set()
                continue

            try:
                if disconnect_client is not None:
                    disconnect_client.disconnect()
                    logger.info(
                        "Disconnected MCP server '%s' (last reference released)",
                        server_name,
                    )
            except Exception:
                logger.warning(
                    "Error disconnecting MCP server '%s' during release",
                    server_name,
                    exc_info=True,
                )
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

            if not transition_event.wait(timeout=_TRANSITION_TIMEOUT):
                logger.warning(
                    "Timed out waiting for transition on '%s' during health check",
                    server_name,
                )
                return False

        if client is None or config is None:
            return False

        try:
            match config.transport:
                case "stdio":
                    client.list_tools()
                    return True
                case "http":
                    if not config.url:
                        return False
                    with httpx.Client(
                        base_url=config.url,
                        headers=config.headers,
                        timeout=5.0,
                    ) as http_client:
                        response = http_client.get("/health")
                        response.raise_for_status()
                    return True
                case "sse":
                    client.list_tools()
                    return True
                case "unix":
                    if not config.socket_path:
                        return False
                    with httpx.Client(
                        base_url=config.url or "http://localhost",
                        headers=config.headers,
                        timeout=5.0,
                        transport=httpx.HTTPTransport(uds=config.socket_path),
                    ) as http_client:
                        response = http_client.get("/health")
                        response.raise_for_status()
                    return True
                case _:
                    logger.warning(
                        "Unknown transport '%s' for health check on '%s'",
                        config.transport,
                        server_name,
                    )
                    return False
        except Exception:
            logger.debug(
                "Health check failed for MCP server '%s'",
                server_name,
                exc_info=True,
            )
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
                    transition_event = threading.Event()
                    self._transitions[server_name] = transition_event
                    break

            if not transition_event.wait(timeout=_TRANSITION_TIMEOUT):
                logger.warning(
                    "Timed out waiting for transition on '%s' during reconnect, forcing cleanup",
                    server_name,
                )
                with self._pool_lock:
                    stuck = self._transitions.get(server_name)
                    if stuck is transition_event:
                        self._transitions.pop(server_name, None)
                        transition_event.set()

        # Disconnect old client safely
        if old_client is not None:
            try:
                old_client.disconnect()
                logger.info("Disconnected old client for '%s'", server_name)
            except Exception:
                logger.warning(
                    "Error disconnecting old client for '%s' during reconnect",
                    server_name,
                    exc_info=True,
                )

        logger.info("Reconnecting MCP server '%s'", server_name)
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
                current_refcount = self._refcounts.get(server_name, 0)
                if current_refcount <= 0:
                    # All holders released during reconnect. Discard the
                    # new client instead of creating a phantom reference.
                    # Caller should acquire() fresh if needed.
                    self._transitions.pop(server_name, None)
                    transition_event.set()
                    logger.info(
                        "Reconnected MCP server '%s' but refcount dropped to 0, "
                        "discarding new client",
                        server_name,
                    )
                    try:
                        new_client.disconnect()
                    except Exception:
                        logger.debug(
                            "Error disconnecting discarded client for '%s'",
                            server_name,
                            exc_info=True,
                        )
                    raise KeyError(
                        f"MCP server '{server_name}' was fully released during reconnect"
                    )

                self._pool[server_name] = new_client
                self._configs[server_name] = config
                self._refcounts[server_name] = current_refcount
                self._transitions.pop(server_name, None)
                transition_event.set()
                logger.info(
                    "Reconnected MCP server '%s' (refcount=%d)",
                    server_name,
                    current_refcount,
                )
                return new_client

        try:
            new_client.disconnect()
        except Exception:
            logger.debug(
                "Error disconnecting stale client for '%s' after reconnect race",
                server_name,
                exc_info=True,
            )
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

            all_resolved = all(event.wait(timeout=_TRANSITION_TIMEOUT) for event in pending)
            if not all_resolved:
                logger.warning(
                    "Timed out waiting for pending transitions during cleanup, "
                    "forcing cleanup of stuck transitions",
                )
                with self._pool_lock:
                    for sn, evt in list(self._transitions.items()):
                        if not evt.is_set():
                            self._transitions.pop(sn, None)
                            evt.set()

        logger.info("Cleaning up %d pooled MCP connections", len(clients))
        for server_name, client in clients:
            try:
                client.disconnect()
                logger.debug("Disconnected MCP server '%s' during cleanup", server_name)
            except Exception:
                logger.warning(
                    "Error disconnecting MCP server '%s' during cleanup",
                    server_name,
                    exc_info=True,
                )

        with self._pool_lock:
            for server_name, event in cleanup_events.items():
                current = self._transitions.get(server_name)
                if current is event:
                    self._transitions.pop(server_name, None)
                    event.set()
