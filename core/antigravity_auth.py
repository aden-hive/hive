#!/usr/bin/env python3
"""Antigravity authentication CLI.

Implements OAuth2 flow for Google's Antigravity Code Assist gateway.
Credentials are stored in ~/.hive/antigravity-accounts.json.

Usage:
    python -m antigravity_auth auth account add
    python -m antigravity_auth auth account list
    python -m antigravity_auth auth account remove <email>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from oauth_exceptions import (
    OAuthConfigurationError,
    OAuthCredentialError,
    OAuthNetworkError,
    OAuthRedirectError,
    OAuthServerError,
    OAuthTimeoutError,
    OAuthTokenRefreshError,
    OAuthValidationError,
    parse_oauth_error_response,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# OAuth endpoints
_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Scopes for Antigravity/Cloud Code Assist
_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Credentials file path in ~/.hive/
_ACCOUNTS_FILE = Path.home() / ".hive" / "antigravity-accounts.json"

# Default project ID
_DEFAULT_PROJECT_ID = "rising-fact-p41fc"
_DEFAULT_REDIRECT_PORT = 51121

# OAuth credentials fetched from the opencode-antigravity-auth project.
# This project reverse-engineered and published the public OAuth credentials
# for Google's Antigravity/Cloud Code Assist API.
# Source: https://github.com/NoeFabris/opencode-antigravity-auth
_CREDENTIALS_URL = "https://raw.githubusercontent.com/NoeFabris/opencode-antigravity-auth/dev/src/constants.ts"

# Cached credentials fetched from public source
_cached_client_id: str | None = None
_cached_client_secret: str | None = None


def _fetch_credentials_from_public_source() -> tuple[str | None, str | None]:
    """Fetch OAuth client ID and secret from the public npm package source on GitHub."""
    global _cached_client_id, _cached_client_secret
    if _cached_client_id and _cached_client_secret:
        return _cached_client_id, _cached_client_secret

    try:
        req = urllib.request.Request(_CREDENTIALS_URL, headers={"User-Agent": "Hive-Antigravity-Auth/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            import re

            id_match = re.search(r'ANTIGRAVITY_CLIENT_ID\s*=\s*"([^"]+)"', content)
            secret_match = re.search(r'ANTIGRAVITY_CLIENT_SECRET\s*=\s*"([^"]+)"', content)
            if id_match:
                _cached_client_id = id_match.group(1)
            if secret_match:
                _cached_client_secret = secret_match.group(1)
            return _cached_client_id, _cached_client_secret
    except urllib.error.URLError as e:
        raise OAuthNetworkError(
            "Failed to fetch OAuth credentials from public source",
            details={"url": _CREDENTIALS_URL, "error": str(e)},
        )
    except Exception as e:
        logger.debug(f"Failed to fetch credentials from public source: {e}")
    return None, None


def get_client_id() -> str:
    """Get OAuth client ID from env, config, or public source."""
    env_id = os.environ.get("ANTIGRAVITY_CLIENT_ID")
    if env_id:
        return env_id

    # Try hive config
    hive_cfg = Path.home() / ".hive" / "configuration.json"
    if hive_cfg.exists():
        try:
            with open(hive_cfg) as f:
                cfg = json.load(f)
                cfg_id = cfg.get("llm", {}).get("antigravity_client_id")
                if cfg_id:
                    return cfg_id
        except Exception:
            pass

    # Fetch from public source
    client_id, _ = _fetch_credentials_from_public_source()
    if client_id:
        return client_id

    raise OAuthConfigurationError(
        "Could not obtain Antigravity OAuth client ID",
        details={
            "suggestions": [
                "Set ANTIGRAVITY_CLIENT_ID environment variable",
                "Add 'antigravity_client_id' to ~/.hive/configuration.json",
                "Check network connection to fetch from public source",
            ]
        },
    )


def get_client_secret() -> str | None:
    """Get OAuth client secret from env, config, or public source."""
    secret = os.environ.get("ANTIGRAVITY_CLIENT_SECRET")
    if secret:
        return secret

    # Try to read from hive config
    hive_cfg = Path.home() / ".hive" / "configuration.json"
    if hive_cfg.exists():
        try:
            with open(hive_cfg) as f:
                cfg = json.load(f)
                secret = cfg.get("llm", {}).get("antigravity_client_secret")
                if secret:
                    return secret
        except Exception:
            pass

    # Fetch from public source (npm package on GitHub)
    _, secret = _fetch_credentials_from_public_source()
    return secret


def find_free_port() -> int:
    """Find an available local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return s.getsockname()[1]


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback from browser."""

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress default logging

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/oauth-callback":
            query = urllib.parse.parse_qs(parsed.query)

            if "error" in query:
                self.error = query["error"][0]
                self._send_response("Authentication failed. You can close this window.")
                return

            if "code" in query and "state" in query:
                OAuthCallbackHandler.auth_code = query["code"][0]
                OAuthCallbackHandler.state = query["state"][0]
                self._send_response("Authentication successful! You can close this window and return to the terminal.")
                return

        self._send_response("Waiting for authentication...")

    def _send_response(self, message: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head><title>Antigravity Auth</title></head>
<body style="font-family: system-ui; display: flex; align-items: center;
      justify-content: center; height: 100vh; margin: 0; background: #1a1a2e;
      color: #eee;">
    <div style="text-align: center;">
        <h2>{message}</h2>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode())


def wait_for_callback(port: int, timeout: int = 300) -> tuple[str | None, str | None, str | None]:
    """Start local server and wait for OAuth callback."""
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.timeout = 1

    start = time.time()
    while time.time() - start < timeout:
        if OAuthCallbackHandler.auth_code:
            return (
                OAuthCallbackHandler.auth_code,
                OAuthCallbackHandler.state,
                OAuthCallbackHandler.error,
            )
        server.handle_request()

    raise OAuthTimeoutError(
        "OAuth callback not received within timeout period",
        timeout_seconds=timeout,
        details={"port": port, "suggestion": "Try authenticating again or check if the browser blocked the redirect"},
    )


def exchange_code_for_tokens(
    code: str, redirect_uri: str, client_id: str, client_secret: str | None
) -> dict[str, Any]:
    """Exchange authorization code for tokens.
    
    Raises:
        OAuthCredentialError: Invalid or expired authorization code
        OAuthServerError: OAuth server error
        OAuthNetworkError: Network-related failure
    """
    data = {
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if client_secret:
        data["client_secret"] = client_secret

    body = urllib.parse.urlencode(data).encode()

    req = urllib.request.Request(
        _OAUTH_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Parse error response from OAuth server
        try:
            error_data = json.loads(e.read().decode())
            raise parse_oauth_error_response(error_data, e.code)
        except (json.JSONDecodeError, AttributeError):
            raise OAuthServerError(
                f"Token exchange failed with HTTP {e.code}",
                status_code=e.code,
                details={"url": _OAUTH_TOKEN_URL},
            )
    except urllib.error.URLError as e:
        raise OAuthNetworkError(
            "Network error during token exchange",
            details={"url": _OAUTH_TOKEN_URL, "error": str(e.reason)},
        )
    except socket.timeout:
        raise OAuthTimeoutError(
            "Token exchange request timed out",
            timeout_seconds=30,
            details={"url": _OAUTH_TOKEN_URL},
        )
    except Exception as e:
        raise OAuthServerError(
            f"Unexpected error during token exchange: {type(e).__name__}",
            details={"error": str(e), "url": _OAUTH_TOKEN_URL},
        )


def get_user_email(access_token: str) -> str | None:
    """Get user email from Google API.
    
    Returns:
        User email or None if request fails
    """
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("email")
    except urllib.error.HTTPError as e:
        logger.debug(f"Failed to get user email (HTTP {e.code}): {e.reason}")
        return None
    except urllib.error.URLError as e:
        logger.debug(f"Network error getting user email: {e.reason}")
        return None
    except Exception as e:
        logger.debug(f"Error getting user email: {e}")
        return None


def load_accounts() -> dict[str, Any]:
    """Load existing accounts from file."""
    if not _ACCOUNTS_FILE.exists():
        return {"schemaVersion": 4, "accounts": []}
    try:
        with open(_ACCOUNTS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"schemaVersion": 4, "accounts": []}


def save_accounts(data: dict[str, Any]) -> None:
    """Save accounts to file."""
    _ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_ACCOUNTS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved credentials to {_ACCOUNTS_FILE}")


def validate_credentials(access_token: str, project_id: str = _DEFAULT_PROJECT_ID) -> bool:
    """Test if credentials work by making a simple API call to Antigravity.

    Returns True if credentials are valid, False otherwise.
    
    Raises:
        OAuthValidationError: If validation fails with actionable error details
    """
    endpoint = "https://daily-cloudcode-pa.sandbox.googleapis.com"
    body = {
        "project": project_id,
        "model": "gemini-3-flash",
        "request": {
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "generationConfig": {"maxOutputTokens": 10},
        },
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": "validation-test",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Antigravity/1.18.3"
        ),
        "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    }

    try:
        req = urllib.request.Request(
            f"{endpoint}/v1internal:generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
            return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise OAuthValidationError(
                "Access token is invalid or expired",
                details={"status_code": 401, "suggestion": "Re-authenticate to obtain a new token"},
            )
        elif e.code == 403:
            raise OAuthValidationError(
                "Access forbidden - token may lack required permissions",
                details={"status_code": 403, "project_id": project_id},
            )
        logger.debug(f"Validation failed with HTTP {e.code}")
        return False
    except urllib.error.URLError as e:
        logger.debug(f"Network error during validation: {e.reason}")
        return False
    except Exception as e:
        logger.debug(f"Validation error: {e}")
        return False


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str | None) -> dict[str, Any]:
    """Refresh the access token using the refresh token.
    
    Raises:
        OAuthTokenRefreshError: If refresh fails
        OAuthCredentialError: If refresh token is invalid or expired
        OAuthNetworkError: If network error occurs
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        _OAUTH_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            error_data = json.loads(e.read().decode())
            error = parse_oauth_error_response(error_data, e.code)
            # Wrap in TokenRefreshError for clearer context
            raise OAuthTokenRefreshError(
                f"Failed to refresh token: {error.message}",
                details={"original_error": error_data, "status_code": e.code},
            )
        except (json.JSONDecodeError, AttributeError):
            raise OAuthTokenRefreshError(
                f"Token refresh failed with HTTP {e.code}",
                details={"status_code": e.code, "url": _OAUTH_TOKEN_URL},
            )
    except urllib.error.URLError as e:
        raise OAuthNetworkError(
            "Network error during token refresh",
            details={"url": _OAUTH_TOKEN_URL, "error": str(e.reason)},
        )
    except socket.timeout:
        raise OAuthTimeoutError(
            "Token refresh request timed out",
            timeout_seconds=30,
            details={"url": _OAUTH_TOKEN_URL},
        )
    except Exception as e:
        raise OAuthTokenRefreshError(
            f"Unexpected error during token refresh: {type(e).__name__}",
            details={"error": str(e)},
        )


def cmd_account_add(args: argparse.Namespace) -> int:
    """Add a new Antigravity account via OAuth2.

    First checks if valid credentials already exist. If so, validates them
    and skips OAuth if they work. Otherwise, proceeds with OAuth flow.
    """
    try:
        client_id = get_client_id()
        client_secret = get_client_secret()
    except OAuthConfigurationError as e:
        logger.error(f"Configuration error: {e.message}")
        if e.details.get("suggestions"):
            logger.info("\nSuggestions:")
            for suggestion in e.details["suggestions"]:
                logger.info(f"  - {suggestion}")
        return 1
    except OAuthNetworkError as e:
        logger.error(f"Network error: {e.message}")
        logger.info("Check your internet connection and try again.")
        return 1

    # Check if credentials already exist
    accounts_data = load_accounts()
    accounts = accounts_data.get("accounts", [])

    if accounts:
        account = next((a for a in accounts if a.get("enabled", True) is not False), accounts[0])
        access_token = account.get("access")
        refresh_token_str = account.get("refresh", "")
        refresh_token = refresh_token_str.split("|")[0] if refresh_token_str else None
        project_id = refresh_token_str.split("|")[1] if "|" in refresh_token_str else _DEFAULT_PROJECT_ID
        email = account.get("email", "unknown")
        expires_ms = account.get("expires", 0)
        expires_at = expires_ms / 1000.0 if expires_ms else 0.0

        # Check if token is expired or near expiry
        if access_token and expires_at and time.time() < expires_at - 60:
            # Token still valid, test it
            logger.info(f"Found existing credentials for: {email}")
            logger.info("Validating existing credentials...")
            try:
                if validate_credentials(access_token, project_id):
                    logger.info("✓ Credentials valid! Skipping OAuth.")
                    return 0
                else:
                    logger.info("Credentials failed validation, refreshing...")
            except OAuthValidationError as e:
                logger.warning(f"Validation failed: {e.message}")
                logger.info("Attempting to refresh token...")
        elif refresh_token:
            logger.info(f"Found expired credentials for: {email}")
            logger.info("Attempting token refresh...")

            try:
                tokens = refresh_access_token(refresh_token, client_id, client_secret)
                new_access = tokens.get("access_token")
                expires_in = tokens.get("expires_in", 3600)
                if new_access:
                    # Update the account
                    account["access"] = new_access
                    account["expires"] = int((time.time() + expires_in) * 1000)
                    accounts_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    save_accounts(accounts_data)

                    # Validate the refreshed token
                    logger.info("Validating refreshed credentials...")
                    try:
                        if validate_credentials(new_access, project_id):
                            logger.info("✓ Credentials refreshed and validated!")
                            return 0
                        else:
                            logger.info("Refreshed token failed validation, proceeding with OAuth...")
                    except OAuthValidationError as e:
                        logger.warning(f"Validation failed: {e.message}")
                        logger.info("Proceeding with OAuth...")
            except (OAuthTokenRefreshError, OAuthCredentialError) as e:
                logger.warning(f"Token refresh failed: {e.message}")
                logger.info("Proceeding with OAuth flow...")
            except OAuthNetworkError as e:
                logger.error(f"Network error during refresh: {e.message}")
                return 1

    # No valid credentials, proceed with OAuth
    if not client_secret:
        logger.warning(
            "No client secret configured. Token refresh may fail.\n"
            "Set ANTIGRAVITY_CLIENT_SECRET env var or add "
            "'antigravity_client_secret' to ~/.hive/configuration.json"
        )

    # Use fixed port and path matching Google's expected OAuth redirect URI
    port = _DEFAULT_REDIRECT_PORT
    redirect_uri = f"http://localhost:{port}/oauth-callback"

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(16)

    # Build authorization URL
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_OAUTH_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    logger.info("Opening browser for authentication...")
    logger.info(f"If the browser doesn't open, visit: {auth_url}\n")

    # Open browser
    webbrowser.open(auth_url)

    # Wait for callback
    logger.info(f"Listening for callback on port {port}...")
    try:
        code, received_state, error = wait_for_callback(port)
    except OAuthTimeoutError as e:
        logger.error(f"Timeout: {e.message}")
        if e.details.get("suggestion"):
            logger.info(f"Suggestion: {e.details['suggestion']}")
        return 1

    if error:
        logger.error(f"Authentication failed: {error}")
        return 1

    if not code:
        logger.error("No authorization code received")
        return 1

    if received_state != state:
        logger.error("State mismatch - possible CSRF attack")
        return 1

    # Exchange code for tokens
    logger.info("Exchanging authorization code for tokens...")
    try:
        tokens = exchange_code_for_tokens(code, redirect_uri, client_id, client_secret)
    except OAuthCredentialError as e:
        logger.error(f"Credential error: {e.message}")
        if e.error_code == "invalid_grant":
            logger.info("The authorization code may have expired. Please try again.")
        return 1
    except OAuthRedirectError as e:
        logger.error(f"Redirect URI error: {e.message}")
        logger.info(
            f"Expected redirect URI: {redirect_uri}\n"
            "Ensure this matches the OAuth client configuration."
        )
        return 1
    except OAuthServerError as e:
        logger.error(f"Server error: {e.message}")
        if e.recoverable:
            logger.info("This may be a temporary issue. Please try again later.")
        return 1
    except OAuthNetworkError as e:
        logger.error(f"Network error: {e.message}")
        return 1
    except OAuthTimeoutError as e:
        logger.error(f"Timeout: {e.message}")
        return 1

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token:
        logger.error("No access token in response")
        return 1

    # Get user email
    email = get_user_email(access_token)
    if email:
        logger.info(f"Authenticated as: {email}")

    # Load existing accounts and add/update
    accounts_data = load_accounts()
    accounts = accounts_data.get("accounts", [])

    # Build new account entry (V4 schema)
    expires_ms = int((time.time() + expires_in) * 1000)
    refresh_entry = f"{refresh_token}|{_DEFAULT_PROJECT_ID}"

    new_account = {
        "access": access_token,
        "refresh": refresh_entry,
        "expires": expires_ms,
        "email": email,
        "enabled": True,
    }

    # Update existing account or add new one
    existing_idx = next((i for i, a in enumerate(accounts) if a.get("email") == email), None)
    if existing_idx is not None:
        accounts[existing_idx] = new_account
        logger.info(f"Updated existing account: {email}")
    else:
        accounts.append(new_account)
        logger.info(f"Added new account: {email}")

    accounts_data["accounts"] = accounts
    accounts_data["schemaVersion"] = 4
    accounts_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    save_accounts(accounts_data)
    logger.info("\n✓ Authentication complete!")
    return 0


def cmd_account_list(args: argparse.Namespace) -> int:
    """List all stored accounts."""
    data = load_accounts()
    accounts = data.get("accounts", [])

    if not accounts:
        logger.info("No accounts configured.")
        logger.info("Run 'antigravity auth account add' to add one.")
        return 0

    logger.info("Configured accounts:\n")
    for i, account in enumerate(accounts, 1):
        email = account.get("email", "unknown")
        enabled = "enabled" if account.get("enabled", True) else "disabled"
        logger.info(f"  {i}. {email} ({enabled})")

    return 0


def cmd_account_remove(args: argparse.Namespace) -> int:
    """Remove an account by email."""
    email = args.email
    data = load_accounts()
    accounts = data.get("accounts", [])

    original_len = len(accounts)
    accounts = [a for a in accounts if a.get("email") != email]

    if len(accounts) == original_len:
        logger.error(f"No account found with email: {email}")
        return 1

    data["accounts"] = accounts
    save_accounts(data)
    logger.info(f"Removed account: {email}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Antigravity authentication CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # auth account add
    auth_parser = subparsers.add_parser("auth", help="Authentication commands")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    account_parser = auth_subparsers.add_parser("account", help="Account management")
    account_subparsers = account_parser.add_subparsers(dest="account_command")

    add_parser = account_subparsers.add_parser("add", help="Add a new account via OAuth2")
    add_parser.set_defaults(func=cmd_account_add)

    list_parser = account_subparsers.add_parser("list", help="List configured accounts")
    list_parser.set_defaults(func=cmd_account_list)

    remove_parser = account_subparsers.add_parser("remove", help="Remove an account")
    remove_parser.add_argument("email", help="Email of account to remove")
    remove_parser.set_defaults(func=cmd_account_remove)

    args = parser.parse_args()

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
