from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import httpx
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter
from .models import GrafanaAlert, GrafanaAnnotation, GrafanaDashboard
from ..file_system_toolkits.command_sanitizer import sanitize_for_log

_logger = logging.getLogger(__name__)

class GrafanaToolError(Exception):
    """Custom exception for Grafana tool failures."""
    pass

def with_retry(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for exponential backoff on 429 and 5xx errors."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in [429, 500, 502, 503, 504]:
                        retries += 1
                        if retries == max_retries:
                            raise GrafanaToolError(f"Max retries reached: {e}")
                        delay = base_delay * (2 ** (retries - 1))
                        _logger.warning(f"Grafana API error {e.response.status_code}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        if e.response.status_code == 401:
                            raise GrafanaToolError("Unauthorized. Check your GRAFANA_API_KEY.")
                        raise GrafanaToolError(f"Grafana API error: {e}")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


class GrafanaClient:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip('/')
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._client = httpx.AsyncClient(timeout=30.0)

    @with_retry()
    async def request(self, method: str, endpoint: str, **kwargs) -> Any:
        response = await self._client.request(
            method, 
            f"{self.url}/api/{endpoint}", 
            headers=self.headers, 
            **kwargs
        )
        response.raise_for_status()
        return response.json()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Grafana tools with the MCP server."""

    def _get_auth() -> dict[str, str] | tuple[str, str]:
        """Get Grafana URL and API key from credential manager or environment."""
        url = None
        token = None

        if credentials is not None:
            grafana_creds = credentials.get("grafana")
            if grafana_creds and isinstance(grafana_creds, dict):
                url = grafana_creds.get("url")
                token = grafana_creds.get("api_key") or grafana_creds.get("token")

        if not url:
            url = os.getenv("GRAFANA_URL")
        if not token:
            token = os.getenv("GRAFANA_API_KEY")

        if not url or not token:
            return {
                "error": "Grafana credentials not configured",
                "help": "Set GRAFANA_URL and GRAFANA_API_KEY environment variables.",
            }

        return url, token

    def _get_client() -> GrafanaClient | dict[str, Any]:
        auth = _get_auth()
        if isinstance(auth, dict):
            return auth
        url, token = auth
        return GrafanaClient(url, token)

    @mcp.tool()
    async def grafana_list_dashboards() -> List[Dict[str, Any]] | dict[str, Any]:
        """Search and list all available Grafana dashboards (returns title, UID, and tags)."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        _logger.info("listing_dashboards", extra={"url": sanitize_for_log(client.url)})
        try:
            results = await client.request("GET", "search?type=dash-db")
            if not isinstance(results, list):
                # Handle unexpectedly malformed JSON API responses
                raise GrafanaToolError("Malformed API response: expected list of dashboards")
            
            dashboards = []
            for d in results:
                # Basic validation skipping unparseable structures
                try:
                    dashboards.append(
                        GrafanaDashboard(
                            uid=d.get("uid", ""),
                            title=d.get("title", "Untitled"),
                            uri=d.get("uri", ""),
                            tags=d.get("tags", []),
                            isStarred=d.get("isStarred", False)
                        ).model_dump()
                    )
                except Exception as e:
                    _logger.warning(f"Failed to parse dashboard object: {e}")
            return dashboards
        except GrafanaToolError as e:
            return {"error": str(e)}

    @mcp.tool()
    async def grafana_get_dashboard(uid: str) -> Dict[str, Any]:
        """Retrieve full JSON model of a Grafana dashboard by UID."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        _logger.info("getting_dashboard", extra={"uid": sanitize_for_log(uid)})
        try:
            return await client.request("GET", f"dashboards/uid/{uid}")
        except GrafanaToolError as e:
            return {"error": str(e)}

    @mcp.tool()
    async def grafana_query_panel(
        dashboard_uid: str,
        panel_id: int,
        from_time: str = "now-1h",
        to_time: str = "now",
    ) -> Dict[str, Any]:
        """Fetch data from a specific panel within a dashboard using time range parameters."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        _logger.info(
            "querying_panel",
            extra={
                "dashboard_uid": sanitize_for_log(dashboard_uid),
                "panel_id": panel_id,
            },
        )
        try:
            payload = {
                "queries": [
                    {
                        "refId": "A",
                        "dashboardId": dashboard_uid,
                        "panelId": panel_id
                    }
                ],
                "from": from_time,
                "to": to_time,
            }
            return await client.request("POST", "ds/query", json=payload)
        except GrafanaToolError as e:
            return {"error": str(e)}

    @mcp.tool()
    async def grafana_create_annotation(
        dashboard_uid: str,
        text: str,
        tags: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Creates an annotation on a specific Grafana dashboard."""
        if tags is None:
            tags = []
            
        client = _get_client()
        if isinstance(client, dict):
            return client

        sanitized_text = sanitize_for_log(text)
        payload = {
            "dashboardUID": dashboard_uid,
            "time": int(time.time() * 1000),
            "text": sanitized_text,
            "tags": tags + ["hive-agent", "execution-log"],
        }
        _logger.info("creating_annotation", extra={"dashboard": sanitize_for_log(dashboard_uid)})
        try:
            return await client.request("POST", "annotations", json=payload)
        except GrafanaToolError as e:
             return {"error": str(e)}

    @mcp.tool()
    async def grafana_list_alerts() -> List[Dict[str, Any]] | Dict[str, Any]:
        """Fetch current status of Grafana Alert Rules."""
        client = _get_client()
        if isinstance(client, dict):
            return client

        _logger.info("listing_alerts", extra={"url": sanitize_for_log(client.url)})
        try:
            results = await client.request("GET", "v1/provisioning/alert-rules")
            if not isinstance(results, list):
                raise GrafanaToolError("Malformed API response: expected list of alerts")
            
            alerts = []
            for d in results:
                try:
                    alerts.append(
                        GrafanaAlert(
                            uid=d.get("uid", ""),
                            title=d.get("title", "Untitled Alert"),
                            state=d.get("execErrState", "unknown"),
                            lastEvaluation=None
                        ).model_dump()
                    )
                except Exception as e:
                    _logger.warning(f"Failed to parse alert object: {e}")
            return alerts
        except GrafanaToolError as e:
            return {"error": str(e)}
