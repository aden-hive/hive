"""
Tests for Health Server.

Tests cover:
- Server lifecycle (start/stop)
- Health endpoints (/health, /health/live, /health/ready)
- HTTP response format
- Error handling
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from framework.runtime.agent_runtime import AgentRuntime, AgentState
from framework.runtime.health_server import HealthServer, create_health_server

# === FIXTURES ===


@pytest.fixture
def mock_graph():
    """Create a mock graph spec."""
    graph = MagicMock()
    graph.get_node = MagicMock(return_value=MagicMock())
    return graph


@pytest.fixture
def mock_goal():
    """Create a mock goal."""
    goal = MagicMock()
    goal.id = "test-goal"
    return goal


@pytest.fixture
def mock_storage(tmp_path):
    """Create a temporary storage path."""
    return tmp_path / "storage"


async def http_get(host: str, port: int, path: str) -> tuple[int, str, dict]:
    """
    Make a simple HTTP GET request.

    Returns:
        Tuple of (status_code, body, headers)
    """
    reader, writer = await asyncio.open_connection(host, port)

    try:
        # Send request
        request = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()

        # Read response
        response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        response_str = response.decode("utf-8")

        # Parse status line
        lines = response_str.split("\r\n")
        status_line = lines[0]
        status_code = int(status_line.split(" ")[1])

        # Find body (after empty line)
        body_start = response_str.find("\r\n\r\n")
        body = response_str[body_start + 4 :] if body_start != -1 else ""

        # Parse headers
        headers = {}
        for line in lines[1:]:
            if line == "":
                break
            if ": " in line:
                key, value = line.split(": ", 1)
                headers[key.lower()] = value

        return status_code, body, headers

    finally:
        writer.close()
        await writer.wait_closed()


# === SERVER LIFECYCLE TESTS ===


class TestHealthServerLifecycle:
    """Tests for server start/stop."""

    @pytest.mark.asyncio
    async def test_server_start(self, mock_graph, mock_goal, mock_storage):
        """Server starts and is_running becomes True."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        server = HealthServer(runtime, port=0)  # Port 0 = random available port

        try:
            await server.start()
            assert server.is_running
        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_server_stop(self, mock_graph, mock_goal, mock_storage):
        """Server stops and is_running becomes False."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        server = HealthServer(runtime, port=0)
        await server.start()
        await server.stop()

        assert not server.is_running

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_server_context_manager(self, mock_graph, mock_goal, mock_storage):
        """Server works as async context manager."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        async with HealthServer(runtime, port=0) as server:
            assert server.is_running

        assert not server.is_running

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_factory_function(self, mock_graph, mock_goal, mock_storage):
        """Factory creates and starts server."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        server = await create_health_server(runtime, port=0)

        try:
            assert server.is_running
        finally:
            await server.stop()
            await runtime.stop()


# === HEALTH ENDPOINT TESTS ===


class TestHealthEndpoints:
    """Tests for HTTP health endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, mock_graph, mock_goal, mock_storage):
        """GET /health returns full health status."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        # Use a specific port for testing
        port = 18080
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, headers = await http_get("127.0.0.1", port, "/health")

            assert status_code == 200
            assert headers["content-type"] == "application/json"

            data = json.loads(body)
            assert "status" in data
            assert "state" in data
            assert "uptime_seconds" in data
            assert data["status"] == "healthy"
            assert data["state"] == "ready"

        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_liveness_endpoint_healthy(self, mock_graph, mock_goal, mock_storage):
        """GET /health/live returns 200 when healthy."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        port = 18081
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, _ = await http_get("127.0.0.1", port, "/health/live")

            assert status_code == 200
            assert body == "OK"

        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_liveness_endpoint_error_state(
        self, mock_graph, mock_goal, mock_storage
    ):
        """GET /health/live returns 503 in ERROR state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        # Force error state
        runtime._state = AgentState.ERROR

        port = 18082
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, _ = await http_get("127.0.0.1", port, "/health/live")

            assert status_code == 503
            assert body == "Service Unavailable"

        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_readiness_endpoint_ready(self, mock_graph, mock_goal, mock_storage):
        """GET /health/ready returns 200 when ready."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        port = 18083
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, _ = await http_get("127.0.0.1", port, "/health/ready")

            assert status_code == 200
            assert body == "OK"

        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_readiness_endpoint_paused(self, mock_graph, mock_goal, mock_storage):
        """GET /health/ready returns 503 when paused."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()
        await runtime.pause()

        port = 18084
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, _ = await http_get("127.0.0.1", port, "/health/ready")

            assert status_code == 503
            assert body == "Service Unavailable"

        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_root_redirects_to_health(self, mock_graph, mock_goal, mock_storage):
        """GET / returns health status."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        port = 18085
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, headers = await http_get("127.0.0.1", port, "/")

            assert status_code == 200
            assert headers["content-type"] == "application/json"

        finally:
            await server.stop()
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_not_found(self, mock_graph, mock_goal, mock_storage):
        """GET /unknown returns 404."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        await runtime.start()

        port = 18086
        server = HealthServer(runtime, host="127.0.0.1", port=port)
        await server.start()

        try:
            status_code, body, _ = await http_get("127.0.0.1", port, "/unknown")

            assert status_code == 404
            assert body == "Not Found"

        finally:
            await server.stop()
            await runtime.stop()


# === SERVER PROPERTIES TESTS ===


class TestHealthServerProperties:
    """Tests for server properties."""

    @pytest.mark.asyncio
    async def test_port_property(self, mock_graph, mock_goal, mock_storage):
        """Port property returns configured port."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        server = HealthServer(runtime, port=9999)
        assert server.port == 9999

    @pytest.mark.asyncio
    async def test_url_property(self, mock_graph, mock_goal, mock_storage):
        """URL property returns base URL."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        server = HealthServer(runtime, host="127.0.0.1", port=8080)
        assert server.url == "http://127.0.0.1:8080"

    @pytest.mark.asyncio
    async def test_url_property_all_interfaces(self, mock_graph, mock_goal, mock_storage):
        """URL property converts 0.0.0.0 to localhost."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        server = HealthServer(runtime, host="0.0.0.0", port=8080)
        assert server.url == "http://localhost:8080"
