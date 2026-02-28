"""Shared Hive configuration utilities.

Centralises reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.graph.edge import DEFAULT_MAX_TOKENS

# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"


def get_hive_config() -> dict[str, Any]:
    """Load hive configuration from ~/.hive/configuration.json."""
    if not HIVE_CONFIG_FILE.exists():
        return {}
    try:
        with open(HIVE_CONFIG_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------


def get_preferred_model() -> str:
    """Return the user's preferred LLM model string (e.g. 'anthropic/claude-sonnet-4-20250514')."""
    llm = get_hive_config().get("llm", {})
    if llm.get("provider") and llm.get("model"):
        return f"{llm['provider']}/{llm['model']}"
    return "anthropic/claude-sonnet-4-20250514"


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)


def get_api_key() -> str | None:
    """Return the API key, supporting env var, Claude Code subscription, Codex, and ZAI Code.

    Priority:
    1. Claude Code subscription (``use_claude_code_subscription: true``)
       reads the OAuth token from ``~/.claude/.credentials.json``.
    2. Codex subscription (``use_codex_subscription: true``)
       reads the OAuth token from macOS Keychain or ``~/.codex/auth.json``.
    3. Environment variable named in ``api_key_env_var``.
    """
    llm = get_hive_config().get("llm", {})

    # Claude Code subscription: read OAuth token directly
    if llm.get("use_claude_code_subscription"):
        try:
            from framework.runner.runner import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Codex subscription: read OAuth token from Keychain / auth.json
    if llm.get("use_codex_subscription"):
        try:
            from framework.runner.runner import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    # Standard env-var path (covers ZAI Code and all API-key providers)
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)
    return None


def get_api_base() -> str | None:
    """Return the api_base URL for OpenAI-compatible endpoints, if configured."""
    llm = get_hive_config().get("llm", {})
    if llm.get("use_codex_subscription"):
        # Codex subscription routes through the ChatGPT backend, not api.openai.com.
        return "https://chatgpt.com/backend-api/codex"
    return llm.get("api_base")


def get_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for LiteLLMProvider (e.g. OAuth headers).

    When ``use_claude_code_subscription`` is enabled, returns
    ``extra_headers`` with the OAuth Bearer token so that litellm's
    built-in Anthropic OAuth handler adds the required beta headers.

    When ``use_codex_subscription`` is enabled, returns
    ``extra_headers`` with the Bearer token, ``ChatGPT-Account-Id``,
    and ``store=False`` (required by the ChatGPT backend).
    """
    llm = get_hive_config().get("llm", {})
    if llm.get("use_claude_code_subscription"):
        api_key = get_api_key()
        if api_key:
            return {
                "extra_headers": {"authorization": f"Bearer {api_key}"},
            }
    if llm.get("use_codex_subscription"):
        api_key = get_api_key()
        if api_key:
            headers: dict[str, str] = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "CodexBar",
            }
            try:
                from framework.runner.runner import get_codex_account_id

                account_id = get_codex_account_id()
                if account_id:
                    headers["ChatGPT-Account-Id"] = account_id
            except ImportError:
                pass
            return {
                "extra_headers": headers,
                "store": False,
                "allowed_openai_params": ["store"],
            }
    return {}


# ---------------------------------------------------------------------------
# RuntimeConfig – shared across agent templates
# ---------------------------------------------------------------------------


@dataclass
class RuntimeConfig:
    """Agent runtime configuration loaded from ~/.hive/configuration.json."""

    model: str = field(default_factory=get_preferred_model)
    temperature: float = 0.7
    max_tokens: int = field(default_factory=get_max_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)
    extra_kwargs: dict[str, Any] = field(default_factory=get_llm_extra_kwargs)
