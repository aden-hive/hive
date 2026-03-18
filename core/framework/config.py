"""Shared Hive configuration utilities.

Centralises reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.graph.edge import DEFAULT_MAX_TOKENS

# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"

# Hive LLM router endpoint (Anthropic-compatible).
# litellm's Anthropic handler appends /v1/messages, so this is just the base host.
HIVE_LLM_ENDPOINT = "https://api.adenhq.com"
logger = logging.getLogger(__name__)


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


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)


DEFAULT_MAX_CONTEXT_TOKENS = 32_000


def get_max_context_tokens() -> int:
    """Return the configured max_context_tokens, falling back to DEFAULT_MAX_CONTEXT_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)


def get_api_key() -> str | None:
    """Return the API key from explicit sources only.

    Priority:
    1. Environment variable named in ``api_key_env_var`` config field.
    2. ``api_key`` field stored in ~/.hive/configuration.json.

    Auto-detection of third-party credentials (Claude Code, Codex, Kimi)
    has been removed for security reasons. Users must provide their API key
    explicitly via environment variable or during setup.
    See: https://github.com/aden-hive/hive/issues/6573
    """
    llm = get_hive_config().get("llm", {})
    # 1. Environment variable
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        key = os.environ.get(api_key_env_var)
        if key:
            return key
    # 2. Explicitly stored api_key in config
    stored_key = llm.get("api_key")
    if stored_key:
        return stored_key
    return None

def get_gcu_enabled() -> bool:
    """Return whether GCU (browser automation) is enabled in user config."""
    return get_hive_config().get("gcu_enabled", True)


def get_gcu_viewport_scale() -> float:
    """Return GCU viewport scale factor (0.1-1.0), default 0.8."""
    scale = get_hive_config().get("gcu_viewport_scale", 0.8)
    if isinstance(scale, (int, float)) and 0.1 <= scale <= 1.0:
        return float(scale)
    return 0.8


def get_api_base() -> str | None:
    """Return the api_base URL for OpenAI-compatible endpoints, if configured.

    Only returns explicitly configured api_base values.
    Auto-detection of third-party endpoints (Codex, Kimi) has been removed
    for security reasons. See: https://github.com/aden-hive/hive/issues/6573
    """
    llm = get_hive_config().get("llm", {})
    return llm.get("api_base")


def get_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for LiteLLMProvider.

    Auto-forwarding of OAuth tokens to third-party endpoints has been removed
    for security reasons. See: https://github.com/aden-hive/hive/issues/6573
    """
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
    max_context_tokens: int = field(default_factory=get_max_context_tokens)
    api_key: str | None = field(default_factory=get_api_key)
    api_base: str | None = field(default_factory=get_api_base)
    extra_kwargs: dict[str, Any] = field(default_factory=get_llm_extra_kwargs)


def get_api_key() -> str | None:
    """Return the API key from explicit sources only.

    Priority:
    1. Environment variable named in ``api_key_env_var`` config field.
    2. ``api_key`` field stored in ~/.hive/configuration.json.

    Auto-detection of third-party credentials (Claude Code, Codex, Kimi)
    has been removed for security reasons. Users must provide their API key
    explicitly via environment variable or during setup.
    See: https://github.com/aden-hive/hive/issues/6573
    """
    llm = get_hive_config().get("llm", {})
    # 1. Environment variable
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        key = os.environ.get(api_key_env_var)
        if key:
            return key
    # 2. Explicitly stored api_key in config
    stored_key = llm.get("api_key")
    if stored_key:
        return stored_key
    return None
