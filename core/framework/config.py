"""Shared Hive configuration utilities.

Centralises reading of ~/.hive/configuration.json so that the runner
and every agent template share one implementation instead of copy-pasting
helper functions.
"""

import json
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_MAX_TOKENS = 8192

# ---------------------------------------------------------------------------
# Desktop mode — set by Electron shell to skip frontend builds, etc.
# ---------------------------------------------------------------------------
DESKTOP_MODE: bool = bool(os.environ.get("HIVE_DESKTOP_MODE"))

# ---------------------------------------------------------------------------
# Hive home directory structure
#
# The runtime normally stores state in ``~/.hive/``. When the runtime is
# spawned by the Electron desktop shell, the shell passes ``HIVE_HOME`` as
# an env var pointing at the platform-native userData directory (e.g.
# ``~/Library/Application Support/Hive/`` on macOS), so the desktop app
# does NOT share state with an OSS ``hive`` install on the same machine.
# ---------------------------------------------------------------------------


def _resolve_hive_home() -> Path:
    override = os.environ.get("HIVE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hive"


HIVE_HOME = _resolve_hive_home()
QUEENS_DIR = HIVE_HOME / "queens"
COLONIES_DIR = HIVE_HOME / "colonies"
MEMORIES_DIR = HIVE_HOME / "memories"
FAILED_REQUESTS_DIR = HIVE_HOME / "failed_requests"


def resolve_hive_paths_in_text(text: str) -> str:
    """Replace ``~/.hive`` references with the active ``HIVE_HOME`` path.

    Many prompt strings and tool docstrings reference ``~/.hive/...`` as
    the canonical hive root. On the desktop ``HIVE_HOME`` lives elsewhere
    (e.g. ``~/Library/Application Support/Hive/users/<hash>``), so a model
    that reads those literal references will emit tool calls against
    paths that do not exist. Apply this substitution to anything the
    model sees so the prompt always shows the real on-disk location.
    """
    if not text or "~/.hive" not in text:
        return text
    return text.replace("~/.hive", str(HIVE_HOME))


def resolve_hive_paths_deep(obj):
    """Recursively apply :func:`resolve_hive_paths_in_text` to every string
    inside a dict / list. Used to sanitise tool schemas before they go out
    to the LLM — descriptions live both at the top level and inside
    ``parameters.properties[*].description``.
    """
    if isinstance(obj, str):
        return resolve_hive_paths_in_text(obj)
    if isinstance(obj, dict):
        return {k: resolve_hive_paths_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_hive_paths_deep(v) for v in obj]
    return obj


def queen_dir(queen_name: str = "default") -> Path:
    """Return the queen's home directory.

    v3 layout: ``$HIVE_HOME/queens/<queen_id>/`` contains everything that
    belongs to a queen *identity* — profile, skills, memories, and her
    DM chat sessions. Colony work lives under ``colonies/<name>/``, even
    when the queen is overseeing it.
    """
    return QUEENS_DIR / queen_name


def queen_profile_path(queen_name: str) -> Path:
    return queen_dir(queen_name) / "profile.yaml"


def queen_sessions_dir(queen_name: str) -> Path:
    """All DM sessions for this queen.

    Each subdirectory is a ``<session_id>`` containing ``meta.json``,
    ``events.jsonl``, ``conversations/``, ``compaction.json``.
    """
    return queen_dir(queen_name) / "sessions"


def queen_session_dir(queen_name: str, session_id: str) -> Path:
    return queen_sessions_dir(queen_name) / session_id


def queen_skills_dir(queen_name: str) -> Path:
    return queen_dir(queen_name) / "skills"


def colony_dir(colony_id: str) -> Path:
    """Self-contained colony directory.

    Layout::

        colonies/<name>/
        ├── metadata.json, worker.json, tools.json, skills_overrides.json
        ├── skills/                 colony-scoped skills
        ├── tracker/                tracker DB + WAL siblings
        │   └── tracker.db (+ -wal, -shm)
        ├── seed_conversation/      the queen-snapshot a forked worker inherits
        ├── queens/<queen_name>/sessions/<session_id>/  queen-as-overseer sessions
        └── workers/<session_id>/   parallel worker run state
    """
    return COLONIES_DIR / colony_id


def colony_tracker_dir(colony_id: str) -> Path:
    """Holds ``tracker.db`` and its WAL/SHM siblings. v3 moved this out
    of the ambiguous ``data/`` namespace."""
    return colony_dir(colony_id) / "tracker"


def colony_tracker_db_path(colony_id: str) -> Path:
    return colony_tracker_dir(colony_id) / "tracker.db"


def colony_skills_dir(colony_id: str) -> Path:
    return colony_dir(colony_id) / "skills"


def colony_seed_conversation_dir(colony_id: str) -> Path:
    """The queen transcript snapshot used as the starting context for
    workers spawned in this colony. Written by ``fork_session_into_colony``."""
    return colony_dir(colony_id) / "seed_conversation"


def colony_queens_dir(colony_id: str) -> Path:
    """Container for every queen's overseer sessions for this colony.

    Each subdir is a queen id; under that, a ``sessions/`` dir holds the
    individual session subdirs. Multiple queens can oversee the same colony
    on different threads.
    """
    return colony_dir(colony_id) / "queens"


def colony_queen_dir(colony_id: str, queen_name: str) -> Path:
    """Root for one queen's overseer state within this colony."""
    return colony_queens_dir(colony_id) / queen_name


def colony_queen_sessions_dir(colony_id: str, queen_name: str) -> Path:
    """All overseer sessions for ``queen_name`` within this colony."""
    return colony_queen_dir(colony_id, queen_name) / "sessions"


def colony_queen_session_dir(colony_id: str, queen_name: str, session_id: str) -> Path:
    return colony_queen_sessions_dir(colony_id, queen_name) / session_id


def colony_workers_dir(colony_id: str) -> Path:
    """Parallel worker run state (one subdir per spawned worker session)."""
    return colony_dir(colony_id) / "workers"


def colony_worker_session_dir(colony_id: str, session_id: str) -> Path:
    return colony_workers_dir(colony_id) / session_id


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
# Production proxy is `llm.open-hive.com`; the legacy `api.adenhq.com` host is
# kept only for the Bearer-auth allow-list in litellm.py (some old configs
# still point at it). New deployments should target the open-hive endpoint.
HIVE_LLM_ENDPOINT = "https://llm.open-hive.com"
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


def get_vision_fallback_model() -> str | None:
    """Return the configured vision-fallback model, or None if not configured.

    Reads from the ``vision_fallback`` section of ~/.hive/configuration.json.
    Used by the agent-loop hook that captions tool-result images when the
    main agent's model cannot accept image content (text-only LLMs).

    When this returns None the captioning chain's configured + retry
    attempts both no-op (returning None), and only the final
    ``gemini/gemini-3-flash-preview`` override has a chance to succeed
    — and only if a ``GEMINI_API_KEY`` is set in the environment.
    """
    vision = get_hive_config().get("vision_fallback", {})
    if vision.get("provider") and vision.get("model"):
        provider = str(vision["provider"])
        model = str(vision["model"]).strip()
        if provider.lower() == "openrouter" and model.lower().startswith("openrouter/"):
            model = model[len("openrouter/") :]
        if model:
            return f"{provider}/{model}"
    return None


def get_vision_fallback_api_key() -> str | None:
    """Return the API key for the vision-fallback model.

    Resolution order: ``vision_fallback.api_key_env_var`` from the env,
    then the default ``get_api_key()``. No subscription-token branches —
    vision fallback is intended for hosted vision models (Anthropic,
    OpenAI, Google), not for the subscription-bearer providers.
    """
    vision = get_hive_config().get("vision_fallback", {})
    if not vision:
        return get_api_key()
    if vision.get("api_key"):
        return vision["api_key"]
    api_key_env_var = vision.get("api_key_env_var")
    if api_key_env_var:
        return os.environ.get(api_key_env_var)
    return get_api_key()


def get_vision_fallback_api_base() -> str | None:
    """Return the api_base for the vision-fallback model, or None."""
    vision = get_hive_config().get("vision_fallback", {})
    if not vision:
        return None
    if vision.get("api_base"):
        return vision["api_base"]
    if str(vision.get("provider", "")).lower() == "openrouter":
        return OPENROUTER_API_BASE
    return None


def get_worker_api_key() -> str | None:
    """Return the API key for the worker LLM, falling back to the default key.

    Priority mirrors :func:`get_api_key` — credential store is checked
    before the env var so desktop refresh pushes propagate to new
    worker-LLM instances without a process restart.
    """
    worker_llm = get_hive_config().get("worker_llm", {})
    if not worker_llm:
        return get_api_key()

    # Literal key in the worker section (provider activation writes it).
    literal = worker_llm.get("api_key")
    if literal:
        return literal

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

    # Credential store — checked before env var to mirror get_api_key().
    cred_key = _get_api_key_from_credential_store(worker_llm.get("provider", ""))
    if cred_key:
        return cred_key

    api_key_env_var = worker_llm.get("api_key_env_var")
    if api_key_env_var:
        key = os.environ.get(api_key_env_var)
        if key:
            return key

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


DEFAULT_MAX_CONTEXT_TOKENS = 32_000
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def _catalog_limits_for(llm_section: dict[str, Any]) -> tuple[int, int] | None:
    """Look up ``(max_tokens, max_context_tokens)`` for the configured model.

    Resolves the provider/model pair from a ``llm`` (or ``worker_llm``)
    config section against the curated model catalog. Used as a fallback
    when the config itself doesn't pin these limits — picking a model in
    the UI writes only ``provider`` + ``model``, so without this lookup
    every limit collapses to the hardcoded defaults (32k context, 8k
    output) regardless of the model's real window.
    """
    provider = llm_section.get("provider")
    model = llm_section.get("model")
    if not provider or not model:
        return None
    try:
        from framework.llm.model_catalog import get_model_limits

        if str(provider).lower() == "openrouter" and str(model).lower().startswith("openrouter/"):
            model = str(model)[len("openrouter/") :]
        return get_model_limits(str(provider), str(model))
    except Exception:
        return None


def get_worker_max_tokens() -> int:
    """Return max_tokens for the worker LLM, falling back to default."""
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm and "max_tokens" in worker_llm:
        return worker_llm["max_tokens"]
    if worker_llm:
        catalog = _catalog_limits_for(worker_llm)
        if catalog is not None:
            return catalog[0]
    return get_max_tokens()


def get_worker_max_context_tokens(fallback: int | None = None) -> int:
    """Return max_context_tokens for the worker LLM, falling back to default.

    ``fallback`` (when given) replaces the terminal default, letting a call
    site keep its legacy literal while honoring explicit config first. In
    fallback mode the QUEEN model's catalog window is deliberately NOT
    consulted: a worker on an uncataloged local model must not inherit e.g.
    an 872k opus window and never compact before its real 32k limit.
    """
    worker_llm = get_hive_config().get("worker_llm", {})
    if worker_llm and "max_context_tokens" in worker_llm:
        return worker_llm["max_context_tokens"]
    if worker_llm:
        catalog = _catalog_limits_for(worker_llm)
        if catalog is not None:
            return catalog[1]
    if fallback is not None:
        llm = get_hive_config().get("llm", {})
        if "max_context_tokens" in llm:
            return llm["max_context_tokens"]
        return fallback
    return get_max_context_tokens()


def get_max_tokens() -> int:
    """Return the configured max_tokens, falling back to the model's catalog
    entry, then DEFAULT_MAX_TOKENS."""
    llm = get_hive_config().get("llm", {})
    if "max_tokens" in llm:
        return llm["max_tokens"]
    catalog = _catalog_limits_for(llm)
    if catalog is not None:
        return catalog[0]
    return DEFAULT_MAX_TOKENS


def get_max_context_tokens(fallback: int = DEFAULT_MAX_CONTEXT_TOKENS) -> int:
    """Return the configured max_context_tokens, falling back to the model's
    catalog entry, then ``fallback``.

    ``fallback`` lets a call site keep its legacy terminal default (e.g. the
    queen loop's 180k) while still honoring an explicit config key or the
    model catalog's real window.
    """
    llm = get_hive_config().get("llm", {})
    if "max_context_tokens" in llm:
        return llm["max_context_tokens"]
    catalog = _catalog_limits_for(llm)
    if catalog is not None:
        return catalog[1]
    return fallback


def get_aux_max_tokens() -> int:
    """Output budget for small utility LLM calls (``llm.aux_max_tokens``).

    Covers memory-recall selection, queen routing, sentinel/edge classifiers,
    evaluators, and skill-test invocations. One shared knob instead of
    per-site literals: thinking models spend the budget on hidden reasoning
    before any visible output, so the historic tiny caps (150-2048) silently
    starved these calls into empty responses.
    """
    llm = get_hive_config().get("llm", {})
    if "aux_max_tokens" in llm:
        return llm["aux_max_tokens"]
    # Clamp to the main model's output cap: strict local servers (vLLM,
    # llama.cpp) reject requests whose prompt + max_tokens exceed the model
    # window, so a small configured llm.max_tokens must bound aux calls too.
    return min(DEFAULT_MAX_TOKENS, get_max_tokens())


def get_max_tool_result_chars(fallback: int = 30_000) -> int:
    """Spillover threshold for tool results (``loop.max_tool_result_chars``).

    ``fallback`` lets a call site keep a profile-supplied legacy value when
    the config key is unset.
    """
    loop = get_hive_config().get("loop", {})
    if "max_tool_result_chars" in loop:
        return loop["max_tool_result_chars"]
    return fallback


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


def _fp(token: str | None) -> str:
    """Token fingerprint for logs: ``len=N <first6>…<last4>``. Never logs the
    full token. Returns ``<empty>`` for None / empty strings."""
    if not token:
        return "<empty>"
    return f"len={len(token)} {token[:6]}…{token[-4:]}"


def get_api_key() -> str | None:
    """Return the API key, supporting env var, Claude Code subscription, Codex, and ZAI Code.

    Priority:
    0. Explicit key pool (``api_keys`` list) -- returns first key for
       single-key callers; full pool available via :func:`get_api_keys`.
    1. Claude Code subscription (``use_claude_code_subscription: true``)
       reads the OAuth token from ``~/.claude/.credentials.json``.
    2. Codex subscription (``use_codex_subscription: true``)
       reads the OAuth token from macOS Keychain or ``~/.codex/auth.json``.
    3. Kimi Code / Antigravity subscriptions (parallel branches).
    4. Credential store (BYOK + desktop-pushed tokens like the Hive
       ``streamToken`` rotated via ``POST /api/credentials``).
    5. Environment variable named in ``api_key_env_var``.

    Credential store is checked BEFORE the env var so that desktop
    refresh pushes (which can only update the credential store — process
    env is frozen) actually take effect for new ``RuntimeConfig``
    instances spawned after a refresh. The env var remains a fallback
    for cases where no credential is present yet (e.g. fresh
    ``HIVE_API_KEY=""`` spawn before the first credentials push).
    """
    provider = ""

    # If an explicit key pool is configured, use the first key.
    pool_keys = get_api_keys()
    if pool_keys:
        logger.debug("[hive-auth] get_api_key -> pool fp=%s", _fp(pool_keys[0]))
        return pool_keys[0]

    llm = get_hive_config().get("llm", {})
    provider = llm.get("provider", "")

    # Literal key in configuration.json (written by provider activation in
    # the UI). A key that travels WITH the endpoint config beats every
    # ambient source — the whole point of a provider entry is "this base,
    # this model, this key", independent of launch-shell env state.
    literal = llm.get("api_key")
    if literal:
        logger.debug("[hive-auth] get_api_key -> llm.api_key fp=%s", _fp(literal))
        return literal

    # Claude Code subscription: read OAuth token directly
    if llm.get("use_claude_code_subscription"):
        try:
            from framework.loader.agent_loader import get_claude_code_token

            token = get_claude_code_token()
            if token:
                logger.debug("[hive-auth] get_api_key -> claude_code fp=%s", _fp(token))
                return token
        except ImportError:
            pass

    # Codex subscription: read OAuth token from Keychain / auth.json
    if llm.get("use_codex_subscription"):
        try:
            from framework.loader.agent_loader import get_codex_token

            token = get_codex_token()
            if token:
                logger.debug("[hive-auth] get_api_key -> codex fp=%s", _fp(token))
                return token
        except ImportError:
            pass

    # Kimi Code subscription: read API key from ~/.kimi/config.toml
    if llm.get("use_kimi_code_subscription"):
        try:
            from framework.loader.agent_loader import get_kimi_code_token

            token = get_kimi_code_token()
            if token:
                logger.debug("[hive-auth] get_api_key -> kimi_code fp=%s", _fp(token))
                return token
        except ImportError:
            pass

    # Antigravity subscription: read OAuth token from accounts JSON
    if llm.get("use_antigravity_subscription"):
        try:
            from framework.loader.agent_loader import get_antigravity_token

            token = get_antigravity_token()
            if token:
                logger.debug("[hive-auth] get_api_key -> antigravity fp=%s", _fp(token))
                return token
        except ImportError:
            pass

    # Credential store — checked before env var so desktop refresh pushes
    # to POST /api/credentials win over the frozen spawn-time env var.
    # Matches the priority used by ``_resolve_api_key`` in
    # ``routes_config.py`` for the hot-swap path.
    cred_key = _get_api_key_from_credential_store(provider)
    if cred_key:
        logger.debug(
            "[hive-auth] get_api_key -> credential_store provider=%s fp=%s",
            provider,
            _fp(cred_key),
        )
        return cred_key

    # Standard env-var fallback (covers ZAI Code and all API-key
    # providers when no credential has been written yet).
    api_key_env_var = llm.get("api_key_env_var")
    if api_key_env_var:
        key = os.environ.get(api_key_env_var)
        if key:
            logger.debug(
                "[hive-auth] get_api_key -> env_var %s fp=%s",
                api_key_env_var,
                _fp(key),
            )
            return key

    logger.debug("[hive-auth] get_api_key -> None (provider=%s)", provider)
    return None


# OAuth credentials for Antigravity are fetched from the opencode-antigravity-auth project.
# This project reverse-engineered and published the public OAuth credentials
# for Google's Antigravity/Cloud Code Assist API.
# Source: https://github.com/NoeFabris/opencode-antigravity-auth
_ANTIGRAVITY_CREDENTIALS_URL = "https://raw.githubusercontent.com/NoeFabris/opencode-antigravity-auth/dev/src/constants.ts"
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


def get_adaptive_tool_budget_enabled() -> bool:
    """Return whether colony-adaptive worker tool budgets are enabled.

    Resolution (mirrors the retention pattern: env wins over file wins
    over default):
    1. ``HIVE_ADAPTIVE_TOOL_BUDGET`` env var, when explicitly set.
    2. Top-level ``adaptive_tool_budget`` boolean in configuration.json —
       the desktop app's Developer-options toggle writes this via
       PUT /api/config/features.
    3. Default: enabled.

    Read per session start (get_hive_config re-reads the file), so the
    toggle applies to new sessions without a runtime restart. Per-colony
    ``metadata.json`` overrides still beat this global value.
    """
    raw = os.environ.get("HIVE_ADAPTIVE_TOOL_BUDGET")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() not in ("0", "false", "no", "off")
    value = get_hive_config().get("adaptive_tool_budget")
    if isinstance(value, bool):
        return value
    return True


def get_email_senders_enabled() -> bool:
    """Return whether the email-senders suite is enabled.

    Resolution mirrors :func:`get_adaptive_tool_budget_enabled`:
    1. ``HIVE_EMAIL_SENDERS`` env var, when explicitly set.
    2. Top-level ``email_senders`` boolean in configuration.json — the
       desktop app's Developer-options toggle writes this via
       PUT /api/config/features.
    3. Default: DISABLED. Senders are an advanced developer feature; the
       whole surface stays off until the user opts in.

    Off means the model never learns the feature exists: the env var is
    what the ``hive_tools`` MCP subprocess reads to decide whether to
    register the sender tools at all (see
    ``aden_tools.tools._register_verified``), so when it is falsy the
    tools are absent from the catalog — unprompted, unsearchable,
    uncallable, and immune to any allow-all path. ``aden_tools`` reads
    env, never configuration.json; :func:`sync_email_senders_env` is the
    bridge between the two.
    """
    raw = os.environ.get("HIVE_EMAIL_SENDERS")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() not in ("0", "false", "no", "off")
    value = get_hive_config().get("email_senders")
    if isinstance(value, bool):
        return value
    return False


def sync_email_senders_env(enabled: bool | None = None) -> bool:
    """Publish the email-senders flag into ``os.environ``.

    MCP subprocesses inherit the runtime's environment at spawn
    (MCPClient merges ``os.environ`` under the per-server env), so this is
    how the flag reaches every server the runtime starts — queen, worker
    and colony registries alike — without threading it through each
    ToolRegistry.

    Called at server startup with no argument (value resolved from env
    then config), and again from PUT /api/config/features with the value
    just saved. That second call is an explicit user action, so it
    overwrites any pre-existing env var rather than deferring to it.
    Because tools bind when the subprocess spawns, a toggle takes effect
    for sessions started afterwards; colonies already running keep the
    tool set they booted with.
    """
    if enabled is None:
        enabled = get_email_senders_enabled()
    os.environ["HIVE_EMAIL_SENDERS"] = "1" if enabled else "0"
    return enabled


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
    # Generic passthrough: let configuration.json forward a raw ``extra_body``
    # to LiteLLM/the OpenAI SDK (e.g. vLLM's ``chat_template_kwargs`` to disable
    # a model's default thinking). Applied to every LLM call, including the
    # small recall/judge aux calls that otherwise burn their token budget on
    # hidden reasoning and return empty.
    extra_body = llm.get("extra_body")
    if isinstance(extra_body, dict) and extra_body:
        return {"extra_body": extra_body}
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


# ---------------------------------------------------------------------------
# RetentionConfig – data-retention janitor (framework.maintenance)
# ---------------------------------------------------------------------------


@dataclass
class RetentionConfig:
    """Retention windows and switches for the data-retention janitor.

    Loaded from the ``"retention"`` object in ``configuration.json``;
    every field can be overridden by an env var named
    ``HIVE_RETENTION_<FIELD_UPPERCASE>`` (env wins over file wins over
    default). The janitor only ever runs on manual trigger (CLI or
    ``POST /api/maintenance/janitor/run``) — there is no scheduler.
    """

    enabled: bool = True  # master kill switch
    mode: str = "archive"  # "archive" | "delete" — disposal for tiers 2/3
    archive_dir: str = ""  # default: $HIVE_HOME/archive
    # Tier 1 — debug stores, always plain-deleted (no corpus value).
    event_logs_days: int = 7
    llm_logs_days: int = 7
    compaction_log_days: int = 7
    tool_artifacts_days: int = 14
    rotated_logs_days: int = 30
    # Tier 2 — finished-worker deep-clean.
    worker_deep_clean_days: int = 14
    # Tier 3 — cold queen session hygiene.
    queen_hygiene_days: int = 30
    events_rewrite_min_bytes: int = 1_000_000
    # Safety / pacing.
    active_grace_hours: int = 48
    io_sleep_ms: int = 10
    batch_size: int = 200
    junk_min_bytes: int = 50_000_000


def get_retention_config() -> RetentionConfig:
    """Build a RetentionConfig from configuration.json + env overrides."""
    cfg = RetentionConfig()
    raw = get_hive_config().get("retention")
    if isinstance(raw, dict):
        for f in fields(RetentionConfig):
            # Exact type match (not isinstance) so JSON `true` can't land in an int field.
            if f.name in raw and type(raw[f.name]) is type(getattr(cfg, f.name)):
                setattr(cfg, f.name, raw[f.name])
    for f in fields(RetentionConfig):
        env_val = os.environ.get(f"HIVE_RETENTION_{f.name.upper()}")
        if env_val is None:
            continue
        current = getattr(cfg, f.name)
        try:
            if isinstance(current, bool):
                setattr(cfg, f.name, env_val.strip().lower() not in ("0", "false", "no", ""))
            elif isinstance(current, int):
                setattr(cfg, f.name, int(env_val))
            else:
                setattr(cfg, f.name, env_val)
        except ValueError:
            logger.warning("Ignoring invalid HIVE_RETENTION_%s=%r", f.name.upper(), env_val)
    return cfg
