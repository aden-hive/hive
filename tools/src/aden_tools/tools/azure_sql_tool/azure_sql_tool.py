"""Azure SQL Database management API integration.

Provides server and database management via the Azure Resource Manager REST API.
Requires AZURE_SQL_ACCESS_TOKEN and AZURE_SUBSCRIPTION_ID.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP

BASE_URL = "https://management.azure.com"
API_VERSION = "2023-08-01"


def _get_config() -> tuple[dict, str] | dict:
    """Return (headers, subscription_id) or error dict."""
    token = os.getenv("AZURE_SQL_ACCESS_TOKEN", "")
    sub_id = os.getenv("AZURE_SUBSCRIPTION_ID", "")
    if not token or not sub_id:
        return {
            "error": "AZURE_SQL_ACCESS_TOKEN and AZURE_SUBSCRIPTION_ID are required",
            "help": "Set AZURE_SQL_ACCESS_TOKEN and AZURE_SUBSCRIPTION_ID environment variables",
        }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return headers, sub_id


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    """Send a GET request."""
    final_params = {"api-version": API_VERSION}
    if params:
        final_params.update(params)
    resp = httpx.get(url, headers=headers, params=final_params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _extract_server(s: dict) -> dict:
    """Extract key fields from a server resource."""
    props = s.get("properties", {})
    return {
        "id": s.get("id"),
        "name": s.get("name"),
        "location": s.get("location"),
        "fqdn": props.get("fullyQualifiedDomainName"),
        "state": props.get("state"),
        "version": props.get("version"),
        "admin_login": props.get("administratorLogin"),
    }


def _extract_database(d: dict) -> dict:
    """Extract key fields from a database resource."""
    props = d.get("properties", {})
    sku = d.get("sku", {})
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "location": d.get("location"),
        "status": props.get("status"),
        "sku_name": sku.get("name"),
        "sku_tier": sku.get("tier"),
        "max_size_bytes": props.get("maxSizeBytes"),
        "collation": props.get("collation"),
        "creation_date": props.get("creationDate"),
        "current_service_objective": props.get("currentServiceObjectiveName"),
        "zone_redundant": props.get("zoneRedundant"),
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Azure SQL tools."""

    @mcp.tool()
    def azure_sql_list_servers(resource_group: str = "") -> dict:
        """List Azure SQL servers in the subscription or a specific resource group.

        Args:
            resource_group: Resource group name (empty for all servers in subscription).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        headers, sub_id = cfg

        if resource_group:
            url = (
                f"{BASE_URL}/subscriptions/{sub_id}"
                f"/resourceGroups/{resource_group}"
                "/providers/Microsoft.Sql/servers"
            )
        else:
            url = f"{BASE_URL}/subscriptions/{sub_id}/providers/Microsoft.Sql/servers"

        data = _get(url, headers)
        if "error" in data:
            return data

        servers = data.get("value", [])
        return {
            "count": len(servers),
            "servers": [_extract_server(s) for s in servers],
        }

    @mcp.tool()
    def azure_sql_get_server(resource_group: str, server_name: str) -> dict:
        """Get details of a specific Azure SQL server.

        Args:
            resource_group: Resource group name.
            server_name: SQL server name.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        headers, sub_id = cfg
        if not resource_group or not server_name:
            return {"error": "resource_group and server_name are required"}

        url = (
            f"{BASE_URL}/subscriptions/{sub_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Sql/servers/{server_name}"
        )
        data = _get(url, headers)
        if "error" in data:
            return data

        return _extract_server(data)

    @mcp.tool()
    def azure_sql_list_databases(resource_group: str, server_name: str) -> dict:
        """List databases on an Azure SQL server.

        Args:
            resource_group: Resource group name.
            server_name: SQL server name.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        headers, sub_id = cfg
        if not resource_group or not server_name:
            return {"error": "resource_group and server_name are required"}

        url = (
            f"{BASE_URL}/subscriptions/{sub_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Sql/servers/{server_name}/databases"
        )
        data = _get(url, headers)
        if "error" in data:
            return data

        databases = data.get("value", [])
        return {
            "count": len(databases),
            "databases": [_extract_database(d) for d in databases],
        }

    @mcp.tool()
    def azure_sql_get_database(resource_group: str, server_name: str, database_name: str) -> dict:
        """Get details of a specific Azure SQL database.

        Args:
            resource_group: Resource group name.
            server_name: SQL server name.
            database_name: Database name.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        headers, sub_id = cfg
        if not resource_group or not server_name or not database_name:
            return {"error": "resource_group, server_name, and database_name are required"}

        url = (
            f"{BASE_URL}/subscriptions/{sub_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Sql/servers/{server_name}"
            f"/databases/{database_name}"
        )
        data = _get(url, headers)
        if "error" in data:
            return data

        return _extract_database(data)

    @mcp.tool()
    def azure_sql_list_firewall_rules(resource_group: str, server_name: str) -> dict:
        """List firewall rules for an Azure SQL server.

        Args:
            resource_group: Resource group name.
            server_name: SQL server name.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        headers, sub_id = cfg
        if not resource_group or not server_name:
            return {"error": "resource_group and server_name are required"}

        url = (
            f"{BASE_URL}/subscriptions/{sub_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Sql/servers/{server_name}"
            "/firewallRules"
        )
        data = _get(url, headers)
        if "error" in data:
            return data

        rules = data.get("value", [])
        return {
            "count": len(rules),
            "firewall_rules": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "start_ip": r.get("properties", {}).get("startIpAddress"),
                    "end_ip": r.get("properties", {}).get("endIpAddress"),
                }
                for r in rules
            ],
        }
