"""
Google Analytics Tool - Query GA4 website traffic and marketing performance data.

Provides read-only access to Google Analytics 4 via the Data API v1.

Supports:
- Service account authentication (GOOGLE_APPLICATION_CREDENTIALS)
- Credential store via CredentialStoreAdapter

API Reference: https://developers.google.com/analytics/devguides/reporting/data/v1
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    MinuteRange,
    RunRealtimeReportRequest,
    RunReportRequest,
)
from google.oauth2.service_account import Credentials

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)


class _GAClient:
    """Internal client wrapping Google Analytics 4 Data API v1beta calls."""

    def __init__(self, credentials_path: str):
        self._credentials_path = credentials_path
        creds = Credentials.from_service_account_file(credentials_path)
        self._client = BetaAnalyticsDataClient(credentials=creds)

    def run_report(
        self,
        property_id: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Run a GA4 report and return structured results."""
        request = RunReportRequest(
            property=property_id,
            metrics=[Metric(name=m) for m in metrics],
            dimensions=[Dimension(name=d) for d in (dimensions or [])],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=limit,
        )

        response = self._client.run_report(request)
        return self._format_report_response(response)

    def run_realtime_report(
        self,
        property_id: str,
        metrics: list[str],
    ) -> dict[str, Any]:
        """Run a GA4 realtime report."""
        request = RunRealtimeReportRequest(
            property=property_id,
            metrics=[Metric(name=m) for m in metrics],
            minute_ranges=[MinuteRange(start_minutes_ago=29, end_minutes_ago=0)],
        )

        response = self._client.run_realtime_report(request)
        return self._format_realtime_response(response)

    def _format_report_response(
        self,
        response: Any,
    ) -> dict[str, Any]:
        """Format a RunReportResponse into a plain dict."""
        rows = []
        dim_headers = [h.name for h in response.dimension_headers]
        metric_headers = [h.name for h in response.metric_headers]

        for row in response.rows:
            row_data: dict[str, str] = {}
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dim_headers[i]] = dim_value.value
            for i, metric_value in enumerate(row.metric_values):
                row_data[metric_headers[i]] = metric_value.value
            rows.append(row_data)

        return {
            "row_count": response.row_count,
            "rows": rows,
            "dimension_headers": dim_headers,
            "metric_headers": metric_headers,
        }

    def _format_realtime_response(
        self,
        response: Any,
    ) -> dict[str, Any]:
        """Format a RunRealtimeReportResponse into a plain dict."""
        rows = []
        metric_headers = [h.name for h in response.metric_headers]

        for row in response.rows:
            row_data: dict[str, str] = {}
            for i, metric_value in enumerate(row.metric_values):
                row_data[metric_headers[i]] = metric_value.value
            rows.append(row_data)

        return {
            "row_count": response.row_count,
            "rows": rows,
            "metric_headers": metric_headers,
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Analytics tools with the MCP server."""

    def _get_credentials_path() -> str | None:
        """Get GA credentials path from credential store or environment."""
        if credentials is not None:
            path = credentials.get("google_analytics")
            if path is not None and not isinstance(path, str):
                raise TypeError(
                    f"Expected string from credentials.get('google_analytics'), "
                    f"got {type(path).__name__}"
                )
            return path
        return os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    def _get_client() -> _GAClient | dict[str, str]:
        """Get a GA client, or return an error dict if no credentials."""
        creds_path = _get_credentials_path()
        if not creds_path:
            return {
                "error": "Google Analytics credentials not configured",
                "help": (
                    "Set GOOGLE_APPLICATION_CREDENTIALS environment variable "
                    "to the path of your service account JSON key file, "
                    "or configure via credential store"
                ),
            }
        try:
            return _GAClient(creds_path)
        except Exception as e:
            return {"error": f"Failed to initialize Google Analytics client: {e}"}

    def _validate_inputs(property_id: str, *, limit: int | None = None) -> dict[str, str] | None:
        """Validate common inputs. Returns an error dict or None."""
        if not property_id or not property_id.startswith("properties/"):
            return {
                "error": "property_id must start with 'properties/' (e.g., 'properties/123456')"
            }
        if limit is not None and (limit < 1 or limit > 10000):
            return {"error": "limit must be between 1 and 10000"}
        return None

    @mcp.tool()
    def ga_run_report(
        property_id: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        limit: int = 100,
    ) -> dict:
        """
        Run a custom Google Analytics 4 report.

        Use this tool to query website traffic data with custom dimensions,
        metrics, and date ranges.

        Args:
            property_id: GA4 property ID (e.g., "properties/123456")
            metrics: Metrics to retrieve
                (e.g., ["sessions", "totalUsers", "conversions"])
            dimensions: Dimensions to group by
                (e.g., ["pagePath", "sessionSource"])
            start_date: Start date (e.g., "2024-01-01" or "28daysAgo")
            end_date: End date (e.g., "today")
            limit: Max rows to return (1-10000)

        Returns:
            Dict with report rows or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if err := _validate_inputs(property_id, limit=limit):
            return err
        if not metrics:
            return {"error": "metrics list must not be empty"}

        try:
            return client.run_report(
                property_id=property_id,
                metrics=metrics,
                dimensions=dimensions,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except Exception as e:
            logger.warning("ga_run_report failed: %s", e)
            return {"error": f"Google Analytics API error: {e}"}

    @mcp.tool()
    def ga_get_realtime(
        property_id: str,
        metrics: list[str] | None = None,
    ) -> dict:
        """
        Get real-time Google Analytics data (active users, current pages).

        Use this tool to check current website activity and detect traffic anomalies.

        Args:
            property_id: GA4 property ID (e.g., "properties/123456")
            metrics: Metrics to retrieve (default: ["activeUsers"])

        Returns:
            Dict with real-time data or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if err := _validate_inputs(property_id):
            return err

        effective_metrics = metrics or ["activeUsers"]

        try:
            return client.run_realtime_report(
                property_id=property_id,
                metrics=effective_metrics,
            )
        except Exception as e:
            logger.warning("ga_get_realtime failed: %s", e)
            return {"error": f"Google Analytics API error: {e}"}

    @mcp.tool()
    def ga_get_top_pages(
        property_id: str,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        limit: int = 10,
    ) -> dict:
        """
        Get top pages by views and engagement.

        Convenience wrapper that returns the most-visited pages with
        key engagement metrics.

        Args:
            property_id: GA4 property ID (e.g., "properties/123456")
            start_date: Start date (e.g., "2024-01-01" or "28daysAgo")
            end_date: End date (e.g., "today")
            limit: Max pages to return (1-10000, default 10)

        Returns:
            Dict with top pages, their views, avg engagement time, and bounce rate
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if err := _validate_inputs(property_id, limit=limit):
            return err

        try:
            return client.run_report(
                property_id=property_id,
                metrics=["screenPageViews", "averageSessionDuration", "bounceRate"],
                dimensions=["pagePath", "pageTitle"],
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except Exception as e:
            logger.warning("ga_get_top_pages failed: %s", e)
            return {"error": f"Google Analytics API error: {e}"}

    @mcp.tool()
    def ga_get_traffic_sources(
        property_id: str,
        start_date: str = "28daysAgo",
        end_date: str = "today",
        limit: int = 10,
    ) -> dict:
        """
        Get traffic breakdown by source/medium.

        Convenience wrapper that shows which channels drive visitors to the site.

        Args:
            property_id: GA4 property ID (e.g., "properties/123456")
            start_date: Start date (e.g., "2024-01-01" or "28daysAgo")
            end_date: End date (e.g., "today")
            limit: Max sources to return (1-10000, default 10)

        Returns:
            Dict with traffic sources, sessions, users, and conversions per source
        """
        client = _get_client()
        if isinstance(client, dict):
            return client

        if err := _validate_inputs(property_id, limit=limit):
            return err

        try:
            return client.run_report(
                property_id=property_id,
                metrics=["sessions", "totalUsers", "conversions"],
                dimensions=["sessionSource", "sessionMedium"],
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except Exception as e:
            logger.warning("ga_get_traffic_sources failed: %s", e)
            return {"error": f"Google Analytics API error: {e}"}
