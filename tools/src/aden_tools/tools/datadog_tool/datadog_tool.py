"""Datadog monitoring integration.

Provides metrics querying, monitor management, event listing, and log search
via the Datadog API v1/v2.

Required credentials:
    DATADOG_API_KEY  — Datadog API key (required for all operations)
    DATADOG_APP_KEY  — Datadog application key (required for most operations)

Optional:
    DATADOG_SITE     — Datadog site (default: datadoghq.com; use datadoghq.eu for EU)
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastmcp import FastMCP


def _base_url() -> str:
    site = os.getenv("DATADOG_SITE", "datadoghq.com").strip().rstrip("/")
    return f"https://api.{site}"


def _get_headers(require_app_key: bool = True) -> dict | None:
    """Return Datadog auth headers or None if required credentials are missing."""
    api_key = os.getenv("DATADOG_API_KEY", "")
    if not api_key:
        return None
    headers = {
        "DD-API-KEY": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if require_app_key:
        app_key = os.getenv("DATADOG_APP_KEY", "")
        if not app_key:
            return None
        headers["DD-APPLICATION-KEY"] = app_key
    return headers


def _get(path: str, headers: dict, params: dict | None = None) -> dict:
    resp = httpx.get(f"{_base_url()}{path}", headers=headers, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _post(path: str, headers: dict, body: dict) -> dict:
    resp = httpx.post(f"{_base_url()}{path}", headers=headers, json=body, timeout=30)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _no_creds_error() -> dict:
    return {
        "error": "DATADOG_API_KEY and DATADOG_APP_KEY are required",
        "help": "Set DATADOG_API_KEY and DATADOG_APP_KEY environment variables",
    }


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register Datadog monitoring tools."""

    @mcp.tool()
    def datadog_query_metrics(
        query: str,
        from_time: int,
        to_time: int,
    ) -> dict:
        """Query Datadog metrics time series data.

        Args:
            query: Datadog metric query string (e.g. 'avg:system.cpu.user{*}').
            from_time: Start of the query window as a UNIX timestamp (seconds).
            to_time: End of the query window as a UNIX timestamp (seconds).
        """
        headers = _get_headers()
        if headers is None:
            return _no_creds_error()
        if not query:
            return {"error": "query is required"}

        params = {"query": query, "from": from_time, "to": to_time}
        data = _get("/api/v1/query", headers, params)
        if "error" in data:
            return data

        series = data.get("series", [])
        return {
            "status": data.get("status"),
            "from_date": data.get("from_date"),
            "to_date": data.get("to_date"),
            "series_count": len(series),
            "series": [
                {
                    "metric": s.get("metric"),
                    "display_name": s.get("display_name"),
                    "unit": (s.get("unit") or [{}])[0].get("name") if s.get("unit") else None,
                    "pointlist": s.get("pointlist", []),
                    "scope": s.get("scope"),
                    "length": s.get("length", 0),
                }
                for s in series
            ],
        }

    @mcp.tool()
    def datadog_list_monitors(
        name: str = "",
        tags: str = "",
        monitor_tags: str = "",
        with_downtimes: bool = False,
        limit: int = 50,
    ) -> dict:
        """List Datadog monitors with optional filters.

        Args:
            name: Filter monitors by name substring (optional).
            tags: Comma-separated scope tags to filter by (e.g. 'env:prod,service:web').
            monitor_tags: Comma-separated monitor tags (e.g. 'team:backend').
            with_downtimes: Include active downtime objects in the response.
            limit: Maximum number of monitors to return (default 50, max 1000).
        """
        headers = _get_headers()
        if headers is None:
            return _no_creds_error()

        params: dict[str, Any] = {"page_size": min(limit, 1000)}
        if name:
            params["name"] = name
        if tags:
            params["tags"] = tags
        if monitor_tags:
            params["monitor_tags"] = monitor_tags
        if with_downtimes:
            params["with_downtimes"] = True

        data = _get("/api/v1/monitor", headers, params)
        if isinstance(data, dict) and "error" in data:
            return data

        monitors = data if isinstance(data, list) else []
        return {
            "count": len(monitors),
            "monitors": [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "type": m.get("type"),
                    "status": m.get("overall_state"),
                    "query": m.get("query"),
                    "message": (m.get("message") or "")[:200],
                    "tags": m.get("tags", []),
                    "created": m.get("created"),
                    "modified": m.get("modified"),
                }
                for m in monitors
            ],
        }

    @mcp.tool()
    def datadog_get_monitor(monitor_id: int) -> dict:
        """Get details of a specific Datadog monitor.

        Args:
            monitor_id: The numeric ID of the monitor.
        """
        headers = _get_headers()
        if headers is None:
            return _no_creds_error()

        data = _get(f"/api/v1/monitor/{monitor_id}", headers)
        if "error" in data:
            return data

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": data.get("type"),
            "status": data.get("overall_state"),
            "query": data.get("query"),
            "message": data.get("message"),
            "tags": data.get("tags", []),
            "options": data.get("options", {}),
            "created": data.get("created"),
            "modified": data.get("modified"),
            "creator": (data.get("creator") or {}).get("email"),
        }

    @mcp.tool()
    def datadog_mute_monitor(
        monitor_id: int,
        scope: str = "",
        end: int = 0,
    ) -> dict:
        """Mute a Datadog monitor to suppress notifications.

        Args:
            monitor_id: The numeric ID of the monitor to mute.
            scope: Scope to apply the mute to (e.g. 'host:web-01'). Omit for all.
            end: UNIX timestamp when the mute should expire (0 = indefinite).
        """
        headers = _get_headers()
        if headers is None:
            return _no_creds_error()

        body: dict[str, Any] = {}
        if scope:
            body["scope"] = scope
        if end:
            body["end"] = end

        data = _post(f"/api/v1/monitor/{monitor_id}/mute", headers, body)
        if "error" in data:
            return data

        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "status": data.get("overall_state"),
            "result": "muted",
        }

    @mcp.tool()
    def datadog_list_events(
        start: int,
        end: int,
        tags: str = "",
        sources: str = "",
        priority: str = "",
        unaggregated: bool = False,
        limit: int = 50,
    ) -> dict:
        """List Datadog events within a time range.

        Args:
            start: Start of the time range as UNIX timestamp (seconds).
            end: End of the time range as UNIX timestamp (seconds).
            tags: Comma-separated tags to filter events (e.g. 'env:prod').
            sources: Comma-separated sources to filter by (e.g. 'my-apps').
            priority: Filter by priority: 'normal' or 'low'.
            unaggregated: If True, show unaggregated events (not merged into groups).
            limit: Maximum events to return (default 50, max 1000).
        """
        headers = _get_headers(require_app_key=False)
        if headers is None:
            return {
                "error": "DATADOG_API_KEY is required",
                "help": "Set DATADOG_API_KEY environment variable",
            }

        params: dict[str, Any] = {
            "start": start,
            "end": end,
            "count": min(limit, 1000),
        }
        if tags:
            params["tags"] = tags
        if sources:
            params["sources"] = sources
        if priority:
            params["priority"] = priority
        if unaggregated:
            params["unaggregated"] = True

        data = _get("/api/v1/events", headers, params)
        if "error" in data:
            return data

        events = data.get("events", [])
        return {
            "count": len(events),
            "events": [
                {
                    "id": e.get("id"),
                    "title": e.get("title"),
                    "text": (e.get("text") or "")[:300],
                    "date_happened": e.get("date_happened"),
                    "source": e.get("source_type_name"),
                    "priority": e.get("priority"),
                    "alert_type": e.get("alert_type"),
                    "tags": e.get("tags", []),
                    "host": e.get("host"),
                }
                for e in events
            ],
        }

    @mcp.tool()
    def datadog_search_logs(
        query: str = "",
        from_time: str = "now-15m",
        to_time: str = "now",
        limit: int = 50,
        sort: str = "timestamp",
    ) -> dict:
        """Search Datadog logs using the Logs Search API v2.

        Args:
            query: Datadog log search query (e.g. 'service:web status:error').
                   Leave empty to match all logs.
            from_time: Start of the query window. Accepts ISO 8601 datetime
                       or relative values like 'now-1h', 'now-15m' (default 'now-15m').
            to_time: End of the query window (default 'now').
            limit: Maximum number of log events to return (default 50, max 1000).
            sort: Sort order: 'timestamp' (ascending) or '-timestamp' (descending).
        """
        headers = _get_headers()
        if headers is None:
            return _no_creds_error()

        body: dict[str, Any] = {
            "filter": {
                "query": query,
                "from": from_time,
                "to": to_time,
            },
            "page": {"limit": min(limit, 1000)},
            "sort": sort,
        }

        data = _post("/api/v2/logs/events/search", headers, body)
        if "error" in data:
            return data

        events = data.get("data", [])
        return {
            "count": len(events),
            "logs": [
                {
                    "id": e.get("id"),
                    "timestamp": (e.get("attributes") or {}).get("timestamp"),
                    "status": (e.get("attributes") or {}).get("status"),
                    "service": (e.get("attributes") or {}).get("service"),
                    "host": (e.get("attributes") or {}).get("host"),
                    "message": ((e.get("attributes") or {}).get("message") or "")[:500],
                    "tags": (e.get("attributes") or {}).get("tags", []),
                }
                for e in events
            ],
            "meta": data.get("meta", {}),
        }
