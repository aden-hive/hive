"""Shared Hive configuration utilities.

Centralises reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from framework.graph.edge import DEFAULT_MAX_TOKENS

# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"
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


LLMAuthMode = Literal["api_key", "claude_code", "codex", "kimi_code"]
_SUPPORTED_AUTH_MODES = {"api_key", "claude_code", "codex", "kimi_code"}


def _get_llm_config(llm: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the LLM subsection from configuration.json."""
    return llm if llm is not None else get_hive_config().get("llm", {})


def _get_preferred_model(llm: dict[str, Any]) -> str:
    """Return the fully-qualified model name for an llm config block."""
    if llm.get("provider") and llm.get("model"):
        return f"{llm['provider']}/{llm['model']}"
    return "anthropic/claude-sonnet-4-20250514"


def get_preferred_model() -> str:
    """Return the user's preferred LLM model string (e.g. 'anthropic/claude-sonnet-4-20250514')."""
    return _get_preferred_model(_get_llm_config())


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_tokens", DEFAULT_MAX_TOKENS)


DEFAULT_MAX_CONTEXT_TOKENS = 32_000


def get_max_context_tokens() -> int:
    """Return the configured max_context_tokens, falling back to DEFAULT_MAX_CONTEXT_TOKENS."""
    return get_hive_config().get("llm", {}).get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)


def resolve_llm_auth_mode(llm: dict[str, Any] | None = None) -> LLMAuthMode:
    """Resolve the active authentication mode for the LLM configuration.

    ``auth_mode`` is authoritative when present so stale legacy flags cannot
    keep a session on the wrong credential path after the user switches modes.
    """
    llm = _get_llm_config(llm)
    auth_mode = str(llm.get("auth_mode", "")).strip().lower()
    if auth_mode in _SUPPORTED_AUTH_MODES:
        return cast(LLMAuthMode, auth_mode)
    if llm.get("use_claude_code_subscription"):
        return "claude_code"
    if llm.get("use_codex_subscription"):
        return "codex"
    if llm.get("use_kimi_code_subscription"):
        return "kimi_code"
    return "api_key"


def _get_subscription_api_key(auth_mode: LLMAuthMode) -> str | None:
    """Resolve tokens for subscription-backed auth modes."""
    try:
        if auth_mode == "claude_code":
            from framework.runner.runner import get_claude_code_token

            return get_claude_code_token()
        if auth_mode == "codex":
            from framework.runner.runner import get_codex_token

            return get_codex_token()
        if auth_mode == "kimi_code":
            from framework.runner.runner import get_kimi_code_token

            return get_kimi_code_token()
    except ImportError:
        return None
    return None


def get_api_key(llm: dict[str, Any] | None = None) -> str | None:
    """Return the API key or subscription token for the active auth mode."""
    llm = _get_llm_config(llm)
    auth_mode = resolve_llm_auth_mode(llm)
    if auth_mode != "api_key":
        return _get_subscription_api_key(auth_mode)

    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)
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


def get_api_base(llm: dict[str, Any] | None = None) -> str | None:
    """Return the api_base URL for the active auth mode, if configured."""
    llm = _get_llm_config(llm)
    auth_mode = resolve_llm_auth_mode(llm)
    if auth_mode == "codex":
        # Codex subscription routes through the ChatGPT backend, not api.openai.com.
        return "https://chatgpt.com/backend-api/codex"
    if auth_mode == "kimi_code":
        # Kimi Code uses an Anthropic-compatible endpoint (no /v1 suffix).
        return "https://api.kimi.com/coding"
    return llm.get("api_base")


def get_llm_extra_kwargs(llm: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return extra kwargs for LiteLLMProvider (e.g. OAuth headers).

    When Claude Code auth is enabled, returns
    ``extra_headers`` with the OAuth Bearer token so that litellm's
    built-in Anthropic OAuth handler adds the required beta headers.

    When Codex auth is enabled, returns
    ``extra_headers`` with the Bearer token, ``ChatGPT-Account-Id``,
    and ``store=False`` (required by the ChatGPT backend).
    """
    llm = _get_llm_config(llm)
    auth_mode = resolve_llm_auth_mode(llm)
    if auth_mode == "claude_code":
        api_key = get_api_key(llm)
        if api_key:
            return {
                "extra_headers": {"authorization": f"Bearer {api_key}"},
            }
    if auth_mode == "codex":
        api_key = get_api_key(llm)
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


def get_llm_runtime_fingerprint(
    model: str | None = None,
    llm: dict[str, Any] | None = None,
) -> str:
    """Return a stable digest of the effective LLM runtime settings.

    Excludes live credential material so routine OAuth token refreshes do not
    make an unchanged session look stale.
    """
    llm = _get_llm_config(llm)
    payload = {
        "auth_mode": resolve_llm_auth_mode(llm),
        "provider": llm.get("provider"),
        "model": model or _get_preferred_model(llm),
        "api_base": get_api_base(llm),
        "api_key_env_var": llm.get("api_key_env_var"),
    }
    encoded = json.dumps(
        payload,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
