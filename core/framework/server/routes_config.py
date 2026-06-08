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
    """Hot-swap the LLM on all running sessions. Returns count of swapped sessions.

    Also refreshes the SessionManager's default model so that subsequent
    one-shot LLM consumers (e.g. /messages/classify, new session bootstrap)
    pick up the new provider/model instead of the stale startup override.
    """
    from framework.server.session_manager import SessionManager

    manager: SessionManager = request.app["manager"]
    manager._model = full_model
    swapped = 0
    for session in manager.list_sessions():
        llm_provider = getattr(session, "llm", None)
        if llm_provider and hasattr(llm_provider, "reconfigure"):
            llm_provider.reconfigure(full_model, api_key=api_key, api_base=api_base)
            swapped += 1
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
                return check_anthropic_compatible(api_key, api_base.rstrip("/") + "/v1/messages", "Kimi")
            if api_base and pid == "hive":
                return check_anthropic_compatible(api_key, api_base.rstrip("/") + "/v1/messages", "Hive")
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

    return await asyncio.get_event_loop().run_in_executor(None, _check)


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
        }
    )


async def handle_update_llm_config(request: web.Request) -> web.Response:
    """PUT /api/config/llm — set active provider + model, hot-swap running sessions.

    Accepts two modes:
    1. API key mode: {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
    2. Subscription mode: {"subscription": "claude_code"} (uses preset model)
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

        check = await _validate_provider_key(provider, token, api_base=api_base)
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


async def handle_get_profile(request: web.Request) -> web.Response:
    """GET /api/config/profile — user display name and about."""
    profile = get_hive_config().get("user_profile", {})
    return web.json_response(
        {
            "displayName": profile.get("displayName", ""),
            "about": profile.get("about", ""),
            "theme": profile.get("theme", ""),
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
        }
    )


async def handle_get_models(request: web.Request) -> web.Response:
    """GET /api/config/models — curated provider→models list."""
    return web.json_response({"models": MODELS_CATALOGUE})


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


def register_routes(app: web.Application) -> None:
    """Register LLM config routes."""
    app.router.add_get("/api/config/llm", handle_get_llm_config)
    app.router.add_put("/api/config/llm", handle_update_llm_config)
    app.router.add_get("/api/config/models", handle_get_models)
    app.router.add_get("/api/config/profile", handle_get_profile)
    app.router.add_put("/api/config/profile", handle_update_profile)
    app.router.add_post("/api/config/profile/avatar", handle_upload_user_avatar)
    app.router.add_get("/api/config/profile/avatar", handle_get_user_avatar)
