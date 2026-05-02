import os
import pytest
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import patch, MagicMock

# Import the code to test
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.browser_remote import create_app


class TestBrowserRemoteAuth:
    async def setup_client(self):
        # Mock get_mcp_client to avoid real connection
        self.mock_get_patcher = patch("scripts.browser_remote.get_mcp_client")
        self.mock_get = self.mock_get_patcher.start()
        self.mock_client = MagicMock()
        self.mock_client.list_tools.return_value = []
        self.mock_get.return_value = self.mock_client

        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        return self.client

    async def teardown_client(self):
        await self.client.close()
        self.mock_get_patcher.stop()

    @pytest.mark.asyncio
    async def test_status_no_auth_required(self):
        """GET /status should always be accessible."""
        cli = await self.setup_client()
        try:
            resp = await cli.get("/status")
            assert resp.status == 200
            data = await resp.json()
            assert "connected" in data
        finally:
            await self.teardown_client()

    @pytest.mark.asyncio
    async def test_post_requires_auth_when_token_set(self):
        """POST actions should require BROWSER_REMOTE_TOKEN if it's set in env."""
        cli = await self.setup_client()
        try:
            with patch.dict(os.environ, {"BROWSER_REMOTE_TOKEN": "secret-token"}):
                # No token
                resp = await cli.post("/browser_click", json={"selector": "body"})
                assert resp.status == 401

                # Wrong token
                resp = await cli.post(
                    "/browser_click", json={"selector": "body"}, headers={"Authorization": "Bearer wrong"}
                )
                assert resp.status == 401

                # Correct token
                resp = await cli.post(
                    "/browser_click", json={"selector": "body"}, headers={"Authorization": "Bearer secret-token"}
                )
                assert resp.status == 200
        finally:
            await self.teardown_client()

    @pytest.mark.asyncio
    async def test_post_no_auth_when_token_unset(self):
        """POST actions should NOT require auth if BROWSER_REMOTE_TOKEN is empty."""
        cli = await self.setup_client()
        try:
            with patch.dict(os.environ, {"BROWSER_REMOTE_TOKEN": ""}):
                resp = await cli.post("/browser_click", json={"selector": "body"})
                assert resp.status == 200
        finally:
            await self.teardown_client()

    @pytest.mark.asyncio
    async def test_cors_origin_restriction(self):
        """Origin must be localhost or 127.0.0.1."""
        cli = await self.setup_client()
        try:
            with patch.dict(os.environ, {"BROWSER_REMOTE_TOKEN": ""}):
                # Allowed origin
                resp = await cli.post("/browser_click", headers={"Origin": "http://localhost:3000"})
                assert resp.status == 200

                # Forbidden origin
                resp = await cli.post("/browser_click", headers={"Origin": "http://evil.com"})
                assert resp.status == 403
                data = await resp.json()
                assert data["error"] == "Forbidden origin"
        finally:
            await self.teardown_client()

    @pytest.mark.asyncio
    async def test_options_restriction(self):
        """OPTIONS requests should also respect origin restriction."""
        cli = await self.setup_client()
        try:
            # Allowed origin
            resp = await cli.options("/browser_click", headers={"Origin": "http://localhost:3000"})
            assert resp.status == 200

            # Forbidden origin
            resp = await cli.options("/browser_click", headers={"Origin": "http://evil.com"})
            assert resp.status == 403
        finally:
            await self.teardown_client()
