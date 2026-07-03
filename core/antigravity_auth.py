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
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class OAuthError(Exception):
    """Base class for OAuth-related errors."""

    def __init__(self, message: str, *, suggestion: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.suggestion = suggestion
        self.retryable = retryable

    def __str__(self) -> str:
        msg = super().__str__()
        if self.suggestion:
            return f"{msg}\n  → {self.suggestion}"
        return msg


class OAuthNetworkError(OAuthError):
    """Raised when a network request fails due to connectivity issues."""


class OAuthCredentialError(OAuthError):
    """Raised when credentials are missing, expired, or rejected by the server."""


class OAuthConfigError(OAuthError):
    """Raised when required configuration is missing or invalid."""


class OAuthServerError(OAuthError):
    """Raised when the OAuth server returns an unexpected HTTP error."""

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
    """Fetch OAuth client ID and secret from the public npm package source on GitHub.

    Returns:
        Tuple of (client_id, client_secret), either may be None on failure.
    """
    global _cached_client_id, _cached_client_secret
    if _cached_client_id and _cached_client_secret:
        return _cached_client_id, _cached_client_secret

    import re

    req = urllib.request.Request(_CREDENTIALS_URL, headers={"User-Agent": "Hive-Antigravity-Auth/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            id_match = re.search(r'ANTIGRAVITY_CLIENT_ID\s*=\s*"([^"]+)"', content)
            secret_match = re.search(r'ANTIGRAVITY_CLIENT_SECRET\s*=\s*"([^"]+)"', content)
            if id_match:
                _cached_client_id = id_match.group(1)
            if secret_match:
                _cached_client_secret = secret_match.group(1)
            if not _cached_client_id:
                logger.debug("Public source did not contain ANTIGRAVITY_CLIENT_ID")
            return _cached_client_id, _cached_client_secret
    except urllib.error.HTTPError as e:
        logger.debug(f"HTTP {e.code} fetching credentials from public source: {e.reason}")
    except urllib.error.URLError as e:
        logger.debug(f"Network error fetching credentials from public source: {e.reason}")
    except TimeoutError:
        logger.debug("Timeout fetching credentials from public source")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Unexpected error fetching credentials from public source: {e}")
    return None, None


def get_client_id() -> str:
    """Get OAuth client ID from env, config, or public source.

    Raises:
        OAuthConfigError: If the client ID cannot be found from any source.
    """
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
        except json.JSONDecodeError as e:
            logger.debug(f"Could not parse {hive_cfg}: {e}")
        except OSError as e:
            logger.debug(f"Could not read {hive_cfg}: {e}")

    # Fetch from public source
    client_id, _ = _fetch_credentials_from_public_source()
    if client_id:
        return client_id

    raise OAuthConfigError(
        "Could not obtain Antigravity OAuth client ID",
        suggestion=(
            "Set the ANTIGRAVITY_CLIENT_ID environment variable, or add "
            "'antigravity_client_id' under the 'llm' key in ~/.hive/configuration.json"
        ),
    )


def get_client_secret() -> str | None:
    """Get OAuth client secret from env, config, or public source.

    Returns None if not found (some flows work without a secret).
    """
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
        except json.JSONDecodeError as e:
            logger.debug(f"Could not parse {hive_cfg}: {e}")
        except OSError as e:
            logger.debug(f"Could not read {hive_cfg}: {e}")

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

    return None, None, "timeout"


def exchange_code_for_tokens(
    code: str, redirect_uri: str, client_id: str, client_secret: str | None
) -> dict[str, Any] | None:
    """Exchange authorization code for tokens.

    Returns:
        Token response dict, or None on failure (error already logged).

    Raises:
        OAuthServerError: On unexpected HTTP errors (4xx/5xx).
        OAuthNetworkError: On network connectivity failures.
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
        raw = b""
        try:
            raw = e.read()
        except Exception:  # noqa: BLE001
            pass
        try:
            error_body = json.loads(raw)
            error_code = error_body.get("error", "unknown_error")
            error_desc = error_body.get("error_description", "No description provided")
        except (json.JSONDecodeError, ValueError):
            error_code = "parse_error"
            error_desc = raw.decode("utf-8", errors="replace") or e.reason

        if e.code == 400:
            # authorization_code is one-time-use; a 400 here often means it was already redeemed
            if error_code in ("invalid_grant", "invalid_code"):
                logger.error(
                    f"Token exchange failed: authorization code is invalid or has already been used.\n"
                    f"  Error: {error_code} — {error_desc}\n"
                    f"  → Restart the OAuth flow to obtain a fresh authorization code."
                )
            else:
                logger.error(
                    f"Token exchange failed with HTTP 400 ({error_code}): {error_desc}\n"
                    f"  → Check that redirect_uri matches your OAuth application configuration."
                )
        elif e.code == 401:
            logger.error(
                f"Token exchange failed with HTTP 401 ({error_code}): {error_desc}\n"
                f"  → Verify that ANTIGRAVITY_CLIENT_ID and ANTIGRAVITY_CLIENT_SECRET are correct."
            )
        else:
            logger.error(
                f"Token exchange failed with HTTP {e.code} ({error_code}): {error_desc}"
            )
        return None
    except urllib.error.URLError as e:
        logger.error(
            f"Token exchange failed: network error — {e.reason}\n"
            f"  → Check your internet connection and try again."
        )
        return None
    except TimeoutError:
        logger.error(
            "Token exchange timed out after 30 seconds.\n"
            "  → Check your internet connection or try again."
        )
        return None
    except Exception as e:  # noqa: BLE001
        logger.error(f"Token exchange failed unexpectedly: {e}")
        return None


def get_user_email(access_token: str) -> str | None:
    """Get user email from Google API.

    Returns None on failure — email is optional context, not critical.
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
        if e.code == 401:
            logger.debug("Could not fetch user email: access token is invalid or expired (HTTP 401)")
        else:
            logger.debug(f"Could not fetch user email: HTTP {e.code}")
        return None
    except urllib.error.URLError as e:
        logger.debug(f"Could not fetch user email: network error — {e.reason}")
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Could not fetch user email: {e}")
        return None


def load_accounts() -> dict[str, Any]:
    """Load existing accounts from file.

    Returns an empty accounts dict if the file is missing, unreadable, or corrupt.
    """
    if not _ACCOUNTS_FILE.exists():
        return {"schemaVersion": 4, "accounts": []}
    try:
        with open(_ACCOUNTS_FILE) as f:
            data = json.load(f)
            # Ensure expected shape
            if not isinstance(data, dict):
                logger.warning(f"Accounts file {_ACCOUNTS_FILE} has unexpected format; resetting.")
                return {"schemaVersion": 4, "accounts": []}
            return data
    except json.JSONDecodeError as e:
        logger.warning(f"Accounts file {_ACCOUNTS_FILE} is corrupt (JSON error: {e}); resetting.")
        return {"schemaVersion": 4, "accounts": []}
    except OSError as e:
        logger.warning(f"Could not read accounts file {_ACCOUNTS_FILE}: {e}")
        return {"schemaVersion": 4, "accounts": []}


def save_accounts(data: dict[str, Any]) -> None:
    """Save accounts to file.

    Raises:
        OSError: If the file cannot be written (propagated to caller).
    """
    _ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_ACCOUNTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved credentials to {_ACCOUNTS_FILE}")
    except OSError as e:
        logger.error(f"Failed to save credentials to {_ACCOUNTS_FILE}: {e}")
        raise


def validate_credentials(access_token: str, project_id: str = _DEFAULT_PROJECT_ID) -> bool:
    """Test if credentials work by making a simple API call to Antigravity.

    Returns True if credentials are valid, False otherwise.
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

    req = urllib.request.Request(
        f"{endpoint}/v1internal:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
            return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.debug("Credential validation failed: access token rejected (HTTP 401)")
        elif e.code == 403:
            logger.debug(
                f"Credential validation failed: access denied for project '{project_id}' (HTTP 403). "
                "The account may not have Cloud Code Assist entitlement."
            )
        else:
            logger.debug(f"Credential validation failed: HTTP {e.code}")
        return False
    except urllib.error.URLError as e:
        logger.debug(f"Credential validation failed: network error — {e.reason}")
        return False
    except TimeoutError:
        logger.debug("Credential validation timed out")
        return False
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Credential validation failed unexpectedly: {e}")
        return False


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str | None) -> dict | None:
    """Refresh the access token using the refresh token.

    Returns:
        Token response dict, or None if the refresh fails (error is logged at debug level).
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
        raw = b""
        try:
            raw = e.read()
        except Exception:  # noqa: BLE001
            pass
        try:
            error_body = json.loads(raw)
            error_code = error_body.get("error", "unknown_error")
            error_desc = error_body.get("error_description", "")
        except (json.JSONDecodeError, ValueError):
            error_code = "parse_error"
            error_desc = raw.decode("utf-8", errors="replace") or e.reason

        if e.code in (400, 401) and error_code in ("invalid_grant", "token_expired"):
            logger.debug(
                f"Token refresh rejected (HTTP {e.code}): {error_code} — {error_desc}. "
                "Refresh token has been revoked or expired."
            )
        else:
            logger.debug(f"Token refresh failed with HTTP {e.code} ({error_code}): {error_desc}")
        return None
    except urllib.error.URLError as e:
        logger.debug(f"Token refresh failed: network error — {e.reason}")
        return None
    except TimeoutError:
        logger.debug("Token refresh timed out after 30 seconds")
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Token refresh failed unexpectedly: {e}")
        return None


def cmd_account_add(args: argparse.Namespace) -> int:
    """Add a new Antigravity account via OAuth2.

    First checks if valid credentials already exist. If so, validates them
    and skips OAuth if they work. Otherwise, proceeds with OAuth flow.
    """
    try:
        client_id = get_client_id()
    except OAuthConfigError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    client_secret = get_client_secret()

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
            if validate_credentials(access_token, project_id):
                logger.info("✓ Credentials valid! Skipping OAuth.")
                return 0
            else:
                logger.info("Credentials failed validation, refreshing...")
        elif refresh_token:
            logger.info(f"Found expired credentials for: {email}")
            logger.info("Attempting token refresh...")

            tokens = refresh_access_token(refresh_token, client_id, client_secret)
            if tokens:
                new_access = tokens.get("access_token")
                expires_in = tokens.get("expires_in", 3600)
                if new_access:
                    # Update the account
                    account["access"] = new_access
                    account["expires"] = int((time.time() + expires_in) * 1000)
                    accounts_data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    try:
                        save_accounts(accounts_data)
                    except OSError:
                        # save_accounts already logged the error
                        return 1

                    # Validate the refreshed token
                    logger.info("Validating refreshed credentials...")
                    if validate_credentials(new_access, project_id):
                        logger.info("✓ Credentials refreshed and validated!")
                        return 0
                    else:
                        logger.info("Refreshed token failed validation, proceeding with OAuth...")
            else:
                logger.info("Token refresh failed, proceeding with OAuth...")

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
    code, received_state, error = wait_for_callback(port)

    if error == "timeout":
        logger.error(
            "Authentication timed out: no callback received within 300 seconds.\n"
            "  → Ensure the browser opened and you completed the sign-in flow.\n"
            f"  → If the browser did not open automatically, visit:\n    {auth_url}"
        )
        return 1

    if error:
        logger.error(
            f"Authentication failed: Google returned error '{error}'.\n"
            "  → Check that your account has access to Antigravity / Cloud Code Assist."
        )
        return 1

    if not code:
        logger.error("No authorization code received from browser callback.")
        return 1

    if received_state != state:
        logger.error(
            "State mismatch in OAuth callback — possible CSRF attack or stale redirect.\n"
            "  → Do not reuse browser tabs from a previous authentication attempt."
        )
        return 1

    # Exchange code for tokens
    logger.info("Exchanging authorization code for tokens...")
    tokens = exchange_code_for_tokens(code, redirect_uri, client_id, client_secret)

    if not tokens:
        # exchange_code_for_tokens already logged a specific error
        return 1

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token:
        logger.error(
            "Token exchange succeeded but no access_token was returned.\n"
            "  → This may indicate a misconfigured OAuth application or a server-side issue."
        )
        return 1

    if not refresh_token:
        logger.warning(
            "No refresh_token was returned. You will need to re-authenticate when the access token expires.\n"
            "  → To enable refresh tokens, ensure 'prompt=consent' and 'access_type=offline' are set."
        )

    # Get user email
    email = get_user_email(access_token)
    if email:
        logger.info(f"Authenticated as: {email}")
    else:
        logger.warning("Could not retrieve account email — proceeding anyway.")

    # Load existing accounts and add/update
    accounts_data = load_accounts()
    accounts = accounts_data.get("accounts", [])

    # Build new account entry (V4 schema)
    expires_ms = int((time.time() + expires_in) * 1000)
    refresh_entry = f"{refresh_token}|{_DEFAULT_PROJECT_ID}" if refresh_token else ""

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

    try:
        save_accounts(accounts_data)
    except OSError:
        # save_accounts already logged the error
        return 1

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
