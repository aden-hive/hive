#!/usr/bin/env python3
"""Structured exception classes for OAuth authentication.

This module provides detailed exception types for different OAuth failure scenarios,
making it easier to debug, handle, and provide actionable error messages to users.
"""

from __future__ import annotations

from typing import Any


class OAuthError(Exception):
    """Base exception for all OAuth-related errors.
    
    Attributes:
        message: Human-readable error description
        details: Additional context about the error
        recoverable: Whether the error can potentially be recovered from
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None, recoverable: bool = False):
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)

    def __str__(self) -> str:
        base = self.message
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{base} ({details_str})"
        return base


class OAuthConfigurationError(OAuthError):
    """OAuth configuration is missing or invalid.
    
    Examples:
        - Missing client ID or client secret
        - Invalid redirect URI configuration
        - Missing required environment variables
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details, recoverable=True)


class OAuthNetworkError(OAuthError):
    """Network-related OAuth failure.
    
    Examples:
        - Connection timeout
        - DNS resolution failure
        - Network unreachable
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details, recoverable=True)


class OAuthServerError(OAuthError):
    """OAuth server returned an error response.
    
    Examples:
        - 500 Internal Server Error
        - 503 Service Unavailable
        - Rate limiting (429 Too Many Requests)
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        details = details or {}
        if status_code:
            details["status_code"] = status_code
        if error_code:
            details["error_code"] = error_code
        super().__init__(message, details, recoverable=status_code in (429, 500, 503) if status_code else False)
        self.status_code = status_code
        self.error_code = error_code


class OAuthCredentialError(OAuthError):
    """Invalid or expired credentials.
    
    Examples:
        - invalid_grant: Authorization code expired or already used
        - invalid_client: Client authentication failed
        - unauthorized_client: Client not authorized for this grant type
    """

    def __init__(self, message: str, error_code: str | None = None, details: dict[str, Any] | None = None):
        details = details or {}
        if error_code:
            details["error_code"] = error_code
        # Invalid grant errors may be recoverable by re-authenticating
        recoverable = error_code in ("invalid_grant", "expired_token")
        super().__init__(message, details, recoverable=recoverable)
        self.error_code = error_code


class OAuthRedirectError(OAuthError):
    """Redirect URI mismatch or callback error.
    
    Examples:
        - redirect_uri_mismatch: Redirect URI doesn't match registered URI
        - Callback timeout
        - Invalid state parameter (CSRF protection)
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details, recoverable=True)


class OAuthAccessDeniedError(OAuthError):
    """User denied access or authorization was cancelled.
    
    This typically occurs when the user clicks "Deny" or cancels
    the authorization flow in the OAuth consent screen.
    """

    def __init__(self, message: str = "User denied access", details: dict[str, Any] | None = None):
        super().__init__(message, details, recoverable=True)


class OAuthTokenRefreshError(OAuthError):
    """Failed to refresh access token.
    
    Examples:
        - Refresh token expired or revoked
        - Invalid refresh token
        - Client credentials changed
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details, recoverable=False)


class OAuthValidationError(OAuthError):
    """Token validation failed.
    
    Examples:
        - Access token rejected by API
        - Token has insufficient scopes
        - Token has been revoked
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details, recoverable=True)


class OAuthTimeoutError(OAuthNetworkError):
    """Operation timed out.
    
    Examples:
        - Authorization callback not received within timeout
        - Token exchange request timed out
        - API request timed out
    """

    def __init__(self, message: str, timeout_seconds: int | None = None, details: dict[str, Any] | None = None):
        details = details or {}
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds
        super().__init__(message, details)
        self.timeout_seconds = timeout_seconds


def parse_oauth_error_response(error_data: dict[str, Any] | None, status_code: int | None = None) -> OAuthError:
    """Parse OAuth error response and return appropriate exception.
    
    Args:
        error_data: Error response from OAuth server (typically contains 'error', 'error_description')
        status_code: HTTP status code if available
        
    Returns:
        Appropriate OAuthError subclass based on error type
    """
    if not error_data:
        return OAuthServerError("Unknown OAuth error", status_code=status_code)

    error_code = error_data.get("error", "unknown_error")
    error_description = error_data.get("error_description", "No description provided")
    error_uri = error_data.get("error_uri")

    details: dict[str, Any] = {"raw_error": error_data}
    if error_uri:
        details["error_uri"] = error_uri

    # Map OAuth error codes to appropriate exception types
    if error_code == "access_denied":
        return OAuthAccessDeniedError(error_description, details)

    if error_code in ("invalid_grant", "invalid_token", "expired_token"):
        return OAuthCredentialError(error_description, error_code, details)

    if error_code in ("invalid_client", "unauthorized_client"):
        return OAuthCredentialError(
            f"Client authentication failed: {error_description}",
            error_code,
            details,
        )

    if error_code in ("redirect_uri_mismatch", "invalid_redirect_uri"):
        return OAuthRedirectError(
            f"Redirect URI configuration error: {error_description}",
            details,
        )

    if error_code in ("invalid_request", "invalid_scope", "unsupported_grant_type"):
        return OAuthConfigurationError(
            f"OAuth configuration error: {error_description}",
            details,
        )

    if error_code == "server_error" or (status_code and status_code >= 500):
        return OAuthServerError(
            f"OAuth server error: {error_description}",
            status_code=status_code,
            error_code=error_code,
            details=details,
        )

    # Generic error for unknown error codes
    return OAuthError(f"OAuth error ({error_code}): {error_description}", details)
