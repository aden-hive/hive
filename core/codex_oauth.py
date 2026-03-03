"""OpenAI Codex OAuth PKCE login flow.

Runs the full browser-based OAuth flow so users can authenticate with their
ChatGPT Plus/Pro subscription without needing the Codex CLI installed.

Usage (from quickstart.sh):
    uv run python codex_oauth.py

Exit codes:
    0 - success (credentials saved to ~/.codex/auth.json)
    1 - failure (user cancelled, timeout, or token exchange error)
"""

import base64
import hashlib
import http.server
import json
import platform
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# OAuth constants (from the Codex CLI binary)
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
CALLBACK_PORT = 1455

# Where to save credentials (same location the Codex CLI uses)
CODEX_AUTH_FILE = Path.home() / ".codex" / "auth.json"

# JWT claim path for account_id
JWT_CLAIM_PATH = "https://api.openai.com/auth"


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier_bytes = secrets.token_bytes(32)
    verifier = _base64url(verifier_bytes)
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(state: str, challenge: str) -> str:
    """Build the OpenAI OAuth authorize URL with PKCE."""
    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "hive",
        }
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code_for_tokens(code: str, verifier: str) -> dict | None:
    """Exchange the authorization code for tokens."""
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
        print(f"\033[0;31mToken exchange failed: {exc}\033[0m", file=sys.stderr)
        return None

    if not token_data.get("access_token") or not token_data.get("refresh_token"):
        print("\033[0;31mToken response missing required fields\033[0m", file=sys.stderr)
        return None

    return token_data


def decode_jwt_payload(token: str) -> dict | None:
    """Decode the payload of a JWT (no signature verification)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        # Add padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def get_account_id(access_token: str) -> str | None:
    """Extract the ChatGPT account_id from the access token JWT."""
    payload = decode_jwt_payload(access_token)
    if not payload:
        return None
    auth = payload.get(JWT_CLAIM_PATH)
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def save_credentials(token_data: dict, account_id: str) -> None:
    """Save credentials to ~/.codex/auth.json in the same format the Codex CLI uses."""
    auth_data = {
        "tokens": {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "account_id": account_id,
        },
        "auth_mode": "chatgpt",
        "last_refresh": datetime.now(UTC).isoformat(),
    }
    if "id_token" in token_data:
        auth_data["tokens"]["id_token"] = token_data["id_token"]

    CODEX_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CODEX_AUTH_FILE, "w") as f:
        json.dump(auth_data, f, indent=2)


def open_browser(url: str) -> bool:
    """Open the URL in the user's default browser."""
    system = platform.system()
    try:
        devnull = subprocess.DEVNULL
        if system == "Darwin":
            subprocess.Popen(["open", url], stdout=devnull, stderr=devnull)
        elif system == "Windows":
            subprocess.Popen(["cmd", "/c", "start", url], stdout=devnull, stderr=devnull)
        else:
            subprocess.Popen(["xdg-open", url], stdout=devnull, stderr=devnull)
        return True
    except OSError:
        return False


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback."""

    auth_code: str | None = None
    received_state: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing authorization code")
            return

        OAuthCallbackHandler.auth_code = code
        OAuthCallbackHandler.received_state = state

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<!doctype html><html><head><meta charset='utf-8'/></head>"
            b"<body><h2>Authentication successful</h2>"
            b"<p>Return to your terminal to continue.</p></body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:
        # Suppress request logging
        pass


def wait_for_callback(state: str, timeout_secs: int = 120) -> str | None:
    """Start a local HTTP server and wait for the OAuth callback.

    Returns the authorization code on success, None on timeout.
    """
    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.received_state = None

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), OAuthCallbackHandler)
    server.timeout = 1

    deadline = time.time() + timeout_secs
    server_thread = threading.Thread(target=_serve_until_done, args=(server, deadline, state))
    server_thread.daemon = True
    server_thread.start()
    server_thread.join(timeout=timeout_secs + 2)

    server.server_close()

    if OAuthCallbackHandler.auth_code and OAuthCallbackHandler.received_state == state:
        return OAuthCallbackHandler.auth_code
    return None


def _serve_until_done(server: http.server.HTTPServer, deadline: float, state: str) -> None:
    while time.time() < deadline:
        server.handle_request()
        if OAuthCallbackHandler.auth_code and OAuthCallbackHandler.received_state == state:
            return


def parse_manual_input(value: str, expected_state: str) -> str | None:
    """Parse user-pasted redirect URL or auth code."""
    value = value.strip()
    if not value:
        return None
    try:
        parsed = urllib.parse.urlparse(value)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if state and state != expected_state:
            return None
        return code
    except Exception:
        pass
    # Maybe it's just the raw code
    if len(value) > 10 and " " not in value:
        return value
    return None


def main() -> int:
    # Generate PKCE and state
    verifier, challenge = generate_pkce()
    state = secrets.token_hex(16)

    # Build URL
    auth_url = build_authorize_url(state, challenge)

    print()
    print("\033[1mOpenAI Codex OAuth Login\033[0m")
    print()

    # Try to start the local callback server first
    try:
        server_available = True
        # Quick test that port is free
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", CALLBACK_PORT))
        sock.close()
        if result == 0:
            print(f"\033[1;33mPort {CALLBACK_PORT} is in use. Using manual paste mode.\033[0m")
            server_available = False
    except Exception:
        server_available = True

    # Open browser
    browser_opened = open_browser(auth_url)
    if browser_opened:
        print("  Browser opened for OpenAI sign-in...")
    else:
        print("  Could not open browser automatically.")

    print()
    print("  If the browser didn't open, visit this URL:")
    print(f"  \033[0;36m{auth_url}\033[0m")
    print()

    code = None

    if server_available:
        print("  Waiting for authentication (up to 2 minutes)...")
        print("  \033[2mOr paste the redirect URL below if the callback didn't work:\033[0m")
        print()

        # Start callback server in background
        callback_result: list[str | None] = [None]

        def run_server() -> None:
            callback_result[0] = wait_for_callback(state, timeout_secs=120)

        server_thread = threading.Thread(target=run_server)
        server_thread.daemon = True
        server_thread.start()

        # Also accept manual input in parallel
        # We poll for both the server result and stdin
        try:
            import select

            while server_thread.is_alive():
                # Check if stdin has data (non-blocking on unix)
                if hasattr(select, "select"):
                    ready, _, _ = select.select([sys.stdin], [], [], 0.5)
                    if ready:
                        manual = sys.stdin.readline()
                        if manual.strip():
                            code = parse_manual_input(manual, state)
                            if code:
                                break
                else:
                    time.sleep(0.5)

                if callback_result[0]:
                    code = callback_result[0]
                    break
        except (KeyboardInterrupt, EOFError):
            print("\n\033[0;31mCancelled.\033[0m")
            return 1

        if not code:
            code = callback_result[0]
    else:
        # Manual paste mode
        try:
            manual = input("  Paste the redirect URL: ").strip()
            code = parse_manual_input(manual, state)
        except (KeyboardInterrupt, EOFError):
            print("\n\033[0;31mCancelled.\033[0m")
            return 1

    if not code:
        print("\n\033[0;31mAuthentication timed out or failed.\033[0m")
        return 1

    # Exchange code for tokens
    print()
    print("  Exchanging authorization code for tokens...")
    token_data = exchange_code_for_tokens(code, verifier)
    if not token_data:
        return 1

    # Extract account_id from JWT
    account_id = get_account_id(token_data["access_token"])
    if not account_id:
        print("\033[0;31mFailed to extract account ID from token.\033[0m", file=sys.stderr)
        return 1

    # Save credentials
    save_credentials(token_data, account_id)
    print("  \033[0;32mAuthentication successful!\033[0m")
    print(f"  Credentials saved to {CODEX_AUTH_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
