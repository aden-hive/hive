# OAuth Structured Error Handling

## Overview

This document describes the structured error handling system for OAuth authentication in the Hive project. The system replaces generic `RuntimeError` and broad exceptions with specific, actionable exception classes.

## Problem Statement

The original OAuth implementation had several issues:
- Generic `RuntimeError` exceptions made debugging difficult
- Broad `except Exception` blocks masked specific failures
- No distinction between configuration, network, credential, and server errors
- Limited actionable error messages for users

## Solution

### Exception Hierarchy

All OAuth exceptions inherit from `OAuthError`, which provides:
- `message`: Human-readable error description
- `details`: Dictionary with additional context
- `recoverable`: Boolean indicating if the error can be recovered from

```
OAuthError (base)
├── OAuthConfigurationError (missing/invalid config)
├── OAuthNetworkError (connection/timeout issues)
│   └── OAuthTimeoutError (specific timeout failures)
├── OAuthServerError (HTTP 4xx/5xx from OAuth server)
├── OAuthCredentialError (invalid/expired credentials)
├── OAuthRedirectError (redirect URI mismatch)
├── OAuthAccessDeniedError (user denied consent)
├── OAuthTokenRefreshError (token refresh failures)
└── OAuthValidationError (token validation failures)
```

### Exception Types

#### `OAuthConfigurationError`
**When:** Missing or invalid OAuth configuration
- Missing client ID or client secret
- Invalid redirect URI configuration
- Missing required environment variables

**Recoverable:** Yes
**Example:**
```python
raise OAuthConfigurationError(
    "Could not obtain Antigravity OAuth client ID",
    details={
        "suggestions": [
            "Set ANTIGRAVITY_CLIENT_ID environment variable",
            "Add 'antigravity_client_id' to ~/.hive/configuration.json",
        ]
    },
)
```

#### `OAuthNetworkError`
**When:** Network-related failures
- Connection timeout
- DNS resolution failure
- Network unreachable

**Recoverable:** Yes
**Example:**
```python
raise OAuthNetworkError(
    "Network error during token exchange",
    details={"url": token_url, "error": str(e.reason)},
)
```

#### `OAuthTimeoutError`
**When:** Operation times out (subclass of `OAuthNetworkError`)
- Authorization callback not received
- Token exchange request timeout
- API request timeout

**Recoverable:** Yes
**Example:**
```python
raise OAuthTimeoutError(
    "OAuth callback not received within timeout period",
    timeout_seconds=300,
    details={"port": 51121},
)
```

#### `OAuthServerError`
**When:** OAuth server returns error response
- 500 Internal Server Error
- 503 Service Unavailable
- 429 Too Many Requests (rate limiting)

**Recoverable:** Yes for 429, 500, 503; No for others
**Example:**
```python
raise OAuthServerError(
    "Token exchange failed with HTTP 401",
    status_code=401,
    error_code="unauthorized",
    details={"url": token_url},
)
```

#### `OAuthCredentialError`
**When:** Invalid or expired credentials
- `invalid_grant`: Authorization code expired or already used
- `invalid_client`: Client authentication failed
- `unauthorized_client`: Client not authorized
- `invalid_token`: Access token invalid
- `expired_token`: Token has expired

**Recoverable:** Yes for `invalid_grant` and `expired_token`; No for others
**Example:**
```python
raise OAuthCredentialError(
    "Authorization code expired",
    error_code="invalid_grant",
    details={"suggestion": "Try authenticating again"},
)
```

#### `OAuthRedirectError`
**When:** Redirect URI issues or callback errors
- `redirect_uri_mismatch`: Redirect URI doesn't match registered URI
- Callback timeout
- Invalid state parameter (CSRF protection)

**Recoverable:** Yes
**Example:**
```python
raise OAuthRedirectError(
    "Redirect URI configuration error: URI mismatch",
    details={"expected": "http://localhost:51121/oauth-callback"},
)
```

#### `OAuthAccessDeniedError`
**When:** User denies access
- User clicks "Deny" in consent screen
- User cancels authorization flow

**Recoverable:** Yes
**Example:**
```python
raise OAuthAccessDeniedError(
    "User denied access",
    details={"suggestion": "User must approve access to continue"},
)
```

#### `OAuthTokenRefreshError`
**When:** Token refresh fails
- Refresh token expired or revoked
- Invalid refresh token
- Client credentials changed

**Recoverable:** No
**Example:**
```python
raise OAuthTokenRefreshError(
    "Failed to refresh token: refresh token expired",
    details={"original_error": error_data},
)
```

#### `OAuthValidationError`
**When:** Token validation fails
- Access token rejected by API
- Token has insufficient scopes
- Token has been revoked

**Recoverable:** Yes
**Example:**
```python
raise OAuthValidationError(
    "Access token is invalid or expired",
    details={"status_code": 401, "suggestion": "Re-authenticate"},
)
```

## Usage

### Parsing OAuth Error Responses

The `parse_oauth_error_response()` function automatically maps OAuth error codes to appropriate exception types:

```python
from oauth_exceptions import parse_oauth_error_response

try:
    # Make OAuth request
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
except urllib.error.HTTPError as e:
    error_data = json.loads(e.read().decode())
    raise parse_oauth_error_response(error_data, e.code)
```

### Handling Exceptions

```python
from oauth_exceptions import (
    OAuthConfigurationError,
    OAuthCredentialError,
    OAuthNetworkError,
    OAuthTimeoutError,
)

try:
    tokens = exchange_code_for_tokens(code, redirect_uri, client_id, client_secret)
except OAuthCredentialError as e:
    logger.error(f"Credential error: {e.message}")
    if e.error_code == "invalid_grant":
        logger.info("The authorization code may have expired. Please try again.")
    return 1
except OAuthNetworkError as e:
    logger.error(f"Network error: {e.message}")
    if e.recoverable:
        logger.info("This may be a temporary issue. Check your connection.")
    return 1
except OAuthTimeoutError as e:
    logger.error(f"Timeout: {e.message} (after {e.timeout_seconds}s)")
    return 1
```

## Benefits

### 1. Easier Debugging
- Specific exception types immediately indicate the failure category
- Rich error details provide context for troubleshooting
- Stack traces show exact failure points

### 2. Better User Experience
- Actionable error messages guide users toward solutions
- Suggestions field provides specific remediation steps
- Recoverable flag indicates whether retrying makes sense

### 3. More Maintainable Code
- Type-safe error handling with specific exception catches
- Clear separation between different failure modes
- Easier to add logging, metrics, or retry logic per error type

### 4. Common OAuth Failure Identification
- `invalid_grant` → Authorization code expired
- `redirect_uri_mismatch` → Configuration issue
- Network timeouts → Connectivity problem
- 401/403 responses → Credential or permission issue

## Migration Guide

### Before
```python
try:
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
except Exception as e:
    logger.error(f"Token exchange failed: {e}")
    return None
```

### After
```python
try:
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
except urllib.error.HTTPError as e:
    error_data = json.loads(e.read().decode())
    raise parse_oauth_error_response(error_data, e.code)
except urllib.error.URLError as e:
    raise OAuthNetworkError(
        "Network error during token exchange",
        details={"url": url, "error": str(e.reason)},
    )
except socket.timeout:
    raise OAuthTimeoutError(
        "Token exchange request timed out",
        timeout_seconds=30,
        details={"url": url},
    )
```

## Testing

Run the test suite to verify exception handling:

```bash
python test_oauth_exceptions.py
```

The test suite covers:
- All exception types and their properties
- Error response parsing for common OAuth error codes
- Recoverable vs non-recoverable error classification
- Error message formatting and details

## Future Enhancements

1. **Retry Logic**: Implement automatic retry for recoverable errors with exponential backoff
2. **Metrics**: Add structured logging/metrics per exception type
3. **Error Codes**: Standardize internal error codes for cross-system correlation
4. **User Guidance**: Expand suggestion fields with links to documentation

## References

- [RFC 6749 - OAuth 2.0 Authorization Framework](https://tools.ietf.org/html/rfc6749)
- [RFC 6750 - OAuth 2.0 Bearer Token Usage](https://tools.ietf.org/html/rfc6750)
- [Google OAuth 2.0 Error Responses](https://developers.google.com/identity/protocols/oauth2/web-server#handlingresponse)
