"""Tests for Salesforce CRM tool - Leads, Contacts, Accounts, Opportunities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.salesforce_tool.salesforce_tool import (
    _SalesforceClient,
    _build_search_soql,
    _sanitize_field_list,
    _sanitize_search_query,
    _validate_record_id,
    _VALID_SOBJECTS,
    register_tools,
)


# --- _validate_record_id ---


def test_validate_record_id_valid_15():
    assert _validate_record_id("001000000000001") is None


def test_validate_record_id_valid_18():
    assert _validate_record_id("001000000000001AAA") is None


def test_validate_record_id_invalid_length():
    assert "15 or 18" in (_validate_record_id("001") or "")
    assert "15 or 18" in (_validate_record_id("001000000000001AAAA") or "")


def test_validate_record_id_invalid_chars():
    assert "alphanumeric" in (_validate_record_id("001-000-000") or "")


def test_validate_record_id_empty():
    assert _validate_record_id("") is not None


# --- _sanitize_search_query ---


def test_sanitize_search_query_allows_alnum_space_hyphen_underscore():
    assert _sanitize_search_query("acme corp_1") == "acme corp_1"


def test_sanitize_search_query_strips_dangerous():
    result = _sanitize_search_query("acme; DROP TABLE Lead;")
    assert ";" not in result  # SOQL injection delimiter stripped
    assert "acme" in result


# --- _sanitize_field_list ---


def test_sanitize_field_list_allows_valid_identifiers():
    assert _sanitize_field_list(["Id", "Name", "Custom_Field__c"]) == ["Id", "Name", "Custom_Field__c"]


def test_sanitize_field_list_rejects_injection():
    result = _sanitize_field_list(["Id", "Name; DROP TABLE Lead"])
    assert not any(";" in f for f in result)


# --- _build_search_soql ---


def test_build_search_soql_with_query():
    soql = _build_search_soql("Lead", ["Id", "Name"], "acme", 10)
    assert "SELECT" in soql
    assert "Lead" in soql
    assert "acme" in soql
    assert "LIMIT 10" in soql


def test_build_search_soql_limit_capped():
    soql = _build_search_soql("Contact", ["Id"], "", 300)
    assert "LIMIT 200" in soql


def test_build_search_soql_invalid_sobject_falls_back():
    soql = _build_search_soql("InvalidObj", ["Id"], "", 10)
    assert "Lead" in soql


# --- _SalesforceClient ---


class TestSalesforceClient:
    def setup_method(self):
        self.client = _SalesforceClient("https://test.salesforce.com", "test-token")

    def test_api_path(self):
        assert "v59.0" in self.client._api_path
        assert "test.salesforce.com" in self.client._api_path

    def test_headers_authorization_set(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test-token"

    def test_handle_response_401_generic(self):
        response = MagicMock()
        response.status_code = 401
        result = self.client._handle_response(response)
        assert "error" in result
        assert "token" in result["error"].lower()
        assert "test-token" not in result["error"]

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    @patch("aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get")
    def test_query(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"totalSize": 1, "records": [{"Id": "001", "Name": "Acme"}]}
        mock_get.return_value = mock_response
        result = self.client.query("SELECT Id, Name FROM Account LIMIT 10")
        mock_get.assert_called_once()
        assert result["totalSize"] == 1

    @patch("aden_tools.tools.salesforce_tool.salesforce_tool.httpx.get")
    def test_get_record_valid_id(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Id": "001000000000001", "Name": "Acme"}
        mock_get.return_value = mock_response
        result = self.client.get_record("Account", "001000000000001")
        assert result["Name"] == "Acme"

    def test_get_record_invalid_sobject(self):
        result = self.client.get_record("BadObj", "001000000000001")
        assert "error" in result
        assert "Invalid sobject" in result["error"]

    def test_get_record_invalid_id(self):
        result = self.client.get_record("Account", "bad-id")
        assert "error" in result
        assert "Record ID" in result["error"]

    @patch("aden_tools.tools.salesforce_tool.salesforce_tool.httpx.patch")
    def test_update_record_invalid_id(self, mock_patch):
        result = self.client.update_record("Lead", "x" * 10, {"Status": "Qualified"})
        assert "error" in result
        mock_patch.assert_not_called()


# --- Registration ---


def test_register_tools_runs_without_error(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    assert mcp is not None


def test_register_tools_with_credential_store_dict(mcp: FastMCP):
    class MockCreds:
        def get(self, key: str):
            if key == "salesforce":
                return {"instance_url": "https://x.salesforce.com", "access_token": "tok"}
            return None

    register_tools(mcp, credentials=MockCreds())
    assert mcp is not None


def test_valid_sobjects_const():
    assert _VALID_SOBJECTS == frozenset({"Lead", "Contact", "Account", "Opportunity"})
