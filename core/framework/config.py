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

DEFAULT_MAX_TOKENS = 8192

# ---------------------------------------------------------------------------
# Hive home directory structure
# ---------------------------------------------------------------------------

HIVE_HOME = Path.home() / ".hive"
QUEENS_DIR = HIVE_HOME / "agents" / "queens"
COLONIES_DIR = HIVE_HOME / "colonies"
MEMORIES_DIR = HIVE_HOME / "memories"


def queen_dir(queen_name: str = "default") -> Path:
    """Return the storage directory for a named queen agent."""
    return QUEENS_DIR / queen_name


def colony_dir(colony_name: str) -> Path:
    """Return the directory for a named colony."""
    return COLONIES_DIR / colony_name


def memory_dir(scope: str, name: str | None = None) -> Path:
    """Return memory dir for a scope.

    Examples::

        memory_dir("global")                  -> ~/.hive/memories/global
        memory_dir("colonies", "my_agent")    -> ~/.hive/memories/colonies/my_agent
        memory_dir("agents/queens", "default")-> ~/.hive/memories/agents/queens/default
        memory_dir("agents", "worker_name")   -> ~/.hive/memories/agents/worker_name
    """
    base = MEMORIES_DIR / scope
    return base / name if name else base


# ---------------------------------------------------------------------------
# Low-level config file access
# ---------------------------------------------------------------------------

HIVE_CONFIG_FILE = HIVE_HOME / "configuration.json"

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
# Credential store helpers (for BYOK keys)
# ---------------------------------------------------------------------------

# Provider name → credential store ID mapping
_PROVIDER_CRED_MAP: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "google": "gemini",
    "minimax": "minimax",
    "groq": "groq",
    "cerebras": "cerebras",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "together": "together",
    "together_ai": "together",
    "deepseek": "deepseek",
    "kimi": "kimi",
    "hive": "hive",
}


def _get_api_key_from_credential_store(provider: str) -> str | None:
    """Look up a BYOK API key from the encrypted credential store.

    Returns None if no key is found or the credential store is unavailable.
    """
    if not os.environ.get("HIVE_CREDENTIAL_KEY"):
        return None
    cred_id = _PROVIDER_CRED_MAP.get(provider.lower())
    if not cred_id:
        return None
    try:
        from framework.credentials import CredentialStore

        store = CredentialStore.with_encrypted_storage()
        return store.get(cred_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------


def get_preferred_model() -> str:
    """Return the user's preferred LLM model string (e.g. 'anthropic/claude-sonnet-4-20250514')."""
    llm = get_hive_config().get("llm", {})
    if llm.get("provider") and llm.get("model"):
        provider = str(llm["provider"])
        model = str(llm["model"]).strip()
        # OpenRouter quickstart stores raw model IDs; tolerate pasted "openrouter/<id>" too.
        if provider.lower() == "openrouter" and model.lower().startswith("openrouter/"):
            model = model[len("openrouter/") :]
        if model:
            return f"{provider}/{model}"
    return "anthropic/claude-sonnet-4-20250514"


def get_preferred_worker_model() -> str | None:
    """Return the user's preferred worker LLM model, or None if not configured.

    Reads from the ``worker_llm`` section of ~/.hive/configuration.json.
    Returns None when no worker-specific model is set, so callers can
    fall back to the default (queen) model via ``get_preferred_model()``.
    """
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm.get("provider") and worker_llm.get("model"):
        provider = str(worker_llm["provider"])
        model = str(worker_llm["model"]).strip()
        if provider.lower() == "openrouter" and model.lower().startswith("openrouter/"):
            model = model[len("openrouter/") :]
        if model:
            return f"{provider}/{model}"
    return None


def get_worker_api_key() -> str | None:
    """Return the API key for the worker LLM, falling back to the default key."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_api_key()

    # Worker-specific subscription / env var
    if worker_llm.get("use_claude_code_subscription"):
        try:
            from framework.loader.agent_loader import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    if worker_llm.get("use_codex_subscription"):
        try:
            from framework.loader.agent_loader import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    if worker_llm.get("use_kimi_code_subscription"):
        try:
            from framework.loader.agent_loader import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                return token
        except ImportError:
            pass

    if worker_llm.get("use_antigravity_subscription"):
        try:
            from framework.loader.agent_loader import get_antigravity_token

            token = get_antigravity_token()
            if token:
                return token
        except ImportError:
            pass

    api_key_env_var = worker_llm.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)

    # Fall back to default key
    return get_api_key()


def get_worker_api_base() -> str | None:
    """Return the api_base for the worker LLM, falling back to the default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_api_base()

    if worker_llm.get("use_codex_subscription"):
        return "https://chatgpt.com/backend-api/codex"
    if worker_llm.get("use_kimi_code_subscription"):
        return "https://api.kimi.com/coding"
    if worker_llm.get("use_antigravity_subscription"):
        # Antigravity uses AntigravityProvider directly — no api_base needed.
        return None
    if worker_llm.get("api_base"):
        return worker_llm["api_base"]
    if str(worker_llm.get("provider", "")).lower() == "openrouter":
        return OPENROUTER_API_BASE
    return None


def get_worker_llm_extra_kwargs() -> dict[str, Any]:
    """Return extra kwargs for the worker LLM provider."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_llm_extra_kwargs()

    if worker_llm.get("use_claude_code_subscription"):
        api_key = get_worker_api_key()
        if api_key:
            return {
                "extra_headers": {"authorization": f"Bearer {api_key}"},
            }
    if worker_llm.get("use_codex_subscription"):
        api_key = get_worker_api_key()
        if api_key:
            headers: dict[str, str] = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "CodexBar",
            }
            try:
                from framework.loader.agent_loader import get_codex_account_id

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
    if worker_llm.get("provider") == "ollama":
        return {"num_ctx": worker_llm.get("num_ctx", 16384)}
    return {}


def get_worker_max_tokens() -> int:
    """Return max_tokens for the worker LLM, falling back to default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm:
        value = worker_llm.get("max_tokens")
        if isinstance(value, int) and value > 0:
            return value
    return get_max_tokens()


def get_worker_max_context_tokens() -> int:
    """Return max_context_tokens for the worker LLM, falling back to default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm:
        value = worker_llm.get("max_context_tokens")
        if isinstance(value, int) and value > 0:
            return value
    return get_max_context_tokens()


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to DEFAULT_MAX_TOKENS."""
    value = get_hive_config().get("llm", {}).get("max_tokens")
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_MAX_TOKENS


DEFAULT_MAX_CONTEXT_TOKENS = 32_000
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def get_max_context_tokens() -> int:
    """Return the configured max_context_tokens, falling back to DEFAULT_MAX_CONTEXT_TOKENS."""
    value = get_hive_config().get("llm", {}).get("max_context_tokens")
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_MAX_CONTEXT_TOKENS


def get_api_keys() -> list[str] | None:
    """Return a list of API keys if ``api_keys`` is configured, else ``None``.

    This supports key-pool rotation: configure multiple keys in
    ``~/.hive/configuration.json`` under ``llm.api_keys`` and the
    :class:`~framework.llm.key_pool.KeyPool` will rotate through them.
    """
    llm = get_hive_config().get("llm", {})
    keys = llm.get("api_keys")
    if keys and isinstance(keys, list) and len(keys) > 0:
        return [k for k in keys if k]  # filter empties
    return None


def get_api_key() -> str | None:
    """Return the API key, supporting env var, Claude Code subscription, Codex, and ZAI Code.

    Priority:
    0. Explicit key pool (``api_keys`` list) -- returns first key for
       single-key callers; full pool available via :func:`get_api_keys`.
    1. Claude Code subscription (``use_claude_code_subscription: true``)
       reads the OAuth token from ``~/.claude/.credentials.json``.
    2. Codex subscription (``use_codex_subscription: true``)
       reads the OAuth token from macOS Keychain or ``~/.codex/auth.json``.
    3. Environment variable named in ``api_key_env_var``.
    """
    # If an explicit key pool is configured, use the first key.
    pool_keys = get_api_keys()
    if pool_keys:
        return pool_keys[0]

    llm = get_hive_config().get("llm", {})

    # Claude Code subscription: read OAuth token directly
    if llm.get("use_claude_code_subscription"):
        try:
            from framework.loader.agent_loader import get_claude_code_token

            token = get_claude_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Codex subscription: read OAuth token from Keychain / auth.json
    if llm.get("use_codex_subscription"):
        try:
            from framework.loader.agent_loader import get_codex_token

            token = get_codex_token()
            if token:
                return token
        except ImportError:
            pass

    # Kimi Code subscription: read API key from ~/.kimi/config.toml
    if llm.get("use_kimi_code_subscription"):
        try:
            from framework.loader.agent_loader import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                return token
        except ImportError:
            pass

    # Antigravity subscription: read OAuth token from accounts JSON
    if llm.get("use_antigravity_subscription"):
        try:
            from framework.loader.agent_loader import get_antigravity_token

            token = get_antigravity_token()
            if token:
                return token
        except ImportError:
            pass

    # Standard env-var path (covers ZAI Code and all API-key providers)
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        key = os.environ.get(api_key_env_var)
        if key:
            return key

    # Credential store fallback — BYOK keys stored via the UI
    return _get_api_key_from_credential_store(llm.get("provider", ""))


# OAuth credentials for Antigravity are fetched from the opencode-antigravity-auth project.
# This project reverse-engineered and published the public OAuth credentials
# for Google's Antigravity/Cloud Code Assist API.
# Source: https://github.com/NoeFabris/opencode-antigravity-auth
_ANTIGRAVITY_CREDENTIALS_URL = (
    "https://raw.githubusercontent.com/NoeFabris/opencode-antigravity-auth/dev/src/constants.ts"
)
_antigravity_credentials_cache: tuple[str | None, str | None] = (None, None)


def _fetch_antigravity_credentials() -> tuple[str | None, str | None]:
    """Fetch OAuth client ID and secret from the public npm package source on GitHub."""
    global _antigravity_credentials_cache
    if _antigravity_credentials_cache[0] and _antigravity_credentials_cache[1]:
        return _antigravity_credentials_cache

    import re
    import urllib.request

    try:
        req = urllib.request.Request(_ANTIGRAVITY_CREDENTIALS_URL, headers={"User-Agent": "Hive/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            id_match = re.search(r'ANTIGRAVITY_CLIENT_ID\s*=\s*"([^"]+)"', content)
            secret_match = re.search(r'ANTIGRAVITY_CLIENT_SECRET\s*=\s*"([^"]+)"', content)
            client_id = id_match.group(1) if id_match else None
            client_secret = secret_match.group(1) if secret_match else None
            if client_id and client_secret:
                _antigravity_credentials_cache = (client_id, client_secret)
            return client_id, client_secret
    except Exception as e:
        logger.debug("Failed to fetch Antigravity credentials from public source: %s", e)
    return None, None


def get_antigravity_client_id() -> str:
    """Return the Antigravity OAuth application client ID.

    Checked in order:
    1. ``ANTIGRAVITY_CLIENT_ID`` environment variable
    2. ``llm.antigravity_client_id`` in ~/.hive/configuration.json
    3. Fetch from public source (opencode-antigravity-auth project on GitHub)
    """
    env = os.environ.get("ANTIGRAVITY_CLIENT_ID")
    if env:
        return env
    cfg_val = get_hive_config().get("llm", {}).get("antigravity_client_id")
    if cfg_val:
        return cfg_val
    # Fetch from public source
    client_id, _ = _fetch_antigravity_credentials()
    if client_id:
        return client_id
    raise RuntimeError("Could not obtain Antigravity OAuth client ID")


def get_antigravity_client_secret() -> str | None:
    """Return the Antigravity OAuth client secret.

    Checked in order:
    1. ``ANTIGRAVITY_CLIENT_SECRET`` environment variable
    2. ``llm.antigravity_client_secret`` in ~/.hive/configuration.json
    3. Fetch from public source (opencode-antigravity-auth project on GitHub)

    Returns None when not found — token refresh will be skipped and
    the caller must use whatever access token is already available.
    """
    env = os.environ.get("ANTIGRAVITY_CLIENT_SECRET")
    if env:
        return env
    cfg_val = get_hive_config().get("llm", {}).get("antigravity_client_secret") or None
    if cfg_val:
        return cfg_val
    # Fetch from public source
    _, secret = _fetch_antigravity_credentials()
    return secret


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
    """Return the api_base URL for OpenAI-compatible endpoints, if configured."""
    llm = get_hive_config().get("llm", {})
    if llm.get("use_codex_subscription"):
        # Codex subscription routes through the ChatGPT backend, not api.openai.com.
        return "https://chatgpt.com/backend-api/codex"
    if llm.get("use_kimi_code_subscription"):
        # Kimi Code uses an Anthropic-compatible endpoint (no /v1 suffix).
        return "https://api.kimi.com/coding"
    if llm.get("use_antigravity_subscription"):
        # Antigravity uses AntigravityProvider directly — no api_base needed.
        return None
    if llm.get("api_base"):
        return llm["api_base"]
    if str(llm.get("provider", "")).lower() == "openrouter":
        return OPENROUTER_API_BASE
    return None


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
                from framework.loader.agent_loader import get_codex_account_id

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
    if llm.get("provider") == "ollama":
        # Pass num_ctx to Ollama so it doesn't silently truncate the ~9.5k Queen prompt.
        # Ollama's default num_ctx is only 2048. We set it to 16384 here so LiteLLM
        # passes it through as a provider-specific option.
        return {"num_ctx": llm.get("num_ctx", 16384)}
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
