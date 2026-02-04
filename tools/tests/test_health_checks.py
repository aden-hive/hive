"""Tests for credential health checkers."""

from unittest.mock import MagicMock, patch

import httpx

from aden_tools.credentials.health_check import (
    HEALTH_CHECKERS,
    AnthropicHealthChecker,
    GitHubHealthChecker,
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

    def test_all_expected_checkers_registered(self):
        """All expected health checkers are in the registry."""
        expected = {"hubspot", "brave_search", "google_search", "anthropic", "github", "resend"}
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
