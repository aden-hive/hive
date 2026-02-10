import os
import json
import httpx
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP

# Constants
DEFAULT_SITE = "datadoghq.com"
DEFAULT_TIMEOUT = 30.0

def _get_config() -> tuple[str, str, str]:
    """
    Retrieve Datadog configuration from environment variables.
    
    Returns:
        tuple: (api_key, app_key, site)
    """
    api_key = os.environ.get("DATADOG_API_KEY")
    app_key = os.environ.get("DATADOG_APP_KEY")
    site = os.environ.get("DATADOG_SITE", DEFAULT_SITE)
    
    if not api_key:
        raise ValueError("DATADOG_API_KEY environment variable is not set.")
    if not app_key:
        # App key is required for most read operations (logs/metrics)
        raise ValueError("DATADOG_APP_KEY environment variable is not set. It is required for reading logs and metrics.")
        
    return api_key, app_key, site

def _get_base_url(site: str) -> str:
    return f"https://api.{site}"

def _handle_error(response: httpx.Response) -> str:
    """Format error responses from Datadog API."""
    try:
        error_json = response.json()
        errors = error_json.get("errors", [])
        error_msg = "; ".join(errors) if isinstance(errors, list) else str(errors)
    except Exception:
        error_msg = response.text
        
    return f"Error {response.status_code}: {error_msg}"

def register_tools(mcp: FastMCP):
    """Register Datadog observability tools with the MCP server."""

    @mcp.tool()
    def datadog_list_logs(
        query: str,
        time_from: str = "now-15m",
        time_to: str = "now",
        limit: int = 20,
        indexes: Optional[str] = None
    ) -> str:
        """
        Query Datadog logs to identify root causes of failures or check system events.
        
        Args:
            query: The search query (e.g., 'service:web-server status:error', 'trace_id:123').
            time_from: Start time (ISO 8601 or relative like 'now-15m'). Default: 'now-15m'.
            time_to: End time (ISO 8601 or relative like 'now'). Default: 'now'.
            limit: Maximum number of logs to return (max 100). Default: 20.
            indexes: Comma-separated list of log indexes to search (e.g., 'main,archive'). Default: all.
            
        Returns:
            JSON string containing list of log events with timestamp, message, and attributes.
        """
        try:
            api_key, app_key, site = _get_config()
        except ValueError as e:
            return f"Configuration Error: {str(e)}"

        url = f"{_get_base_url(site)}/api/v2/logs/events/search"
        headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Enforce max limit to prevent context overflow
        limit = min(limit, 100)
        
        payload = {
            "filter": {
                "query": query,
                "from": time_from,
                "to": time_to,
            },
            "page": {
                "limit": limit
            },
            "sort": "-timestamp"  # Newest first
        }
        
        if indexes:
            # The API expects "indexes" as a list of strings at the filter level? 
            # Checking docs: POST /api/v2/logs/events/search
            # "filter": {"indexes": ["main"]}
            payload["filter"]["indexes"] = [idx.strip() for idx in indexes.split(",")]

        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                response = client.post(url, headers=headers, json=payload)
                
                if response.status_code == 403:
                    return "Error 403: Forbidden. Verify your DATADOG_API_KEY and DATADOG_APP_KEY."
                if response.status_code != 200:
                    return _handle_error(response)
                
                data = response.json()
                data_list = data.get("data", [])
                
                results = []
                for log in data_list:
                    attrs = log.get("attributes", {})
                    results.append({
                        "timestamp": attrs.get("timestamp"),
                        "service": attrs.get("service"),
                        "status": attrs.get("status"),
                        "message": attrs.get("message"),
                        "tags": attrs.get("tags", [])
                    })
                    
                return json.dumps(results, indent=2)
                
        except httpx.RequestError as e:
            return f"Network Error: {str(e)}"
        except Exception as e:
            return f"Unexpected Error: {str(e)}"

    @mcp.tool()
    def datadog_get_metrics(
        query: str,
        from_seconds_ago: int = 3600,
        to_seconds_ago: int = 0
    ) -> str:
        """
        Fetch timeseries metrics from Datadog to track latency, error rates, or throughput.
        
        Args:
            query: The metric query (e.g., 'avg:system.cpu.idle{*}', 'sum:http.requests.count{service:web}').
            from_seconds_ago: Start time in seconds relative to now. Default: 3600 (1 hour).
            to_seconds_ago: End time in seconds relative to now. Default: 0 (now).
            
        Returns:
            JSON string containing pointlist for the queried metric.
        """
        try:
            api_key, app_key, site = _get_config()
        except ValueError as e:
            return f"Configuration Error: {str(e)}"
            
        import time
        now = int(time.time())
        from_time = now - from_seconds_ago
        to_time = now - to_seconds_ago
        
        url = f"{_get_base_url(site)}/api/v1/query"
        headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Accept": "application/json"
        }
        
        params = {
            "query": query,
            "from": from_time,
            "to": to_time
        }
        
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                response = client.get(url, headers=headers, params=params)
                
                if response.status_code != 200:
                    return _handle_error(response)
                
                data = response.json()
                series = data.get("series", [])
                
                if not series:
                    return "No metrics found for the given query and time range."
                
                # Simplify output
                formatted_series = []
                for s in series:
                    pointlist = s.get("pointlist", [])
                    # Limit points if too many (e.g., > 50) to save context?
                    # Datadog often returns hundreds. Let's simple-sample or just return start/end/avg if too big.
                    # For now, return all but warn if massive.
                    formatted_series.append({
                        "metric": s.get("metric"),
                        "scope": s.get("scope"),
                        "points_count": len(pointlist),
                        "points": pointlist  # [timestamp, value]
                    })
                    
                return json.dumps(formatted_series, indent=2)
                
        except httpx.RequestError as e:
            return f"Network Error: {str(e)}"
        except Exception as e:
            return f"Unexpected Error: {str(e)}"

    @mcp.tool()
    def datadog_get_monitor_status(
        monitor_tags: str,
        group_states: Optional[str] = "Alert,Warn"
    ) -> str:
        """
        Check the status of Datadog monitors (alerts) to identify triggered incidents.
        
        Args:
            monitor_tags: Comma-separated tags to filter monitors (e.g., 'service:backend,env:prod').
            group_states: Comma-separated states to include (Alert, Warn, No Data, OK). Default: 'Alert,Warn'.
            
        Returns:
            JSON string summary of Monitors in Alert/Warn state.
        """
        try:
            api_key, app_key, site = _get_config()
        except ValueError as e:
            return f"Configuration Error: {str(e)}"
            
        url = f"{_get_base_url(site)}/api/v1/monitor/search"
        headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Accept": "application/json"
        }
        
        params = {
            "query": monitor_tags,
            # 'per_page': 20
        }
        
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                response = client.get(url, headers=headers, params=params)
                
                if response.status_code != 200:
                    return _handle_error(response)
                
                data = response.json()
                monitors = data.get("monitors", [])
                
                states_filter = set(s.strip() for s in group_states.split(",")) if group_states else None
                
                results = []
                for m in monitors:
                    status = m.get("overall_state")
                    # Filter by state if requested
                    if states_filter and status not in states_filter:
                        continue
                        
                    results.append({
                        "name": m.get("name"),
                        "status": status,
                        "type": m.get("type"),
                        "id": m.get("id"),
                        "tags": m.get("tags")
                    })
                
                if not results:
                    return f"No monitors found with tags '{monitor_tags}' in states: {group_states}"
                    
                return json.dumps(results, indent=2)

        except httpx.RequestError as e:
            return f"Network Error: {str(e)}"
        except Exception as e:
            return f"Unexpected Error: {str(e)}"
