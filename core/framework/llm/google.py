"""Google Gemini LLM provider for the public Gemini API.

Provides two provider classes sharing a common Gemini API implementation:

- ``GoogleApiKeyProvider`` — authenticated with an API key
  (``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``).
- ``GoogleGeminiCliProvider`` — authenticated with Google OAuth tokens
  obtained via the ``google_auth`` CLI (browser login flow).

Both target ``https://generativelanguage.googleapis.com/v1beta`` and speak
the native Gemini request/response format (no LiteLLM dependency).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
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

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_CLOUD_CODE_ASSIST_BASE_URL = "https://cloudcode-pa.googleapis.com/v1internal"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_TOKEN_REFRESH_BUFFER_SECS = 60

# Synthetic thoughtSignature used when no real signature was captured.
# The Gemini API requires thoughtSignature on functionCall parts for Gemini 3+.
_SYNTHETIC_THOUGHT_SIG = "skip_thought_signature_validator"

# OAuth credentials source — fetched from the official gemini-cli repo.
_OAUTH_CREDENTIALS_URL = (
    "https://raw.githubusercontent.com/google-gemini/gemini-cli/main/packages/core/src/code_assist/oauth2.ts"
)

# Credentials file for the OAuth-based provider
_ACCOUNTS_FILE = Path.home() / ".hive" / "google-gemini-cli-accounts.json"

# Cached OAuth credentials
_cached_client_id: str | None = None
_cached_client_secret: str | None = None


# ---------------------------------------------------------------------------
# Model ID normalization
# ---------------------------------------------------------------------------

# Models that need the -preview suffix when bare.
_PREVIEW_SUFFIX_MAP: dict[str, str] = {
    "gemini-3-pro": "gemini-3-pro-preview",
    "gemini-3-flash": "gemini-3-flash-preview",
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    "gemini-3.1-flash": "gemini-3.1-flash-preview",
    "gemini-3.1-flash-lite": "gemini-3.1-flash-lite-preview",
}


def _normalize_model(model: str) -> str:
    """Normalize a bare model name to the full Gemini API model ID."""
    return _PREVIEW_SUFFIX_MAP.get(model, model)


# ---------------------------------------------------------------------------
# OAuth credential helpers
# ---------------------------------------------------------------------------


def _fetch_oauth_credentials() -> tuple[str | None, str | None]:
    """Fetch OAuth client ID and secret from the official gemini-cli source."""
    global _cached_client_id, _cached_client_secret
    if _cached_client_id and _cached_client_secret:
        return _cached_client_id, _cached_client_secret

    try:
        import urllib.request  # noqa: PLC0415

        req = urllib.request.Request(
            _OAUTH_CREDENTIALS_URL,
            headers={"User-Agent": "Hive-Google-Auth/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            content = resp.read().decode("utf-8")
        # Match official gemini-cli variable names.
        # OAUTH_CLIENT_ID may span two lines in the TS source.
        id_match = re.search(r"OAUTH_CLIENT_ID\s*=\s*\n?\s*'([a-z0-9\-\.]+\.apps\.googleusercontent\.com)'", content)
        secret_match = re.search(r"OAUTH_CLIENT_SECRET\s*=\s*'([^']+)'", content)
        if id_match:
            _cached_client_id = id_match.group(1)
        if secret_match:
            _cached_client_secret = secret_match.group(1)
        return _cached_client_id, _cached_client_secret
    except Exception as e:
        logger.debug("Failed to fetch Google OAuth credentials: %s", e)
    return None, None


def get_google_client_id() -> str:
    """Get Google OAuth client ID from env, config, or official source."""
    env_id = os.environ.get("GOOGLE_GEMINI_CLI_CLIENT_ID")
    if env_id:
        return env_id

    hive_cfg = Path.home() / ".hive" / "configuration.json"
    if hive_cfg.exists():
        try:
            with open(hive_cfg) as f:
                cfg = json.load(f)
                cfg_id = cfg.get("llm", {}).get("google_gemini_cli_client_id")
                if cfg_id:
                    return cfg_id
        except Exception:
            pass

    client_id, _ = _fetch_oauth_credentials()
    if client_id:
        return client_id

    raise RuntimeError("Could not obtain Google OAuth client ID")


def get_google_client_secret() -> str | None:
    """Get Google OAuth client secret from env, config, or official source."""
    secret = os.environ.get("GOOGLE_GEMINI_CLI_CLIENT_SECRET")
    if secret:
        return secret

    hive_cfg = Path.home() / ".hive" / "configuration.json"
    if hive_cfg.exists():
        try:
            with open(hive_cfg) as f:
                cfg = json.load(f)
                secret = cfg.get("llm", {}).get("google_gemini_cli_client_secret")
                if secret:
                    return secret
        except Exception:
            pass

    _, secret = _fetch_oauth_credentials()
    return secret


# ---------------------------------------------------------------------------
# Credential loading (for GoogleGeminiCliProvider)
# ---------------------------------------------------------------------------


def _load_accounts_from_json() -> tuple[str | None, str | None, float]:
    """Read credentials from ``~/.hive/google-gemini-cli-accounts.json``.

    Returns ``(access_token | None, refresh_token | None, expires_at)``.
    ``expires_at`` is a Unix timestamp in seconds; 0.0 means unknown.
    """
    if not _ACCOUNTS_FILE.exists():
        return None, None, 0.0
    try:
        with open(_ACCOUNTS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to read Google Gemini CLI accounts file: %s", exc)
        return None, None, 0.0

    accounts = data.get("accounts", [])
    if not accounts:
        return None, None, 0.0

    account = next((a for a in accounts if a.get("enabled", True) is not False), accounts[0])
    refresh_str = account.get("refresh", "")
    refresh_token = refresh_str.split("|")[0] if refresh_str else None

    access_token: str | None = account.get("access")
    expires_ms: int = account.get("expires", 0)
    expires_at = float(expires_ms) / 1000.0 if expires_ms else 0.0

    # Treat near-expiry tokens as absent so _ensure_token() triggers a refresh.
    if access_token and expires_at and time.time() >= expires_at - _TOKEN_REFRESH_BUFFER_SECS:
        access_token = None
        expires_at = 0.0

    return access_token, refresh_token, expires_at


def _do_token_refresh(refresh_token: str) -> tuple[str, float] | None:
    """Refresh an OAuth token. Returns ``(new_access_token, expires_at)`` or None."""
    import urllib.error  # noqa: PLC0415
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    client_id = get_google_client_id()
    client_secret = get_google_client_secret()

    params: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
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
        return access_token, time.time() + expires_in
    except Exception as exc:
        logger.debug("Google token refresh failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Message conversion helpers
# ---------------------------------------------------------------------------


def _clean_tool_name(name: str) -> str:
    """Sanitize a tool name for the Gemini function-calling schema."""
    name = re.sub(r"[/\s]", "_", name)
    if name and not (name[0].isalpha() or name[0] == "_"):
        name = "_" + name
    return name[:64]


def _to_gemini_contents(
    messages: list[dict[str, Any]],
    thought_sigs: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert OpenAI-format messages to Gemini-style ``contents`` array."""
    tc_id_to_name: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                tc_id = tc.get("id")
                fn_name = tc.get("function", {}).get("name", "")
                if tc_id and fn_name:
                    tc_id_to_name[tc_id] = fn_name

    contents: list[dict[str, Any]] = []
    pending_tool_parts: list[dict[str, Any]] = []

    def _flush_tool_results() -> None:
        if pending_tool_parts:
            contents.append({"role": "user", "parts": list(pending_tool_parts)})
            pending_tool_parts.clear()

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "system":
            continue

        if role == "tool":
            result_str = content if isinstance(content, str) else str(content or "")
            tc_id = msg.get("tool_call_id", "")
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

        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            tc_id = tc.get("id", str(uuid.uuid4()))
            fc_part: dict[str, Any] = {
                "functionCall": {
                    "name": fn.get("name", ""),
                    "args": args,
                    "id": tc_id,
                }
            }
            # Gemini 3 requires thoughtSignature on functionCall parts.
            # If we captured one during streaming, use it; otherwise inject
            # a synthetic one to avoid 400 errors from the API.
            sig = (thought_sigs or {}).get(tc_id, "") if thought_sigs else ""
            fc_part["thoughtSignature"] = sig or _SYNTHETIC_THOUGHT_SIG
            parts.append(fc_part)

        if parts:
            contents.append({"role": gemini_role, "parts": parts})

    _flush_tool_results()

    # Gemini requires the first turn to be a user turn.
    while contents and contents[0].get("role") == "model":
        contents.pop(0)

    return contents


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _map_finish_reason(reason: str) -> str:
    mapping = {
        "STOP": "stop",
        "MAX_TOKENS": "max_tokens",
        "SAFETY": "safety",
        "RECITATION": "recitation",
        "BLOCKLIST": "blocklist",
        "PROHIBITED": "prohibited",
        "SPII": "spii",
        "MALFORMED_FUNCTION_CALL": "error",
        "UNEXPECTED_TOOL_CALL": "error",
    }
    return mapping.get((reason or "").upper(), "stop")


def _parse_complete_response(raw: dict[str, Any], model: str) -> LLMResponse:
    """Parse a non-streaming Gemini API response → LLMResponse."""
    # Gemini API returns response directly; Antigravity wraps in {"response": ...}.
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


def _parse_sse_stream(
    response: Any,
    model: str,
    on_thought_signature: Callable[[str, str], None] | None = None,
) -> Iterator[StreamEvent]:
    """Parse Gemini SSE response → StreamEvents."""
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

        # Gemini API returns directly; Antigravity wraps in {"response": ...}.
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
                    tool_use_id = fc.get("id") or str(uuid.uuid4())
                    thought_sig = part.get("thoughtSignature", "")
                    if thought_sig and on_thought_signature:
                        on_thought_signature(tool_use_id, thought_sig)
                    args = fc.get("args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    yield ToolCallEvent(
                        tool_use_id=tool_use_id,
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
# Base provider
# ---------------------------------------------------------------------------


class _GoogleBaseProvider(LLMProvider):
    """Shared Gemini API implementation. Subclasses provide auth."""

    model: str
    _thought_sigs: dict[str, str]

    def _get_auth_headers(self) -> dict[str, str]:
        raise NotImplementedError

    # --- Request building -------------------------------------------------- #

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        contents = _to_gemini_contents(messages, self._thought_sigs)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 1.0,
                "topP": 0.95,
            },
        }
        # Enable thinking for Gemini 3+ models
        model_lower = _normalize_model(self.model).lower()
        if any(p in model_lower for p in ("gemini-3", "gemini-2.5")):
            body["generationConfig"]["thinkingConfig"] = {"includeThoughts": True}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [
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
        return body

    # --- HTTP transport ---------------------------------------------------- #

    def _post(self, body: dict[str, Any], *, streaming: bool) -> Any:
        """POST to the Gemini API with retry for transient errors."""
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        auth_headers = self._get_auth_headers()
        model_id = _normalize_model(self.model)

        path = (
            f"/models/{model_id}:streamGenerateContent?alt=sse"
            if streaming
            else f"/models/{model_id}:generateContent"
        )
        url = f"{_GEMINI_BASE_URL}{path}"
        headers = {
            **auth_headers,
            "Content-Type": "application/json",
        }
        if streaming:
            headers["Accept"] = "text/event-stream"

        body_bytes = json.dumps(body).encode("utf-8")
        max_retries = 3
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            try:
                return urllib.request.urlopen(req, timeout=120)  # noqa: S310
            except urllib.error.HTTPError as exc:
                # Retry on transient errors: 429 (rate limit), 500, 502, 503, 504
                if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.debug("Google Gemini HTTP %d, retrying in %ds (attempt %d/%d)",
                                 exc.code, wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    last_exc = exc
                    continue
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = "(unreadable)"
                raise RuntimeError(f"Google Gemini HTTP {exc.code} from {url}: {err_body}") from exc
            except (urllib.error.URLError, OSError) as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.debug("Google Gemini network error, retrying in %ds: %s", wait, exc)
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise RuntimeError(f"Google Gemini network error: {exc}") from exc

        raise RuntimeError(f"Google Gemini request failed after {max_retries} retries") from last_exc

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
                for event in _parse_sse_stream(
                    http_resp, self.model, self._thought_sigs.__setitem__
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                logger.error("Google Gemini stream error: %s", exc)
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


# ---------------------------------------------------------------------------
# API Key provider
# ---------------------------------------------------------------------------


class GoogleApiKeyProvider(_GoogleBaseProvider):
    """Google Gemini provider authenticated with an API key."""

    def __init__(
        self,
        model: str = "gemini-3-flash-preview",
        api_key: str | None = None,
    ) -> None:
        if "/" in model:
            model = model.split("/", 1)[1]
        self.model = _normalize_model(model)
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "No Google API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY."
            )
        self._thought_sigs: dict[str, str] = {}

    def has_credentials(self) -> bool:
        return bool(self._api_key)

    def _get_auth_headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key}


# ---------------------------------------------------------------------------
# OAuth provider (Google Gemini CLI)
# ---------------------------------------------------------------------------


class GoogleGeminiCliProvider(_GoogleBaseProvider):
    """Google Gemini provider authenticated with Google OAuth tokens."""

    def __init__(self, model: str = "gemini-3-flash-preview") -> None:
        if "/" in model:
            model = model.split("/", 1)[1]
        self.model = _normalize_model(model)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0
        self._thought_sigs: dict[str, str] = {}
        self._init_credentials()

    def _init_credentials(self) -> None:
        access, refresh, expires_at = _load_accounts_from_json()
        if refresh or access:
            self._access_token = access
            self._refresh_token = refresh
            self._token_expires_at = expires_at

    def has_credentials(self) -> bool:
        return bool(self._access_token or self._refresh_token)

    def _ensure_token(self) -> str:
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
            logger.warning("Using potentially stale Google access token")
            return self._access_token

        raise RuntimeError(
            "No valid Google Gemini CLI credentials. "
            "Run: uv run python core/google_auth.py auth account add"
        )

    def _get_auth_headers(self) -> dict[str, str]:
        token = self._ensure_token()
        return {"Authorization": f"Bearer {token}"}

    def _post(self, body: dict[str, Any], *, streaming: bool) -> Any:
        """POST to Cloud Code Assist API (cloudcode-pa.googleapis.com).

        Overrides base class to use the Cloud Code Assist endpoint format:
        - URL: ``{base}:{method}`` (model goes in the body, not the path)
        - Body: ``{"model": "models/{id}", "request": {original_body}}``
        """
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        auth_headers = self._get_auth_headers()
        model_id = _normalize_model(self.model)

        method = "streamGenerateContent" if streaming else "generateContent"
        url = f"{_CLOUD_CODE_ASSIST_BASE_URL}:{method}"

        headers = {
            **auth_headers,
            "Content-Type": "application/json",
        }
        if streaming:
            headers["Accept"] = "text/event-stream"

        wrapped_body = {
            "model": f"models/{model_id}",
            "request": body,
        }
        body_bytes = json.dumps(wrapped_body).encode("utf-8")
        max_retries = 3
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            try:
                return urllib.request.urlopen(req, timeout=120)  # noqa: S310
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.debug("Cloud Code Assist HTTP %d, retrying in %ds (attempt %d/%d)",
                                 exc.code, wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    last_exc = exc
                    continue
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = "(unreadable)"
                raise RuntimeError(
                    f"Cloud Code Assist HTTP {exc.code} from {url}: {err_body}"
                ) from exc
            except (urllib.error.URLError, OSError) as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.debug("Cloud Code Assist network error, retrying in %ds: %s", wait, exc)
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise RuntimeError(f"Cloud Code Assist network error: {exc}") from exc

        raise RuntimeError(
            f"Cloud Code Assist request failed after {max_retries} retries"
        ) from last_exc
