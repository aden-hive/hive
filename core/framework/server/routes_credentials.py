"""Credential CRUD routes."""

import asyncio
import logging
import os

from aiohttp import web
from pydantic import SecretStr

from framework.credentials.models import CredentialDecryptionError, CredentialKey, CredentialObject
from framework.credentials.store import CredentialStore
from framework.server.app import validate_agent_path

logger = logging.getLogger(__name__)

_llm_key_providers_cache: dict | None = None


def _get_llm_key_providers() -> dict:
    """Lazily load the PROVIDERS dict from scripts/check_llm_key.py (cached)."""
    global _llm_key_providers_cache
    if _llm_key_providers_cache is None:
        import importlib.util
        from pathlib import Path as _Path

        script = _Path(__file__).resolve().parents[3] / "scripts" / "check_llm_key.py"
        if not script.exists():
            logger.warning("check_llm_key.py not found at %s — key validation disabled", script)
            _llm_key_providers_cache = {}
            return _llm_key_providers_cache
        spec = importlib.util.spec_from_file_location("check_llm_key", script)
        if spec is None or spec.loader is None:
            logger.warning("Failed to load spec for %s — key validation disabled", script)
            _llm_key_providers_cache = {}
            return _llm_key_providers_cache
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _llm_key_providers_cache = mod.PROVIDERS
    return _llm_key_providers_cache


def _get_store(request: web.Request) -> CredentialStore:
    return request.app["credential_store"]


def _invalidate_queen_credentials_cache(request: web.Request) -> None:
    """Force every live Queen session to rebuild its ambient credentials block.

    Called after credential save/delete so newly added or removed integrations
    appear in the Queen's prompt on her next turn instead of waiting for the
    cache TTL to expire.
    """
    manager = request.app.get("manager")
    if manager is None:
        return
    sessions = getattr(manager, "_sessions", None)
    if not sessions:
        return
    for session in sessions.values():
        phase_state = getattr(session, "phase_state", None)
        if phase_state is None:
            continue
        provider = getattr(phase_state, "credentials_prompt_provider", None)
        invalidate = getattr(provider, "invalidate", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                logger.debug(
                    "Credentials cache invalidate failed for session %s",
                    getattr(session, "id", "?"),
                    exc_info=True,
                )


def _credential_to_dict(cred: CredentialObject) -> dict:
    """Serialize a CredentialObject to JSON — never include secret values."""
    return {
        "credential_id": cred.id,
        "credential_type": str(cred.credential_type),
        "key_names": list(cred.keys.keys()),
        "created_at": cred.created_at.isoformat() if cred.created_at else None,
        "updated_at": cred.updated_at.isoformat() if cred.updated_at else None,
    }


def _is_available_for_specs(store: CredentialStore, credential_id: str) -> bool:
    """Best-effort availability check for the repair UI.

    The credential settings page must stay reachable even when an encrypted
    file was written with the wrong key or is otherwise unreadable.
    """
    try:
        return store.is_available(credential_id)
    except CredentialDecryptionError as exc:
        logger.warning("Credential '%s' is unreadable; marking unavailable in specs: %s", credential_id, exc)
        return False


async def handle_list_credentials(request: web.Request) -> web.Response:
    """GET /api/credentials — list all credential metadata (no secrets)."""
    store = _get_store(request)
    cred_ids = store.list_credentials()
    credentials = []
    unreadable = []
    for cid in cred_ids:
        try:
            cred = store.get_credential(cid, refresh_if_needed=False)
        except CredentialDecryptionError as exc:
            logger.warning("Credential '%s' is unreadable while listing credentials: %s", cid, exc)
            unreadable.append(cid)
            continue
        if cred:
            credentials.append(_credential_to_dict(cred))
    return web.json_response({"credentials": credentials, "unreadable_credentials": unreadable})


async def handle_get_credential(request: web.Request) -> web.Response:
    """GET /api/credentials/{credential_id} — get single credential metadata."""
    credential_id = request.match_info["credential_id"]
    store = _get_store(request)
    try:
        cred = store.get_credential(credential_id, refresh_if_needed=False)
    except CredentialDecryptionError:
        return web.json_response(
            {
                "error": f"Credential '{credential_id}' could not be decrypted",
                "credential_id": credential_id,
                "recoverable": True,
            },
            status=409,
        )
    if cred is None:
        return web.json_response({"error": f"Credential '{credential_id}' not found"}, status=404)
    return web.json_response(_credential_to_dict(cred))


async def handle_save_credential(request: web.Request) -> web.Response:
    """POST /api/credentials — store a credential.

    Body: {"credential_id": "...", "keys": {"key_name": "value", ...}}
    """
    body = await request.json()

    credential_id = body.get("credential_id")
    keys = body.get("keys")

    if not credential_id or not keys or not isinstance(keys, dict):
        return web.json_response({"error": "credential_id and keys are required"}, status=400)

    # ADEN_API_KEY is stored in the encrypted store via key_storage module
    if credential_id == "aden_api_key":
        key = keys.get("api_key", "").strip()
        if not key:
            return web.json_response({"error": "api_key is required"}, status=400)

        from framework.credentials.key_storage import save_aden_api_key

        save_aden_api_key(key)

        # Immediately sync OAuth tokens from Aden (runs in executor because
        # _presync_aden_tokens makes blocking HTTP calls to the Aden server).
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS

            from framework.credentials.validation import _presync_aden_tokens

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _presync_aden_tokens, CREDENTIAL_SPECS)
        except Exception as exc:
            logger.warning("Aden token sync after key save failed: %s", exc)

        _invalidate_queen_credentials_cache(request)
        return web.json_response({"saved": "aden_api_key"}, status=201)

    store = _get_store(request)
    cred = CredentialObject(
        id=credential_id,
        keys={k: CredentialKey(name=k, value=SecretStr(v)) for k, v in keys.items()},
    )
    store.save_credential(cred)
    _invalidate_queen_credentials_cache(request)
    return web.json_response({"saved": credential_id}, status=201)


async def handle_delete_credential(request: web.Request) -> web.Response:
    """DELETE /api/credentials/{credential_id} — delete a credential."""
    credential_id = request.match_info["credential_id"]

    if credential_id == "aden_api_key":
        from framework.credentials.key_storage import delete_aden_api_key

        deleted = delete_aden_api_key()
        if not deleted:
            return web.json_response({"error": "Credential 'aden_api_key' not found"}, status=404)
        return web.json_response({"deleted": True})

    store = _get_store(request)
    deleted_from_store = store.delete_credential(credential_id)

    # Also clear the env var for this process so the key doesn't
    # reappear via the env-var fallback in _resolve_api_key().
    from framework.server.routes_config import PROVIDER_ENV_VARS

    env_var = PROVIDER_ENV_VARS.get(credential_id.lower())
    deleted_from_env = False
    if env_var and os.environ.pop(env_var, None) is not None:
        deleted_from_env = True

    if not deleted_from_store and not deleted_from_env:
        return web.json_response({"error": f"Credential '{credential_id}' not found"}, status=404)
    _invalidate_queen_credentials_cache(request)
    return web.json_response({"deleted": True})


async def handle_check_agent(request: web.Request) -> web.Response:
    """POST /api/credentials/check-agent — check and validate agent credentials.

    Uses the same ``validate_agent_credentials`` as agent startup:
    1. Presence — is the credential available (env, encrypted store, Aden)?
    2. Health check — does the credential actually work (lightweight HTTP call)?

    Body: {"agent_path": "...", "verify": true}
    """
    body = await request.json()
    agent_path = body.get("agent_path")
    verify = body.get("verify", True)

    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    try:
        agent_path = str(validate_agent_path(agent_path))
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    try:
        from framework.credentials.setup import load_agent_nodes
        from framework.credentials.validation import (
            ensure_credential_key_env,
            validate_agent_credentials,
        )

        # Load env vars from shell config (same as runtime startup)
        ensure_credential_key_env()

        nodes = load_agent_nodes(agent_path)
        result = validate_agent_credentials(nodes, verify=verify, raise_on_error=False, force_refresh=True)

        # If any credential needs Aden, include ADEN_API_KEY as a first-class row
        if any(c.aden_supported for c in result.credentials):
            aden_key_status = {
                "credential_name": "Aden Platform",
                "credential_id": "aden_api_key",
                "env_var": "ADEN_API_KEY",
                "description": "API key from the Developers tab in Settings",
                "help_url": "https://hive.adenhq.com/",
                "tools": [],
                "node_types": [],
                "available": result.has_aden_key,
                "valid": None,
                "validation_message": None,
                "direct_api_key_supported": True,
                "aden_supported": True,  # renders with "Authorize" button to open Aden
                "credential_key": "api_key",
            }
            required = [aden_key_status] + [_status_to_dict(c) for c in result.credentials]
        else:
            required = [_status_to_dict(c) for c in result.credentials]

        return web.json_response(
            {
                "required": required,
                "has_aden_key": result.has_aden_key,
            }
        )
    except Exception as e:
        logger.exception(f"Error checking agent credentials: {e}")
        return web.json_response(
            {"error": "Internal server error while checking credentials"},
            status=500,
        )


def _status_to_dict(c) -> dict:
    """Convert a CredentialStatus to the JSON dict expected by the frontend."""
    return {
        "credential_name": c.credential_name,
        "credential_id": c.credential_id,
        "env_var": c.env_var,
        "description": c.description,
        "help_url": c.help_url,
        "tools": c.tools,
        "node_types": c.node_types,
        "available": c.available,
        "direct_api_key_supported": c.direct_api_key_supported,
        "aden_supported": c.aden_supported,
        "credential_key": c.credential_key,
        "valid": c.valid,
        "validation_message": c.validation_message,
        "alternative_group": c.alternative_group,
    }


def _collect_accounts_by_provider() -> dict[str, list[dict]]:
    """Snapshot connected accounts grouped by provider (credential_id).

    Returns a dict mapping provider → list of account dicts with the
    fields the frontend needs to render per-account rows. Best-effort —
    returns {} if the adapter cannot be built.
    """
    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        adapter = CredentialStoreAdapter.default()
        grouped: dict[str, list[dict]] = {}
        for acct in adapter.get_all_account_info():
            provider = acct.get("provider", "")
            if not provider:
                continue
            grouped.setdefault(provider, []).append(
                {
                    "provider": provider,
                    "alias": acct.get("alias", ""),
                    "identity": acct.get("identity", {}) or {},
                    "source": acct.get("source", "aden"),
                    "credential_id": acct.get("credential_id", provider),
                }
            )
        return grouped
    except Exception:
        logger.debug("Failed to collect accounts for specs response", exc_info=True)
        return {}


async def handle_resync_credentials(request: web.Request) -> web.Response:
    """POST /api/credentials/resync — force-resync Aden OAuth tokens.

    Called by the frontend after the user completes an OAuth flow on
    hive.adenhq.com so the new account appears in Hive without waiting
    for a cache TTL. Returns the current connected-accounts snapshot so
    the caller can diff against what it had before opening the Aden tab.
    """
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        from framework.credentials.validation import _presync_aden_tokens, ensure_credential_key_env

        ensure_credential_key_env()

        if not os.environ.get("ADEN_API_KEY"):
            return web.json_response(
                {"error": "Aden API key not configured", "accounts_by_provider": {}},
                status=400,
            )

        loop = asyncio.get_running_loop()
        # _presync_aden_tokens makes blocking HTTP calls to the Aden server.
        await loop.run_in_executor(None, lambda: _presync_aden_tokens(CREDENTIAL_SPECS, force=True))

        _invalidate_queen_credentials_cache(request)

        accounts_by_provider = _collect_accounts_by_provider()
        return web.json_response(
            {
                "synced": True,
                "accounts_by_provider": accounts_by_provider,
            }
        )
    except Exception as exc:
        logger.exception("Error during credential resync: %s", exc)
        return web.json_response(
            {"error": "Internal server error during resync"},
            status=500,
        )


async def handle_list_specs(request: web.Request) -> web.Response:
    """GET /api/credentials/specs — list ALL credential specs with availability."""
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        from framework.credentials.storage import (
            CompositeStorage,
            EncryptedFileStorage,
            EnvVarStorage,
        )
        from framework.credentials.store import CredentialStore
        from framework.credentials.validation import _presync_aden_tokens, ensure_credential_key_env

        ensure_credential_key_env()

        has_aden_key = bool(os.environ.get("ADEN_API_KEY"))
        if has_aden_key:
            _presync_aden_tokens(CREDENTIAL_SPECS)

        # Build composite store (env → encrypted file)
        env_mapping = {(spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()}
        env_storage = EnvVarStorage(env_mapping=env_mapping)
        if os.environ.get("HIVE_CREDENTIAL_KEY"):
            storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
        else:
            storage = env_storage
        store = CredentialStore(storage=storage)

        # Snapshot accounts once — the adapter walks the same specs internally
        # and hits both Aden and local stores, so we reuse it for every row.
        accounts_by_provider = _collect_accounts_by_provider()

        specs = []
        any_aden = False
        for name, spec in CREDENTIAL_SPECS.items():
            cred_id = spec.credential_id or name
            if spec.aden_supported:
                any_aden = True
            accounts = accounts_by_provider.get(cred_id, [])
            # Pure-OAuth (Aden-only, no direct API key) credentials are
            # authoritative through Aden — the accounts list is the source of
            # truth. Local stores can hold stale cache entries after a remote
            # deletion, so trusting `store.is_available()` here would surface
            # ghost "Connected" rows with no accounts and no add affordance.
            if spec.aden_supported and not spec.direct_api_key_supported:
                available = len(accounts) > 0
            else:
                available = _is_available_for_specs(store, cred_id)
            specs.append(
                {
                    "credential_name": name,
                    "credential_id": cred_id,
                    "env_var": spec.env_var,
                    "description": spec.description,
                    "help_url": spec.help_url,
                    "api_key_instructions": spec.api_key_instructions,
                    "tools": spec.tools,
                    "aden_supported": spec.aden_supported,
                    "direct_api_key_supported": spec.direct_api_key_supported,
                    "credential_key": spec.credential_key,
                    "credential_group": spec.credential_group,
                    "available": available,
                    "accounts": accounts,
                }
            )

        # Include aden_api_key synthetic row if any spec uses Aden
        if any_aden:
            specs.insert(
                0,
                {
                    "credential_name": "Aden Platform",
                    "credential_id": "aden_api_key",
                    "env_var": "ADEN_API_KEY",
                    "description": "API key from the Developers tab in Settings",
                    "help_url": "https://hive.adenhq.com/",
                    "api_key_instructions": (
                        "1. Go to hive.adenhq.com\n2. Open Settings > Developers\n3. Copy your API key"
                    ),
                    "tools": [],
                    "aden_supported": True,
                    "direct_api_key_supported": True,
                    "credential_key": "api_key",
                    "credential_group": "",
                    "available": has_aden_key,
                },
            )

        return web.json_response({"specs": specs, "has_aden_key": has_aden_key})
    except Exception as e:
        logger.exception(f"Error listing credential specs: {e}")
        return web.json_response(
            {"error": "Internal server error while listing credential specs"},
            status=500,
        )


async def handle_validate_key(request: web.Request) -> web.Response:
    """POST /api/credentials/validate-key — health-check an LLM provider key.

    Body: {"provider_id": "anthropic", "api_key": "sk-..."}
    Returns: {"valid": bool|null, "message": str}

    Runs the same checks as ``quickstart.sh`` (scripts/check_llm_key.py)
    but in-process — no subprocess overhead.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    provider_id = body.get("provider_id", "").strip()
    api_key = body.get("api_key", "").strip()

    if not provider_id or not api_key:
        return web.json_response({"error": "provider_id and api_key are required"}, status=400)

    try:
        checker = _get_llm_key_providers().get(provider_id)
        if not checker:
            return web.json_response({"valid": True, "message": f"No health check for {provider_id}"})

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: checker(api_key))
        return web.json_response(result)

    except Exception as exc:
        logger.warning("LLM key validation failed for %s: %s", provider_id, exc)
        return web.json_response({"valid": None, "message": f"Validation error: {exc}"})


def register_routes(app: web.Application) -> None:
    """Register credential routes on the application."""
    # specs and check-agent must be registered BEFORE the {credential_id} wildcard
    app.router.add_get("/api/credentials/specs", handle_list_specs)
    app.router.add_post("/api/credentials/check-agent", handle_check_agent)
    app.router.add_post("/api/credentials/resync", handle_resync_credentials)
    app.router.add_post("/api/credentials/validate-key", handle_validate_key)
    app.router.add_get("/api/credentials", handle_list_credentials)
    app.router.add_post("/api/credentials", handle_save_credential)
    app.router.add_get("/api/credentials/{credential_id}", handle_get_credential)
    app.router.add_delete("/api/credentials/{credential_id}", handle_delete_credential)
