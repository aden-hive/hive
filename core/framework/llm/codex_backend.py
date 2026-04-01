"""Shared helpers for Codex's ChatGPT-backed transport.

Codex CLI talks to the ChatGPT Codex backend, which is not the standard
platform OpenAI API. Hive keeps its normal provider contract by centralizing
the transport-specific headers and request kwargs here.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

CODEX_API_BASE = "https://chatgpt.com/backend-api/codex"
CODEX_USER_AGENT = "CodexBar"
CODEX_ALLOWED_OPENAI_PARAMS = ("store",)
_CODEX_HOST = "chatgpt.com"
_CODEX_PATH = "/backend-api/codex"


def is_codex_api_base(api_base: str | None) -> bool:
    """Return True when *api_base* targets the ChatGPT Codex backend."""
    if not api_base:
        return False
    parsed = urlparse(api_base)
    path = parsed.path.rstrip("/")
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname == _CODEX_HOST
        and (path == _CODEX_PATH or path == f"{_CODEX_PATH}/responses")
    )


def normalize_codex_api_base(api_base: str | None) -> str | None:
    """Normalize ChatGPT Codex backend URLs to the stable base endpoint."""
    if not api_base:
        return api_base
    parsed = urlparse(api_base)
    path = parsed.path.rstrip("/")
    if not is_codex_api_base(api_base):
        return api_base.rstrip("/")
    if path.endswith("/responses"):
        path = path[: -len("/responses")]
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return urlunparse(normalized).rstrip("/")


def merge_codex_allowed_openai_params(params: list[str] | tuple[str, ...] | None) -> list[str]:
    """Ensure Codex-required pass-through params are always present."""
    allowed = set(params or [])
    allowed.update(CODEX_ALLOWED_OPENAI_PARAMS)
    return sorted(allowed)


def build_codex_extra_headers(
    api_key: str | None,
    *,
    account_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build headers for the ChatGPT Codex backend."""
    headers = dict(extra_headers or {})
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    headers.setdefault("User-Agent", CODEX_USER_AGENT)
    if account_id:
        headers.setdefault("ChatGPT-Account-Id", account_id)
    return headers


def build_codex_litellm_kwargs(
    api_key: str | None,
    *,
    account_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the LiteLLM kwargs required by the ChatGPT Codex backend."""
    return {
        "extra_headers": build_codex_extra_headers(
            api_key,
            account_id=account_id,
            extra_headers=extra_headers,
        ),
        "store": False,
        "allowed_openai_params": list(CODEX_ALLOWED_OPENAI_PARAMS),
    }
