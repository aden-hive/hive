"""
Prometheus Tool - Query metrics from a Prometheus server using PromQL.

Required:
- PROMETHEUS_BASE_URL

Optional Authentication:
- PROMETHEUS_TOKEN (Bearer token)
- PROMETHEUS_USERNAME and PROMETHEUS_PASSWORD (Basic Auth)

API Reference: https://prometheus.io/docs/prometheus/latest/querying/api/
"""

import os

import httpx
from fastmcp import FastMCP

from aden_tools.credentials import CREDENTIAL_SPECS
from aden_tools.credentials.store_adapter import CredentialStoreAdapter

DEFAULT_TIMEOUT = 5


def _get_prometheus_base_url(
    credentials: CredentialStoreAdapter | None,
) -> str | None:
    """
    Return Prometheus base URL.

    Priority:
    1. Credential store
    2. Environment variable fallback

    Parameters:
        credentials: Credential store to query

    Returns:
        Base URL string or None
    """
    base_url: str | None = None

    if credentials:
        base_url = credentials.get("prometheus")

    if not base_url:
        base_url = os.getenv("PROMETHEUS_BASE_URL")

    return base_url


def _missing_prometheus_credential_response() -> dict:
    """
    Return a standardized response for missing Prometheus configuration.
    """
    spec = CREDENTIAL_SPECS["prometheus"]

    return {
        "error": f"Missing required credential: {spec.description}",
        "help": spec.api_key_instructions,
        "success": False,
    }


def _get_auth():
    headers = {}
    auth = None

    # Bearer token
    token = os.getenv("PROMETHEUS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers, None

    # Basic auth
    username = os.getenv("PROMETHEUS_USERNAME")
    password = os.getenv("PROMETHEUS_PASSWORD")
    if username and password:
        auth = httpx.BasicAuth(username, password)

    return headers, auth


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Prometheus tools with MCP."""

    @mcp.tool()
    def prometheus_query(
        query: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict:
        """
        Query Prometheus using PromQL.

        Use this tool to fetch real-time metrics from a Prometheus server.

        Args:
            query: PromQL query string (e.g., 'up', 'sum(rate(http_requests_total[1m]))')
            timeout: Request timeout in seconds (1-30)

        Returns:
            Dict containing query results or error
        """

        # limit query length
        if not query or len(query) > 1000:
            return {"error": "Query must be between 1 and 1000 characters"}

        if timeout < 1 or timeout > 30:
            timeout = DEFAULT_TIMEOUT

        base_url = _get_prometheus_base_url(credentials)

        if not base_url:
            return _missing_prometheus_credential_response()

        url = f"{base_url.rstrip('/')}/api/v1/query"

        headers, auth = _get_auth()

        try:
            response = httpx.get(
                url,
                params={"query": query},
                headers=headers,
                auth=auth,
                timeout=timeout,
            )

            if response.status_code != 200:
                return {
                    "error": f"Prometheus returned status {response.status_code}",
                    "details": response.text,
                }

            data = response.json()

            if data.get("status") != "success":
                return {
                    "error": "Prometheus query failed",
                    "details": data,
                }

            return {"success": True, "query": query, "result": data.get("data", {}).get("result", []), "raw": data}

        except httpx.TimeoutException:
            return {"error": "Request to Prometheus timed out"}

        except httpx.ConnectError:
            return {
                "error": "Failed to connect to Prometheus",
                "help": "Check if Prometheus is running and base_url is correct",
            }

        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    def prometheus_query_range(
        query: str,
        start: str,
        end: str,
        step: str = "60s",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict:
        """
        Query Prometheus over a time range using PromQL.

        Use this tool to fetch historical metrics and time series data
        from a Prometheus server. Suitable for trend analysis, graphing,
        and monitoring over a defined time window.

        Args:
            query: PromQL query string (e.g., 'rate(http_requests_total[5m])')
            start: Start time (Unix timestamp or RFC3339 format, e.g., "2024-01-01T00:00:00Z")
            end: End time (Unix timestamp or RFC3339 format, e.g., "2024-01-01T00:00:00Z")
            step: Query resolution step (e.g., '15s', '5m', '1h')
            timeout: Request timeout in seconds (1-30)

        Returns:
            Dict containing time-series results or error
        """

        if not query or len(query) > 1000:
            return {"error": "Query must be between 1 and 1000 characters"}

        if not start or not end:
            return {"error": "start and end time are required"}

        if timeout < 1 or timeout > 30:
            timeout = DEFAULT_TIMEOUT

        base_url = _get_prometheus_base_url(credentials)

        if not base_url:
            return _missing_prometheus_credential_response()

        url = f"{base_url.rstrip('/')}/api/v1/query_range"

        headers, auth = _get_auth()

        try:
            response = httpx.get(
                url,
                params={
                    "query": query,
                    "start": start,
                    "end": end,
                    "step": step,
                },
                headers=headers,
                auth=auth,
                timeout=timeout,
            )

            if response.status_code != 200:
                return {
                    "error": f"Prometheus returned status {response.status_code}",
                    "details": response.text,
                }

            data = response.json()

            if data.get("status") != "success":
                return {
                    "error": "Prometheus range query failed",
                    "details": data,
                }

            return {
                "success": True,
                "query": query,
                "start": start,
                "end": end,
                "step": step,
                "result": data.get("data", {}).get("result", []),
                "raw": data,
            }

        except httpx.TimeoutException:
            return {"error": "Request to Prometheus timed out"}

        except httpx.ConnectError:
            return {
                "error": "Failed to connect to Prometheus",
                "help": "Check if Prometheus is running and base_url is correct",
            }

        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
