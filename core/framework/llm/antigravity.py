"""Antigravity (Google internal Cloud Code Assist) LLM provider.

Antigravity is Google's unified gateway API that routes requests to Gemini,
Claude, and GPT-OSS models through a single Gemini-style interface.  It is
NOT the public ``generativelanguage.googleapis.com`` API.

Authentication uses Google OAuth2.  Token refresh is done directly with the
OAuth client secret — no local proxy (``antigravity-auth serve``) required.

Credential sources (checked in order):
  1. ``~/.config/opencode/antigravity-accounts.json``  (written by the
     opencode-antigravity-auth plugin — V4 schema with proper expiry info)
  2. Antigravity IDE SQLite state DB  (macOS / Linux)

References:
  https://github.com/NoeFabris/opencode-antigravity-auth
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Fallback order: daily sandbox → autopush sandbox → production
_ENDPOINTS = [
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
    "https://autopush-cloudcode-pa.sandbox.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]
_DEFAULT_PROJECT_ID = "rising-fact-p41fc"
_TOKEN_REFRESH_BUFFER_SECS = 60

_ACCOUNTS_FILE = Path.home() / ".config" / "opencode" / "antigravity-accounts.json"
_IDE_STATE_DB_MAC = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Antigravity"
    / "User"
    / "globalStorage"
    / "state.vscdb"
)
_IDE_STATE_DB_LINUX = (
    Path.home() / ".config" / "Antigravity" / "User" / "globalStorage" / "state.vscdb"
)
_IDE_STATE_DB_KEY = "antigravityUnifiedStateSync.oauthToken"

_BASE_HEADERS: dict[str, str] = {
    # Mimic the Antigravity Electron app so the API accepts the request.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Antigravity/1.18.3 Chrome/138.0.7204.235 "
        "Electron/37.3.1 Safari/537.36"
    ),
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"ANTIGRAVITY","platform":"MACOS","pluginType":"GEMINI"}',
}


# ---------------------------------------------------------------------------
# Credential loading helpers
# ---------------------------------------------------------------------------


def _load_from_json_file() -> tuple[str | None, str | None, str, float]:
    """Read credentials from ``~/.config/opencode/antigravity-accounts.json``.

    Returns ``(access_token | None, refresh_token | None, project_id, expires_at)``.
    ``expires_at`` is a Unix timestamp (seconds); 0.0 means unknown.
    """
    if not _ACCOUNTS_FILE.exists():
        return None, None, _DEFAULT_PROJECT_ID, 0.0
    try:
        with open(_ACCOUNTS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read Antigravity accounts file: %s", exc)
        return None, None, _DEFAULT_PROJECT_ID, 0.0

    accounts = data.get("accounts", [])
    if not accounts:
        return None, None, _DEFAULT_PROJECT_ID, 0.0

    account = next((a for a in accounts if a.get("enabled", True) is not False), accounts[0])
    schema_version = data.get("schemaVersion", 1)

    if schema_version >= 4:
        # V4 schema: refresh = "refreshToken|projectId[|managedProjectId]"
        refresh_str = account.get("refresh", "")
        parts = refresh_str.split("|") if refresh_str else []
        refresh_token: str | None = parts[0] if parts else None
        project_id = parts[1] if len(parts) >= 2 and parts[1] else _DEFAULT_PROJECT_ID

        access_token: str | None = account.get("access")
        expires_ms: int = account.get("expires", 0)
        expires_at = float(expires_ms) / 1000.0 if expires_ms else 0.0

        # Treat near-expiry tokens as absent so _ensure_token() triggers a refresh.
        if access_token and expires_at and time.time() >= expires_at - _TOKEN_REFRESH_BUFFER_SECS:
            access_token = None
            expires_at = 0.0

        return access_token, refresh_token, project_id, expires_at
    else:
        # V1–V3 schema: plain accessToken / refreshToken fields
        access_token = account.get("accessToken")
        refresh_token = account.get("refreshToken")
        # Estimate expiry from last_refresh + 1 h
        last_refresh_str: str | None = data.get("last_refresh")
        expires_at = 0.0
        if last_refresh_str:
            try:
                from datetime import datetime  # noqa: PLC0415

                ts = datetime.fromisoformat(last_refresh_str.replace("Z", "+00:00")).timestamp()
                expires_at = ts + 3600.0
                if time.time() >= expires_at - _TOKEN_REFRESH_BUFFER_SECS:
                    access_token = None
            except (ValueError, TypeError):
                pass
        return access_token, refresh_token, _DEFAULT_PROJECT_ID, expires_at


def _load_from_ide_db() -> tuple[str | None, str | None, float]:
    """Extract ``(access_token, refresh_token, expires_at)`` from the IDE SQLite DB."""
    import base64  # noqa: PLC0415
    import sqlite3  # noqa: PLC0415

    for db_path in (_IDE_STATE_DB_MAC, _IDE_STATE_DB_LINUX):
        if not db_path.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = con.execute(
                    "SELECT value FROM ItemTable WHERE key = ?",
                    (_IDE_STATE_DB_KEY,),
                ).fetchone()
            finally:
                con.close()
            if not row:
                continue

            blob = base64.b64decode(row[0])
            candidates = re.findall(rb"[A-Za-z0-9+/=_\-]{40,}", blob)
            access_token: str | None = None
            refresh_token: str | None = None
            for candidate in candidates:
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
                # Estimate expiry from DB mtime (IDE refreshes while running)
                mtime = db_path.stat().st_mtime
                expires_at = mtime + 3600.0
                return access_token, refresh_token, expires_at
        except Exception as exc:
            logger.debug("Failed to read Antigravity IDE state DB: %s", exc)
            continue
    return None, None, 0.0


def _do_token_refresh(refresh_token: str) -> tuple[str, float] | None:
    """POST to Google OAuth endpoint and return ``(new_access_token, expires_at)``.

    The client secret is sourced via ``get_antigravity_client_secret()`` (env var,
    config file, or npm package fallback). When unavailable the refresh is attempted
    without it — Google will reject it for web-app clients, but the npm fallback in
    ``get_antigravity_client_secret()`` should ensure the secret is found at runtime.

    Returns None when the HTTP request fails.
    """
    from framework.config import get_antigravity_client_secret  # noqa: PLC0415

    client_secret = get_antigravity_client_secret()
    if not client_secret:
        logger.debug(
            "Antigravity client secret not configured — attempting refresh without it. "
            "Set ANTIGRAVITY_CLIENT_SECRET or run quickstart to configure."
        )

    import urllib.error  # noqa: PLC0415
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    from framework.config import get_antigravity_client_id  # noqa: PLC0415

    params: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": get_antigravity_client_id(),
    }
    if client_secret:
        params["client_secret"] = client_secret
    body = urllib.parse.urlencode(params).encode("utf-8")

    req = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            payload = json.loads(resp.read())
        access_token: str = payload["access_token"]
        expires_in: int = payload.get("expires_in", 3600)
        logger.debug("Antigravity token refreshed successfully")
        return access_token, time.time() + expires_in
    except Exception as exc:
        logger.debug("Antigravity token refresh failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Message conversion helpers
# ---------------------------------------------------------------------------


def _clean_tool_name(name: str) -> str:
    """Sanitize a tool name for the Antigravity function-calling schema."""
    name = re.sub(r"[/\s]", "_", name)
    if name and not (name[0].isalpha() or name[0] == "_"):
        name = "_" + name
    return name[:64]


def _to_gemini_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-format messages to Gemini-style ``contents`` array."""
    # Pre-build a map tool_call_id → function_name from assistant messages.
    # Tool result messages (role="tool") only carry tool_call_id, not the name,
    # but Gemini requires functionResponse.name to match the functionCall.name.
    tc_id_to_name: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tc_id = tc.get("id")
                fn_name = tc.get("function", {}).get("name", "")
                if tc_id and fn_name:
                    tc_id_to_name[tc_id] = fn_name

    contents: list[dict[str, Any]] = []
    # Consecutive tool-result messages must be batched into one user turn.
    pending_tool_parts: list[dict[str, Any]] = []

    def _flush_tool_results() -> None:
        if pending_tool_parts:
            contents.append({"role": "user", "parts": list(pending_tool_parts)})
            pending_tool_parts.clear()

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "system":
            continue  # Handled via systemInstruction, not in contents.

        if role == "tool":
            # OpenAI tool result → Gemini functionResponse part.
            result_str = content if isinstance(content, str) else str(content or "")
            tc_id = msg.get("tool_call_id", "")
            # Look up function name from the pre-built map; fall back to msg.name.
            fn_name = tc_id_to_name.get(tc_id) or msg.get("name", "")
            pending_tool_parts.append(
                {
                    "functionResponse": {
                        "name": fn_name,
                        "id": tc_id,
                        "response": {"content": result_str},
                    }
                }
            )
            continue

        _flush_tool_results()

        gemini_role = "model" if role == "assistant" else "user"
        parts: list[dict[str, Any]] = []

        if isinstance(content, str) and content:
            parts.append({"text": content})
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        parts.append({"text": text})
                # Other block types (image_url etc.) skipped.

        # Assistant messages may carry OpenAI-style tool_calls.
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            parts.append(
                {
                    "functionCall": {
                        "name": fn.get("name", ""),
                        "args": args,
                        "id": tc.get("id", str(uuid.uuid4())),
                    }
                }
            )

        if parts:
            contents.append({"role": gemini_role, "parts": parts})

    _flush_tool_results()

    # Gemini requires the first turn to be a user turn.  Drop any leading
    # model messages so the API doesn't reject with a 400.
    while contents and contents[0].get("role") == "model":
        contents.pop(0)

    return contents


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _map_finish_reason(reason: str) -> str:
    return {"STOP": "stop", "MAX_TOKENS": "max_tokens", "OTHER": "tool_use"}.get(
        (reason or "").upper(), "stop"
    )


def _parse_complete_response(raw: dict[str, Any], model: str) -> LLMResponse:
    """Parse a non-streaming Antigravity response dict → LLMResponse."""
    payload: dict[str, Any] = raw.get("response", raw)
    candidates: list[dict[str, Any]] = payload.get("candidates", [])
    usage: dict[str, Any] = payload.get("usageMetadata", {})

    text_parts: list[str] = []
    if candidates:
        for part in candidates[0].get("content", {}).get("parts", []):
            if "text" in part and not part.get("thought"):
                text_parts.append(part["text"])

    return LLMResponse(
        content="".join(text_parts),
        model=payload.get("modelVersion", model),
        input_tokens=usage.get("promptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0),
        stop_reason=_map_finish_reason(candidates[0].get("finishReason", "") if candidates else ""),
        raw_response=raw,
    )


def _parse_sse_stream(response: Any, model: str) -> Iterator[StreamEvent]:
    """Parse Antigravity SSE response line-by-line → StreamEvents.

    Each SSE line looks like::

        data: {"response": {"candidates": [...], "usageMetadata": {...}}, "traceId": "..."}
    """
    accumulated = ""
    input_tokens = 0
    output_tokens = 0
    finish_reason = ""

    for raw_line in response:
        line: str = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            data: dict[str, Any] = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        # The outer envelope is {"response": {...}, "traceId": "..."}.
        payload: dict[str, Any] = data.get("response", data)

        usage = payload.get("usageMetadata", {})
        if usage:
            input_tokens = usage.get("promptTokenCount", input_tokens)
            output_tokens = usage.get("candidatesTokenCount", output_tokens)

        for candidate in payload.get("candidates", []):
            fr = candidate.get("finishReason", "")
            if fr:
                finish_reason = fr

            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part and not part.get("thought"):
                    delta: str = part["text"]
                    accumulated += delta
                    yield TextDeltaEvent(content=delta, snapshot=accumulated)
                elif "functionCall" in part:
                    fc: dict[str, Any] = part["functionCall"]
                    args = fc.get("args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    yield ToolCallEvent(
                        tool_use_id=fc.get("id") or str(uuid.uuid4()),
                        tool_name=fc.get("name", ""),
                        tool_input=args,
                    )

    if accumulated:
        yield TextEndEvent(full_text=accumulated)
    yield FinishEvent(
        stop_reason=_map_finish_reason(finish_reason),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class AntigravityProvider(LLMProvider):
    """LLM provider for Google's internal Antigravity Code Assist gateway.

    No local proxy required.  Handles OAuth token refresh, Gemini-format
    request/response conversion, and SSE streaming directly.
    """

    def __init__(self, model: str = "gemini-3-flash") -> None:
        # Strip any provider prefix ("openai/gemini-3-flash" → "gemini-3-flash").
        if "/" in model:
            model = model.split("/", 1)[1]
        self.model = model

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._project_id: str = _DEFAULT_PROJECT_ID
        self._token_expires_at: float = 0.0

        self._init_credentials()

    # --- Credential management -------------------------------------------- #

    def _init_credentials(self) -> None:
        """Load credentials from the best available source."""
        access, refresh, project_id, expires_at = _load_from_json_file()
        if refresh:
            self._refresh_token = refresh
            self._project_id = project_id
            self._access_token = access
            self._token_expires_at = expires_at
            return

        # Fall back to IDE state DB.
        access, refresh, expires_at = _load_from_ide_db()
        if access:
            self._access_token = access
            self._refresh_token = refresh
            self._token_expires_at = expires_at

    def has_credentials(self) -> bool:
        """Return True if any credential is available."""
        return bool(self._access_token or self._refresh_token)

    def _ensure_token(self) -> str:
        """Return a valid access token, refreshing via OAuth if needed."""
        if (
            self._access_token
            and self._token_expires_at
            and time.time() < self._token_expires_at - _TOKEN_REFRESH_BUFFER_SECS
        ):
            return self._access_token

        if self._refresh_token:
            result = _do_token_refresh(self._refresh_token)
            if result:
                self._access_token, self._token_expires_at = result
                return self._access_token

        if self._access_token:
            logger.warning("Using potentially stale Antigravity access token")
            return self._access_token

        raise RuntimeError(
            "No valid Antigravity credentials. Authenticate with the "
            "opencode-antigravity-auth plugin: "
            "https://github.com/NoeFabris/opencode-antigravity-auth"
        )

    # --- Request building -------------------------------------------------- #

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        contents = _to_gemini_contents(messages)
        inner: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            inner["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            inner["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": _clean_tool_name(t.name),
                            "description": t.description,
                            "parameters": t.parameters
                            or {
                                "type": "object",
                                "properties": {},
                            },
                        }
                        for t in tools
                    ]
                }
            ]
        return {
            "project": self._project_id,
            "model": self.model,
            "request": inner,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": f"agent-{uuid.uuid4()}",
        }

    # --- HTTP transport ---------------------------------------------------- #

    def _post(self, body: dict[str, Any], *, streaming: bool) -> Any:
        """POST to the Antigravity endpoint, falling back through the endpoint list."""
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        token = self._ensure_token()
        body_bytes = json.dumps(body).encode("utf-8")
        path = (
            "/v1internal:streamGenerateContent?alt=sse"
            if streaming
            else "/v1internal:generateContent"
        )
        headers = {
            **_BASE_HEADERS,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if streaming:
            headers["Accept"] = "text/event-stream"

        last_exc: Exception | None = None
        for base_url in _ENDPOINTS:
            url = f"{base_url}{path}"
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            try:
                return urllib.request.urlopen(req, timeout=120)  # noqa: S310
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403) and self._refresh_token:
                    # Token rejected — refresh once and retry this endpoint.
                    result = _do_token_refresh(self._refresh_token)
                    if result:
                        self._access_token, self._token_expires_at = result
                        headers["Authorization"] = f"Bearer {self._access_token}"
                        req2 = urllib.request.Request(
                            url, data=body_bytes, headers=headers, method="POST"
                        )
                        try:
                            return urllib.request.urlopen(req2, timeout=120)  # noqa: S310
                        except urllib.error.HTTPError as exc2:
                            last_exc = exc2
                            continue
                    last_exc = exc
                    continue
                elif exc.code >= 500:
                    last_exc = exc
                    continue
                # Include the API response body in the exception for easier debugging.
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = "(unreadable)"
                raise RuntimeError(f"Antigravity HTTP {exc.code} from {url}: {err_body}") from exc
            except (urllib.error.URLError, OSError) as exc:
                last_exc = exc
                continue

        raise RuntimeError(
            f"All Antigravity endpoints failed. Last error: {last_exc}"
        ) from last_exc

    # --- LLMProvider interface --------------------------------------------- #

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        if json_mode:
            suffix = "\n\nPlease respond with a valid JSON object."
            system = (system + suffix) if system else suffix.strip()

        body = self._build_body(messages, system, tools, max_tokens)
        resp = self._post(body, streaming=False)
        return _parse_complete_response(json.loads(resp.read()), self.model)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        import asyncio  # noqa: PLC0415
        import concurrent.futures  # noqa: PLC0415

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

        def _blocking_work() -> None:
            try:
                body = self._build_body(messages, system, tools, max_tokens)
                http_resp = self._post(body, streaming=True)
                for event in _parse_sse_stream(http_resp, self.model):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                logger.error("Antigravity stream error: %s", exc)
                loop.call_soon_threadsafe(queue.put_nowait, StreamErrorEvent(error=str(exc)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = loop.run_in_executor(executor, _blocking_work)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            await fut
            executor.shutdown(wait=False)
