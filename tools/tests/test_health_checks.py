"""Tests for credential health checkers."""

from unittest.mock import MagicMock, patch

import httpx

from aden_tools.credentials.health_check import (
    HEALTH_CHECKERS,
    AnthropicHealthChecker,
    DiscordHealthChecker,
    GitHubHealthChecker,
    GoogleHealthChecker,
    GoogleMapsHealthChecker,
    GoogleSearchHealthChecker,
    ResendHealthChecker,
    check_credential_health,
)


class TestHealthCheckerRegistry:
    """Tests for the HEALTH_CHECKERS registry."""

    def test_google_search_registered(self):
        """GoogleSearchHealthChecker is registered in HEALTH_CHECKERS."""
        assert "google_search" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["google_search"], GoogleSearchHealthChecker)

    def test_anthropic_registered(self):
        """AnthropicHealthChecker is registered in HEALTH_CHECKERS."""
        assert "anthropic" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["anthropic"], AnthropicHealthChecker)

    def test_github_registered(self):
        """GitHubHealthChecker is registered in HEALTH_CHECKERS."""
        assert "github" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["github"], GitHubHealthChecker)

    def test_resend_registered(self):
        """ResendHealthChecker is registered in HEALTH_CHECKERS."""
        assert "resend" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["resend"], ResendHealthChecker)

    def test_google_maps_registered(self):
        """GoogleMapsHealthChecker is registered in HEALTH_CHECKERS."""
        assert "google_maps" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["google_maps"], GoogleMapsHealthChecker)

    def test_google_registered(self):
        """GoogleHealthChecker is registered in HEALTH_CHECKERS under 'google'."""
        assert "google" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["google"], GoogleHealthChecker)

    def test_discord_registered(self):
        """DiscordHealthChecker is registered in HEALTH_CHECKERS."""
        assert "discord" in HEALTH_CHECKERS
        assert isinstance(HEALTH_CHECKERS["discord"], DiscordHealthChecker)

    def test_all_expected_checkers_registered(self):
        """All expected health checkers are in the registry."""
        expected = {
            "hubspot",
            "brave_search",
            "google_search",
            "google_maps",
            "anthropic",
            "github",
            "resend",
            "google",
            "slack",
            "discord",
        }
        assert set(HEALTH_CHECKERS.keys()) == expected


class TestAnthropicHealthChecker:
    """Tests for AnthropicHealthChecker."""

    def _mock_response(self, status_code, json_data=None):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        if json_data:
            response.json.return_value = json_data
        return response

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_valid_key_200(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._mock_response(200)

        checker = AnthropicHealthChecker()
        result = checker.check("sk-ant-test-key")

        assert result.valid is True
        assert "valid" in result.message.lower()

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_invalid_key_401(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._mock_response(401)

        checker = AnthropicHealthChecker()
        result = checker.check("invalid-key")

        assert result.valid is False
        assert result.details["status_code"] == 401

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_rate_limited_429(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._mock_response(429)

        checker = AnthropicHealthChecker()
        result = checker.check("sk-ant-test-key")

        assert result.valid is True
        assert result.details.get("rate_limited") is True

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_bad_request_400_still_valid(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = self._mock_response(400)

        checker = AnthropicHealthChecker()
        result = checker.check("sk-ant-test-key")

        assert result.valid is True

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("timed out")

        checker = AnthropicHealthChecker()
        result = checker.check("sk-ant-test-key")

        assert result.valid is False
        assert result.details["error"] == "timeout"


class TestGitHubHealthChecker:
    """Tests for GitHubHealthChecker."""

    def _mock_response(self, status_code, json_data=None):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        if json_data:
            response.json.return_value = json_data
        return response

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_valid_token_200(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(200, {"login": "testuser"})

        checker = GitHubHealthChecker()
        result = checker.check("ghp_test-token")

        assert result.valid is True
        assert "testuser" in result.message
        assert result.details["username"] == "testuser"

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_invalid_token_401(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(401)

        checker = GitHubHealthChecker()
        result = checker.check("invalid-token")

        assert result.valid is False
        assert result.details["status_code"] == 401

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_forbidden_403(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(403)

        checker = GitHubHealthChecker()
        result = checker.check("ghp_test-token")

        assert result.valid is False
        assert result.details["status_code"] == 403

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        checker = GitHubHealthChecker()
        result = checker.check("ghp_test-token")

        assert result.valid is False
        assert result.details["error"] == "timeout"

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_request_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.RequestError("connection failed")

        checker = GitHubHealthChecker()
        result = checker.check("ghp_test-token")

        assert result.valid is False
        assert "connection failed" in result.details["error"]


class TestResendHealthChecker:
    """Tests for ResendHealthChecker."""

    def _mock_response(self, status_code, json_data=None):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        if json_data:
            response.json.return_value = json_data
        return response

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_valid_key_200(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(200)

        checker = ResendHealthChecker()
        result = checker.check("re_test-key")

        assert result.valid is True
        assert "valid" in result.message.lower()

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_invalid_key_401(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(401)

        checker = ResendHealthChecker()
        result = checker.check("invalid-key")

        assert result.valid is False
        assert result.details["status_code"] == 401

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_forbidden_403(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(403)

        checker = ResendHealthChecker()
        result = checker.check("re_test-key")

        assert result.valid is False
        assert result.details["status_code"] == 403

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        checker = ResendHealthChecker()
        result = checker.check("re_test-key")

        assert result.valid is False
        assert result.details["error"] == "timeout"


class TestGoogleMapsHealthChecker:
    """Tests for GoogleMapsHealthChecker."""

    def _mock_response(self, status_code, json_data=None):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        if json_data:
            response.json.return_value = json_data
        return response

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_valid_key_ok_status(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(200, {"status": "OK", "results": []})

        checker = GoogleMapsHealthChecker()
        result = checker.check("test-api-key")

        assert result.valid is True
        assert "valid" in result.message.lower()

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_invalid_key_request_denied(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(
            200, {"status": "REQUEST_DENIED", "results": []}
        )

        checker = GoogleMapsHealthChecker()
        result = checker.check("invalid-key")

        assert result.valid is False
        assert result.details["status"] == "REQUEST_DENIED"

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_quota_exceeded_still_valid(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(
            200, {"status": "OVER_QUERY_LIMIT", "results": []}
        )

        checker = GoogleMapsHealthChecker()
        result = checker.check("test-api-key")

        assert result.valid is True
        assert result.details.get("rate_limited") is True

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_http_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = self._mock_response(500)

        checker = GoogleMapsHealthChecker()
        result = checker.check("test-api-key")

        assert result.valid is False
        assert result.details["status_code"] == 500

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        checker = GoogleMapsHealthChecker()
        result = checker.check("test-api-key")

        assert result.valid is False
        assert result.details["error"] == "timeout"

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_request_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.RequestError("connection failed")

        checker = GoogleMapsHealthChecker()
        result = checker.check("test-api-key")

        assert result.valid is False
        assert "connection failed" in result.details["error"]


class TestCheckCredentialHealthDispatcher:
    """Tests for the check_credential_health() top-level dispatcher."""

    def test_unknown_credential_returns_valid(self):
        """Unregistered credential names are assumed valid."""
        result = check_credential_health("nonexistent_service", "some-key")

        assert result.valid is True
        assert result.details.get("no_checker") is True

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_dispatches_to_registered_checker(self, mock_client_cls):
        """Normal dispatch calls the registered checker."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        mock_client.get.return_value = response

        result = check_credential_health("brave_search", "test-key")

        assert result.valid is True
        mock_client.get.assert_called_once()

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_google_search_with_cse_id(self, mock_client_cls):
        """google_search special case passes cse_id to checker."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        mock_client.get.return_value = response

        result = check_credential_health("google_search", "api-key", cse_id="cse-123")

        assert result.valid is True
        # Verify the request included the cse_id as the cx param
        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1]["params"]["cx"] == "cse-123"

    def test_google_search_without_cse_id(self):
        """google_search without cse_id does partial check (no HTTP call)."""
        result = check_credential_health("google_search", "api-key")

        assert result.valid is True
        assert result.details.get("partial_check") is True


class TestGoogleHealthChecker:
    """Tests for GoogleHealthChecker (Gmail, Calendar, Sheets)."""

    def _setup_mock_client(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        return mock_client

    def _mock_response(self, status_code):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        return response

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_all_scopes_valid(self, mock_client_cls):
        """All three endpoints return 200/404 → valid."""
        mock_client = self._setup_mock_client(mock_client_cls)
        # Gmail 200, Calendar 200, Sheets 404 (no spreadsheet, but scope works)
        mock_client.get.side_effect = [
            self._mock_response(200),
            self._mock_response(200),
            self._mock_response(404),
        ]

        checker = GoogleHealthChecker()
        result = checker.check("test-token")

        assert result.valid is True
        assert "Gmail" in result.message
        assert "Calendar" in result.message
        assert "Sheets" in result.message

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_invalid_token_401_fails_fast(self, mock_client_cls):
        """401 on the first endpoint → token invalid, no further calls."""
        mock_client = self._setup_mock_client(mock_client_cls)
        mock_client.get.return_value = self._mock_response(401)

        checker = GoogleHealthChecker()
        result = checker.check("expired-token")

        assert result.valid is False
        assert result.details["status_code"] == 401
        # Should fail fast — only one call made
        assert mock_client.get.call_count == 1

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_missing_calendar_scope(self, mock_client_cls):
        """Gmail OK, Calendar 403, Sheets OK → reports missing calendar scope."""
        mock_client = self._setup_mock_client(mock_client_cls)
        mock_client.get.side_effect = [
            self._mock_response(200),  # gmail
            self._mock_response(403),  # calendar
            self._mock_response(404),  # sheets (404 = scope OK)
        ]

        checker = GoogleHealthChecker()
        result = checker.check("test-token")

        assert result.valid is False
        assert "calendar" in result.details["missing_scopes"]
        assert "gmail" not in result.details["missing_scopes"]

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_missing_gmail_and_sheets_scopes(self, mock_client_cls):
        """Gmail 403, Calendar OK, Sheets 403 → reports both missing."""
        mock_client = self._setup_mock_client(mock_client_cls)
        mock_client.get.side_effect = [
            self._mock_response(403),  # gmail
            self._mock_response(200),  # calendar
            self._mock_response(403),  # sheets
        ]

        checker = GoogleHealthChecker()
        result = checker.check("test-token")

        assert result.valid is False
        assert "gmail" in result.details["missing_scopes"]
        assert "sheets" in result.details["missing_scopes"]
        assert len(result.details["missing_scopes"]) == 2

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_sheets_404_is_success(self, mock_client_cls):
        """Sheets returns 404 for non-existent spreadsheet — that's valid."""
        mock_client = self._setup_mock_client(mock_client_cls)
        mock_client.get.side_effect = [
            self._mock_response(200),
            self._mock_response(200),
            self._mock_response(404),
        ]

        checker = GoogleHealthChecker()
        result = checker.check("test-token")

        assert result.valid is True

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_unexpected_status_code(self, mock_client_cls):
        """500 on any endpoint → reports failure with scope name."""
        mock_client = self._setup_mock_client(mock_client_cls)
        mock_client.get.side_effect = [
            self._mock_response(200),  # gmail
            self._mock_response(500),  # calendar
        ]

        checker = GoogleHealthChecker()
        result = checker.check("test-token")

        assert result.valid is False
        assert result.details["status_code"] == 500
        assert result.details["scope"] == "calendar"

    @patch("aden_tools.credentials.health_check.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = self._setup_mock_client(mock_client_cls)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        checker = GoogleHealthChecker()
        result = checker.check("test-token")

        assert result.valid is False
        assert result.details["error"] == "timeout"

    def test_request_error_with_bearer_token_sanitized(self):
        """Sanitizes Bearer tokens in error messages."""
        checker = GoogleHealthChecker()

        with patch("aden_tools.credentials.health_check.httpx.Client") as mock_client_cls:
            mock_client = self._setup_mock_client(mock_client_cls)
            mock_client.get.side_effect = httpx.RequestError(
                "Connection failed with Bearer ya29.secret-token-here"
            )

            result = checker.check("ya29.secret-token-here")

        assert not result.valid
        assert "Bearer" not in result.message
        assert "ya29" not in result.message
        assert "redacted" in result.message

    def test_request_error_without_sensitive_data_passes_through(self):
        """Non-sensitive error messages pass through unchanged."""
        checker = GoogleHealthChecker()

        with patch("aden_tools.credentials.health_check.httpx.Client") as mock_client_cls:
            mock_client = self._setup_mock_client(mock_client_cls)
            mock_client.get.side_effect = httpx.RequestError("Connection refused")

            result = checker.check("token123")

        assert not result.valid
        assert "Connection refused" in result.message
