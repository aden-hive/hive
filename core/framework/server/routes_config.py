"""LLM configuration routes — BYOK key management, subscriptions, and model selection.

Routes:
- GET  /api/config/llm           — current active LLM configuration
- PUT  /api/config/llm           — update active provider + model (hot-swaps running sessions)
- GET  /api/config/models        — curated provider→models list
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from aiohttp import web

from framework.config import (
    HIVE_CONFIG_FILE,
    OPENROUTER_API_BASE,
    _PROVIDER_CRED_MAP,
    get_hive_config,
)
from framework.agents.queen.queen_memory_v2 import (
    global_memory_dir,
    build_memory_document,
)

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
}

# ---------------------------------------------------------------------------
# Subscription metadata (mirrors quickstart.sh subscription modes)
# ---------------------------------------------------------------------------

SUBSCRIPTIONS: list[dict] = [
    {
        "id": "claude_code",
        "name": "Claude Code Subscription",
        "description": "Use your Claude Max/Pro plan",
        "provider": "anthropic",
        "flag": "use_claude_code_subscription",
        "default_model": "claude-sonnet-4-20250514",
    },
    {
        "id": "codex",
        "name": "OpenAI Codex Subscription",
        "description": "Use your Codex/ChatGPT Plus plan",
        "provider": "openai",
        "flag": "use_codex_subscription",
        "default_model": "gpt-5-mini",
        "api_base": "https://chatgpt.com/backend-api/codex",
    },
    {
        "id": "kimi_code",
        "name": "Kimi Code Subscription",
        "description": "Use your Kimi Code plan",
        "provider": "kimi",
        "flag": "use_kimi_code_subscription",
        "default_model": "kimi/moonshot-v1",
    },
    {
        "id": "antigravity",
        "name": "Antigravity Subscription",
        "description": "Use your Google/Gemini plan",
        "provider": "antigravity",
        "flag": "use_antigravity_subscription",
        "default_model": "antigravity/gemini-2.5-pro",
    },
]

# All subscription config flags
_ALL_SUBSCRIPTION_FLAGS = [s["flag"] for s in SUBSCRIPTIONS]

# Map subscription ID → subscription metadata
_SUBSCRIPTION_MAP = {s["id"]: s for s in SUBSCRIPTIONS}

# Model catalogue — mirrors quickstart.sh MODEL_CHOICES_*
MODELS_CATALOGUE: dict[str, list[dict]] = {
    "anthropic": [
        {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5 - Fast + cheap", "recommended": True, "max_tokens": 8192, "max_context_tokens": 180000},
        {"id": "claude-sonnet-4-20250514", "label": "Sonnet 4 - Fast + capable", "recommended": False, "max_tokens": 8192, "max_context_tokens": 180000},
        {"id": "claude-sonnet-4-5-20250929", "label": "Sonnet 4.5 - Best balance", "recommended": False, "max_tokens": 16384, "max_context_tokens": 180000},
        {"id": "claude-opus-4-6", "label": "Opus 4.6 - Most capable", "recommended": False, "max_tokens": 32768, "max_context_tokens": 180000},
    ],
    "openai": [
        {"id": "gpt-5-mini", "label": "GPT-5 Mini - Fast + cheap", "recommended": True, "max_tokens": 16384, "max_context_tokens": 120000},
        {"id": "gpt-5.2", "label": "GPT-5.2 - Most capable", "recommended": False, "max_tokens": 16384, "max_context_tokens": 120000},
    ],
    "gemini": [
        {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash - Fast", "recommended": True, "max_tokens": 8192, "max_context_tokens": 900000},
        {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro - Best quality", "recommended": False, "max_tokens": 8192, "max_context_tokens": 900000},
    ],
    "groq": [
        {"id": "moonshotai/kimi-k2-instruct-0905", "label": "Kimi K2 - Best quality", "recommended": True, "max_tokens": 8192, "max_context_tokens": 120000},
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B - Fast reasoning", "recommended": False, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
    "cerebras": [
        {"id": "zai-glm-4.7", "label": "ZAI-GLM 4.7 - Best quality", "recommended": True, "max_tokens": 8192, "max_context_tokens": 120000},
        {"id": "qwen3-235b-a22b-instruct-2507", "label": "Qwen3 235B - Frontier reasoning", "recommended": False, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
    "minimax": [
        {"id": "MiniMax-M2.5", "label": "MiniMax-M2.5", "recommended": True, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
    "mistral": [
        {"id": "mistral-large-latest", "label": "Mistral Large", "recommended": True, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
    "together": [
        {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "label": "Llama 3.3 70B Turbo", "recommended": True, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "label": "DeepSeek Chat", "recommended": True, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
    "openrouter": [
        {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro", "recommended": True, "max_tokens": 8192, "max_context_tokens": 900000},
        {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash", "recommended": False, "max_tokens": 8192, "max_context_tokens": 900000},
        {"id": "anthropic/claude-sonnet-4", "label": "Claude Sonnet 4 (via OR)", "recommended": False, "max_tokens": 8192, "max_context_tokens": 180000},
        {"id": "deepseek/deepseek-r1", "label": "DeepSeek R1", "recommended": False, "max_tokens": 8192, "max_context_tokens": 120000},
    ],
}

# Default model per provider (matches quickstart DEFAULT_MODELS)
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5-mini",
    "minimax": "MiniMax-M2.5",
    "gemini": "gemini-3-flash-preview",
    "groq": "moonshotai/kimi-k2-instruct-0905",
    "cerebras": "zai-glm-4.7",
    "mistral": "mistral-large-latest",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "deepseek": "deepseek-chat",
    "openrouter": "google/gemini-2.5-pro",
}


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
    for m in MODELS_CATALOGUE.get(provider, []):
        if m["id"] == model_id:
            return m
    return None


def _write_config_atomic(config: dict) -> None:
    """Write config to ~/.hive/configuration.json atomically."""
    HIVE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(HIVE_CONFIG_FILE.parent), suffix=".tmp"
    )
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

    # Codex subscription
    try:
        from framework.loader.agent_loader import get_codex_token
        if get_codex_token():
            detected.append("codex")
    except Exception:
        pass

    # Kimi Code subscription
    try:
        from framework.loader.agent_loader import get_kimi_code_token
        if get_kimi_code_token():
            detected.append("kimi_code")
    except Exception:
        pass

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
    elif sub_id == "codex":
        from framework.loader.agent_loader import get_codex_token
        return get_codex_token()
    elif sub_id == "kimi_code":
        from framework.loader.agent_loader import get_kimi_code_token
        return get_kimi_code_token()
    elif sub_id == "antigravity":
        from framework.loader.agent_loader import get_antigravity_token
        return get_antigravity_token()
    return None


def _hot_swap_sessions(request: web.Request, full_model: str, api_key: str | None, api_base: str | None) -> int:
    """Hot-swap the LLM on all running sessions. Returns count of swapped sessions."""
    from framework.server.session_manager import SessionManager

    manager: SessionManager = request.app["manager"]
    swapped = 0
    for session in manager.list_sessions():
        llm_provider = getattr(session, "llm", None)
        if llm_provider and hasattr(llm_provider, "reconfigure"):
            llm_provider.reconfigure(full_model, api_key=api_key, api_base=api_base)
            swapped += 1
    return swapped


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

    # Subscription detection
    active_subscription = _get_active_subscription(llm)
    detected_subscriptions = _detect_subscriptions()

    return web.json_response({
        "provider": provider,
        "model": model,
        "has_api_key": has_key,
        "max_tokens": llm.get("max_tokens"),
        "max_context_tokens": llm.get("max_context_tokens"),
        "connected_providers": connected,
        "active_subscription": active_subscription,
        "detected_subscriptions": detected_subscriptions,
        "subscriptions": SUBSCRIPTIONS,
    })


async def handle_update_llm_config(request: web.Request) -> web.Response:
    """PUT /api/config/llm — set active provider + model, hot-swap running sessions.

    Accepts two modes:
    1. API key mode: {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
    2. Subscription mode: {"subscription": "claude_code", "model": "claude-sonnet-4-20250514"}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    subscription_id = body.get("subscription")

    if subscription_id:
        # ── Subscription mode ────────────────────────────────────────
        sub = _SUBSCRIPTION_MAP.get(subscription_id)
        if not sub:
            return web.json_response(
                {"error": f"Unknown subscription: {subscription_id}"}, status=400
            )

        model = body.get("model") or sub["default_model"]
        provider = sub["provider"]
        api_base = sub.get("api_base")

        # Look up token limits
        # Subscriptions use same models as their provider (e.g., claude_code → anthropic)
        model_info = _find_model_info(provider, model)
        if not model_info:
            # Try looking up in the mapped provider's catalogue
            for prov_id, models in MODELS_CATALOGUE.items():
                model_info = next((m for m in models if m["id"] == model), None)
                if model_info:
                    break
        max_tokens = model_info["max_tokens"] if model_info else 8192
        max_context_tokens = model_info["max_context_tokens"] if model_info else 120000

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

        # Hot-swap with subscription token
        token = _get_subscription_token(subscription_id)
        full_model = f"{provider}/{model}"
        swapped = _hot_swap_sessions(request, full_model, api_key=token, api_base=api_base)

        logger.info(
            "LLM config updated: subscription=%s model=%s, hot-swapped %d session(s)",
            subscription_id, model, swapped,
        )

        return web.json_response({
            "provider": provider,
            "model": model,
            "has_api_key": token is not None,
            "max_tokens": max_tokens,
            "max_context_tokens": max_context_tokens,
            "sessions_swapped": swapped,
            "active_subscription": subscription_id,
        })

    else:
        # ── API key mode ─────────────────────────────────────────────
        provider = body.get("provider")
        model = body.get("model")
        if not provider or not model:
            return web.json_response(
                {"error": "Both 'provider' and 'model' are required"}, status=400
            )

        # Look up token limits from catalogue
        model_info = _find_model_info(provider, model)
        max_tokens = model_info["max_tokens"] if model_info else 8192
        max_context_tokens = model_info["max_context_tokens"] if model_info else 120000

        # Determine env var and api_base
        env_var = PROVIDER_ENV_VARS.get(provider.lower(), "")
        api_base = _get_api_base_for_provider(provider)

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

        # Hot-swap all running sessions
        api_key = _resolve_api_key(provider, request)
        full_model = f"{provider}/{model}"
        swapped = _hot_swap_sessions(request, full_model, api_key=api_key, api_base=api_base)

        logger.info(
            "LLM config updated: provider=%s model=%s, hot-swapped %d session(s)",
            provider, model, swapped,
        )

        return web.json_response({
            "provider": provider,
            "model": model,
            "has_api_key": api_key is not None,
            "max_tokens": max_tokens,
            "max_context_tokens": max_context_tokens,
            "sessions_swapped": swapped,
            "active_subscription": None,
        })


async def handle_get_profile(request: web.Request) -> web.Response:
    """GET /api/config/profile — user display name and about."""
    profile = get_hive_config().get("user_profile", {})
    return web.json_response({
        "displayName": profile.get("displayName", ""),
        "about": profile.get("about", ""),
        "theme": profile.get("theme", ""),
    })


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
    config["user_profile"] = profile
    _write_config_atomic(config)

    # Sync to global memory (profile type)
    _update_user_profile_memory(
        profile.get("displayName", ""),
        profile.get("about", "")
    )

    logger.info("User profile updated: displayName=%s", profile.get("displayName", ""))
    return web.json_response({
        "displayName": profile.get("displayName", ""),
        "about": profile.get("about", ""),
        "theme": profile.get("theme", ""),
    })


async def handle_get_models(request: web.Request) -> web.Response:
    """GET /api/config/models — curated provider→models list."""
    return web.json_response({"models": MODELS_CATALOGUE})


# ------------------------------------------------------------------
# Route registration
# ------------------------------------------------------------------


def register_routes(app: web.Application) -> None:
    """Register LLM config routes."""
    app.router.add_get("/api/config/llm", handle_get_llm_config)
    app.router.add_put("/api/config/llm", handle_update_llm_config)
    app.router.add_get("/api/config/models", handle_get_models)
    app.router.add_get("/api/config/profile", handle_get_profile)
    app.router.add_put("/api/config/profile", handle_update_profile)
