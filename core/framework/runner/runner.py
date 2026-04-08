"""Agent Runner - loads and runs exported agents."""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from framework.config import get_hive_config, get_max_context_tokens, get_preferred_model
from framework.credentials.validation import (
    ensure_credential_key_env as _ensure_credential_key_env,
)
from framework.graph import Goal
from framework.graph.edge import (
    DEFAULT_MAX_TOKENS,
    EdgeCondition,
    EdgeSpec,
    GraphSpec,
)
from framework.graph.executor import ExecutionResult
from framework.graph.node import NodeSpec
from framework.llm.provider import LLMProvider, Tool
from framework.runner.preload_validation import run_preload_validation
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.runtime_log_store import RuntimeLogStore
from framework.tools.flowchart_utils import generate_fallback_flowchart
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

CLAUDE_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
CLAUDE_OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"

# Buffer in seconds before token expiry to trigger a proactive refresh
_TOKEN_REFRESH_BUFFER_SECS = 300  # 5 minutes

# Codex (OpenAI) subscription auth
CODEX_AUTH_FILE = Path.home() / ".codex" / "auth.json"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_KEYCHAIN_SERVICE = "Codex Auth"
_CODEX_TOKEN_LIFETIME_SECS = 3600  # 1 hour (no explicit expiry field)


def _read_claude_keychain() -> dict | None:
    """Read Claude Code credentials from macOS Keychain.

    Returns the parsed JSON dict, or None if not on macOS or entry missing.
    """
    import getpass
    import platform
    import subprocess

    if platform.system() != "Darwin":
        return None

    try:
        account = getpass.getuser()
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                CLAUDE_KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=5,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        return json.loads(raw)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.debug("Claude keychain read failed: %s", exc)
        return None


def _save_claude_keychain(creds: dict) -> bool:
    """Write Claude Code credentials to macOS Keychain. Returns True on success."""
    import getpass
    import platform
    import subprocess

    if platform.system() != "Darwin":
        return False

    try:
        account = getpass.getuser()
        data = json.dumps(creds)
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                CLAUDE_KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
                data,
            ],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("Claude keychain write failed: %s", exc)
        return False


def _read_claude_credentials() -> dict | None:
    """Read Claude Code credentials from Keychain (macOS) or file (Linux/Windows)."""
    # Try macOS Keychain first
    creds = _read_claude_keychain()
    if creds:
        return creds

    # Fall back to file
    if not CLAUDE_CREDENTIALS_FILE.exists():
        return None

    try:
        with open(CLAUDE_CREDENTIALS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _refresh_claude_code_token(refresh_token: str) -> dict | None:
    """Refresh the Claude Code OAuth token using the refresh token.

    POSTs to the Anthropic OAuth token endpoint with form-urlencoded data
    (per OAuth 2.0 RFC 6749 Section 4.1.3).

    Returns:
        Dict with new token data (access_token, refresh_token, expires_in)
        on success, None on failure.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLAUDE_OAUTH_CLIENT_ID,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_OAUTH_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        logger.debug("Claude Code token refresh failed: %s", exc)
        return None


def _save_refreshed_credentials(token_data: dict) -> None:
    """Write refreshed token data back to Keychain (macOS) or credentials file."""
    import time

    creds = _read_claude_credentials()
    if not creds:
        return

    try:
        oauth = creds.get("claudeAiOauth", {})
        oauth["accessToken"] = token_data["access_token"]
        if "refresh_token" in token_data:
            oauth["refreshToken"] = token_data["refresh_token"]
        if "expires_in" in token_data:
            oauth["expiresAt"] = int((time.time() + token_data["expires_in"]) * 1000)
        creds["claudeAiOauth"] = oauth

        # Try Keychain first (macOS), fall back to file
        if _save_claude_keychain(creds):
            logger.debug("Claude Code credentials refreshed in Keychain")
            return

        if CLAUDE_CREDENTIALS_FILE.exists():
            with atomic_write(CLAUDE_CREDENTIALS_FILE, chmod=0o600) as f:
                json.dump(creds, f, indent=2)
            logger.debug("Claude Code credentials refreshed in file")
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.debug("Failed to save refreshed credentials: %s", exc)


def get_claude_code_token() -> str | None:
    """Get the OAuth token from Claude Code subscription with auto-refresh.

    Reads from macOS Keychain (on Darwin) or ~/.claude/.credentials.json
    (on Linux/Windows), as created by the Claude Code CLI.

    If the token is expired or close to expiry, attempts an automatic
    refresh using the stored refresh token.

    Returns:
        The access token if available, None otherwise.
    """
    import time

    creds = _read_claude_credentials()
    if not creds:
        return None

    oauth = creds.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken")
    if not access_token:
        return None

    # Check token expiry (expiresAt is in milliseconds)
    expires_at_ms = oauth.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    buffer_ms = _TOKEN_REFRESH_BUFFER_SECS * 1000

    if expires_at_ms > now_ms + buffer_ms:
        # Token is still valid
        return access_token

    # Token is expired or near expiry — attempt refresh
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        logger.warning("Claude Code token expired and no refresh token available")
        return access_token  # Return expired token; it may still work briefly

    logger.info("Claude Code token expired or near expiry, refreshing...")
    token_data = _refresh_claude_code_token(refresh_token)

    if token_data and "access_token" in token_data:
        _save_refreshed_credentials(token_data)
        return token_data["access_token"]

    # Refresh failed — return the existing token and warn
    logger.warning("Claude Code token refresh failed. Run 'claude' to re-authenticate.")
    return access_token


# ---------------------------------------------------------------------------
# Codex (OpenAI) subscription token helpers
# ---------------------------------------------------------------------------


def _get_codex_keychain_account() -> str:
    """Compute the macOS Keychain account name used by the Codex CLI.

    The Codex CLI stores credentials under the account
    ``cli|<sha256(~/.codex)[:16]>`` in the ``Codex Auth`` service.
    """
    import hashlib

    codex_dir = str(Path.home() / ".codex")
    digest = hashlib.sha256(codex_dir.encode()).hexdigest()[:16]
    return f"cli|{digest}"


def _read_codex_keychain() -> dict | None:
    """Read Codex auth data from macOS Keychain (macOS only).

    Returns the parsed JSON from the Keychain entry, or None if not
    available (wrong platform, entry missing, etc.).
    """
    import platform
    import subprocess

    if platform.system() != "Darwin":
        return None

    try:
        account = _get_codex_keychain_account()
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                CODEX_KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=5,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        return json.loads(raw)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.debug("Codex keychain read failed: %s", exc)
        return None


def _read_codex_auth_file() -> dict | None:
    """Read Codex auth data from ~/.codex/auth.json (fallback)."""
    if not CODEX_AUTH_FILE.exists():
        return None
    try:
        with open(CODEX_AUTH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _is_codex_token_expired(auth_data: dict) -> bool:
    """Check whether the Codex token is expired or close to expiry.

    The Codex auth.json has no explicit ``expiresAt`` field, so we infer
    expiry as ``last_refresh + _CODEX_TOKEN_LIFETIME_SECS``.  Falls back
    to the file mtime when ``last_refresh`` is absent.
    """
    import time
    from datetime import datetime

    now = time.time()
    last_refresh = auth_data.get("last_refresh")

    if last_refresh is None:
        # Fall back to file modification time
        try:
            last_refresh = CODEX_AUTH_FILE.stat().st_mtime
        except OSError:
            # Cannot determine age — assume expired
            return True
    elif isinstance(last_refresh, str):
        # Codex stores last_refresh as an ISO 8601 timestamp string —
        # convert to Unix epoch float for arithmetic.
        try:
            last_refresh = datetime.fromisoformat(last_refresh.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return True

    expires_at = last_refresh + _CODEX_TOKEN_LIFETIME_SECS
    return now >= (expires_at - _TOKEN_REFRESH_BUFFER_SECS)


def _refresh_codex_token(refresh_token: str) -> dict | None:
    """Refresh the Codex OAuth token using the refresh token.

    POSTs to the OpenAI auth endpoint with form-urlencoded data.

    Returns:
        Dict with new token data on success, None on failure.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CODEX_OAUTH_CLIENT_ID,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        CODEX_OAUTH_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        logger.debug("Codex token refresh failed: %s", exc)
        return None


def _save_refreshed_codex_credentials(auth_data: dict, token_data: dict) -> None:
    """Write refreshed tokens back to ~/.codex/auth.json only (not Keychain).

    The Codex CLI manages its own Keychain entries, so we only update the
    file-based credentials.
    """
    from datetime import datetime

    try:
        tokens = auth_data.get("tokens", {})
        tokens["access_token"] = token_data["access_token"]
        if "refresh_token" in token_data:
            tokens["refresh_token"] = token_data["refresh_token"]
        if "id_token" in token_data:
            tokens["id_token"] = token_data["id_token"]
        auth_data["tokens"] = tokens
        auth_data["last_refresh"] = datetime.now(UTC).isoformat()

        CODEX_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(CODEX_AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)
        logger.debug("Codex credentials refreshed successfully")
    except (OSError, KeyError) as exc:
        logger.debug("Failed to save refreshed Codex credentials: %s", exc)


def get_codex_token() -> str | None:
    """Get the OAuth token from Codex subscription with auto-refresh.

    Reads from macOS Keychain first, then falls back to
    ``~/.codex/auth.json``.  If the token is expired or close to
    expiry, attempts an automatic refresh.

    Returns:
        The access token if available, None otherwise.
    """
    # Try Keychain first, then file
    auth_data = _read_codex_keychain() or _read_codex_auth_file()
    if not auth_data:
        return None

    tokens = auth_data.get("tokens", {})
    access_token = tokens.get("access_token")
    if not access_token:
        return None

    # Check if token is still valid
    if not _is_codex_token_expired(auth_data):
        return access_token

    # Token is expired or near expiry — attempt refresh
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        logger.warning("Codex token expired and no refresh token available")
        return access_token  # Return expired token; it may still work briefly

    logger.info("Codex token expired or near expiry, refreshing...")
    token_data = _refresh_codex_token(refresh_token)

    if token_data and "access_token" in token_data:
        _save_refreshed_codex_credentials(auth_data, token_data)
        return token_data["access_token"]

    # Refresh failed — return the existing token and warn
    logger.warning("Codex token refresh failed. Run 'codex' to re-authenticate.")
    return access_token


def _get_account_id_from_jwt(access_token: str) -> str | None:
    """Extract the ChatGPT account_id from the access token JWT.

    The OpenAI access token JWT contains a claim at
    ``https://api.openai.com/auth`` with a ``chatgpt_account_id`` field.
    This is used as a fallback when the auth.json doesn't store the
    account_id explicitly.
    """
    import base64

    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        # Add base64 padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        auth = claims.get("https://api.openai.com/auth")
        if isinstance(auth, dict):
            account_id = auth.get("chatgpt_account_id")
            if isinstance(account_id, str) and account_id:
                return account_id
    except Exception:
        pass
    return None


def get_codex_account_id() -> str | None:
    """Extract the account ID from Codex auth data for the ChatGPT-Account-Id header.

    Checks the ``tokens.account_id`` field first, then falls back to
    decoding the account ID from the access token JWT.

    Returns:
        The account_id string if available, None otherwise.
    """
    auth_data = _read_codex_keychain() or _read_codex_auth_file()
    if not auth_data:
        return None
    tokens = auth_data.get("tokens", {})
    account_id = tokens.get("account_id")
    if account_id:
        return account_id
    # Fallback: extract from JWT
    access_token = tokens.get("access_token")
    if access_token:
        return _get_account_id_from_jwt(access_token)
    return None


# ---------------------------------------------------------------------------
# Kimi Code subscription token helpers
# ---------------------------------------------------------------------------


def get_kimi_code_token() -> str | None:
    """Get the API key from a Kimi Code CLI installation.

    Reads the API key from ``~/.kimi/config.toml``, which is created when
    the user runs ``kimi /login`` in the Kimi Code CLI.

    Returns:
        The API key if available, None otherwise.
    """
    import tomllib

    config_path = Path.home() / ".kimi" / "config.toml"
    if not config_path.exists():
        return None

    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        providers = config.get("providers", {})
        # kimi-cli stores credentials under providers.kimi-for-coding
        for provider_cfg in providers.values():
            if isinstance(provider_cfg, dict):
                key = provider_cfg.get("api_key")
                if key:
                    return key
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Antigravity subscription token helpers
# ---------------------------------------------------------------------------

# Antigravity IDE (native macOS/Linux app) stores OAuth tokens in its
# VSCode-style SQLite state database under the key
# "antigravityUnifiedStateSync.oauthToken" as a base64-encoded protobuf blob.
ANTIGRAVITY_IDE_STATE_DB = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Antigravity"
    / "User"
    / "globalStorage"
    / "state.vscdb"
)
# Linux fallback for the IDE state DB
ANTIGRAVITY_IDE_STATE_DB_LINUX = (
    Path.home() / ".config" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
)
# Antigravity credentials stored by native OAuth implementation
ANTIGRAVITY_AUTH_FILE = Path.home() / ".hive" / "antigravity-accounts.json"

ANTIGRAVITY_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_ANTIGRAVITY_TOKEN_LIFETIME_SECS = 3600  # Google access tokens expire in 1 hour
_ANTIGRAVITY_IDE_STATE_DB_KEY = "antigravityUnifiedStateSync.oauthToken"


def _read_antigravity_ide_credentials() -> dict | None:
    """Read credentials from the Antigravity IDE's SQLite state database.

    The Antigravity desktop IDE (VSCode-based) stores its OAuth token as a
    base64-encoded protobuf blob in a SQLite database.  The access token is
    a standard Google OAuth ``ya29.*`` bearer token.

    Returns:
        Dict with ``accessToken`` and optionally ``refreshToken`` keys,
        plus ``_source: "ide"`` to skip file-based save on refresh.
        Returns None if the database is absent or the key is not found.
    """
    import re
    import sqlite3

    for db_path in (ANTIGRAVITY_IDE_STATE_DB, ANTIGRAVITY_IDE_STATE_DB_LINUX):
        if not db_path.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key = ?",
                    (_ANTIGRAVITY_IDE_STATE_DB_KEY,),
                ).fetchone()
            finally:
                con.close()

            if not row:
                continue

            import base64

            blob = base64.b64decode(row[0])

            # The protobuf blob contains the access token (ya29.*) and
            # refresh token (1//*) as length-prefixed UTF-8 strings.
            # Decode the inner base64 layer and extract with regex.
            inner_b64_candidates = re.findall(rb"[A-Za-z0-9+/=_\-]{40,}", blob)
            access_token: str | None = None
            refresh_token: str | None = None
            for candidate in inner_b64_candidates:
                try:
                    padded = candidate + b"=" * (-len(candidate) % 4)
                    inner = base64.urlsafe_b64decode(padded)
                except Exception:
                    continue
                if not access_token:
                    m = re.search(rb"ya29\.[A-Za-z0-9_\-\.]+", inner)
                    if m:
                        access_token = m.group(0).decode("ascii")
                if not refresh_token:
                    m = re.search(rb"1//[A-Za-z0-9_\-\.]+", inner)
                    if m:
                        refresh_token = m.group(0).decode("ascii")
                if access_token and refresh_token:
                    break

            if access_token:
                return {
                    "accounts": [
                        {
                            "accessToken": access_token,
                            "refreshToken": refresh_token or "",
                        }
                    ],
                    "_source": "ide",
                    "_db_path": str(db_path),
                }
        except Exception as exc:
            logger.debug("Failed to read Antigravity IDE state DB: %s", exc)
            continue

    return None


def _read_antigravity_credentials() -> dict | None:
    """Read Antigravity auth data from all supported credential sources.

    Checks in order:
    1. Antigravity IDE SQLite state database (native macOS/Linux app)
    2. Native OAuth credentials file (~/.hive/antigravity-accounts.json)

    Returns:
        Auth data dict with an ``accounts`` list on success, None otherwise.
    """
    # 1. Native Antigravity IDE (primary on macOS)
    ide_creds = _read_antigravity_ide_credentials()
    if ide_creds:
        return ide_creds

    # 2. Native OAuth credentials file
    if ANTIGRAVITY_AUTH_FILE.exists():
        try:
            with open(ANTIGRAVITY_AUTH_FILE, encoding="utf-8") as f:
                data = json.load(f)
            accounts = data.get("accounts", [])
            if accounts and isinstance(accounts[0], dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _is_antigravity_token_expired(auth_data: dict) -> bool:
    """Check whether the Antigravity access token is expired or near expiry.

    For IDE-sourced credentials: uses the state DB's mtime as last_refresh
    since the IDE keeps the DB fresh while it's running.
    For JSON-sourced credentials: uses the ``last_refresh`` field or file mtime.
    """
    import time
    from datetime import datetime

    now = time.time()

    if auth_data.get("_source") == "ide":
        # The IDE refreshes tokens automatically while running.
        # Use the DB file's mtime as a proxy for when the token was last updated.
        try:
            db_path = Path(auth_data.get("_db_path", str(ANTIGRAVITY_IDE_STATE_DB)))
            last_refresh: float = db_path.stat().st_mtime
        except OSError:
            return True
        expires_at = last_refresh + _ANTIGRAVITY_TOKEN_LIFETIME_SECS
        return now >= (expires_at - _TOKEN_REFRESH_BUFFER_SECS)

    last_refresh_val: float | str | None = auth_data.get("last_refresh")
    if last_refresh_val is None:
        try:
            last_refresh_val = ANTIGRAVITY_AUTH_FILE.stat().st_mtime
        except OSError:
            return True
    elif isinstance(last_refresh_val, str):
        try:
            last_refresh_val = datetime.fromisoformat(
                last_refresh_val.replace("Z", "+00:00")
            ).timestamp()
        except (ValueError, TypeError):
            return True

    expires_at = float(last_refresh_val) + _ANTIGRAVITY_TOKEN_LIFETIME_SECS
    return now >= (expires_at - _TOKEN_REFRESH_BUFFER_SECS)


def _refresh_antigravity_token(refresh_token: str) -> dict | None:
    """Refresh the Antigravity access token via Google OAuth.

    POSTs form-encoded ``grant_type=refresh_token`` to the Google token
    endpoint using Antigravity's public OAuth client ID.

    Returns:
        Parsed response dict (containing ``access_token``) on success,
        None on any error.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    from framework.config import get_antigravity_client_id, get_antigravity_client_secret

    client_id = get_antigravity_client_id()
    client_secret = get_antigravity_client_secret()
    params: dict = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        params["client_secret"] = client_secret

    data = urllib.parse.urlencode(params).encode("utf-8")

    req = urllib.request.Request(
        ANTIGRAVITY_OAUTH_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        logger.debug("Antigravity token refresh failed: %s", exc)
        return None


def _save_refreshed_antigravity_credentials(auth_data: dict, token_data: dict) -> None:
    """Write refreshed tokens back to the Antigravity JSON credentials file.

    Skipped for IDE-sourced credentials (the IDE manages its own DB).
    Updates ``accounts[0].accessToken`` (and ``refreshToken`` if present),
    then persists ``last_refresh`` as an ISO-8601 UTC string.
    """
    from datetime import datetime

    # IDE manages its own state — we do not write back to its SQLite DB
    if auth_data.get("_source") == "ide":
        return

    try:
        accounts = auth_data.get("accounts", [])
        if not accounts:
            return
        account = accounts[0]
        account["accessToken"] = token_data["access_token"]
        if "refresh_token" in token_data:
            account["refreshToken"] = token_data["refresh_token"]
        auth_data["accounts"] = accounts
        auth_data["last_refresh"] = datetime.now(UTC).isoformat()

        ANTIGRAVITY_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(ANTIGRAVITY_AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)
        logger.debug("Antigravity credentials refreshed and saved")
    except (OSError, KeyError) as exc:
        logger.debug("Failed to save refreshed Antigravity credentials: %s", exc)


def get_antigravity_token() -> str | None:
    """Get the OAuth access token from an Antigravity subscription.

    Credential sources checked in order:
    1. Antigravity IDE SQLite state DB (native app, macOS/Linux)
    2. antigravity-auth CLI JSON file

    For IDE credentials the token is read directly (the IDE refreshes it
    automatically while running).  For JSON credentials an automatic OAuth
    refresh is attempted when the token is near expiry.

    Returns:
        The ``ya29.*`` Google OAuth access token, or None if unavailable.
    """
    auth_data = _read_antigravity_credentials()
    if not auth_data:
        return None

    accounts = auth_data.get("accounts", [])
    if not accounts:
        return None
    account = accounts[0]

    access_token = account.get("accessToken")
    if not access_token:
        return None

    if not _is_antigravity_token_expired(auth_data):
        return access_token

    # Token is expired or near expiry — attempt a refresh
    refresh_token = account.get("refreshToken")
    if not refresh_token:
        logger.warning(
            "Antigravity token expired and no refresh token available. "
            "Re-open the Antigravity IDE to refresh, or run 'antigravity-auth accounts add'."
        )
        return access_token  # return stale token; proxy may still accept it briefly

    logger.info("Antigravity token expired or near expiry, refreshing...")
    token_data = _refresh_antigravity_token(refresh_token)

    if token_data and "access_token" in token_data:
        _save_refreshed_antigravity_credentials(auth_data, token_data)
        return token_data["access_token"]

    logger.warning(
        "Antigravity token refresh failed. "
        "Re-open the Antigravity IDE or run 'antigravity-auth accounts add'."
    )
    return access_token


@dataclass
class AgentInfo:
    """Information about an exported agent."""

    name: str
    description: str
    goal_name: str
    goal_description: str
    node_count: int
    edge_count: int
    nodes: list[dict]
    edges: list[dict]
    entry_node: str
    terminal_nodes: list[str]
    success_criteria: list[dict]
    constraints: list[dict]
    required_tools: list[str]
    has_tools_module: bool


@dataclass
class ValidationResult:
    """Result of agent validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    missing_credentials: list[str] = field(default_factory=list)


def load_agent_export(data: str | dict) -> tuple[GraphSpec, Goal]:
    """
    Load GraphSpec and Goal from export_graph() output.

    Args:
        data: JSON string or dict from export_graph()

    Returns:
        Tuple of (GraphSpec, Goal)
    """
    if isinstance(data, str):
        data = json.loads(data)

    # Extract graph and goal
    graph_data = data.get("graph", {})
    goal_data = data.get("goal", {})

    # Build NodeSpec objects
    nodes = []
    for node_data in graph_data.get("nodes", []):
        nodes.append(NodeSpec(**node_data))

    # Build EdgeSpec objects
    edges = []
    for edge_data in graph_data.get("edges", []):
        condition_str = edge_data.get("condition", "on_success")
        condition_map = {
            "always": EdgeCondition.ALWAYS,
            "on_success": EdgeCondition.ON_SUCCESS,
            "on_failure": EdgeCondition.ON_FAILURE,
            "conditional": EdgeCondition.CONDITIONAL,
            "llm_decide": EdgeCondition.LLM_DECIDE,
        }
        edge = EdgeSpec(
            id=edge_data["id"],
            source=edge_data["source"],
            target=edge_data["target"],
            condition=condition_map.get(condition_str, EdgeCondition.ON_SUCCESS),
            condition_expr=edge_data.get("condition_expr"),
            priority=edge_data.get("priority", 0),
            input_mapping=edge_data.get("input_mapping", {}),
        )
        edges.append(edge)

    # Build GraphSpec
    graph = GraphSpec(
        id=graph_data.get("id", "agent-graph"),
        goal_id=graph_data.get("goal_id", ""),
        version=graph_data.get("version", "1.0.0"),
        entry_node=graph_data.get("entry_node", ""),
        entry_points=graph_data.get("entry_points", {}),  # Support pause/resume architecture
        terminal_nodes=graph_data.get("terminal_nodes", []),
        pause_nodes=graph_data.get("pause_nodes", []),  # Support pause/resume architecture
        nodes=nodes,
        edges=edges,
        max_steps=graph_data.get("max_steps", 100),
        max_retries_per_node=graph_data.get("max_retries_per_node", 3),
        description=graph_data.get("description", ""),
    )

    # Build Goal
    from framework.graph.goal import Constraint, SuccessCriterion

    success_criteria = []
    for sc_data in goal_data.get("success_criteria", []):
        success_criteria.append(
            SuccessCriterion(
                id=sc_data["id"],
                description=sc_data["description"],
                metric=sc_data.get("metric", ""),
                target=sc_data.get("target", ""),
                weight=sc_data.get("weight", 1.0),
            )
        )

    constraints = []
    for c_data in goal_data.get("constraints", []):
        constraints.append(
            Constraint(
                id=c_data["id"],
                description=c_data["description"],
                constraint_type=c_data.get("constraint_type", "hard"),
                category=c_data.get("category", "safety"),
                check=c_data.get("check", ""),
            )
        )

    goal = Goal(
        id=goal_data.get("id", ""),
        name=goal_data.get("name", ""),
        description=goal_data.get("description", ""),
        success_criteria=success_criteria,
        constraints=constraints,
    )

    return graph, goal


class AgentRunner:
    """
    Loads and runs exported agents with minimal boilerplate.

    Handles:
    - Loading graph and goal from agent.json
    - Auto-discovering tools from tools.py
    - Setting up Runtime, LLM, and executor
    - Executing with dynamic edge traversal

    Usage:
        # Simple usage
        runner = AgentRunner.load("exports/outbound-sales-agent")
        result = await runner.run({"lead_id": "123"})

        # With context manager
        async with AgentRunner.load("exports/outbound-sales-agent") as runner:
            result = await runner.run({"lead_id": "123"})

        # With custom tools
        runner = AgentRunner.load("exports/outbound-sales-agent")
        runner.register_tool("my_tool", my_tool_func)
        result = await runner.run({"lead_id": "123"})
    """

    @staticmethod
    def _resolve_default_model() -> str:
        """Resolve the default model from ~/.hive/configuration.json."""
        return get_preferred_model()

    def __init__(
        self,
        agent_path: Path,
        graph: GraphSpec,
        goal: Goal,
        mock_mode: bool = False,
        storage_path: Path | None = None,
        model: str | None = None,
        intro_message: str = "",
        runtime_config: "AgentRuntimeConfig | None" = None,
        interactive: bool = True,
        skip_credential_validation: bool = False,
        requires_account_selection: bool = False,
        configure_for_account: Callable | None = None,
        list_accounts: Callable | None = None,
        credential_store: Any | None = None,
    ):
        """
        Initialize the runner (use AgentRunner.load() instead).

        Args:
            agent_path: Path to agent folder
            graph: Loaded GraphSpec object
            goal: Loaded Goal object
            mock_mode: If True, use mock LLM responses
            storage_path: Path for runtime storage (defaults to temp)
            model: Model to use (reads from agent config or ~/.hive/configuration.json if None)
            intro_message: Optional greeting shown to user on TUI load
            runtime_config: Optional AgentRuntimeConfig (webhook settings, etc.)
            interactive: If True (default), offer interactive credential setup on failure.
                Set to False when called from the TUI (which handles setup via its own screen).
            skip_credential_validation: If True, skip credential checks at load time.
            requires_account_selection: If True, TUI shows account picker before starting.
            configure_for_account: Callback(runner, account_dict) to scope tools after selection.
            list_accounts: Callback() -> list[dict] to fetch available accounts.
            credential_store: Optional shared CredentialStore (avoids creating redundant stores).
        """
        self.agent_path = agent_path
        self.graph = graph
        self.goal = goal
        self.mock_mode = mock_mode
        self.model = model or self._resolve_default_model()
        self.intro_message = intro_message
        self.runtime_config = runtime_config
        self._interactive = interactive
        self.skip_credential_validation = skip_credential_validation
        self.requires_account_selection = requires_account_selection
        self._configure_for_account = configure_for_account
        self._list_accounts = list_accounts
        self._credential_store = credential_store

        # Set up storage
        if storage_path:
            self._storage_path = storage_path
            self._temp_dir = None
        else:
            # Use persistent storage in ~/.hive/agents/{agent_name}/ per RUNTIME_LOGGING.md spec
            home = Path.home()
            default_storage = home / ".hive" / "agents" / agent_path.name
            default_storage.mkdir(parents=True, exist_ok=True)
            self._storage_path = default_storage
            self._temp_dir = None

        # Load HIVE_CREDENTIAL_KEY from shell config if not in env.
        # Must happen before MCP subprocesses are spawned so they inherit it.
        _ensure_credential_key_env()

        # Initialize components
        self._tool_registry = ToolRegistry()
        self._llm: LLMProvider | None = None
        self._approval_callback: Callable | None = None

        # AgentRuntime — unified execution path for all agents
        self._agent_runtime: AgentRuntime | None = None
        # Pre-load validation: structural checks + credentials.
        # Fails fast with actionable guidance — no MCP noise on screen.
        run_preload_validation(
            self.graph,
            interactive=self._interactive,
            skip_credential_validation=self.skip_credential_validation,
        )

        # Auto-discover tools from tools.py
        tools_path = agent_path / "tools.py"
        if tools_path.exists():
            self._tool_registry.discover_from_module(tools_path)

        # Set environment variables for MCP subprocesses
        # These are inherited by MCP servers (e.g., GCU browser tools)
        os.environ["HIVE_AGENT_NAME"] = agent_path.name
        os.environ["HIVE_STORAGE_PATH"] = str(self._storage_path)

        # Auto-discover MCP servers from mcp_servers.json
        mcp_config_path = agent_path / "mcp_servers.json"
        if mcp_config_path.exists():
            self._load_mcp_servers_from_config(mcp_config_path)

        # Auto-discover registry-selected MCP servers from mcp_registry.json
        self._load_registry_mcp_servers(agent_path)

    @staticmethod
    def _import_agent_module(agent_path: Path):
        """Import an agent package from its directory path.

        Ensures the agent's parent directory is on sys.path so the package
        can be imported normally (supports relative imports within the agent).

        Always reloads the package and its submodules so that code changes
        made since the last import (or since a previous session load in the
        same server process) are picked up.
        """
        import importlib
        import sys

        package_name = agent_path.name
        parent_dir = str(agent_path.resolve().parent)

        # Always place the correct parent directory first on sys.path.
        # Multiple agent dirs can contain packages with the same name
        # (e.g. exports/deep_research_agent and examples/deep_research_agent).
        # Without this, a previously-added parent dir could shadow the
        # agent we actually want to load.
        if parent_dir in sys.path:
            sys.path.remove(parent_dir)
        sys.path.insert(0, parent_dir)

        # Evict cached submodules first (e.g. deep_research_agent.nodes,
        # deep_research_agent.agent) so the top-level reload picks up
        # changes in the entire package — not just __init__.py.
        stale = [
            name
            for name in sys.modules
            if name == package_name or name.startswith(f"{package_name}.")
        ]
        for name in stale:
            del sys.modules[name]

        return importlib.import_module(package_name)

    @classmethod
    def load(
        cls,
        agent_path: str | Path,
        mock_mode: bool = False,
        storage_path: Path | None = None,
        model: str | None = None,
        interactive: bool = True,
        skip_credential_validation: bool | None = None,
        credential_store: Any | None = None,
    ) -> "AgentRunner":
        """
        Load an agent from an export folder.

        Imports the agent's Python package and reads module-level variables
        (goal, nodes, edges, etc.) to build a GraphSpec. Falls back to
        agent.json if no Python module is found.

        Args:
            agent_path: Path to agent folder
            mock_mode: If True, use mock LLM responses
            storage_path: Path for runtime storage (defaults to ~/.hive/agents/{name})
            model: LLM model to use (reads from agent's default_config if None)
            interactive: If True (default), offer interactive credential setup.
                Set to False from TUI callers that handle setup via their own UI.
            skip_credential_validation: If True, skip credential checks at load time.
                When None (default), uses the agent module's setting.
            credential_store: Optional shared CredentialStore (avoids creating redundant stores).

        Returns:
            AgentRunner instance ready to run
        """
        agent_path = Path(agent_path)

        # Try loading from Python module first (code-based agents)
        agent_py = agent_path / "agent.py"
        if agent_py.exists():
            agent_module = cls._import_agent_module(agent_path)

            goal = getattr(agent_module, "goal", None)
            nodes = getattr(agent_module, "nodes", None)
            edges = getattr(agent_module, "edges", None)

            if goal is None or nodes is None or edges is None:
                raise ValueError(
                    f"Agent at {agent_path} must define 'goal', 'nodes', and 'edges' "
                    f"in agent.py (or __init__.py)"
                )

            # Read model and max_tokens from agent's config if not explicitly provided
            agent_config = getattr(agent_module, "default_config", None)
            if model is None:
                if agent_config and hasattr(agent_config, "model"):
                    model = agent_config.model

            if agent_config and hasattr(agent_config, "max_tokens"):
                max_tokens = agent_config.max_tokens
                logger.info(
                    "Agent default_config overrides max_tokens: %d "
                    "(configuration.json value ignored)",
                    max_tokens,
                )
            else:
                hive_config = get_hive_config()
                max_tokens = hive_config.get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)

            # Resolve max_context_tokens with priority:
            #   1. agent loop_config["max_context_tokens"] (explicit, wins silently)
            #   2. agent default_config.max_context_tokens (logged)
            #   3. configuration.json llm.max_context_tokens
            #   4. hardcoded default (32_000)
            agent_loop_config: dict = dict(getattr(agent_module, "loop_config", {}))
            if "max_context_tokens" not in agent_loop_config:
                if agent_config and hasattr(agent_config, "max_context_tokens"):
                    agent_loop_config["max_context_tokens"] = agent_config.max_context_tokens
                    logger.info(
                        "Agent default_config overrides max_context_tokens: %d"
                        " (configuration.json value ignored)",
                        agent_config.max_context_tokens,
                    )
                else:
                    agent_loop_config["max_context_tokens"] = get_max_context_tokens()

            # Read intro_message from agent metadata (shown on TUI load)
            agent_metadata = getattr(agent_module, "metadata", None)
            intro_message = ""
            if agent_metadata and hasattr(agent_metadata, "intro_message"):
                intro_message = agent_metadata.intro_message

            # Build GraphSpec from module-level variables
            graph_kwargs: dict = {
                "id": f"{agent_path.name}-graph",
                "goal_id": goal.id,
                "version": "1.0.0",
                "entry_node": getattr(agent_module, "entry_node", nodes[0].id),
                "entry_points": getattr(agent_module, "entry_points", {}),
                "terminal_nodes": getattr(agent_module, "terminal_nodes", []),
                "pause_nodes": getattr(agent_module, "pause_nodes", []),
                "nodes": nodes,
                "edges": edges,
                "max_tokens": max_tokens,
                "loop_config": agent_loop_config,
            }
            # Only pass optional fields if explicitly defined by the agent module
            conversation_mode = getattr(agent_module, "conversation_mode", None)
            if conversation_mode is not None:
                graph_kwargs["conversation_mode"] = conversation_mode
            identity_prompt = getattr(agent_module, "identity_prompt", None)
            if identity_prompt is not None:
                graph_kwargs["identity_prompt"] = identity_prompt

            graph = GraphSpec(**graph_kwargs)

            # Generate flowchart.json if missing (for template/legacy agents)
            generate_fallback_flowchart(graph, goal, agent_path)
            # Read skill configuration from agent module
            agent_default_skills = getattr(agent_module, "default_skills", None)
            agent_skills = getattr(agent_module, "skills", None)

            # Read runtime config (webhook settings, etc.) if defined
            agent_runtime_config = getattr(agent_module, "runtime_config", None)

            # Read pre-run hooks (e.g., credential_tester needs account selection)
            skip_cred = getattr(agent_module, "skip_credential_validation", False)
            if skip_credential_validation is not None:
                skip_cred = skip_credential_validation
            needs_acct = getattr(agent_module, "requires_account_selection", False)
            configure_fn = getattr(agent_module, "configure_for_account", None)
            list_accts_fn = getattr(agent_module, "list_connected_accounts", None)

            runner = cls(
                agent_path=agent_path,
                graph=graph,
                goal=goal,
                mock_mode=mock_mode,
                storage_path=storage_path,
                model=model,
                intro_message=intro_message,
                runtime_config=agent_runtime_config,
                interactive=interactive,
                skip_credential_validation=skip_cred,
                requires_account_selection=needs_acct,
                configure_for_account=configure_fn,
                list_accounts=list_accts_fn,
                credential_store=credential_store,
            )
            # Stash skill config for use in _setup()
            runner._agent_default_skills = agent_default_skills
            runner._agent_skills = agent_skills
            return runner

        # Fallback: load from agent.json (legacy JSON-based agents)
        agent_json_path = agent_path / "agent.json"
        if not agent_json_path.is_file():
            raise FileNotFoundError(f"No agent.py or agent.json found in {agent_path}")

        with open(agent_json_path, encoding="utf-8") as f:
            export_data = f.read()

        if not export_data.strip():
            raise ValueError(f"Empty agent export file: {agent_json_path}")

        try:
            graph, goal = load_agent_export(export_data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in agent export file: {agent_json_path}") from exc

        # Generate flowchart.json if missing (for legacy JSON-based agents)
        generate_fallback_flowchart(graph, goal, agent_path)

        runner = cls(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=mock_mode,
            storage_path=storage_path,
            model=model,
            interactive=interactive,
            skip_credential_validation=skip_credential_validation or False,
            credential_store=credential_store,
        )
        runner._agent_default_skills = None
        runner._agent_skills = None
        return runner

    def register_tool(
        self,
        name: str,
        tool_or_func: Tool | Callable,
        executor: Callable | None = None,
    ) -> None:
        """
        Register a tool for use by the agent.

        Args:
            name: Tool name
            tool_or_func: Either a Tool object or a callable function
            executor: Executor function (required if tool_or_func is a Tool)
        """
        if isinstance(tool_or_func, Tool):
            if executor is None:
                raise ValueError("executor required when registering a Tool object")
            self._tool_registry.register(name, tool_or_func, executor)
        else:
            # It's a function, auto-generate Tool
            self._tool_registry.register_function(tool_or_func, name=name)

    def register_mcp_server(
        self,
        name: str,
        transport: str,
        **config_kwargs,
    ) -> int:
        """
        Register an MCP server and discover its tools.

        Args:
            name: Server name
            transport: "stdio" or "http"
            **config_kwargs: Additional configuration (command, args, url, etc.)

        Returns:
            Number of tools registered from this server

        Example:
            # Register STDIO MCP server
            runner.register_mcp_server(
                name="tools",
                transport="stdio",
                command="python",
                args=["-m", "aden_tools.mcp_server", "--stdio"],
                cwd="/path/to/tools"
            )

            # Register HTTP MCP server
            runner.register_mcp_server(
                name="tools",
                transport="http",
                url="http://localhost:4001"
            )
        """
        server_config = {
            "name": name,
            "transport": transport,
            **config_kwargs,
        }
        return self._tool_registry.register_mcp_server(server_config)

    def _load_mcp_servers_from_config(self, config_path: Path) -> None:
        """Load and register MCP servers from a configuration file."""
        self._tool_registry.load_mcp_config(config_path)

    def _load_registry_mcp_servers(self, agent_path: Path) -> None:
        """Load and register MCP servers selected via ``mcp_registry.json``."""
        registry_json = agent_path / "mcp_registry.json"
        if registry_json.is_file():
            self._tool_registry.set_mcp_registry_agent_path(agent_path)
        else:
            self._tool_registry.set_mcp_registry_agent_path(None)

        from framework.runner.mcp_registry import MCPRegistry

        try:
            registry = MCPRegistry()
            registry.initialize()
            server_configs, selection_max_tools = registry.load_agent_selection(agent_path)
        except Exception as exc:
            logger.warning(
                "Failed to load MCP registry servers for '%s': %s",
                agent_path.name,
                exc,
            )
            return

        if not server_configs:
            return

        results = self._tool_registry.load_registry_servers(
            server_configs,
            preserve_existing_tools=True,
            log_collisions=True,
            max_tools=selection_max_tools,
        )
        loaded = [result for result in results if result["status"] == "loaded"]
        skipped = [result for result in results if result["status"] != "loaded"]

        logger.info(
            "Loaded %d/%d MCP registry server(s) for agent '%s'",
            len(loaded),
            len(results),
            agent_path.name,
        )
        if skipped:
            logger.info(
                "Skipped MCP registry servers for agent '%s': %s",
                agent_path.name,
                [
                    {"server": result["server"], "reason": result["skipped_reason"]}
                    for result in skipped
                ],
            )

    def set_approval_callback(self, callback: Callable) -> None:
        """
        Set a callback for human-in-the-loop approval during execution.

        Args:
            callback: Function to call for approval (receives node info, returns bool)
        """
        self._approval_callback = callback

    def _setup(self, event_bus=None) -> None:
        """Set up runtime, LLM, and executor."""
        # Configure structured logging (auto-detects JSON vs human-readable)
        from framework.observability import configure_logging

        configure_logging(level="INFO", format="auto")

        # Set up session context for tools (agent_id)
        agent_id = self.graph.id or "unknown"

        self._tool_registry.set_session_context(
            agent_id=agent_id,
        )

        # Create LLM provider
        # Uses LiteLLM which auto-detects the provider from model name
        # Skip if already injected (e.g. worker agents with a pre-built LLM)
        if self._llm is not None:
            pass  # LLM already configured externally
        elif self.mock_mode:
            # Use mock LLM for testing without real API calls
            from framework.llm.mock import MockLLMProvider

            self._llm = MockLLMProvider(model=self.model)
        else:
            from framework.llm.litellm import LiteLLMProvider

            # Check if a subscription mode is configured
            config = get_hive_config()
            llm_config = config.get("llm", {})
            use_claude_code = llm_config.get("use_claude_code_subscription", False)
            use_codex = llm_config.get("use_codex_subscription", False)
            use_kimi_code = llm_config.get("use_kimi_code_subscription", False)
            use_antigravity = llm_config.get("use_antigravity_subscription", False)
            api_base = llm_config.get("api_base")

            api_key = None
            if use_claude_code:
                # Get OAuth token from Claude Code subscription
                api_key = get_claude_code_token()
                if not api_key:
                    logger.warning(
                        "Claude Code subscription configured but no token found. "
                        "Run 'claude' to authenticate, then try again."
                    )
            elif use_codex:
                # Get OAuth token from Codex subscription
                api_key = get_codex_token()
                if not api_key:
                    logger.warning(
                        "Codex subscription configured but no token found. "
                        "Run 'codex' to authenticate, then try again."
                    )
            elif use_kimi_code:
                # Get API key from Kimi Code CLI config (~/.kimi/config.toml)
                api_key = get_kimi_code_token()
                if not api_key:
                    logger.warning(
                        "Kimi Code subscription configured but no key found. "
                        "Run 'kimi /login' to authenticate, then try again."
                    )
            elif use_antigravity:
                pass  # AntigravityProvider handles credentials internally

            if api_key and use_claude_code:
                # Use litellm's built-in Anthropic OAuth support.
                # The lowercase "authorization" key triggers OAuth detection which
                # adds the required anthropic-beta and browser-access headers.
                self._llm = LiteLLMProvider(
                    model=self.model,
                    api_key=api_key,
                    api_base=api_base,
                    extra_headers={"authorization": f"Bearer {api_key}"},
                )
            elif api_key and use_codex:
                # OpenAI Codex subscription routes through the ChatGPT backend
                # (chatgpt.com/backend-api/codex/responses), NOT the standard
                # OpenAI API.  The consumer OAuth token lacks platform API scopes.
                extra_headers: dict[str, str] = {
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "CodexBar",
                }
                account_id = get_codex_account_id()
                if account_id:
                    extra_headers["ChatGPT-Account-Id"] = account_id
                self._llm = LiteLLMProvider(
                    model=self.model,
                    api_key=api_key,
                    api_base="https://chatgpt.com/backend-api/codex",
                    extra_headers=extra_headers,
                    store=False,
                    allowed_openai_params=["store"],
                )
            elif api_key and use_kimi_code:
                # Kimi Code subscription uses the Kimi coding API (OpenAI-compatible).
                # The api_base is set automatically by LiteLLMProvider for kimi/ models.
                self._llm = LiteLLMProvider(
                    model=self.model,
                    api_key=api_key,
                    api_base=api_base,
                )
            elif use_antigravity:
                # Direct OAuth to Google's internal Cloud Code Assist gateway.
                # No local proxy required — AntigravityProvider handles token
                # refresh and Gemini-format request/response conversion natively.
                from framework.llm.antigravity import AntigravityProvider  # noqa: PLC0415

                provider = AntigravityProvider(model=self.model)
                if not provider.has_credentials():
                    print(
                        "Warning: Antigravity credentials not found. "
                        "Run: uv run python core/antigravity_auth.py auth account add"
                    )
                self._llm = provider
            else:
                # Local models (e.g. Ollama) don't need an API key
                if self._is_local_model(self.model):
                    self._llm = LiteLLMProvider(
                        model=self.model,
                        api_base=api_base,
                    )
                else:
                    # Fall back to environment variable
                    # First check api_key_env_var from config (set by quickstart)
                    api_key_env = llm_config.get("api_key_env_var") or self._get_api_key_env_var(
                        self.model
                    )
                    if api_key_env and os.environ.get(api_key_env):
                        self._llm = LiteLLMProvider(
                            model=self.model,
                            api_key=os.environ[api_key_env],
                            api_base=api_base,
                        )
                    else:
                        # Fall back to credential store
                        api_key = self._get_api_key_from_credential_store()
                        if api_key:
                            self._llm = LiteLLMProvider(
                                model=self.model, api_key=api_key, api_base=api_base
                            )
                            # Set env var so downstream code (e.g. cleanup LLM in
                            # node._extract_json) can also find it
                            if api_key_env:
                                os.environ[api_key_env] = api_key
                        elif api_key_env:
                            logger.warning(
                                "%s not set. LLM calls will fail. "
                                "Set it with: export %s=your-api-key",
                                api_key_env,
                                api_key_env,
                            )

            # Fail fast if the agent needs an LLM but none was configured
            if self._llm is None:
                has_llm_nodes = any(
                    node.node_type in ("event_loop", "gcu") for node in self.graph.nodes
                )
                if has_llm_nodes:
                    from framework.credentials.models import CredentialError

                    if self._is_local_model(self.model):
                        raise CredentialError(
                            f"Failed to initialize LLM for local model '{self.model}'. "
                            f"Ensure your local LLM server is running "
                            f"(e.g. 'ollama serve' for Ollama)."
                        )
                    api_key_env = self._get_api_key_env_var(self.model)
                    hint = (
                        f"Set it with: export {api_key_env}=your-api-key"
                        if api_key_env
                        else "Configure an API key for your LLM provider."
                    )
                    raise CredentialError(f"LLM API key not found for model '{self.model}'. {hint}")

        # For GCU nodes: auto-register GCU MCP server if needed, then expand tool lists
        has_gcu_nodes = any(node.node_type == "gcu" for node in self.graph.nodes)
        if has_gcu_nodes:
            from framework.graph.gcu import GCU_MCP_SERVER_CONFIG, GCU_SERVER_NAME

            # Auto-register GCU MCP server if tools aren't loaded yet
            gcu_tool_names = self._tool_registry.get_server_tool_names(GCU_SERVER_NAME)
            if not gcu_tool_names:
                # Resolve cwd to repo-level tools/ (not relative to agent_path)
                gcu_config = dict(GCU_MCP_SERVER_CONFIG)
                _repo_root = Path(__file__).resolve().parent.parent.parent.parent
                gcu_config["cwd"] = str(_repo_root / "tools")
                self._tool_registry.register_mcp_server(gcu_config)
                gcu_tool_names = self._tool_registry.get_server_tool_names(GCU_SERVER_NAME)

            # Expand each GCU node's tools list to include all GCU server tools
            if gcu_tool_names:
                for node in self.graph.nodes:
                    if node.node_type == "gcu":
                        existing = set(node.tools)
                        for tool_name in sorted(gcu_tool_names):
                            if tool_name not in existing:
                                node.tools.append(tool_name)

        # For event_loop/gcu nodes: auto-register file tools MCP server, then expand tool lists
        has_loop_nodes = any(node.node_type in ("event_loop", "gcu") for node in self.graph.nodes)
        if has_loop_nodes:
            from framework.graph.files import FILES_MCP_SERVER_CONFIG, FILES_MCP_SERVER_NAME

            files_tool_names = self._tool_registry.get_server_tool_names(FILES_MCP_SERVER_NAME)
            if not files_tool_names:
                # Resolve cwd to repo-level tools/ (not relative to agent_path)
                files_config = dict(FILES_MCP_SERVER_CONFIG)
                _repo_root = Path(__file__).resolve().parent.parent.parent.parent
                files_config["cwd"] = str(_repo_root / "tools")
                self._tool_registry.register_mcp_server(files_config)
                files_tool_names = self._tool_registry.get_server_tool_names(FILES_MCP_SERVER_NAME)

            if files_tool_names:
                for node in self.graph.nodes:
                    if node.node_type in ("event_loop", "gcu"):
                        existing = set(node.tools)
                        for tool_name in sorted(files_tool_names):
                            if tool_name not in existing:
                                node.tools.append(tool_name)

        # Get tools for runtime
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()

        # Collect connected account info for system prompt injection
        accounts_prompt = ""
        accounts_data: list[dict] | None = None
        tool_provider_map: dict[str, str] | None = None
        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter

            if self._credential_store is not None:
                adapter = CredentialStoreAdapter(store=self._credential_store)
            else:
                adapter = CredentialStoreAdapter.default()
            accounts_data = adapter.get_all_account_info()
            tool_provider_map = adapter.get_tool_provider_map()
            if accounts_data:
                from framework.graph.prompting import build_accounts_prompt

                accounts_prompt = build_accounts_prompt(accounts_data, tool_provider_map)
        except Exception:
            pass  # Best-effort — agent works without account info

        # Skill configuration — the runtime handles discovery, loading, trust-gating and
        # prompt rasterization.  The runner just builds the config.
        from framework.skills.config import SkillsConfig
        from framework.skills.manager import SkillsManagerConfig

        skills_manager_config = SkillsManagerConfig(
            skills_config=SkillsConfig.from_agent_vars(
                default_skills=getattr(self, "_agent_default_skills", None),
                skills=getattr(self, "_agent_skills", None),
            ),
            project_root=self.agent_path,
            interactive=self._interactive,
        )

        self._setup_agent_runtime(
            tools,
            tool_executor,
            accounts_prompt=accounts_prompt,
            accounts_data=accounts_data,
            tool_provider_map=tool_provider_map,
            event_bus=event_bus,
            skills_manager_config=skills_manager_config,
        )

    def _get_api_key_env_var(self, model: str) -> str | None:
        """Get the environment variable name for the API key based on model name."""
        model_lower = model.lower()

        # Map model prefixes to API key environment variables
        # LiteLLM uses these conventions
        if model_lower.startswith("cerebras/"):
            return "CEREBRAS_API_KEY"
        elif model_lower.startswith("openai/") or model_lower.startswith("gpt-"):
            return "OPENAI_API_KEY"
        elif model_lower.startswith("anthropic/") or model_lower.startswith("claude"):
            return "ANTHROPIC_API_KEY"
        elif model_lower.startswith("gemini/") or model_lower.startswith("google/"):
            return "GEMINI_API_KEY"
        elif model_lower.startswith("mistral/"):
            return "MISTRAL_API_KEY"
        elif model_lower.startswith("groq/"):
            return "GROQ_API_KEY"
        elif model_lower.startswith("openrouter/"):
            return "OPENROUTER_API_KEY"
        elif self._is_local_model(model_lower):
            return None  # Local models don't need an API key
        elif model_lower.startswith("azure/"):
            return "AZURE_API_KEY"
        elif model_lower.startswith("cohere/"):
            return "COHERE_API_KEY"
        elif model_lower.startswith("replicate/"):
            return "REPLICATE_API_KEY"
        elif model_lower.startswith("together/"):
            return "TOGETHER_API_KEY"
        elif model_lower.startswith("minimax/") or model_lower.startswith("minimax-"):
            return "MINIMAX_API_KEY"
        elif model_lower.startswith("kimi/"):
            return "KIMI_API_KEY"
        elif model_lower.startswith("hive/"):
            return "HIVE_API_KEY"
        else:
            # Default: assume OpenAI-compatible
            return "OPENAI_API_KEY"

    def _get_api_key_from_credential_store(self) -> str | None:
        """Get the LLM API key from the encrypted credential store.

        Maps model name to credential store ID (e.g. "anthropic/..." -> "anthropic")
        and retrieves the key via CredentialStore.get().
        """
        if not os.environ.get("HIVE_CREDENTIAL_KEY"):
            return None

        # Map model prefix to credential store ID
        model_lower = self.model.lower()
        cred_id = None
        if model_lower.startswith("anthropic/") or model_lower.startswith("claude"):
            cred_id = "anthropic"
        elif model_lower.startswith("minimax/") or model_lower.startswith("minimax-"):
            cred_id = "minimax"
        elif model_lower.startswith("kimi/"):
            cred_id = "kimi"
        elif model_lower.startswith("hive/"):
            cred_id = "hive"
        # Add more mappings as providers are added to LLM_CREDENTIALS

        if cred_id is None:
            return None

        try:
            store = self._credential_store
            if store is None:
                from framework.credentials import CredentialStore

                store = CredentialStore.with_encrypted_storage()
            return store.get(cred_id)
        except Exception:
            return None

    @staticmethod
    def _is_local_model(model: str) -> bool:
        """Check if a model is a local model that doesn't require an API key.

        Local providers like Ollama run on the user's machine and do not
        need any authentication credentials.
        """
        LOCAL_PREFIXES = (
            "ollama/",
            "ollama_chat/",
            "vllm/",
            "lm_studio/",
            "llamacpp/",
        )
        return model.lower().startswith(LOCAL_PREFIXES)

    def _setup_agent_runtime(
        self,
        tools: list,
        tool_executor: Callable | None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
        event_bus=None,
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
        skill_dirs: list[str] | None = None,
        skills_manager_config=None,
    ) -> None:
        """Set up multi-entry-point execution using AgentRuntime."""
        entry_points = []

        # Always create a primary entry point for the graph's entry node.
        # For multi-entry-point agents this ensures the primary path (e.g.
        # user-facing rule setup) is reachable alongside async entry points.
        if self.graph.entry_node:
            entry_points.insert(
                0,
                EntryPointSpec(
                    id="default",
                    name="Default",
                    entry_node=self.graph.entry_node,
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            )

        # Create AgentRuntime with all entry points
        log_store = RuntimeLogStore(base_path=self._storage_path / "runtime_logs")

        # Enable checkpointing by default for resumable sessions
        from framework.graph.checkpoint_config import CheckpointConfig

        checkpoint_config = CheckpointConfig(
            enabled=True,
            checkpoint_on_node_start=False,  # Only checkpoint after nodes complete
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=7,
            async_checkpoint=True,  # Non-blocking
        )

        # Handle runtime_config - only pass through if it's actually an AgentRuntimeConfig.
        # Agents may export a RuntimeConfig (LLM settings) or queen-generated custom classes
        # that would crash AgentRuntime if passed through.
        runtime_config = None
        if self.runtime_config is not None:
            from framework.runtime.agent_runtime import AgentRuntimeConfig

            if isinstance(self.runtime_config, AgentRuntimeConfig):
                runtime_config = self.runtime_config

        self._agent_runtime = create_agent_runtime(
            graph=self.graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_points,
            llm=self._llm,
            tools=tools,
            tool_executor=tool_executor,
            runtime_log_store=log_store,
            checkpoint_config=checkpoint_config,
            config=runtime_config,
            graph_id=self.graph.id or self.agent_path.name,
            accounts_prompt=accounts_prompt,
            accounts_data=accounts_data,
            tool_provider_map=tool_provider_map,
            event_bus=event_bus,
            skills_manager_config=skills_manager_config,
        )

        # Pass intro_message through for TUI display
        self._agent_runtime.intro_message = self.intro_message

    # ------------------------------------------------------------------
    # Execution modes
    #
    # run()              – One-shot, blocking execution for worker agents
    #                      (headless CLI via ``hive run``). Validates, runs
    #                      the graph to completion, and returns the result.
    #
    # start() / trigger() – Long-lived runtime for the frontend (queen).
    #                      start() boots the runtime; trigger() sends
    #                      non-blocking execution requests. Used by the
    #                      server session manager and API routes.
    # ------------------------------------------------------------------

    async def run(
        self,
        input_data: dict | None = None,
        session_state: dict | None = None,
        entry_point_id: str | None = None,
    ) -> ExecutionResult:
        """One-shot execution for worker agents (headless CLI).

        Validates credentials, runs the graph to completion, and returns
        the result. Used by ``hive run`` and programmatic callers.

        For the frontend (queen), use start() + trigger() instead.

        Args:
            input_data: Input data for the agent (e.g., {"lead_id": "123"})
            session_state: Optional session state to resume from
            entry_point_id: For multi-entry-point agents, which entry point to trigger
                           (defaults to first entry point or "default")

        Returns:
            ExecutionResult with output, path, and metrics
        """
        # Validate credentials before execution (fail-fast)
        validation = self.validate()
        if validation.missing_credentials:
            error_lines = ["Cannot run agent: missing required credentials\n"]
            for warning in validation.warnings:
                if "Missing " in warning:
                    error_lines.append(f"  {warning}")
            error_lines.append("\nSet the required environment variables and re-run the agent.")
            error_msg = "\n".join(error_lines)
            return ExecutionResult(
                success=False,
                error=error_msg,
            )

        return await self._run_with_agent_runtime(
            input_data=input_data or {},
            entry_point_id=entry_point_id,
            session_state=session_state,
        )

    async def _run_with_agent_runtime(
        self,
        input_data: dict,
        entry_point_id: str | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult:
        """Run using AgentRuntime."""
        import sys

        if self._agent_runtime is None:
            self._setup()

        # Start runtime if not running
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

        # Set up stdin-based I/O for the queen in headless mode.
        # When the queen calls ask_user(), it emits
        # CLIENT_INPUT_REQUESTED on the event bus and blocks.  We subscribe
        # a handler that prints the prompt and reads from stdin, then injects
        # the user's response back into the node to unblock it.
        has_queen = any(n.is_queen_node() for n in self.graph.nodes)
        sub_ids: list[str] = []

        if has_queen and sys.stdin.isatty():
            from framework.runtime.event_bus import EventType

            runtime = self._agent_runtime

            async def _handle_client_output(event):
                """Print agent output to stdout as it streams."""
                content = event.data.get("content", "")
                if content:
                    print(content, end="", flush=True)

            async def _handle_input_requested(event):
                """Read user input from stdin and inject it into the node."""
                import asyncio

                node_id = event.node_id
                try:
                    loop = asyncio.get_event_loop()
                    user_input = await loop.run_in_executor(None, input, "\n>>> ")
                except EOFError:
                    user_input = ""

                # Inject into the waiting EventLoopNode via runtime
                await runtime.inject_input(node_id, user_input)

            sub_ids.append(
                runtime.subscribe_to_events(
                    event_types=[EventType.CLIENT_OUTPUT_DELTA],
                    handler=_handle_client_output,
                )
            )
            sub_ids.append(
                runtime.subscribe_to_events(
                    event_types=[EventType.CLIENT_INPUT_REQUESTED],
                    handler=_handle_input_requested,
                )
            )

        # Determine entry point
        if entry_point_id is None:
            # Use first entry point or "default" if no entry points defined
            entry_points = self._agent_runtime.get_entry_points()
            if entry_points:
                entry_point_id = entry_points[0].id
            else:
                entry_point_id = "default"

        try:
            # Trigger and wait for result
            result = await self._agent_runtime.trigger_and_wait(
                entry_point_id=entry_point_id,
                input_data=input_data,
                session_state=session_state,
            )

            # Return result or create error result
            if result is not None:
                return result
            else:
                return ExecutionResult(
                    success=False,
                    error="Execution timed out or failed to complete",
                )
        finally:
            # Clean up subscriptions
            for sub_id in sub_ids:
                self._agent_runtime.unsubscribe_from_events(sub_id)

    # === Runtime API ===

    async def start(self) -> None:
        """Boot the agent runtime for the frontend (queen).

        Pair with trigger() to send execution requests. Used by the
        server session manager. For headless worker agents, use run()
        instead.
        """
        if self._agent_runtime is None:
            self._setup()

        await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime."""
        if self._agent_runtime is not None:
            await self._agent_runtime.stop()

    async def trigger(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """Send a non-blocking execution request to a running runtime.

        Used by the server API routes after start(). For headless
        worker agents, use run() instead.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            correlation_id: Optional ID to correlate related executions

        Returns:
            Execution ID for tracking
        """
        if self._agent_runtime is None:
            self._setup()

        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

        return await self._agent_runtime.trigger(
            entry_point_id=entry_point_id,
            input_data=input_data,
            correlation_id=correlation_id,
        )

    def get_entry_points(self) -> list[EntryPointSpec]:
        """
        Get all registered entry points.

        Returns:
            List of EntryPointSpec objects
        """
        if self._agent_runtime is None:
            self._setup()

        return self._agent_runtime.get_entry_points()

    @property
    def is_running(self) -> bool:
        """Check if the agent runtime is running (for multi-entry-point agents)."""
        if self._agent_runtime is None:
            return False
        return self._agent_runtime.is_running

    def info(self) -> AgentInfo:
        """Return agent metadata (nodes, edges, goal, required tools)."""
        # Extract required tools from nodes
        required_tools = set()
        nodes_info = []

        for node in self.graph.nodes:
            node_info = {
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "type": node.node_type,
                "input_keys": node.input_keys,
                "output_keys": node.output_keys,
            }

            if node.tools:
                required_tools.update(node.tools)
                node_info["tools"] = node.tools

            nodes_info.append(node_info)

        edges_info = [
            {
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition.value,
            }
            for edge in self.graph.edges
        ]

        return AgentInfo(
            name=self.graph.id,
            description=self.graph.description,
            goal_name=self.goal.name,
            goal_description=self.goal.description,
            node_count=len(self.graph.nodes),
            edge_count=len(self.graph.edges),
            nodes=nodes_info,
            edges=edges_info,
            entry_node=self.graph.entry_node,
            terminal_nodes=self.graph.terminal_nodes,
            success_criteria=[
                {
                    "id": sc.id,
                    "description": sc.description,
                    "metric": sc.metric,
                    "target": sc.target,
                }
                for sc in self.goal.success_criteria
            ],
            constraints=[
                {"id": c.id, "description": c.description, "type": c.constraint_type}
                for c in self.goal.constraints
            ],
            required_tools=sorted(required_tools),
            has_tools_module=(self.agent_path / "tools.py").exists(),
        )

    def validate(self) -> ValidationResult:
        """
        Check agent is valid and all required tools are registered.

        Returns:
            ValidationResult with errors, warnings, and missing tools
        """
        errors = []
        warnings = []
        missing_tools = []

        # Validate graph structure
        graph_result = self.graph.validate()
        errors.extend(graph_result["errors"])
        warnings.extend(graph_result["warnings"])

        # Check goal has success criteria
        if not self.goal.success_criteria:
            warnings.append("Goal has no success criteria defined")

        # Check required tools are registered
        info = self.info()
        for tool_name in info.required_tools:
            if not self._tool_registry.has_tool(tool_name):
                missing_tools.append(tool_name)

        if missing_tools:
            warnings.append(f"Missing tool implementations: {', '.join(missing_tools)}")

        # Check credentials for required tools and node types
        # Uses CredentialStoreAdapter.default() which includes Aden sync support
        missing_credentials = []
        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter

            adapter = CredentialStoreAdapter.default()

            # Check tool credentials
            for _cred_name, spec in adapter.get_missing_for_tools(list(info.required_tools)):
                missing_credentials.append(spec.env_var)
                affected_tools = [t for t in info.required_tools if t in spec.tools]
                tools_str = ", ".join(affected_tools)
                warning_msg = f"Missing {spec.env_var} for {tools_str}"
                if spec.help_url:
                    warning_msg += f"\n  Get it at: {spec.help_url}"
                warnings.append(warning_msg)

            # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
            node_types = list({node.node_type for node in self.graph.nodes})
            for _cred_name, spec in adapter.get_missing_for_node_types(node_types):
                missing_credentials.append(spec.env_var)
                affected_types = [t for t in node_types if t in spec.node_types]
                types_str = ", ".join(affected_types)
                warning_msg = f"Missing {spec.env_var} for {types_str} nodes"
                if spec.help_url:
                    warning_msg += f"\n  Get it at: {spec.help_url}"
                warnings.append(warning_msg)
        except ImportError:
            # aden_tools not installed - fall back to direct check
            has_llm_nodes = any(
                node.node_type in ("event_loop", "gcu") for node in self.graph.nodes
            )
            if has_llm_nodes:
                api_key_env = self._get_api_key_env_var(self.model)
                if api_key_env and not os.environ.get(api_key_env):
                    if api_key_env not in missing_credentials:
                        missing_credentials.append(api_key_env)
                    warnings.append(
                        f"Agent has LLM nodes but {api_key_env} not set (model: {self.model})"
                    )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            missing_tools=missing_tools,
            missing_credentials=missing_credentials,
        )

    def cleanup(self) -> None:
        """Clean up resources (synchronous)."""
        # Clean up MCP client connections
        self._tool_registry.cleanup()

        if self._temp_dir:
            self._temp_dir.cleanup()
            self._temp_dir = None

    async def cleanup_async(self) -> None:
        """Clean up resources (asynchronous)."""
        # Stop agent runtime if running
        if self._agent_runtime is not None and self._agent_runtime.is_running:
            await self._agent_runtime.stop()

        # Run synchronous cleanup
        self.cleanup()

    async def __aenter__(self) -> "AgentRunner":
        """Context manager entry."""
        self._setup()
        if self._agent_runtime is not None:
            await self._agent_runtime.start()
        return self

    async def __aexit__(self, *args) -> None:
        """Context manager exit."""
        await self.cleanup_async()

    def __del__(self) -> None:
        """Destructor - cleanup temp dir."""
        self.cleanup()
