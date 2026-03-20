"""Tests for cloudflare tools."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.credentials.cloudflare import CLOUDFLARE_CREDENTIALS
from aden_tools.tools.cloudflare_tool.cloudflare_tool import register_tools


@pytest.fixture
def tools_registry(mcp: FastMCP):
    """Register and return all cloudflare tools."""
    register_tools(mcp)
    return mcp._tool_manager._tools


def _mock_success_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "result": []}
    return mock_resp


class TestCloudflareIntegration:
    def test_spec_tools_registered(self, tools_registry):
        """Ensure every tool listed in the credential spec is registered."""
        spec = CLOUDFLARE_CREDENTIALS.get("cloudflare")
        assert spec is not None
        spec_tools = getattr(spec, "tools", []) or []
        for t in spec_tools:
            assert t in tools_registry


class TestCloudflareTools:
    """Tests for all 54 Cloudflare tools."""

    def test_cloudflare_list_zones(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_zones"].fn
            result = fn()
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_zone(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_zone"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_zone_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_zone_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_zone_custom_pages(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_zone_custom_pages"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_ssl_verification(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_ssl_verification"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_zone_certificates(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_zone_certificates"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_zone_subscriptions(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_zone_subscriptions"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_dnssec_status(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_dnssec_status"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_update_zone_setting(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_update_zone_setting"].fn
            result = fn(zone_id="z_test", setting_id="ssl", value="on")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_dns_records(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_dns_records"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_dns_record(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_dns_record"].fn
            result = fn(zone_id="z_test", record_id="r_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_dns_record_scan(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_dns_record_scan"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_dns_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_dns_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_dns_analytics_report(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_dns_analytics_report"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_check_domain_dns_health(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_check_domain_dns_health"].fn
            result = fn(domain="example.com")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_create_dns_record(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_create_dns_record"].fn
            result = fn(zone_id="z_test", type="A", name="x", content="1.2.3.4")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_update_dns_record(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_update_dns_record"].fn
            result = fn(zone_id="z_test", record_id="r_test", content="1.2.3.5")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_delete_dns_record(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_delete_dns_record"].fn
            result = fn(zone_id="z_test", record_id="r_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_zone_analytics(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_zone_analytics"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_top_analytics(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_top_analytics"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_security_analytics(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_security_analytics"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_cache_analytics(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_cache_analytics"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_performance_analytics(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_performance_analytics"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_http_analytics_report(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_http_analytics_report"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_firewall_events(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_firewall_events"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_security_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_security_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_page_rules(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_page_rules"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_waf_rulesets(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_waf_rulesets"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_bot_management_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_bot_management_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_managed_transforms(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_managed_transforms"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_ddos_protection_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_ddos_protection_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_create_firewall_rule(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_create_firewall_rule"].fn
            result = fn(zone_id="z_test", action="block", expression="ip.src eq 1.2.3.4")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_delete_firewall_rule(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_delete_firewall_rule"].fn
            result = fn(zone_id="z_test", rule_id="rule1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_speed_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_speed_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_cache_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_cache_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_http_config(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_http_config"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_network_settings(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_network_settings"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_purge_cache_all(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_purge_cache_all"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_purge_cache_files(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_purge_cache_files"].fn
            result = fn(zone_id="z_test", urls=["https://example.com/a"])
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_advanced_services(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_advanced_services"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_accounts(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_accounts"].fn
            result = fn()
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_get_account_details(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_get_account_details"].fn
            result = fn(account_id="acct1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_account_members(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_account_members"].fn
            result = fn(account_id="acct1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_invite_account_member(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_invite_account_member"].fn
            result = fn(account_id="acct1", email="a@b.com", roles=["admin"])
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_delete_account_member(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_delete_account_member"].fn
            result = fn(account_id="acct1", member_id="m1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_custom_hostnames(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_custom_hostnames"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_audit_logs(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_audit_logs"].fn
            result = fn(account_id="acct1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_firewall_rules(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_firewall_rules"].fn
            result = fn(zone_id="z_test")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_access_applications(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_access_applications"].fn
            result = fn(account_id="acct1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_r2_buckets(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_r2_buckets"].fn
            result = fn(account_id="acct1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_list_pages_projects(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_list_pages_projects"].fn
            result = fn(account_id="acct1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_create_access_policy(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_create_access_policy"].fn
            result = fn(
                account_id="acct1", application_id="app1", name="p1", decision="allow", include=[]
            )
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_create_worker_route(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_create_worker_route"].fn
            result = fn(zone_id="z_test", pattern="api.example.com/*", script_name="s1")
            if isinstance(result, dict):
                assert "error" not in result

    def test_cloudflare_set_ssl_mode(self, tools_registry, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-key")
        with (
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_zone_id",
                return_value=None,
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool.httpx.request",
                return_value=_mock_success_response(),
            ),
            patch(
                "aden_tools.tools.cloudflare_tool.cloudflare_tool._validate_domain",
                return_value=None,
            ),
        ):
            fn = tools_registry["cloudflare_set_ssl_mode"].fn
            result = fn(zone_id="z_test", mode="full")
            if isinstance(result, dict):
                assert "error" not in result
