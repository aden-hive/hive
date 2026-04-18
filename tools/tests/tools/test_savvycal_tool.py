"""Tests for SavvyCal tool."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastmcp import FastMCP
from aden_tools.tools.savvycal_tool import register_tools

PATCH_TARGET = "aden_tools.tools.savvycal_tool.savvycal_tool.httpx.AsyncClient.request"


@pytest.fixture
def mcp():
    return FastMCP("test-savvycal")


@pytest.fixture
def savvycal_tools(mcp: FastMCP, monkeypatch):
    monkeypatch.setenv("SAVVYCAL_API_KEY", "test-api-key")
    register_tools(mcp)
    return {
        "list_links":     mcp._tool_manager._tools["savvycal_list_links"].fn,
        "get_link":       mcp._tool_manager._tools["savvycal_get_link"].fn,
        "create_link":    mcp._tool_manager._tools["savvycal_create_link"].fn,
        "update_link":    mcp._tool_manager._tools["savvycal_update_link"].fn,
        "delete_link":    mcp._tool_manager._tools["savvycal_delete_link"].fn,
        "list_bookings":  mcp._tool_manager._tools["savvycal_list_bookings"].fn,
        "get_booking":    mcp._tool_manager._tools["savvycal_get_booking"].fn,
        "cancel_booking": mcp._tool_manager._tools["savvycal_cancel_booking"].fn,
    }


def _ok_response(data):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()  # does NOT raise
    resp.json.return_value = data
    return resp


def _error_response(status_code: int, message: str = "Error"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps({"message": message})
    resp.json.return_value = {"message": message}
    error = httpx.HTTPStatusError("HTTP Error", request=MagicMock(), response=resp)
    resp.raise_for_status.side_effect = error
    return resp


class TestToolRegistration:
    def test_all_tools_registered(self, mcp, monkeypatch):
        monkeypatch.setenv("SAVVYCAL_API_KEY", "test-key")
        register_tools(mcp)
        expected = [
            "savvycal_list_links", "savvycal_get_link", "savvycal_create_link",
            "savvycal_update_link", "savvycal_delete_link", "savvycal_list_bookings",
            "savvycal_get_booking", "savvycal_cancel_booking",
        ]
        for name in expected:
            assert name in mcp._tool_manager._tools


class TestCredentialHandling:
    @pytest.mark.asyncio
    async def test_no_credentials_returns_error(self, mcp, monkeypatch):
        monkeypatch.delenv("SAVVYCAL_API_KEY", raising=False)
        register_tools(mcp)
        fn = mcp._tool_manager._tools["savvycal_list_links"].fn
        result = await fn()
        assert result["success"] is False
        assert "not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_credentials_from_store(self, mcp, monkeypatch):
        monkeypatch.delenv("SAVVYCAL_API_KEY", raising=False)
        creds = MagicMock()
        creds.get.return_value = "store-key"
        register_tools(mcp, credentials=creds)
        with patch(PATCH_TARGET, new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _ok_response({"links": []})
            fn = mcp._tool_manager._tools["savvycal_list_links"].fn
            await fn()
            creds.get.assert_called_with("savvycal")


class TestErrorResponses:
    @pytest.mark.asyncio
    async def test_401_unauthorized(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _error_response(401)
            result = await savvycal_tools["list_links"]()
        assert result["success"] is False
        assert result["status_code"] == 401
        assert "Invalid or expired" in result["error"]

    @pytest.mark.asyncio
    async def test_404_not_found(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _error_response(404)
            result = await savvycal_tools["get_link"](slug="missing")
        assert result["success"] is False
        assert result["status_code"] == 404
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_500_server_error(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock) as mock_req:
            mock_req.return_value = _error_response(500, "Internal Server Error")
            result = await savvycal_tools["list_links"]()
        assert result["success"] is False
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_429_rate_limit_exhausted(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock) as mock_req, \
             patch("asyncio.sleep") as mock_sleep:
            mock_req.return_value = _error_response(429)
            result = await savvycal_tools["list_links"]()
        assert result["success"] is False
        assert result["status_code"] == 429
        assert "Rate limit exceeded" in result["error"]
        assert mock_sleep.call_count == 2  # 3 retries = 2 sleeps

    @pytest.mark.asyncio
    async def test_malformed_json(self, savvycal_tools):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        resp.text = "Gateway Timeout"
        with patch(PATCH_TARGET, new_callable=AsyncMock, return_value=resp):
            result = await savvycal_tools["list_links"]()
        assert result["success"] is False
        assert "Malformed JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout_exception(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   side_effect=httpx.TimeoutException("timeout")):
            result = await savvycal_tools["list_links"]()
        assert result["success"] is False
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_network_exception(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   side_effect=httpx.RequestError("Host down")):
            result = await savvycal_tools["list_links"]()
        assert result["success"] is False
        assert "Network error" in result["error"]


class TestLinks:
    @pytest.mark.asyncio
    async def test_list_links_success(self, savvycal_tools):
        data = [{"id": 1, "slug": "intro-call"}]
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response(data)):
            result = await savvycal_tools["list_links"]()
        assert result["success"] is True
        assert result["data"] == data

    @pytest.mark.asyncio
    async def test_get_link_success(self, savvycal_tools):
        data = {"id": 1, "slug": "intro", "duration": 30}
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response(data)):
            result = await savvycal_tools["get_link"](slug="intro")
        assert result["success"] is True
        assert result["data"] == data

    @pytest.mark.asyncio
    async def test_create_link_missing_name(self, savvycal_tools):
        result = await savvycal_tools["create_link"](name="", duration=30, event_type="type")
        assert result["success"] is False
        assert "name is required" in result["error"]

    @pytest.mark.asyncio
    async def test_create_link_invalid_duration(self, savvycal_tools):
        result = await savvycal_tools["create_link"](name="Intro", duration=0, event_type="type")
        assert result["success"] is False
        assert "positive integer" in result["error"]

    @pytest.mark.asyncio
    async def test_create_link_success(self, savvycal_tools):
        data = {"id": 1, "name": "Intro"}
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response(data)) as mock_req:
            result = await savvycal_tools["create_link"](
                name="Intro", duration=30, event_type="default"
            )
        assert result["success"] is True
        assert mock_req.call_args.kwargs["json"]["name"] == "Intro"
        assert mock_req.call_args.kwargs["json"]["duration"] == 30

    @pytest.mark.asyncio
    async def test_update_link_missing_slug(self, savvycal_tools):
        result = await savvycal_tools["update_link"](slug="")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_update_link_no_fields(self, savvycal_tools):
        result = await savvycal_tools["update_link"](slug="abc")
        assert result["success"] is False
        assert "At least one update field" in result["error"]

    @pytest.mark.asyncio
    async def test_update_link_success(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response({"id": 1})) as mock_req:
            result = await savvycal_tools["update_link"](slug="abc", duration=60)
        assert result["success"] is True
        assert mock_req.call_args.kwargs["json"]["duration"] == 60

    @pytest.mark.asyncio
    async def test_delete_link_success(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response({})) as mock_req:
            result = await savvycal_tools["delete_link"](slug="abc")
        assert result["success"] is True
        mock_req.assert_called_once()


class TestBookings:
    @pytest.mark.asyncio
    async def test_list_bookings_with_filters(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response([])) as mock_req:
            result = await savvycal_tools["list_bookings"](
                start_date="2023-01-01", status="cancelled"
            )
        assert result["success"] is True
        assert mock_req.call_args.kwargs["params"]["start_date"] == "2023-01-01"
        assert mock_req.call_args.kwargs["params"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_get_booking_success(self, savvycal_tools):
        data = {"id": "bkg_123"}
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response(data)):
            result = await savvycal_tools["get_booking"](booking_id="bkg_123")
        assert result["success"] is True
        assert result["data"] == data

    @pytest.mark.asyncio
    async def test_cancel_booking_with_reason(self, savvycal_tools):
        with patch(PATCH_TARGET, new_callable=AsyncMock,
                   return_value=_ok_response({})) as mock_req:
            result = await savvycal_tools["cancel_booking"](
                booking_id="bkg_123", reason="Testing"
            )
        assert result["success"] is True
        assert mock_req.call_args.kwargs["json"]["cancellation_reason"] == "Testing"

    @pytest.mark.asyncio
    async def test_cancel_booking_missing_id(self, savvycal_tools):
        result = await savvycal_tools["cancel_booking"](booking_id="")
        assert result["success"] is False
        assert "booking_id is required" in result["error"]
