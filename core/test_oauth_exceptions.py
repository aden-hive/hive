#!/usr/bin/env python3
"""Tests for structured OAuth exception handling."""

import unittest
from oauth_exceptions import (
    OAuthAccessDeniedError,
    OAuthConfigurationError,
    OAuthCredentialError,
    OAuthError,
    OAuthNetworkError,
    OAuthRedirectError,
    OAuthServerError,
    OAuthTimeoutError,
    OAuthTokenRefreshError,
    OAuthValidationError,
    parse_oauth_error_response,
)


class TestOAuthExceptions(unittest.TestCase):
    """Test OAuth exception classes."""

    def test_base_oauth_error(self):
        """Test base OAuthError class."""
        error = OAuthError("Test error", details={"key": "value"}, recoverable=True)
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.details, {"key": "value"})
        self.assertTrue(error.recoverable)
        self.assertIn("Test error", str(error))
        self.assertIn("key=value", str(error))

    def test_configuration_error(self):
        """Test OAuthConfigurationError."""
        error = OAuthConfigurationError("Missing client ID")
        self.assertEqual(error.message, "Missing client ID")
        self.assertTrue(error.recoverable)

    def test_network_error(self):
        """Test OAuthNetworkError."""
        error = OAuthNetworkError("Connection timeout", details={"host": "oauth.example.com"})
        self.assertEqual(error.message, "Connection timeout")
        self.assertTrue(error.recoverable)

    def test_server_error_recoverable(self):
        """Test OAuthServerError with recoverable status codes."""
        error = OAuthServerError("Service unavailable", status_code=503)
        self.assertEqual(error.status_code, 503)
        self.assertTrue(error.recoverable)

    def test_server_error_non_recoverable(self):
        """Test OAuthServerError with non-recoverable status codes."""
        error = OAuthServerError("Bad request", status_code=400)
        self.assertEqual(error.status_code, 400)
        self.assertFalse(error.recoverable)

    def test_credential_error_recoverable(self):
        """Test OAuthCredentialError with recoverable error codes."""
        error = OAuthCredentialError("Token expired", error_code="invalid_grant")
        self.assertEqual(error.error_code, "invalid_grant")
        self.assertTrue(error.recoverable)

    def test_credential_error_non_recoverable(self):
        """Test OAuthCredentialError with non-recoverable error codes."""
        error = OAuthCredentialError("Invalid client", error_code="invalid_client")
        self.assertEqual(error.error_code, "invalid_client")
        self.assertFalse(error.recoverable)

    def test_redirect_error(self):
        """Test OAuthRedirectError."""
        error = OAuthRedirectError("Redirect URI mismatch")
        self.assertTrue(error.recoverable)

    def test_access_denied_error(self):
        """Test OAuthAccessDeniedError."""
        error = OAuthAccessDeniedError()
        self.assertEqual(error.message, "User denied access")
        self.assertTrue(error.recoverable)

    def test_token_refresh_error(self):
        """Test OAuthTokenRefreshError."""
        error = OAuthTokenRefreshError("Refresh token expired")
        self.assertFalse(error.recoverable)

    def test_validation_error(self):
        """Test OAuthValidationError."""
        error = OAuthValidationError("Token validation failed")
        self.assertTrue(error.recoverable)

    def test_timeout_error(self):
        """Test OAuthTimeoutError."""
        error = OAuthTimeoutError("Request timed out", timeout_seconds=30)
        self.assertEqual(error.timeout_seconds, 30)
        self.assertTrue(error.recoverable)

    def test_parse_access_denied(self):
        """Test parsing access_denied error."""
        error_data = {
            "error": "access_denied",
            "error_description": "User did not approve",
        }
        error = parse_oauth_error_response(error_data)
        self.assertIsInstance(error, OAuthAccessDeniedError)
        self.assertIn("User did not approve", error.message)

    def test_parse_invalid_grant(self):
        """Test parsing invalid_grant error."""
        error_data = {
            "error": "invalid_grant",
            "error_description": "Authorization code expired",
        }
        error = parse_oauth_error_response(error_data)
        self.assertIsInstance(error, OAuthCredentialError)
        self.assertEqual(error.error_code, "invalid_grant")
        self.assertTrue(error.recoverable)

    def test_parse_redirect_uri_mismatch(self):
        """Test parsing redirect_uri_mismatch error."""
        error_data = {
            "error": "redirect_uri_mismatch",
            "error_description": "Redirect URI does not match",
        }
        error = parse_oauth_error_response(error_data)
        self.assertIsInstance(error, OAuthRedirectError)

    def test_parse_invalid_client(self):
        """Test parsing invalid_client error."""
        error_data = {
            "error": "invalid_client",
            "error_description": "Client authentication failed",
        }
        error = parse_oauth_error_response(error_data)
        self.assertIsInstance(error, OAuthCredentialError)
        self.assertEqual(error.error_code, "invalid_client")

    def test_parse_invalid_request(self):
        """Test parsing invalid_request error."""
        error_data = {
            "error": "invalid_request",
            "error_description": "Missing required parameter",
        }
        error = parse_oauth_error_response(error_data)
        self.assertIsInstance(error, OAuthConfigurationError)

    def test_parse_server_error(self):
        """Test parsing server_error."""
        error_data = {
            "error": "server_error",
            "error_description": "Internal server error",
        }
        error = parse_oauth_error_response(error_data, status_code=500)
        self.assertIsInstance(error, OAuthServerError)
        self.assertEqual(error.status_code, 500)
        self.assertTrue(error.recoverable)

    def test_parse_unknown_error(self):
        """Test parsing unknown error code."""
        error_data = {
            "error": "unknown_error_code",
            "error_description": "Some unknown error",
        }
        error = parse_oauth_error_response(error_data)
        self.assertIsInstance(error, OAuthError)
        self.assertIn("unknown_error_code", error.message)

    def test_parse_empty_error(self):
        """Test parsing empty error data."""
        error = parse_oauth_error_response(None)
        self.assertIsInstance(error, OAuthServerError)
        self.assertIn("Unknown", error.message)

    def test_parse_with_error_uri(self):
        """Test parsing error with error_uri."""
        error_data = {
            "error": "invalid_grant",
            "error_description": "Token expired",
            "error_uri": "https://example.com/docs/errors",
        }
        error = parse_oauth_error_response(error_data)
        self.assertEqual(error.details.get("error_uri"), "https://example.com/docs/errors")


if __name__ == "__main__":
    unittest.main()
