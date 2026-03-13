"""Shared Hive configuration utilities.

Centralizes reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from framework.graph.edge import DEFAULT_MAX_TOKENS

# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"
logger = logging.getLogger(__name__)

LLMAuthMode = Literal["api_key", "claude_code", "codex", "kimi_code"]
_VALID_AUTH_MODES: set[str] = {"api_key", "claude_code", "codex", "kimi_code"}


def get_hive_config() -> dict[str, Any]:
    """Load hive configuration from ~/.hive/configuration.json."""
    if not HIVE_CONFIG_FILE.exists():
        return {}
    try:
        with open(HIVE_CONFIG_FILE, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Failed to load Hive config %s: %s",
            HIVE_CONFIG_FILE,
            e,
        )
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


def resolve_llm_auth_mode(llm: dict[str, Any] | None = None) -> LLMAuthMode:
    """Resolve one effective LLM auth mode from config.

    Preference order:
    1. Explicit ``auth_mode`` (new schema)
    2. Legacy subscription booleans
    3. Legacy Kimi subscription heuristic
    4. Default to API-key mode
    """
    llm = llm if llm is not None else get_hive_config().get("llm", {})

    auth_mode = str(llm.get("auth_mode", "")).strip().lower()
    if auth_mode in _VALID_AUTH_MODES:
        return auth_mode  # type: ignore[return-value]

    if llm.get("use_claude_code_subscription"):
        return "claude_code"
    if llm.get("use_codex_subscription"):
        return "codex"
    if llm.get("use_kimi_code_subscription"):
        return "kimi_code"

    # Legacy quickstart kimi config used provider/api_base without explicit flag.
    provider = str(llm.get("provider", "")).strip().lower()
    api_base = str(llm.get("api_base", "")).strip().lower()
    if provider == "kimi" and "api.kimi.com/coding" in api_base:
        return "kimi_code"

    return "api_key"


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)


DEFAULT_MAX_CONTEXT_TOKENS = 32_000


def get_max_context_tokens() -> int:
    """Return the configured max_context_tokens, falling back to DEFAULT_MAX_CONTEXT_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)


def get_api_key() -> str | None:
    """Return the API key based on resolved auth mode.

    Priority:
    1. Explicit ``llm.auth_mode``.
    2. Legacy subscription flags/heuristics.
    3. Environment variable named in ``api_key_env_var``.
    """
    llm = get_hive_config().get("llm", {})
    auth_mode = resolve_llm_auth_mode(llm)

    if auth_mode == "claude_code":
        try:
            from framework.runner.runner import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    elif auth_mode == "codex":
        try:
            from framework.runner.runner import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    elif auth_mode == "kimi_code":
        try:
            from framework.runner.runner import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Standard env-var path (covers ZAI/MiniMax and all API-key providers)
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)
    return None


def get_gcu_enabled() -> bool:
    """Return whether GCU (browser automation) is enabled in user config."""
    return get_hive_config().get("gcu_enabled", True)


def get_api_base() -> str | None:
    """Return the api_base URL for OpenAI-compatible endpoints, if configured."""
    llm = get_hive_config().get("llm", {})
    auth_mode = resolve_llm_auth_mode(llm)

    if auth_mode == "codex":
        # Codex subscription routes through the ChatGPT backend, not api.openai.com.
        return "https://chatgpt.com/backend-api/codex"
    if auth_mode == "kimi_code":
        # Kimi Code uses an Anthropic-compatible endpoint (no /v1 suffix).
        return "https://api.kimi.com/coding"
    return llm.get("api_base")


def get_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for LiteLLMProvider (e.g. OAuth headers)."""
    llm = get_hive_config().get("llm", {})
    auth_mode = resolve_llm_auth_mode(llm)

    if auth_mode == "claude_code":
        api_key = get_api_key()
        if api_key:
            return {
                "extra_headers": {"authorization": f"Bearer {api_key}"},
            }

    if auth_mode == "codex":
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
# RuntimeConfig - shared across agent templates
# ---------------------------------------------------------------------------


@dataclass
class RuntimeConfig:
    """Agent runtime configuration loaded from ~/.hive/configuration.json."""

    model: str = field(default_factory=get_preferred_model)
    temperature: float = 0.7
    max_tokens: int = field(default_factory=get_max_tokens)
    max_context_tokens: int = field(default_factory=get_max_context_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)
    extra_kwargs: dict[str, Any] = field(default_factory=get_llm_extra_kwargs)
