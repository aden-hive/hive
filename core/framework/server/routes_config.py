"""LLM configuration routes — BYOK key management, subscriptions, and model selection.

Routes:
- GET  /api/config/llm           — current active LLM configuration
- PUT  /api/config/llm           — update active provider + model (hot-swaps running sessions)
- GET  /api/config/models        — curated provider→models list
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from aiohttp import web

from framework.agents.queen.queen_memory_v2 import (
    build_memory_document,
    global_memory_dir,
)
from framework.config import (
    _PROVIDER_CRED_MAP,
    HIVE_CONFIG_FILE,
    OPENROUTER_API_BASE,
    get_hive_config,
)
from framework.llm.model_catalog import (
    find_model,
    get_models_catalogue,
    get_preset,
)
from framework.server.app import get_request_executor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider metadata (mirrors quickstart.sh)
# ---------------------------------------------------------------------------

# env var name per provider
PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "together_ai": "TOGETHER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "kimi": "KIMI_API_KEY",
    "hive": "HIVE_API_KEY",
}

_SUBSCRIPTION_DEFINITIONS: list[dict[str, str]] = [
    {
        "id": "claude_code",
        "name": "Claude Code Subscription",
        "description": "Use your Claude Max/Pro plan",
        "flag": "use_claude_code_subscription",
    },
    {
        "id": "zai_code",
        "name": "ZAI Code Subscription",
        "description": "Use your ZAI Code plan",
        "flag": "use_zai_code_subscription",
    },
    {
        "id": "codex",
        "name": "OpenAI Codex Subscription",
        "description": "Use your Codex/ChatGPT Plus plan",
        "flag": "use_codex_subscription",
    },
    {
        "id": "minimax_code",
        "name": "MiniMax Coding Key",
        "description": "Use your MiniMax coding key",
        "flag": "use_minimax_code_subscription",
    },
    {
        "id": "kimi_code",
        "name": "Kimi Code Subscription",
        "description": "Use your Kimi Code plan",
        "flag": "use_kimi_code_subscription",
    },
    {
        "id": "hive_llm",
        "name": "Hive LLM",
        "description": "Use your Hive API key",
        "flag": "use_hive_llm_subscription",
    },
    {
        "id": "antigravity",
        "name": "Antigravity Subscription",
        "description": "Use your Google/Gemini plan",
        "flag": "use_antigravity_subscription",
    },
]


def _build_subscriptions() -> list[dict]:
    subscriptions: list[dict] = []
    for definition in _SUBSCRIPTION_DEFINITIONS:
        preset = get_preset(definition["id"])
        if not preset:
            raise RuntimeError(f"Missing preset for subscription {definition['id']}")

        subscriptions.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "description": definition["description"],
                "provider": preset["provider"],
                "flag": definition["flag"],
                "default_model": preset.get("model", ""),
                **({"api_base": preset["api_base"]} if preset.get("api_base") else {}),
            }
        )
    return subscriptions


# ---------------------------------------------------------------------------
# Subscription metadata (mirrors quickstart subscription modes)
# ---------------------------------------------------------------------------

SUBSCRIPTIONS: list[dict] = _build_subscriptions()

# All subscription config flags
_ALL_SUBSCRIPTION_FLAGS = [s["flag"] for s in SUBSCRIPTIONS]

# Map subscription ID → subscription metadata
_SUBSCRIPTION_MAP = {s["id"]: s for s in SUBSCRIPTIONS}

# Model catalogue loaded from the shared JSON source of truth.
MODELS_CATALOGUE: dict[str, list[dict]] = get_models_catalogue()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_api_base_for_provider(provider: str) -> str | None:
    """Return the api_base URL for a provider, if needed."""
    if provider.lower() == "openrouter":
        return OPENROUTER_API_BASE
    return None


def _find_model_info(provider: str, model_id: str) -> dict | None:
    """Look up a model in the catalogue to get its token limits."""
    return find_model(provider, model_id)


def _write_config_atomic(config: dict) -> None:
    """Write config to ~/.hive/configuration.json atomically."""
    HIVE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(HIVE_CONFIG_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        Path(tmp_path).replace(HIVE_CONFIG_FILE)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _resolve_api_key(provider: str, request: web.Request) -> str | None:
    """Resolve the API key for a provider from credential store or env var."""
    # Try credential store first
    cred_id = _PROVIDER_CRED_MAP.get(provider.lower())
    if cred_id:
        try:
            store = request.app["credential_store"]
            key = store.get(cred_id)
            if key:
                return key
        except Exception:
            pass
    # Fall back to env var
    env_var = PROVIDER_ENV_VARS.get(provider.lower())
    if env_var:
        return os.environ.get(env_var)
    return None


def _detect_subscriptions() -> list[str]:
    """Detect which subscription credentials are available on the system."""
    detected = []

    # Claude Code subscription
    try:
        from framework.loader.agent_loader import get_claude_code_token

        if get_claude_code_token():
            detected.append("claude_code")
    except Exception:
        pass

    # ZAI Code subscription (API key based)
    if os.environ.get("ZAI_API_KEY"):
        detected.append("zai_code")

    # Codex subscription
    try:
        from framework.loader.agent_loader import get_codex_token

        if get_codex_token():
            detected.append("codex")
    except Exception:
        pass

    # MiniMax Coding Key (API key based)
    if os.environ.get("MINIMAX_API_KEY"):
        detected.append("minimax_code")

    # Kimi Code subscription (CLI config file or API key env var)
    kimi_token = None
    try:
        from framework.loader.agent_loader import get_kimi_code_token

        kimi_token = get_kimi_code_token()
    except Exception:
        pass
    if not kimi_token:
        kimi_token = os.environ.get("KIMI_API_KEY")
    if kimi_token:
        detected.append("kimi_code")

    # Hive LLM (API key based)
    if os.environ.get("HIVE_API_KEY"):
        detected.append("hive_llm")

    # Antigravity subscription
    try:
        from framework.loader.agent_loader import get_antigravity_token

        if get_antigravity_token():
            detected.append("antigravity")
    except Exception:
        pass

    return detected


def _get_active_subscription(llm_config: dict) -> str | None:
    """Return the currently active subscription ID, or None."""
    for sub in SUBSCRIPTIONS:
        if llm_config.get(sub["flag"]):
            return sub["id"]
    return None


def _get_subscription_token(sub_id: str) -> str | None:
    """Get the token for a subscription."""
    if sub_id == "claude_code":
        from framework.loader.agent_loader import get_claude_code_token

        return get_claude_code_token()
    elif sub_id == "zai_code":
        return os.environ.get("ZAI_API_KEY")
    elif sub_id == "codex":
        from framework.loader.agent_loader import get_codex_token

        return get_codex_token()
    elif sub_id == "minimax_code":
        return os.environ.get("MINIMAX_API_KEY")
    elif sub_id == "kimi_code":
        from framework.loader.agent_loader import get_kimi_code_token

        token = get_kimi_code_token()
        if not token:
            token = os.environ.get("KIMI_API_KEY")
        return token
    elif sub_id == "hive_llm":
        return os.environ.get("HIVE_API_KEY")
    elif sub_id == "antigravity":
        from framework.loader.agent_loader import get_antigravity_token

        return get_antigravity_token()
    return None


def _hot_swap_sessions(request: web.Request, full_model: str, api_key: str | None, api_base: str | None) -> int:
    """Hot-swap the LLM on all running sessions. Returns count of swapped providers.

    Walks every long-lived LLM holder reachable from a session:
      - ``session.llm`` (the queen's own provider).
      - ``session.colony._llm`` / ``.llm`` when an in-flight ColonyRuntime is
        attached — its baked-in worker provider doesn't appear under
        ``manager.list_sessions()`` but is still rotating LLM calls.

    For api_key freshness on its own, the ``api_key_resolver`` wired through
    ``build_llm`` / ``build_worker_llm`` already re-resolves the credential
    on every call. This hot-swap remains the canonical path for **model**
    and **api_base** changes, and keeps each provider's snapshot in sync as
    a belt-and-suspenders.

    Also refreshes the SessionManager's default model so that subsequent
    one-shot LLM consumers (e.g. /messages/classify, new session bootstrap)
    pick up the new provider/model instead of the stale startup override.
    """
    from framework.server.session_manager import SessionManager

    manager: SessionManager = request.app["manager"]
    manager._model = full_model
    swapped = 0

    def _reconfigure_if_possible(prov: Any) -> bool:
        if prov and hasattr(prov, "reconfigure"):
            prov.reconfigure(full_model, api_key=api_key, api_base=api_base)
            return True
        return False

    for session in manager.list_sessions():
        if _reconfigure_if_possible(getattr(session, "llm", None)):
            swapped += 1
        # ColonyRuntime holds its own worker LLM; expose attribute may be
        # either ``_llm`` (current convention) or ``llm`` (defensive).
        colony = getattr(session, "colony", None)
        if colony is not None:
            for attr in ("_llm", "llm"):
                if _reconfigure_if_possible(getattr(colony, attr, None)):
                    swapped += 1
                    break
    return swapped


async def _validate_provider_key(
    provider: str,
    api_key: str,
    api_base: str | None = None,
    model: str | None = None,
) -> dict:
    """Validate an API key against the provider. Returns {"valid": bool, "message": str}.

    Runs the check in a thread pool to avoid blocking the event loop.
    """
    from scripts.check_llm_key import (
        PROVIDERS as CHECK_PROVIDERS,
        check_anthropic_compatible,
        check_minimax,
        check_openai_compatible,
        check_openrouter,
        check_openrouter_model,
    )

    def _check() -> dict:
        pid = provider.lower()
        try:
            # Subscription providers with custom api_base
            if pid == "openrouter" and model:
                return check_openrouter_model(api_key, model=model, api_base=api_base or "https://openrouter.ai/api/v1")
            if api_base and pid == "minimax":
                return check_minimax(api_key, api_base)
            if api_base and pid == "openrouter":
                return check_openrouter(api_key, api_base)
            if api_base and pid == "kimi":
                return check_anthropic_compatible(
                    api_key,
                    api_base.rstrip("/") + "/v1/messages",
                    "Kimi",
                    model=model or "kimi-k2.6",
                )
            if api_base and pid == "hive":
                return check_anthropic_compatible(
                    api_key,
                    api_base.rstrip("/") + "/v1/messages",
                    "Hive",
                    model=model or "queen",
                    bearer_auth=True,
                )
            if api_base:
                endpoint = api_base.rstrip("/") + "/models"
                name = {"zai": "ZAI"}.get(pid, "Custom provider")
                return check_openai_compatible(api_key, endpoint, name)
            if pid in CHECK_PROVIDERS:
                return CHECK_PROVIDERS[pid](api_key)
            # No check available — assume valid
            return {"valid": True, "message": f"No health check for {pid}"}
        except Exception as exc:
            return {"valid": None, "message": f"Validation error: {exc}"}

    return await asyncio.get_event_loop().run_in_executor(get_request_executor(), _check)


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------


async def handle_get_llm_config(request: web.Request) -> web.Response:
    """GET /api/config/llm — current active LLM configuration."""
    config = get_hive_config()
    llm = config.get("llm", {})
    provider = llm.get("provider", "")
    model = llm.get("model", "")

    # Check if an API key is available for the current provider
    has_key = _resolve_api_key(provider, request) is not None

    # Check ALL providers for key availability (env vars + credential store)
    connected = []
    for pid in PROVIDER_ENV_VARS:
        if pid in ("google", "together_ai"):
            continue  # Skip aliases
        if _resolve_api_key(pid, request) is not None:
            connected.append(pid)

    # Subscription detection — only include subscriptions whose tokens exist
    active_subscription = _get_active_subscription(llm)
    detected_subscriptions = [sid for sid in _detect_subscriptions() if _get_subscription_token(sid)]

    return web.json_response(
        {
            "provider": provider,
            "model": model,
            "has_api_key": has_key,
            "max_tokens": llm.get("max_tokens"),
            "max_context_tokens": llm.get("max_context_tokens"),
            "connected_providers": connected,
            "active_subscription": active_subscription,
            "detected_subscriptions": detected_subscriptions,
            "subscriptions": SUBSCRIPTIONS,
            # Surface the endpoint the config actually points at, so the UI
            # can present a custom OpenAI-compatible endpoint (self-hosted
            # vLLM, vendor proxy, …) as a first-class choice instead of only
            # the hardcoded provider list.
            "api_base": llm.get("api_base"),
            "api_key_env_var": llm.get("api_key_env_var"),
        }
    )


async def handle_update_llm_config(request: web.Request) -> web.Response:
    """PUT /api/config/llm — set active provider + model, hot-swap running sessions.

    Accepts three modes:
    1. API key mode: {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
    2. Subscription mode: {"subscription": "claude_code"} (uses preset model)
    3. Custom endpoint mode: {"custom": true, "model": "...", "api_base"?, "api_key_env_var"?}
       — keeps/updates the config's own endpoint and switches models on it
       without catalogue validation.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    subscription_id = body.get("subscription")

    if body.get("custom"):
        # ── Custom endpoint mode ─────────────────────────────────────
        # The active config may point at an OpenAI-compatible endpoint the
        # shipped catalogue knows nothing about (self-hosted vLLM, a vendor
        # proxy, …). Let the user keep that endpoint and switch models on it
        # freely: no catalogue validation (the endpoint's model list is
        # unknowable here); api_base / api_key_env_var default to what the
        # config already has, so a model switch never clobbers the endpoint
        # it runs on.
        model = str(body.get("model") or "").strip()
        if not model:
            return web.json_response({"error": "'model' is required"}, status=400)
        config = get_hive_config()
        llm_section = config.setdefault("llm", {})
        provider = str(
            body.get("provider") or llm_section.get("provider") or "openai"
        )
        api_base = (
            str(body.get("api_base") or llm_section.get("api_base") or "").strip()
            or None
        )
        env_var = str(
            body.get("api_key_env_var") or llm_section.get("api_key_env_var") or ""
        ).strip()
        api_key = os.environ.get(env_var) if env_var else None
        if api_key is None:
            api_key = _resolve_api_key(provider, request)

        llm_section["provider"] = provider
        llm_section["model"] = model
        if body.get("max_tokens"):
            llm_section["max_tokens"] = int(body["max_tokens"])
        if body.get("max_context_tokens"):
            llm_section["max_context_tokens"] = int(body["max_context_tokens"])
        if env_var:
            llm_section["api_key_env_var"] = env_var
        if api_base:
            llm_section["api_base"] = api_base
        for flag in _ALL_SUBSCRIPTION_FLAGS:
            llm_section.pop(flag, None)
        _write_config_atomic(config)

        full_model = f"{provider}/{model}"
        swapped = _hot_swap_sessions(
            request, full_model, api_key=api_key, api_base=api_base
        )
        logger.info(
            "LLM config updated (custom endpoint): provider=%s model=%s base=%s, "
            "hot-swapped %d session(s)",
            provider,
            model,
            api_base,
            swapped,
        )
        return web.json_response(
            {
                "provider": provider,
                "model": model,
                "has_api_key": api_key is not None,
                "max_tokens": llm_section.get("max_tokens"),
                "max_context_tokens": llm_section.get("max_context_tokens"),
                "sessions_swapped": swapped,
                "active_subscription": None,
                "api_base": api_base,
                "api_key_env_var": env_var or None,
            }
        )

    if subscription_id:
        # ── Subscription mode ────────────────────────────────────────
        sub = _SUBSCRIPTION_MAP.get(subscription_id)
        if not sub:
            return web.json_response({"error": f"Unknown subscription: {subscription_id}"}, status=400)

        preset = get_preset(subscription_id)
        # Subscriptions use the fixed model from their preset (no model switching)
        model = sub["default_model"]
        provider = sub["provider"]
        api_base = sub.get("api_base")

        # Validate the subscription token before committing
        token = _get_subscription_token(subscription_id)
        if not token:
            return web.json_response(
                {"error": f"No credential found for {sub['name']}. Please check your subscription or API key."},
                status=400,
            )

        check = await _validate_provider_key(provider, token, api_base=api_base, model=model)
        if check.get("valid") is False:
            return web.json_response(
                {"error": f"{sub['name']} key validation failed: {check.get('message', 'unknown error')}"},
                status=400,
            )

        # Look up token limits from preset
        max_tokens: int | None = None
        max_context_tokens: int | None = None
        if preset:
            max_tokens = int(preset["max_tokens"])
            max_context_tokens = int(preset["max_context_tokens"])
        else:
            max_tokens = 8192
            max_context_tokens = 120000

        # Update config: activate this subscription, clear others
        config = get_hive_config()
        llm_section = config.setdefault("llm", {})
        llm_section["provider"] = provider
        llm_section["model"] = model
        llm_section["max_tokens"] = max_tokens
        llm_section["max_context_tokens"] = max_context_tokens
        # Clear all subscription flags, then set the active one
        for flag in _ALL_SUBSCRIPTION_FLAGS:
            llm_section.pop(flag, None)
        llm_section[sub["flag"]] = True
        # Remove api_key_env_var since subscriptions don't use it
        llm_section.pop("api_key_env_var", None)
        if api_base:
            llm_section["api_base"] = api_base
        elif "api_base" in llm_section:
            del llm_section["api_base"]

        _write_config_atomic(config)

        # Hot-swap with subscription token (already validated above)
        full_model = f"{provider}/{model}"
        swapped = _hot_swap_sessions(request, full_model, api_key=token, api_base=api_base)

        logger.info(
            "LLM config updated: subscription=%s model=%s, hot-swapped %d session(s)",
            subscription_id,
            model,
            swapped,
        )

        return web.json_response(
            {
                "provider": provider,
                "model": model,
                "has_api_key": token is not None,
                "max_tokens": max_tokens,
                "max_context_tokens": max_context_tokens,
                "sessions_swapped": swapped,
                "active_subscription": subscription_id,
            }
        )

    else:
        # ── API key mode ─────────────────────────────────────────────
        provider = body.get("provider")
        model = body.get("model")
        if not provider or not model:
            return web.json_response({"error": "Both 'provider' and 'model' are required"}, status=400)

        # Verify model exists in the catalogue
        model_info = _find_model_info(provider, model)
        if not model_info:
            return web.json_response(
                {"error": f"Model '{model}' is not available for provider '{provider}'."},
                status=400,
            )

        max_tokens = model_info["max_tokens"]
        max_context_tokens = model_info["max_context_tokens"]

        # Determine env var and api_base
        env_var = PROVIDER_ENV_VARS.get(provider.lower(), "")
        api_base = _get_api_base_for_provider(provider)
        # Hive routes through a proxy whose URL is environment-specific (local
        # dev vs prod) and written into configuration.json by the desktop app.
        # Reuse it so key validation pings the right proxy and the URL isn't
        # dropped from the persisted config below.
        if api_base is None and provider.lower() == "hive":
            api_base = get_hive_config().get("llm", {}).get("api_base")

        # Validate the API key before committing
        api_key = _resolve_api_key(provider, request)
        if not api_key:
            return web.json_response(
                {"error": f"No API key found for {provider}. Please add one in Manage Keys."},
                status=400,
            )

        check = await _validate_provider_key(provider, api_key, api_base=api_base, model=model)
        if check.get("valid") is False:
            return web.json_response(
                {"error": f"API key validation failed for {provider}: {check.get('message', 'unknown error')}"},
                status=400,
            )

        # Update ~/.hive/configuration.json
        config = get_hive_config()
        llm_section = config.setdefault("llm", {})
        llm_section["provider"] = provider
        llm_section["model"] = model
        llm_section["max_tokens"] = max_tokens
        llm_section["max_context_tokens"] = max_context_tokens
        if env_var:
            llm_section["api_key_env_var"] = env_var
        if api_base:
            llm_section["api_base"] = api_base
        elif "api_base" in llm_section:
            del llm_section["api_base"]
        # Clear subscription flags — switching to direct API key mode
        for flag in _ALL_SUBSCRIPTION_FLAGS:
            llm_section.pop(flag, None)

        _write_config_atomic(config)

        # Hot-swap all running sessions (api_key already validated above)
        full_model = f"{provider}/{model}"
        swapped = _hot_swap_sessions(request, full_model, api_key=api_key, api_base=api_base)

        logger.info(
            "LLM config updated: provider=%s model=%s, hot-swapped %d session(s)",
            provider,
            model,
            swapped,
        )

        return web.json_response(
            {
                "provider": provider,
                "model": model,
                "has_api_key": api_key is not None,
                "max_tokens": max_tokens,
                "max_context_tokens": max_context_tokens,
                "sessions_swapped": swapped,
                "active_subscription": None,
            }
        )


# Valid sort keys for the Prompt Library top-right dropdowns. Mirrors
# the SortKey union in the renderer's prompt-library page; anything else
# is rejected so a hand-edited config can't poison the dropdown state.
_PROMPT_SORT_KEYS = ("date", "name", "popular")


def _normalize_prompt_sort(raw: object) -> dict | None:
    """Coerce a stored prompt_library_sort blob into a partial {my, community}
    dict containing only the keys the user actually set. Returns None when
    nothing was saved, so the renderer can fall back to its local cache
    instead of being clobbered by server-side defaults on first hydration."""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for k in ("my", "community"):
        v = raw.get(k)
        if isinstance(v, str) and v in _PROMPT_SORT_KEYS:
            out[k] = v
    return out or None


async def handle_get_profile(request: web.Request) -> web.Response:
    """GET /api/config/profile — user display name and about."""
    profile = get_hive_config().get("user_profile", {})
    return web.json_response(
        {
            "displayName": profile.get("displayName", ""),
            "about": profile.get("about", ""),
            "theme": profile.get("theme", ""),
            "density": profile.get("density", ""),
            "prompt_library_sort": _normalize_prompt_sort(profile.get("prompt_library_sort")),
        }
    )


def _update_user_profile_memory(display_name: str, about: str) -> None:
    """Sync user profile to global memory as a profile-type memory file.

    Uses the canonical filename 'user-profile.md' — this is the single
    source of truth for user identity information, shared with the
    reflection agent.

    Merges with existing content to preserve sections added by the reflection agent.
    """
    try:
        mem_dir = global_memory_dir()
        mem_dir.mkdir(parents=True, exist_ok=True)

        profile_filename = "user-profile.md"
        memory_path = mem_dir / profile_filename

        # Read existing content if present
        existing_body = ""
        if memory_path.exists():
            existing_text = memory_path.read_text(encoding="utf-8")
            # Extract body after frontmatter
            if "---\n" in existing_text:
                parts = existing_text.split("---\n", 2)
                if len(parts) >= 3:
                    existing_body = parts[2].strip()

        # Build Identity section from settings
        identity_lines = []
        if display_name:
            identity_lines.append(f"- **Name:** {display_name}")
        if about:
            identity_lines.append(f"- **About:** {about}")

        identity_section = "## Identity\n" + "\n".join(identity_lines) if identity_lines else ""

        # Merge: replace or prepend Identity section, keep rest
        if existing_body and "## Identity" in existing_body:
            # Replace existing Identity section
            before = existing_body.split("## Identity")[0].rstrip()
            after_parts = existing_body.split("## Identity", 1)[1].split("\n## ", 1)
            after = f"\n## {after_parts[1]}" if len(after_parts) > 1 else ""
            new_body = f"{before}\n{identity_section}{after}".strip()
        elif existing_body:
            # Prepend Identity section before existing content
            new_body = f"{identity_section}\n\n{existing_body}".strip()
        else:
            # Just Identity section
            new_body = identity_section

        content = build_memory_document(
            name="User Profile",
            description=f"User identity: {display_name}" if display_name else "User profile information",
            mem_type="profile",
            body=new_body if new_body else "No profile information yet.",
        )

        memory_path.write_text(content, encoding="utf-8")
        logger.debug("User profile synced to global memory: %s", memory_path)
    except Exception as exc:
        # Don't fail the API call if memory write fails
        logger.warning("Failed to sync user profile to global memory: %s", exc)


async def handle_update_profile(request: web.Request) -> web.Response:
    """PUT /api/config/profile — persist user display name and about."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    config = get_hive_config()
    profile = config.get("user_profile", {})
    if "displayName" in body:
        profile["displayName"] = str(body["displayName"]).strip()
    if "about" in body:
        profile["about"] = str(body["about"]).strip()
    if body.get("theme") in ("light", "dark"):
        profile["theme"] = body["theme"]
    if body.get("density") in ("spacious", "compact"):
        profile["density"] = body["density"]
    # prompt_library_sort: partial merge — caller may send just {my} or just
    # {community}; unknown keys / invalid values are dropped. Note
    # _normalize_prompt_sort returns None when nothing is stored yet, so
    # the merge has to start from a fresh dict on first write.
    if isinstance(body.get("prompt_library_sort"), dict):
        current = _normalize_prompt_sort(profile.get("prompt_library_sort")) or {}
        incoming = body["prompt_library_sort"]
        for k in ("my", "community"):
            v = incoming.get(k)
            if isinstance(v, str) and v in _PROMPT_SORT_KEYS:
                current[k] = v
        if current:
            profile["prompt_library_sort"] = current
    config["user_profile"] = profile
    _write_config_atomic(config)

    # Sync to global memory (profile type)
    _update_user_profile_memory(profile.get("displayName", ""), profile.get("about", ""))

    logger.info("User profile updated: displayName=%s", profile.get("displayName", ""))
    return web.json_response(
        {
            "displayName": profile.get("displayName", ""),
            "about": profile.get("about", ""),
            "theme": profile.get("theme", ""),
            "density": profile.get("density", ""),
            "prompt_library_sort": _normalize_prompt_sort(profile.get("prompt_library_sort")),
        }
    )


async def handle_get_models(request: web.Request) -> web.Response:
    """GET /api/config/models — curated provider→models list."""
    return web.json_response({"models": MODELS_CATALOGUE})


# ------------------------------------------------------------------
# Global sentinel tuning block
# ------------------------------------------------------------------


async def handle_get_sentinel_config(request: web.Request) -> web.Response:
    """GET /api/config/sentinel — the global sentinel tuning block.

    Per-colony opt-in/routing lives in colonies/<id>/notifications.json
    (routes_sentinel); this is only the user-level tuning defaults. Used
    by the desktop vm-sync loop to mirror the block onto the workspace VM.
    """
    return web.json_response({"sentinel": get_hive_config().get("sentinel") or {}})


async def handle_update_sentinel_config(request: web.Request) -> web.Response:
    """PUT /api/config/sentinel — replace the global sentinel block."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    block = body.get("sentinel", body)
    if not isinstance(block, dict):
        return web.json_response({"error": "sentinel must be an object"}, status=400)

    config = get_hive_config()
    if block:
        config["sentinel"] = block
    else:
        config.pop("sentinel", None)
    _write_config_atomic(config)

    # Wake the manager so new tuning applies without a restart — same
    # pattern as routes_sentinel's per-colony config save.
    try:
        from framework.sentinel.manager import get_sentinel_manager

        mgr = get_sentinel_manager()
        if mgr is not None:
            mgr.refresh_listeners()
    except Exception:
        logger.debug("sentinel: refresh_listeners after global config save failed", exc_info=True)

    return web.json_response({"sentinel": block})


# ------------------------------------------------------------------
# Global feature flags (desktop Developer options)
# ------------------------------------------------------------------

# Whitelisted top-level boolean keys in configuration.json that the
# features endpoint may read/write. Keep this in sync with the getters
# in framework.config (e.g. get_adaptive_tool_budget_enabled).
_FEATURE_KEYS = ("adaptive_tool_budget", "email_senders")


def _apply_adaptive_budget_flag(request: web.Request, enabled: bool) -> int:
    """Hot-apply the adaptive-budget flag to running colony runtimes.

    Returns the number of colonies flipped. Skips colonies whose
    metadata.json pins ``adaptive_tool_budget`` explicitly — the
    per-colony override beats the global toggle, matching the resolution
    order at session start (session_manager._start_queen).

    Note: disabling stops sampling and new clamps immediately, but
    workers already clamped keep their shrunk budget (the AgentLoop
    setter is deliberately shrink-only); resume-with-raised-budget is
    the recovery path for those.
    """
    manager = request.app["manager"]
    applied = 0
    for session in manager.list_sessions():
        colony = getattr(session, "colony", None)
        if colony is None:
            continue
        colony_id = getattr(session, "colony_id", None)
        if colony_id:
            try:
                from framework.config import COLONIES_DIR

                meta_path = COLONIES_DIR / colony_id / "metadata.json"
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(meta.get("adaptive_tool_budget"), bool):
                        continue  # per-colony pin wins
            except Exception:
                logger.debug("features: metadata check failed for colony %s", colony_id, exc_info=True)
        cfg = getattr(colony, "_config", None)
        if cfg is not None and getattr(cfg, "adaptive_tool_budget", None) is not None and cfg.adaptive_tool_budget != enabled:
            cfg.adaptive_tool_budget = enabled
            applied += 1
    return applied


async def handle_get_features(request: web.Request) -> web.Response:
    """GET /api/config/features — global feature flags (Developer options)."""
    from framework.config import (
        get_adaptive_tool_budget_enabled,
        get_email_senders_enabled,
    )

    return web.json_response(
        {
            "features": {
                "adaptive_tool_budget": get_adaptive_tool_budget_enabled(),
                "email_senders": get_email_senders_enabled(),
            }
        }
    )


async def handle_update_features(request: web.Request) -> web.Response:
    """PUT /api/config/features — set global feature flags.

    Persists whitelisted boolean keys top-level in configuration.json
    (picked up by every NEW session, since get_hive_config re-reads the
    file) and hot-applies to RUNNING colony runtimes — same
    write-then-apply shape as the sentinel and LLM config routes.
    HIVE_ADAPTIVE_TOOL_BUDGET env, when set, still wins for new sessions
    (see config.get_adaptive_tool_budget_enabled).
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    block = body.get("features", body)
    if not isinstance(block, dict):
        return web.json_response({"error": "features must be an object"}, status=400)

    updates: dict[str, bool] = {}
    for key in _FEATURE_KEYS:
        if key in block:
            if not isinstance(block[key], bool):
                return web.json_response({"error": f"{key} must be a boolean"}, status=400)
            updates[key] = block[key]
    if not updates:
        return web.json_response({"error": f"No known feature keys. Supported: {', '.join(_FEATURE_KEYS)}"}, status=400)

    config = get_hive_config()
    config.update(updates)
    _write_config_atomic(config)

    colonies_applied = 0
    if "adaptive_tool_budget" in updates:
        try:
            colonies_applied = _apply_adaptive_budget_flag(request, updates["adaptive_tool_budget"])
        except Exception:
            logger.debug("features: hot-apply of adaptive_tool_budget failed (non-fatal)", exc_info=True)

    # Senders can't be hot-applied: the tools are registered when an MCP
    # subprocess spawns, so flipping this only changes the tool set of
    # sessions started from here on. Republish the env var the hive_tools
    # server reads, so those new spawns see the new value without waiting
    # for a runtime restart.
    if "email_senders" in updates:
        from framework.config import sync_email_senders_env

        sync_email_senders_env(updates["email_senders"])

    logger.info("features: updated %s (colonies hot-applied: %d)", updates, colonies_applied)
    return web.json_response({"features": updates, "colonies_applied": colonies_applied})


# ------------------------------------------------------------------
# User avatar
# ------------------------------------------------------------------

MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB
_ALLOWED_AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


async def handle_upload_user_avatar(request: web.Request) -> web.Response:
    """POST /api/config/profile/avatar — upload user profile picture."""
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "avatar":
        return web.json_response({"error": "Expected a file field named 'avatar'"}, status=400)

    content_type = getattr(field, "content_type", None) or field.headers.get("Content-Type", "")
    ext = _ALLOWED_AVATAR_TYPES.get(content_type)
    if not ext:
        return web.json_response(
            {"error": f"Unsupported image type: {content_type}. Use JPEG, PNG, or WebP."},
            status=400,
        )

    data = bytearray()
    while True:
        chunk = await field.read_chunk(8192)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_AVATAR_BYTES:
            return web.json_response({"error": "Image too large. Maximum size is 2 MB."}, status=400)

    if not data:
        return web.json_response({"error": "Empty file"}, status=400)

    # Remove existing avatar files
    for existing in HIVE_CONFIG_FILE.parent.glob("avatar.*"):
        existing.unlink(missing_ok=True)

    avatar_path = HIVE_CONFIG_FILE.parent / f"avatar{ext}"
    avatar_path.write_bytes(data)
    logger.info("User avatar uploaded: %s (%d bytes)", avatar_path.name, len(data))
    return web.json_response({"avatar_url": "/api/config/profile/avatar"})


async def handle_get_user_avatar(request: web.Request) -> web.Response:
    """GET /api/config/profile/avatar — serve user profile picture."""
    for ext in _ALLOWED_AVATAR_TYPES.values():
        avatar_path = HIVE_CONFIG_FILE.parent / f"avatar{ext}"
        if avatar_path.exists():
            return web.FileResponse(avatar_path, headers={"Cache-Control": "public, max-age=3600"})
    return web.json_response({"error": "No avatar found"}, status=404)


# ------------------------------------------------------------------
# Route registration
# ------------------------------------------------------------------
# Social rate limits
# ------------------------------------------------------------------


async def handle_get_rate_limits(request: web.Request) -> web.Response:
    """GET /api/config/rate-limits — current effective rate limits."""
    from framework.rate_limiter import get_all_limits

    return web.json_response({"limits": get_all_limits()})


async def handle_update_rate_limits(request: web.Request) -> web.Response:
    """PUT /api/config/rate-limits — update user overrides.

    Body: ``{"limits": {"linkedin.invite.daily": 20, ...}}``

    Keys are ``<platform>.<action>.<window>`` where window is
    ``daily`` or ``weekly``.  Values are clamped to the hard ceiling
    defined in ``rate_limiter._LIMITS``.
    """
    from framework.rate_limiter import _LIMITS

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    incoming = body.get("limits")
    if not isinstance(incoming, dict):
        return web.json_response({"error": "limits must be an object"}, status=400)

    # Validate each key. Values above the ceiling are allowed but flagged.
    cleaned: dict[str, int] = {}
    warnings: list[str] = []
    for key, value in incoming.items():
        parts = key.split(".")
        if len(parts) != 3:
            continue
        platform, action, window = parts
        if window not in ("hourly", "daily", "weekly"):
            continue
        entry = _LIMITS.get((platform, action))
        if entry is None:
            continue
        ceiling = entry.get(f"{window}_max")
        try:
            val = int(value)
        except (TypeError, ValueError):
            continue
        if val < 1:
            val = 1
        if ceiling is not None and val > ceiling:
            warnings.append(
                f"{platform}.{action}.{window}={val} exceeds recommended max of {ceiling}. High values increase the risk of account bans."
            )
        cleaned[key] = val

    config = get_hive_config()
    existing = config.get("rate_limits", {})
    if isinstance(existing, dict):
        existing.update(cleaned)
    else:
        existing = cleaned
    config["rate_limits"] = existing
    _write_config_atomic(config)

    from framework.rate_limiter import get_all_limits

    logger.info("rate_limits: updated %s", cleaned)
    resp: dict[str, Any] = {"limits": get_all_limits()}
    if warnings:
        resp["warnings"] = warnings
    return web.json_response(resp)


# ------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Provider slots — the UI is a verbatim editor over configuration.json's
# llm / worker_llm / vision_fallback sections. No parallel representation,
# no library, no sync: read = the section as stored, write = the section
# as typed. Absolute accuracy by construction.
# ---------------------------------------------------------------------------

_ROLE_SECTIONS = ("llm", "worker_llm", "vision_fallback")


async def handle_get_llm_sections(request: web.Request) -> web.Response:
    """GET /api/config/llm-sections — the three provider slots, verbatim."""
    cfg = get_hive_config()
    return web.json_response(
        {role: (cfg.get(role) or None) for role in _ROLE_SECTIONS}
    )


async def _write_role_section(
    request: web.Request, role: str, section: dict, validate: bool
) -> web.Response:
    """Validate + commit one provider section into a slot, verbatim.

    Shared by the direct slot editor (PUT /llm-sections) and the library
    apply endpoint — both paths must behave identically: same health check,
    same verbatim write, same hot-swap when the main slot changes.
    """
    if not str(section.get("model") or "").strip():
        return web.json_response({"error": "'model' is required"}, status=400)

    provider = str(section.get("provider") or "openai")
    api_base = str(section.get("api_base") or "").strip() or None
    api_key = str(section.get("api_key") or "")
    if not api_key:
        env_var = section.get("api_key_env_var")
        if env_var:
            api_key = os.environ.get(str(env_var), "")

    if validate and api_key and api_base:
        check = await _validate_provider_key(
            provider, api_key, api_base=api_base, model=str(section["model"])
        )
        if check.get("valid") is False:
            return web.json_response(
                {"error": f"Key check failed against {api_base}: "
                          f"{check.get('message', 'unknown error')}"},
                status=400,
            )

    config = get_hive_config()
    config[role] = section  # verbatim — the file mirrors the editor exactly
    _write_config_atomic(config)

    swapped = 0
    if role == "llm":
        full_model = f"{provider}/{section['model']}"
        swapped = _hot_swap_sessions(
            request, full_model, api_key=api_key or None, api_base=api_base
        )
    logger.info(
        "Provider slot %s written: %s/%s @ %s, hot-swapped %d session(s)",
        role,
        provider,
        section.get("model"),
        api_base,
        swapped,
    )
    return web.json_response(
        {"role": role, "section": section, "sessions_swapped": swapped}
    )


async def handle_put_llm_section(request: web.Request) -> web.Response:
    """PUT /api/config/llm-sections — write ONE slot verbatim.

    Body: ``{"role": r, "section": {...} | null, "validate"?: true}``.
    ``section: null`` clears worker_llm / vision_fallback (llm cannot be
    cleared — the runtime always needs a main model). When the section
    carries an api_key + api_base and ``validate`` isn't false, the key is
    health-checked against the endpoint before committing. The section is
    stored exactly as given — unknown keys included.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    role = str(body.get("role") or "")
    if role not in _ROLE_SECTIONS:
        return web.json_response(
            {"error": "'role' must be llm | worker_llm | vision_fallback"},
            status=400,
        )
    section = body.get("section", None)

    if section is None:
        if role == "llm":
            return web.json_response(
                {"error": "The llm slot cannot be cleared - the runtime "
                          "always needs a main model."},
                status=400,
            )
        config = get_hive_config()
        if role in config:
            config.pop(role, None)
            _write_config_atomic(config)
        logger.info("Provider slot cleared: %s", role)
        return web.json_response({"role": role, "section": None})

    if not isinstance(section, dict):
        return web.json_response(
            {"error": "'section' must be a JSON object or null"}, status=400
        )
    return await _write_role_section(
        request, role, section, validate=bool(body.get("validate", True))
    )


# ---------------------------------------------------------------------------
# Provider library — named vendor configs saved under "provider_library" in
# configuration.json. A library entry is the same verbatim section shape as a
# slot; applying one COPIES it into the slot (no reference indirection), so
# the runtime getters and the slots' verbatim contract stay untouched.
# ---------------------------------------------------------------------------


def _get_provider_library() -> dict[str, dict]:
    lib = get_hive_config().get("provider_library")
    if not isinstance(lib, dict):
        return {}
    return {str(k): v for k, v in lib.items() if isinstance(v, dict)}


async def handle_get_provider_library(request: web.Request) -> web.Response:
    """GET /api/config/provider-library — saved vendor configs, verbatim."""
    return web.json_response({"library": _get_provider_library()})


async def handle_put_provider_library(request: web.Request) -> web.Response:
    """PUT /api/config/provider-library — save or delete ONE library entry.

    Body: ``{"name": n, "section": {...} | null}``. ``section: null``
    deletes the entry. No health check here — a stored config may hold a
    key for an endpoint that isn't reachable right now; validation runs
    when the entry is applied to a slot.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    name = str(body.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "'name' is required"}, status=400)
    section = body.get("section", None)

    config = get_hive_config()
    library = config.get("provider_library")
    if not isinstance(library, dict):
        library = {}

    if section is None:
        library.pop(name, None)
        if library:
            config["provider_library"] = library
        else:
            config.pop("provider_library", None)
        _write_config_atomic(config)
        logger.info("Provider library entry deleted: %s", name)
        return web.json_response({"name": name, "section": None})

    if not isinstance(section, dict):
        return web.json_response(
            {"error": "'section' must be a JSON object or null"}, status=400
        )
    if not str(section.get("model") or "").strip():
        return web.json_response({"error": "'model' is required"}, status=400)

    library[name] = section  # verbatim, unknown keys included
    config["provider_library"] = library
    _write_config_atomic(config)
    logger.info(
        "Provider library entry saved: %s (%s/%s)",
        name,
        section.get("provider"),
        section.get("model"),
    )
    return web.json_response({"name": name, "section": section})


async def handle_apply_provider_library(request: web.Request) -> web.Response:
    """POST /api/config/provider-library/apply — copy a library entry into a slot.

    Body: ``{"name": n, "role": r, "validate"?: true}``. The entry is
    written into the slot verbatim through the same path as the direct
    slot editor: health-checked (unless ``validate`` is false) and
    hot-swapped into running sessions when the main llm slot changes.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    role = str(body.get("role") or "")
    if role not in _ROLE_SECTIONS:
        return web.json_response(
            {"error": "'role' must be llm | worker_llm | vision_fallback"},
            status=400,
        )
    name = str(body.get("name") or "").strip()
    section = _get_provider_library().get(name)
    if section is None:
        return web.json_response(
            {"error": f"No provider library entry named '{name}'"}, status=404
        )
    return await _write_role_section(
        request, role, section, validate=bool(body.get("validate", True))
    )


# ---------------------------------------------------------------------------
# External skill sources — configuration.json "external_skills", verbatim.
# Extra skill roots from other agent ecosystems (Claude Code ~/.claude/skills,
# Codex ~/.codex/skills, ...); SKILL.md is a cross-agent standard.
# ---------------------------------------------------------------------------


def _resolve_external_skills(paths: list) -> list[dict]:
    """Resolve each configured path: expansion, existence, parsed-skill count."""
    from framework.skills.discovery import SkillDiscovery

    d = SkillDiscovery()
    out: list[dict] = []
    for raw in paths:
        entry: dict = {"path": raw}
        try:
            ext = Path(os.path.expandvars(str(raw))).expanduser()
            entry["resolved"] = str(ext)
            entry["exists"] = ext.is_dir()
            entry["skills"] = (
                len(d._scan_scope(ext, "user")) if ext.is_dir() else 0
            )
        except Exception as exc:
            entry["exists"] = False
            entry["skills"] = 0
            entry["error"] = str(exc)
        out.append(entry)
    return out


# Well-known per-agent skill roots (all follow the cross-agent SKILL.md
# standard). Probed for auto-discovery suggestions; only dirs that exist
# AND contain at least one parseable skill are surfaced. ~/.agents/skills
# is absent on purpose — Hive scans it natively already.
_KNOWN_AGENT_SKILL_DIRS = (
    "~/.claude/skills",     # Claude Code
    "~/.codex/skills",      # OpenAI Codex CLI
    "~/.cursor/skills",     # Cursor
    "~/.openclaw/skills",   # OpenClaw
    "~/.gemini/skills",     # Gemini CLI
)


def _suggest_external_skills(configured: list[str]) -> list[dict]:
    """Probe known agent skill dirs not yet configured; keep real finds only."""
    def _norm(raw: str) -> str:
        try:
            return str(Path(os.path.expandvars(raw)).expanduser().resolve())
        except Exception:
            return raw

    have = {_norm(p) for p in configured}
    out: list[dict] = []
    for cand in _KNOWN_AGENT_SKILL_DIRS:
        if _norm(cand) in have:
            continue
        [r] = _resolve_external_skills([cand])
        if r.get("exists") and r.get("skills", 0) > 0:
            out.append(r)
    return out


async def handle_get_external_skills(request: web.Request) -> web.Response:
    """GET /api/config/external-skills — configured paths + resolution status,
    plus auto-discovered suggestions from known agent ecosystems."""
    paths = get_hive_config().get("external_skills") or []
    paths = [p for p in paths if isinstance(p, str)]
    # Off-loop: both helpers do full recursive directory walks + SKILL.md
    # parses (up to ~10 roots including the auto-discovery probes).
    resolved = await asyncio.to_thread(_resolve_external_skills, paths)
    suggestions = await asyncio.to_thread(_suggest_external_skills, paths)
    return web.json_response(
        {"paths": paths, "resolved": resolved, "suggestions": suggestions}
    )


async def handle_put_external_skills(request: web.Request) -> web.Response:
    """PUT /api/config/external-skills — write the path list verbatim.

    Body: {"paths": ["~/.claude/skills", ...]}. Non-existent paths are
    allowed (saved with a warning status) — the directory may appear later.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    paths = body.get("paths")
    if not isinstance(paths, list) or not all(isinstance(x, str) for x in paths):
        return web.json_response(
            {"error": "'paths' must be a list of strings"}, status=400
        )
    paths = [x.strip() for x in paths if x.strip()]
    config = get_hive_config()
    if paths:
        config["external_skills"] = paths
    else:
        config.pop("external_skills", None)
    _write_config_atomic(config)
    logger.info("external_skills updated: %s", paths)
    resolved = await asyncio.to_thread(_resolve_external_skills, paths)
    return web.json_response({"paths": paths, "resolved": resolved})


def register_routes(app: web.Application) -> None:
    """Register LLM config routes."""
    app.router.add_get("/api/config/llm", handle_get_llm_config)
    app.router.add_get("/api/config/llm-sections", handle_get_llm_sections)
    app.router.add_get("/api/config/external-skills", handle_get_external_skills)
    app.router.add_put("/api/config/external-skills", handle_put_external_skills)
    app.router.add_put("/api/config/llm-sections", handle_put_llm_section)
    app.router.add_get("/api/config/provider-library", handle_get_provider_library)
    app.router.add_put("/api/config/provider-library", handle_put_provider_library)
    app.router.add_post("/api/config/provider-library/apply", handle_apply_provider_library)
    app.router.add_put("/api/config/llm", handle_update_llm_config)
    app.router.add_get("/api/config/models", handle_get_models)
    app.router.add_get("/api/config/sentinel", handle_get_sentinel_config)
    app.router.add_put("/api/config/sentinel", handle_update_sentinel_config)
    app.router.add_get("/api/config/features", handle_get_features)
    app.router.add_put("/api/config/features", handle_update_features)
    app.router.add_get("/api/config/rate-limits", handle_get_rate_limits)
    app.router.add_put("/api/config/rate-limits", handle_update_rate_limits)
    app.router.add_get("/api/config/profile", handle_get_profile)
    app.router.add_put("/api/config/profile", handle_update_profile)
    app.router.add_post("/api/config/profile/avatar", handle_upload_user_avatar)
    app.router.add_get("/api/config/profile/avatar", handle_get_user_avatar)
