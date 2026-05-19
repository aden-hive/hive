"""Tests for azure_sql_tool - Azure SQL Database management."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.azure_sql_tool.azure_sql_tool import register_tools

ENV = {
    "AZURE_SQL_ACCESS_TOKEN": "test-token",
    "AZURE_SUBSCRIPTION_ID": "sub-123",
}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestAzureSQLListServers:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["azure_sql_list_servers"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "value": [
                {
                    "id": (
                        "/subscriptions/sub-123/resourceGroups/rg"
                        "/providers/Microsoft.Sql/servers/myserver"
                    ),
                    "name": "myserver",
                    "location": "eastus",
                    "properties": {
                        "fullyQualifiedDomainName": "myserver.database.windows.net",
                        "state": "Ready",
                        "version": "12.0",
                        "administratorLogin": "adminuser",
                    },
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.azure_sql_tool.azure_sql_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["azure_sql_list_servers"]()

        assert result["count"] == 1
        assert result["servers"][0]["name"] == "myserver"
        assert result["servers"][0]["fqdn"] == "myserver.database.windows.net"


class TestAzureSQLGetServer:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["azure_sql_get_server"](resource_group="", server_name="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": (
                "/subscriptions/sub-123/resourceGroups/rg/providers/Microsoft.Sql/servers/myserver"
            ),
            "name": "myserver",
            "location": "eastus",
            "properties": {
                "fullyQualifiedDomainName": "myserver.database.windows.net",
                "state": "Ready",
                "version": "12.0",
                "administratorLogin": "adminuser",
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.azure_sql_tool.azure_sql_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["azure_sql_get_server"](resource_group="rg", server_name="myserver")

        assert result["name"] == "myserver"
        assert result["state"] == "Ready"


class TestAzureSQLListDatabases:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["azure_sql_list_databases"](resource_group="", server_name="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "value": [
                {
                    "id": "/subscriptions/sub-123/.../databases/mydb",
                    "name": "mydb",
                    "location": "eastus",
                    "sku": {"name": "S0", "tier": "Standard"},
                    "properties": {
                        "status": "Online",
                        "maxSizeBytes": 268435456000,
                        "collation": "SQL_Latin1_General_CP1_CI_AS",
                        "creationDate": "2024-01-15T10:30:00Z",
                        "currentServiceObjectiveName": "S0",
                        "zoneRedundant": False,
                    },
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.azure_sql_tool.azure_sql_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["azure_sql_list_databases"](
                resource_group="rg", server_name="myserver"
            )

        assert result["count"] == 1
        assert result["databases"][0]["name"] == "mydb"
        assert result["databases"][0]["status"] == "Online"
        assert result["databases"][0]["sku_tier"] == "Standard"


class TestAzureSQLGetDatabase:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["azure_sql_get_database"](
                resource_group="", server_name="", database_name=""
            )
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "name": "mydb",
            "location": "eastus",
            "sku": {"name": "GP_S_Gen5_2", "tier": "GeneralPurpose"},
            "properties": {
                "status": "Online",
                "maxSizeBytes": 34359738368,
                "collation": "SQL_Latin1_General_CP1_CI_AS",
                "creationDate": "2024-01-15T10:30:00Z",
                "currentServiceObjectiveName": "GP_S_Gen5_2",
                "zoneRedundant": True,
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.azure_sql_tool.azure_sql_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["azure_sql_get_database"](
                resource_group="rg", server_name="myserver", database_name="mydb"
            )

        assert result["name"] == "mydb"
        assert result["zone_redundant"] is True


class TestAzureSQLListFirewallRules:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["azure_sql_list_firewall_rules"](resource_group="", server_name="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "value": [
                {
                    "id": "/subscriptions/sub-123/.../firewallRules/AllowAll",
                    "name": "AllowAll",
                    "properties": {
                        "startIpAddress": "0.0.0.0",
                        "endIpAddress": "255.255.255.255",
                    },
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.azure_sql_tool.azure_sql_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["azure_sql_list_firewall_rules"](
                resource_group="rg", server_name="myserver"
            )

        assert result["count"] == 1
        assert result["firewall_rules"][0]["name"] == "AllowAll"
        assert result["firewall_rules"][0]["start_ip"] == "0.0.0.0"
