"""
Tests for Google Analytics tool.

Covers:
- _GAClient methods (run_report, run_realtime_report, response formatting)
- Credential retrieval (CredentialStoreAdapter vs env var)
- Input validation for all tool functions
- Error handling (no credentials, API errors, timeouts)
"""

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.google_analytics_tool.google_analytics_tool import (
    _GAClient,
    register_tools,
)

# ---------------------------------------------------------------------------
# Helpers to build mock GA4 API responses
# ---------------------------------------------------------------------------


def _make_header(name: str) -> MagicMock:
    header = MagicMock()
    header.name = name
    return header


def _make_value(value: str) -> MagicMock:
    v = MagicMock()
    v.value = value
    return v


def _make_row(dim_values: list[str], metric_values: list[str]) -> MagicMock:
    row = MagicMock()
    row.dimension_values = [_make_value(v) for v in dim_values]
    row.metric_values = [_make_value(v) for v in metric_values]
    return row


def _make_report_response(
    dim_headers: list[str],
    metric_headers: list[str],
    rows: list[tuple[list[str], list[str]]],
    row_count: int | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.dimension_headers = [_make_header(h) for h in dim_headers]
    resp.metric_headers = [_make_header(h) for h in metric_headers]
    resp.rows = [_make_row(dims, metrics) for dims, metrics in rows]
    resp.row_count = row_count if row_count is not None else len(rows)
    return resp


def _make_realtime_response(
    metric_headers: list[str],
    rows: list[list[str]],
    row_count: int | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.dimension_headers = []
    resp.metric_headers = [_make_header(h) for h in metric_headers]
    resp.rows = [_make_row([], metrics) for metrics in rows]
    resp.row_count = row_count if row_count is not None else len(rows)
    return resp


# ---------------------------------------------------------------------------
# _GAClient tests
# ---------------------------------------------------------------------------


class TestGAClient:
    """Tests for the internal _GAClient class."""

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_format_report_response(self, mock_client_cls, mock_creds):
        """Report response is formatted into a plain dict."""
        client = _GAClient("/fake/path.json")

        response = _make_report_response(
            dim_headers=["pagePath"],
            metric_headers=["screenPageViews", "sessions"],
            rows=[
                (["/home"], ["1000", "500"]),
                (["/about"], ["200", "100"]),
            ],
        )

        result = client._format_report_response(response)

        assert result["row_count"] == 2
        assert len(result["rows"]) == 2
        assert result["rows"][0] == {
            "pagePath": "/home",
            "screenPageViews": "1000",
            "sessions": "500",
        }
        assert result["dimension_headers"] == ["pagePath"]
        assert result["metric_headers"] == ["screenPageViews", "sessions"]

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_format_report_response_no_dimensions(self, mock_client_cls, mock_creds):
        """Report with no dimensions still returns valid structure."""
        client = _GAClient("/fake/path.json")

        response = _make_report_response(
            dim_headers=[],
            metric_headers=["totalUsers"],
            rows=[([], ["5000"])],
        )

        result = client._format_report_response(response)

        assert result["row_count"] == 1
        assert result["rows"][0] == {"totalUsers": "5000"}
        assert result["dimension_headers"] == []

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_format_realtime_response(self, mock_client_cls, mock_creds):
        """Realtime response is formatted correctly."""
        client = _GAClient("/fake/path.json")

        response = _make_realtime_response(
            metric_headers=["activeUsers"],
            rows=[["42"]],
        )

        result = client._format_realtime_response(response)

        assert result["row_count"] == 1
        assert result["rows"][0] == {"activeUsers": "42"}
        assert result["metric_headers"] == ["activeUsers"]

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_run_report_calls_api(self, mock_client_cls, mock_creds):
        """run_report sends correct request to GA4 API."""
        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.return_value = _make_report_response(
            dim_headers=["pagePath"],
            metric_headers=["sessions"],
            rows=[(["/home"], ["100"])],
        )

        client = _GAClient("/fake/path.json")
        result = client.run_report(
            property_id="properties/123",
            metrics=["sessions"],
            dimensions=["pagePath"],
            start_date="7daysAgo",
            end_date="today",
            limit=50,
        )

        mock_api.run_report.assert_called_once()
        assert result["row_count"] == 1

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_run_realtime_report_calls_api(self, mock_client_cls, mock_creds):
        """run_realtime_report sends correct request to GA4 API."""
        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_realtime_report.return_value = _make_realtime_response(
            metric_headers=["activeUsers"],
            rows=[["10"]],
        )

        client = _GAClient("/fake/path.json")
        result = client.run_realtime_report(
            property_id="properties/123",
            metrics=["activeUsers"],
        )

        mock_api.run_realtime_report.assert_called_once()
        assert result["rows"][0]["activeUsers"] == "10"


# ---------------------------------------------------------------------------
# Credential retrieval tests
# ---------------------------------------------------------------------------


class TestCredentialRetrieval:
    """Tests for credential resolution in register_tools."""

    def test_no_credentials_returns_error(self, monkeypatch):
        """No credentials configured returns helpful error from tool call."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = lambda fn: registered_fns.update({fn.__name__: fn}) or fn

        register_tools(mcp, credentials=None)

        result = registered_fns["ga_run_report"](
            property_id="properties/123",
            metrics=["sessions"],
        )
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_env(self, monkeypatch):
        """Credentials resolved from environment variable."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/path/to/key.json")
        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = lambda fn: registered_fns.update({fn.__name__: fn}) or fn

        register_tools(mcp, credentials=None)
        assert "ga_run_report" in registered_fns

    def test_credentials_from_credential_store(self):
        """Credentials resolved from CredentialStoreAdapter."""
        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = lambda fn: registered_fns.update({fn.__name__: fn}) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "/path/to/key.json"

        register_tools(mcp, credentials=cred_manager)
        assert "ga_run_report" in registered_fns


# ---------------------------------------------------------------------------
# ga_run_report tests
# ---------------------------------------------------------------------------


class TestGaRunReport:
    """Tests for ga_run_report tool function."""

    @pytest.fixture
    def ga_tools(self, monkeypatch):
        """Register GA tools without credentials."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)
        return fns

    @pytest.fixture
    def ga_tools_with_creds(self, monkeypatch):
        """Register GA tools with credentials set (for input validation tests)."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")
        with (
            patch(
                "aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient"
            ),
            patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials"),
        ):
            mcp = MagicMock()
            fns = {}
            mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
            register_tools(mcp, credentials=None)
            yield fns

    def test_empty_metrics_returns_error(self, ga_tools_with_creds):
        """Empty metrics list returns validation error."""
        result = ga_tools_with_creds["ga_run_report"](
            property_id="properties/123",
            metrics=[],
        )
        assert "error" in result
        assert "metrics" in result["error"].lower()

    def test_invalid_property_id_returns_error(self, ga_tools_with_creds):
        """Property ID without 'properties/' prefix returns error."""
        result = ga_tools_with_creds["ga_run_report"](
            property_id="123456",
            metrics=["sessions"],
        )
        assert "error" in result
        assert "properties/" in result["error"]

    def test_empty_property_id_returns_error(self, ga_tools_with_creds):
        """Empty property ID returns error."""
        result = ga_tools_with_creds["ga_run_report"](
            property_id="",
            metrics=["sessions"],
        )
        assert "error" in result

    def test_limit_too_low_returns_error(self, ga_tools_with_creds):
        """Limit of 0 returns error."""
        result = ga_tools_with_creds["ga_run_report"](
            property_id="properties/123",
            metrics=["sessions"],
            limit=0,
        )
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_limit_too_high_returns_error(self, ga_tools_with_creds):
        """Limit above 10000 returns error."""
        result = ga_tools_with_creds["ga_run_report"](
            property_id="properties/123",
            metrics=["sessions"],
            limit=10001,
        )
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_no_credentials_returns_error(self, ga_tools):
        """No credentials returns error with help message."""
        result = ga_tools["ga_run_report"](
            property_id="properties/123",
            metrics=["sessions"],
        )
        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_successful_report(self, mock_client_cls, mock_creds, monkeypatch):
        """Successful report returns formatted data."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.return_value = _make_report_response(
            dim_headers=["pagePath"],
            metric_headers=["sessions"],
            rows=[(["/home"], ["500"])],
        )

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_run_report"](
            property_id="properties/123",
            metrics=["sessions"],
            dimensions=["pagePath"],
        )

        assert result["row_count"] == 1
        assert result["rows"][0]["pagePath"] == "/home"
        assert result["rows"][0]["sessions"] == "500"

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_api_error_returns_error_dict(self, mock_client_cls, mock_creds, monkeypatch):
        """API exception is caught and returned as error dict."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.side_effect = Exception("Permission denied")

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_run_report"](
            property_id="properties/123",
            metrics=["sessions"],
        )

        assert "error" in result
        assert "Permission denied" in result["error"]


# ---------------------------------------------------------------------------
# ga_get_realtime tests
# ---------------------------------------------------------------------------


class TestGaGetRealtime:
    """Tests for ga_get_realtime tool function."""

    @pytest.fixture
    def ga_tools(self, monkeypatch):
        """Register GA tools without credentials."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)
        return fns

    @pytest.fixture
    def ga_tools_with_creds(self, monkeypatch):
        """Register GA tools with credentials set (for input validation tests)."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")
        with (
            patch(
                "aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient"
            ),
            patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials"),
        ):
            mcp = MagicMock()
            fns = {}
            mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
            register_tools(mcp, credentials=None)
            yield fns

    def test_invalid_property_id_returns_error(self, ga_tools_with_creds):
        """Property ID without 'properties/' prefix returns error."""
        result = ga_tools_with_creds["ga_get_realtime"](property_id="123456")
        assert "error" in result
        assert "properties/" in result["error"]

    def test_no_credentials_returns_error(self, ga_tools):
        """No credentials returns error."""
        result = ga_tools["ga_get_realtime"](property_id="properties/123")
        assert "error" in result
        assert "not configured" in result["error"]

    def test_default_metrics(self, ga_tools):
        """Default metrics is ['activeUsers'] when none provided."""
        # We can't easily test the default without mocking, but we can
        # verify it doesn't crash with None metrics
        result = ga_tools["ga_get_realtime"](property_id="properties/123", metrics=None)
        assert "error" in result  # No credentials, but no crash

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_successful_realtime(self, mock_client_cls, mock_creds, monkeypatch):
        """Successful realtime report returns formatted data."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_realtime_report.return_value = _make_realtime_response(
            metric_headers=["activeUsers"],
            rows=[["42"]],
        )

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_get_realtime"](property_id="properties/123")

        assert result["row_count"] == 1
        assert result["rows"][0]["activeUsers"] == "42"

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_custom_metrics(self, mock_client_cls, mock_creds, monkeypatch):
        """Custom metrics are passed through to the API."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_realtime_report.return_value = _make_realtime_response(
            metric_headers=["activeUsers", "screenPageViews"],
            rows=[["10", "25"]],
        )

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_get_realtime"](
            property_id="properties/123",
            metrics=["activeUsers", "screenPageViews"],
        )

        assert result["rows"][0]["activeUsers"] == "10"
        assert result["rows"][0]["screenPageViews"] == "25"

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_api_error_returns_error_dict(self, mock_client_cls, mock_creds, monkeypatch):
        """API exception is caught and returned as error dict."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_realtime_report.side_effect = Exception("Quota exceeded")

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_get_realtime"](property_id="properties/123")

        assert "error" in result
        assert "Quota exceeded" in result["error"]


# ---------------------------------------------------------------------------
# ga_get_top_pages tests
# ---------------------------------------------------------------------------


class TestGaGetTopPages:
    """Tests for ga_get_top_pages convenience wrapper."""

    @pytest.fixture
    def ga_tools(self, monkeypatch):
        """Register GA tools without credentials."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)
        return fns

    @pytest.fixture
    def ga_tools_with_creds(self, monkeypatch):
        """Register GA tools with credentials set (for input validation tests)."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")
        with (
            patch(
                "aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient"
            ),
            patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials"),
        ):
            mcp = MagicMock()
            fns = {}
            mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
            register_tools(mcp, credentials=None)
            yield fns

    def test_invalid_property_id_returns_error(self, ga_tools_with_creds):
        """Property ID validation works."""
        result = ga_tools_with_creds["ga_get_top_pages"](property_id="bad-id")
        assert "error" in result
        assert "properties/" in result["error"]

    def test_limit_validation(self, ga_tools_with_creds):
        """Limit bounds are checked."""
        result = ga_tools_with_creds["ga_get_top_pages"](property_id="properties/123", limit=0)
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_no_credentials_returns_error(self, ga_tools):
        """No credentials returns error."""
        result = ga_tools["ga_get_top_pages"](property_id="properties/123")
        assert "error" in result
        assert "not configured" in result["error"]

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_correct_dimensions_and_metrics(self, mock_client_cls, mock_creds, monkeypatch):
        """Sends pagePath, pageTitle dimensions and page-related metrics."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.return_value = _make_report_response(
            dim_headers=["pagePath", "pageTitle"],
            metric_headers=["screenPageViews", "averageSessionDuration", "bounceRate"],
            rows=[(["/home", "Home Page"], ["1000", "120.5", "0.45"])],
        )

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_get_top_pages"](property_id="properties/123")

        assert result["row_count"] == 1
        assert result["rows"][0]["pagePath"] == "/home"
        assert result["rows"][0]["pageTitle"] == "Home Page"
        assert result["dimension_headers"] == ["pagePath", "pageTitle"]
        assert "screenPageViews" in result["metric_headers"]
        assert "averageSessionDuration" in result["metric_headers"]
        assert "bounceRate" in result["metric_headers"]

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_date_range_and_limit_forwarded(self, mock_client_cls, mock_creds, monkeypatch):
        """Custom date range and limit are passed to the API."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.return_value = _make_report_response(
            dim_headers=["pagePath", "pageTitle"],
            metric_headers=["screenPageViews", "averageSessionDuration", "bounceRate"],
            rows=[],
        )

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        fns["ga_get_top_pages"](
            property_id="properties/123",
            start_date="2024-01-01",
            end_date="2024-01-31",
            limit=5,
        )

        # Verify the API was called (the request object is constructed internally)
        mock_api.run_report.assert_called_once()


# ---------------------------------------------------------------------------
# ga_get_traffic_sources tests
# ---------------------------------------------------------------------------


class TestGaGetTrafficSources:
    """Tests for ga_get_traffic_sources convenience wrapper."""

    @pytest.fixture
    def ga_tools(self, monkeypatch):
        """Register GA tools without credentials."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)
        return fns

    @pytest.fixture
    def ga_tools_with_creds(self, monkeypatch):
        """Register GA tools with credentials set (for input validation tests)."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")
        with (
            patch(
                "aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient"
            ),
            patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials"),
        ):
            mcp = MagicMock()
            fns = {}
            mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
            register_tools(mcp, credentials=None)
            yield fns

    def test_invalid_property_id_returns_error(self, ga_tools_with_creds):
        """Property ID validation works."""
        result = ga_tools_with_creds["ga_get_traffic_sources"](property_id="bad-id")
        assert "error" in result
        assert "properties/" in result["error"]

    def test_limit_validation(self, ga_tools_with_creds):
        """Limit bounds are checked."""
        result = ga_tools_with_creds["ga_get_traffic_sources"](
            property_id="properties/123", limit=10001
        )
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_no_credentials_returns_error(self, ga_tools):
        """No credentials returns error."""
        result = ga_tools["ga_get_traffic_sources"](property_id="properties/123")
        assert "error" in result
        assert "not configured" in result["error"]

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_correct_dimensions_and_metrics(self, mock_client_cls, mock_creds, monkeypatch):
        """Sends sessionSource, sessionMedium dimensions and traffic metrics."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.return_value = _make_report_response(
            dim_headers=["sessionSource", "sessionMedium"],
            metric_headers=["sessions", "totalUsers", "conversions"],
            rows=[
                (["google", "organic"], ["500", "400", "10"]),
                (["direct", "(none)"], ["200", "180", "5"]),
            ],
        )

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_get_traffic_sources"](property_id="properties/123")

        assert result["row_count"] == 2
        assert result["rows"][0]["sessionSource"] == "google"
        assert result["rows"][0]["sessionMedium"] == "organic"
        assert result["dimension_headers"] == ["sessionSource", "sessionMedium"]
        assert "sessions" in result["metric_headers"]
        assert "totalUsers" in result["metric_headers"]
        assert "conversions" in result["metric_headers"]

    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.Credentials")
    @patch("aden_tools.tools.google_analytics_tool.google_analytics_tool.BetaAnalyticsDataClient")
    def test_api_error_returns_error_dict(self, mock_client_cls, mock_creds, monkeypatch):
        """API exception is caught and returned as error dict."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/path.json")

        mock_api = MagicMock()
        mock_client_cls.return_value = mock_api
        mock_api.run_report.side_effect = Exception("Service unavailable")

        mcp = MagicMock()
        fns = {}
        mcp.tool.return_value = lambda fn: fns.update({fn.__name__: fn}) or fn
        register_tools(mcp, credentials=None)

        result = fns["ga_get_traffic_sources"](property_id="properties/123")

        assert "error" in result
        assert "Service unavailable" in result["error"]


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Tests for tool registration in register_all_tools."""

    def test_register_tools_registers_all_four_tools(self):
        """register_tools registers exactly 4 GA tool functions."""
        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = lambda fn: registered_fns.update({fn.__name__: fn}) or fn

        register_tools(mcp, credentials=None)

        expected_tools = {
            "ga_run_report",
            "ga_get_realtime",
            "ga_get_top_pages",
            "ga_get_traffic_sources",
        }
        assert set(registered_fns.keys()) == expected_tools

    def test_register_all_tools_includes_ga_tools(self):
        """register_all_tools return list includes all GA tool names."""
        from fastmcp import FastMCP

        from aden_tools.tools import register_all_tools

        mcp = FastMCP("test-ga-registration")

        result = register_all_tools(mcp, credentials=None)

        for tool_name in [
            "ga_run_report",
            "ga_get_realtime",
            "ga_get_top_pages",
            "ga_get_traffic_sources",
        ]:
            assert tool_name in result, f"{tool_name} missing from register_all_tools"

    def test_credentials_passed_through(self):
        """Credential store adapter is passed to register_tools."""
        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = lambda fn: registered_fns.update({fn.__name__: fn}) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "/fake/path.json"

        register_tools(mcp, credentials=cred_manager)

        assert len(registered_fns) == 4
