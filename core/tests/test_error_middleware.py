from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.server.app import error_middleware


@pytest.mark.asyncio
class TestErrorMiddleware:
    async def test_does_not_leak_file_paths(self) -> None:
        async def handler_with_file_error(request: web.Request) -> web.Response:
            raise FileNotFoundError("/home/user/.hive/credentials/secret_key.json not found")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/", handler_with_file_error)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 500
            body = await resp.json()
            assert body == {"error": "Internal server error"}

    async def test_does_not_leak_connection_strings(self) -> None:
        async def handler_with_db_error(request: web.Request) -> web.Response:
            raise ConnectionError("Failed to connect to postgres://user:password@localhost/db")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/", handler_with_db_error)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 500
            body = await resp.json()
            assert body == {"error": "Internal server error"}

    async def test_does_not_leak_env_var_names(self) -> None:
        async def handler_with_env_error(request: web.Request) -> web.Response:
            raise KeyError("ANTHROPIC_API_KEY")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/", handler_with_env_error)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 500
            body = await resp.json()
            assert body == {"error": "Internal server error"}

    async def test_does_not_leak_exception_type(self) -> None:
        async def handler_with_custom_error(request: web.Request) -> web.Response:
            class CustomInternalException(Exception):
                pass
            raise CustomInternalException("Some internal logic failed")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/", handler_with_custom_error)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 500
            body = await resp.json()
            assert body == {"error": "Internal server error"}

    async def test_success_response_unchanged(self) -> None:
        async def dummy_handler(request: web.Request) -> web.Response:
            return web.json_response({"status": "ok"})

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/", dummy_handler)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            body = await resp.json()
            assert body == {"status": "ok"}

    async def test_http_exceptions_pass_through(self) -> None:
        async def handler_raising_404(request: web.Request) -> web.Response:
            raise web.HTTPNotFound(reason="Resource not found")

        app = web.Application(middlewares=[error_middleware])
        app.router.add_get("/", handler_raising_404)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 404
            assert resp.reason == "Resource not found"
