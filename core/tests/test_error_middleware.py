"""
Tests for error_middleware in framework.server.app.

Verifies that the error middleware does NOT leak internal exception
details (file paths, config values, stack traces) to HTTP clients.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.server.app import error_middleware

# ---------------------------------------------------------------------------
# Handlers used in tests
# ---------------------------------------------------------------------------


async def _handler_raise_value_error(request: web.Request) -> web.Response:
    """Handler that raises ValueError with sensitive path info."""
    raise ValueError("/home/user/.hive/credentials/secret_key.json not found")


async def _handler_raise_runtime_error(request: web.Request) -> web.Response:
    """Handler that raises RuntimeError with internal details."""
    raise RuntimeError("Connection to postgres://admin:s3cret@db:5432/hive failed")


async def _handler_raise_key_error(request: web.Request) -> web.Response:
    """Handler that raises KeyError with config key name."""
    raise KeyError("ANTHROPIC_API_KEY")


async def _handler_success(request: web.Request) -> web.Response:
    """Handler that returns a normal 200 response."""
    return web.json_response({"status": "ok"})


async def _handler_http_not_found(request: web.Request) -> web.Response:
    """Handler that raises aiohttp's HTTP 404."""
    raise web.HTTPNotFound(reason="Agent not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> web.Application:
    """Create a minimal aiohttp app with error_middleware and test routes."""
    app = web.Application(middlewares=[error_middleware])
    app.router.add_get("/value-error", _handler_raise_value_error)
    app.router.add_get("/runtime-error", _handler_raise_runtime_error)
    app.router.add_get("/key-error", _handler_raise_key_error)
    app.router.add_get("/success", _handler_success)
    app.router.add_get("/not-found", _handler_http_not_found)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestErrorMiddlewareInfoLeak:
    """Verify error_middleware returns generic messages, not internal details."""

    @pytest.mark.asyncio
    async def test_does_not_leak_file_paths(self):
        """ValueError with file path must not appear in response body."""
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/value-error")
            assert resp.status == 500
            body = await resp.json()
            assert body["error"] == "Internal server error"
            # Ensure no sensitive details leaked
            assert ".hive" not in body["error"]
            assert "secret_key" not in body["error"]
            assert "type" not in body  # type field should not exist

    @pytest.mark.asyncio
    async def test_does_not_leak_connection_strings(self):
        """RuntimeError with DB connection string must not appear in response."""
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/runtime-error")
            assert resp.status == 500
            body = await resp.json()
            assert body["error"] == "Internal server error"
            assert "postgres" not in body["error"]
            assert "s3cret" not in body["error"]

    @pytest.mark.asyncio
    async def test_does_not_leak_env_var_names(self):
        """KeyError with env var name must not appear in response body."""
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/key-error")
            assert resp.status == 500
            body = await resp.json()
            assert body["error"] == "Internal server error"
            assert "ANTHROPIC_API_KEY" not in body["error"]

    @pytest.mark.asyncio
    async def test_does_not_leak_exception_type(self):
        """Response must not include the Python exception type name."""
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/value-error")
            body = await resp.json()
            assert "type" not in body
            assert "ValueError" not in str(body)

    @pytest.mark.asyncio
    async def test_success_response_unchanged(self):
        """Normal 200 responses must pass through untouched."""
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/success")
            assert resp.status == 200
            body = await resp.json()
            assert body == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_http_exceptions_pass_through(self):
        """aiohttp HTTPExceptions (404, etc.) must not be caught."""
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/not-found")
            assert resp.status == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
