"""
Tests for Cloudflare tool.

Covers:
- _CloudflareClient methods (zones, DNS records, cache purge)
- Error handling (401, 403, 404, 429, API-level errors)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 7 MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.cloudflare_tool import (
    _CloudflareClient,
    register_tools,
)


# --- Helper to build Cloudflare-style API responses ---


def _cf_ok(result: dict | list) -> dict:
    """Build a successful Cloudflare API response body."""
    return {"success": True, "errors": [], "messages": [], "result": result}


def _cf_error(code: int, message: str) -> dict:
    """Build a Cloudflare API error response body."""
    return {"success": False, "errors": [{"code": code, "message": message}]}


def _mock_response(status_code: int = 200, json_data: dict | list | None = None) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = str(json_data or "")
    return resp


# --- _CloudflareClient unit tests ---


class TestCloudflareClient:
    def setup_method(self):
        self.client = _CloudflareClient("test-token-abc")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test-token-abc"
        assert headers["Content-Type"] == "application/json"

    def test_handle_response_success(self):
        zone = {"id": "z1", "name": "example.com", "status": "active"}
        resp = _mock_response(200, _cf_ok(zone))
        result = self.client._handle_response(resp)
        assert result["success"] is True
        assert result["data"]["name"] == "example.com"

    def test_handle_response_401(self):
        resp = _mock_response(401)
        result = self.client._handle_response(resp)
        assert "error" in result
        assert "Invalid" in result["error"]

    def test_handle_response_403(self):
        resp = _mock_response(403)
        result = self.client._handle_response(resp)
        assert "error" in result
        assert "Forbidden" in result["error"]

    def test_handle_response_404(self):
        resp = _mock_response(404)
        result = self.client._handle_response(resp)
        assert "error" in result
        assert "not found" in result["error"]

    def test_handle_response_429(self):
        resp = _mock_response(429)
        result = self.client._handle_response(resp)
        assert "error" in result
        assert "Rate limit" in result["error"]

    def test_handle_response_api_error(self):
        resp = _mock_response(200, _cf_error(1003, "Invalid zone identifier"))
        result = self.client._handle_response(resp)
        assert "error" in result
        assert "Invalid zone identifier" in result["error"]

    def test_handle_response_server_error(self):
        resp = _mock_response(500, {"errors": [{"message": "Internal error"}]})
        result = self.client._handle_response(resp)
        assert "error" in result
        assert "500" in result["error"]

    # --- Zone operations ---

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_zones(self, mock_get):
        zones = [
            {"id": "z1", "name": "example.com", "status": "active"},
            {"id": "z2", "name": "test.io", "status": "pending"},
        ]
        mock_get.return_value = _mock_response(200, _cf_ok(zones))
        result = self.client.list_zones()
        assert result["success"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["name"] == "example.com"

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_zones_with_filters(self, mock_get):
        mock_get.return_value = _mock_response(200, _cf_ok([]))
        self.client.list_zones(name="example.com", status="active", page=2, per_page=10)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["name"] == "example.com"
        assert kwargs["params"]["status"] == "active"
        assert kwargs["params"]["page"] == 2
        assert kwargs["params"]["per_page"] == 10

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_get_zone(self, mock_get):
        zone = {"id": "z1", "name": "example.com", "status": "active", "name_servers": ["ns1"]}
        mock_get.return_value = _mock_response(200, _cf_ok(zone))
        result = self.client.get_zone("z1")
        assert result["success"] is True
        assert result["data"]["id"] == "z1"

    # --- DNS record operations ---

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_dns_records(self, mock_get):
        records = [
            {"id": "r1", "type": "A", "name": "example.com", "content": "1.2.3.4"},
            {"id": "r2", "type": "CNAME", "name": "www.example.com", "content": "example.com"},
        ]
        mock_get.return_value = _mock_response(200, _cf_ok(records))
        result = self.client.list_dns_records("z1")
        assert result["success"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["type"] == "A"

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_dns_records_with_type_filter(self, mock_get):
        mock_get.return_value = _mock_response(200, _cf_ok([]))
        self.client.list_dns_records("z1", record_type="MX", name="example.com")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["type"] == "MX"
        assert kwargs["params"]["name"] == "example.com"

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_create_dns_record(self, mock_post):
        record = {"id": "r10", "type": "A", "name": "blog.example.com", "content": "1.2.3.4"}
        mock_post.return_value = _mock_response(200, _cf_ok(record))
        result = self.client.create_dns_record("z1", "A", "blog.example.com", "1.2.3.4")
        assert result["success"] is True
        assert result["data"]["name"] == "blog.example.com"

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_create_dns_record_with_priority(self, mock_post):
        mock_post.return_value = _mock_response(200, _cf_ok({"id": "r11", "type": "MX"}))
        self.client.create_dns_record(
            "z1", "MX", "example.com", "mail.example.com", priority=10
        )
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["priority"] == 10
        assert kwargs["json"]["type"] == "MX"

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.patch")
    def test_update_dns_record(self, mock_patch):
        record = {"id": "r1", "type": "A", "name": "example.com", "content": "5.6.7.8"}
        mock_patch.return_value = _mock_response(200, _cf_ok(record))
        result = self.client.update_dns_record("z1", "r1", "A", "example.com", "5.6.7.8")
        assert result["success"] is True
        assert result["data"]["content"] == "5.6.7.8"

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.delete")
    def test_delete_dns_record(self, mock_delete):
        mock_delete.return_value = _mock_response(200, _cf_ok({"id": "r1"}))
        result = self.client.delete_dns_record("z1", "r1")
        assert result["success"] is True

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.delete")
    def test_delete_dns_record_not_found(self, mock_delete):
        mock_delete.return_value = _mock_response(404)
        result = self.client.delete_dns_record("z1", "bad-id")
        assert "error" in result

    # --- Cache purge ---

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_purge_cache_everything(self, mock_post):
        mock_post.return_value = _mock_response(200, _cf_ok({"id": "purge-1"}))
        result = self.client.purge_cache("z1", purge_everything=True)
        assert result["success"] is True
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["purge_everything"] is True

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_purge_cache_specific_files(self, mock_post):
        mock_post.return_value = _mock_response(200, _cf_ok({"id": "purge-2"}))
        urls = ["https://example.com/style.css", "https://example.com/app.js"]
        result = self.client.purge_cache("z1", files=urls)
        assert result["success"] is True
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["files"] == urls

    def test_purge_cache_no_target(self):
        result = self.client.purge_cache("z1")
        assert "error" in result
        assert "Specify" in result["error"]


# --- Tool registration and MCP function tests ---


class TestCloudflareListZonesTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_zones_success(self, mock_get):
        zones = [{"id": "z1", "name": "example.com", "status": "active"}]
        mock_get.return_value = _mock_response(200, _cf_ok(zones))
        result = self._fn("cloudflare_list_zones")()
        assert result["success"] is True
        assert result["data"][0]["name"] == "example.com"

    def test_list_zones_no_credentials(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        register_tools(mcp, credentials=None)
        with patch.dict("os.environ", {"CLOUDFLARE_API_TOKEN": ""}, clear=False):
            result = next(f for f in fns if f.__name__ == "cloudflare_list_zones")()
        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result


class TestCloudflareGetZoneTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_get_zone_success(self, mock_get):
        zone = {"id": "z1", "name": "example.com", "status": "active"}
        mock_get.return_value = _mock_response(200, _cf_ok(zone))
        result = self._fn("cloudflare_get_zone")("z1")
        assert result["success"] is True
        assert result["data"]["id"] == "z1"


class TestCloudflareListDnsRecordsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_dns_records_success(self, mock_get):
        records = [{"id": "r1", "type": "A", "name": "example.com", "content": "1.2.3.4"}]
        mock_get.return_value = _mock_response(200, _cf_ok(records))
        result = self._fn("cloudflare_list_dns_records")("z1")
        assert result["success"] is True
        assert len(result["data"]) == 1

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.get")
    def test_list_dns_records_with_type_filter(self, mock_get):
        mock_get.return_value = _mock_response(200, _cf_ok([]))
        self._fn("cloudflare_list_dns_records")("z1", record_type="TXT")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["type"] == "TXT"


class TestCloudflareCreateDnsRecordTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_create_a_record(self, mock_post):
        record = {"id": "r10", "type": "A", "name": "blog.example.com", "content": "1.2.3.4"}
        mock_post.return_value = _mock_response(200, _cf_ok(record))
        result = self._fn("cloudflare_create_dns_record")(
            "z1", record_type="A", name="blog.example.com", content="1.2.3.4"
        )
        assert result["success"] is True

    def test_create_invalid_record_type(self):
        result = self._fn("cloudflare_create_dns_record")(
            "z1", record_type="INVALID", name="x.example.com", content="1.2.3.4"
        )
        assert "error" in result
        assert "Invalid record type" in result["error"]

    def test_create_mx_without_priority(self):
        result = self._fn("cloudflare_create_dns_record")(
            "z1", record_type="MX", name="example.com", content="mail.example.com"
        )
        assert "error" in result
        assert "priority" in result["error"].lower()

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_create_mx_with_priority(self, mock_post):
        record = {"id": "r11", "type": "MX", "name": "example.com"}
        mock_post.return_value = _mock_response(200, _cf_ok(record))
        result = self._fn("cloudflare_create_dns_record")(
            "z1", record_type="MX", name="example.com", content="mail.example.com", priority=10
        )
        assert result["success"] is True


class TestCloudflareUpdateDnsRecordTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.patch")
    def test_update_record_success(self, mock_patch):
        record = {"id": "r1", "type": "A", "name": "example.com", "content": "9.8.7.6"}
        mock_patch.return_value = _mock_response(200, _cf_ok(record))
        result = self._fn("cloudflare_update_dns_record")(
            "z1", record_id="r1", record_type="A", name="example.com", content="9.8.7.6"
        )
        assert result["success"] is True
        assert result["data"]["content"] == "9.8.7.6"


class TestCloudflareDeleteDnsRecordTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.delete")
    def test_delete_record_success(self, mock_delete):
        mock_delete.return_value = _mock_response(200, _cf_ok({"id": "r1"}))
        result = self._fn("cloudflare_delete_dns_record")("z1", record_id="r1")
        assert result["success"] is True


class TestCloudflarePurgeCacheTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-cf-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_purge_everything(self, mock_post):
        mock_post.return_value = _mock_response(200, _cf_ok({"id": "purge-1"}))
        result = self._fn("cloudflare_purge_cache")("z1", purge_everything=True)
        assert result["success"] is True

    @patch("aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.post")
    def test_purge_specific_files(self, mock_post):
        mock_post.return_value = _mock_response(200, _cf_ok({"id": "purge-2"}))
        result = self._fn("cloudflare_purge_cache")(
            "z1", files=["https://example.com/style.css"]
        )
        assert result["success"] is True

    def test_purge_no_target_returns_error(self):
        result = self._fn("cloudflare_purge_cache")("z1")
        assert "error" in result
        assert "Specify" in result["error"]


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_cloudflare_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "cloudflare" in CREDENTIAL_SPECS

    def test_cloudflare_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["cloudflare"]
        assert spec.env_var == "CLOUDFLARE_API_TOKEN"

    def test_cloudflare_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["cloudflare"]
        expected = [
            "cloudflare_list_zones",
            "cloudflare_get_zone",
            "cloudflare_list_dns_records",
            "cloudflare_create_dns_record",
            "cloudflare_update_dns_record",
            "cloudflare_delete_dns_record",
            "cloudflare_purge_cache",
        ]
        for tool in expected:
            assert tool in spec.tools
        assert len(spec.tools) == 7
