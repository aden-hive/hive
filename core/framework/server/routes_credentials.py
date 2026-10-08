"""Credential CRUD routes."""

import asyncio
import logging
import os

from aiohttp import web
from pydantic import SecretStr

from framework.credentials.models import CredentialDecryptionError, CredentialKey, CredentialObject
from framework.credentials.store import CredentialStore
from framework.server.app import get_request_executor, resolve_session, validate_agent_path

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


def _reset_credential_adapter_cache() -> None:
    """Clear the memoized CredentialStoreAdapter so the next call re-syncs.

    The adapter cache is keyed on ``(id(specs), ADEN_API_KEY)``; without
    this reset, a key save/delete done after process startup is invisible
    to in-process MCP tool calls until restart.
    """
    try:
        from aden_tools.credentials.store_adapter import _reset_default_adapter_cache

        _reset_default_adapter_cache()
    except Exception:
        logger.warning("Failed to reset credential adapter cache", exc_info=True)


def _provider_for_credential(credential_id: str) -> str | None:
    """Return the OAuth provider name (``aden_provider_name``) for ``credential_id``.

    Used when publishing global credential events so subscribers can
    flip per-provider UI state without having to look up the spec
    themselves. Returns ``None`` when the credential isn't OAuth-bound
    or aden_tools isn't available.
    """
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        for name, spec in CREDENTIAL_SPECS.items():
            cid = spec.credential_id or name
            if cid == credential_id:
                return getattr(spec, "aden_provider_name", None) or None
    except Exception:
        logger.debug("Could not resolve provider for %s", credential_id, exc_info=True)
    return None


async def _publish_credential_event(
    *,
    connected: bool,
    credential_id: str,
    provider: str | None,
) -> None:
    """Publish a global SSE event so the UI can refetch tool catalogs.

    Pairs every credential save/delete with a single event on the
    process-wide bus. Subscribers (Tool Library, Integrations page)
    use this to refresh per-provider state without polling.
    """
    from framework.host.event_bus import (
        AgentEvent,
        EventType,
        publish_global,
    )

    event_type = EventType.CREDENTIAL_PROVIDER_CONNECTED if connected else EventType.CREDENTIAL_PROVIDER_DISCONNECTED
    await publish_global(
        AgentEvent(
            type=event_type,
            stream_id="global",
            data={
                "credential_id": credential_id,
                "provider": provider,
            },
        )
    )
    # Pair with TOOL_CATALOG_REFRESHED so generic catalog subscribers
    # (which don't care about which provider changed) only need to
    # listen for one event type.
    await publish_global(
        AgentEvent(
            type=EventType.TOOL_CATALOG_REFRESHED,
            stream_id="global",
            data={
                "trigger": "credential_save" if connected else "credential_delete",
                "credential_id": credential_id,
                "provider": provider,
            },
        )
    )


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

        # Make the new key visible to the in-process AdenSyncProvider on
        # the very next CredentialStoreAdapter.default() call. The adapter
        # cache is keyed on this env var.
        os.environ["ADEN_API_KEY"] = key
        _reset_credential_adapter_cache()

        # Upgrade the live framework credential store in place so agents
        # and tool registries pick up Aden-synced OAuth credentials this
        # session. The runtime is spawned with ADEN_API_KEY="" and wires
        # the store local-only at startup; without this in-place upgrade
        # full convergence waited for the next runtime restart.
        try:
            store = request.app.get("credential_store")
            if store is not None and hasattr(store, "enable_aden_sync"):
                loop = asyncio.get_running_loop()
                synced = await loop.run_in_executor(get_request_executor(), store.enable_aden_sync)
                logger.info(
                    "aden_api_key save: live store Aden sync activated (%s credential(s))",
                    synced,
                )
        except Exception as exc:
            logger.warning("aden_api_key save: enable_aden_sync failed: %s", exc)

        # Immediately sync OAuth tokens from Aden (runs in executor because
        # _presync_aden_tokens makes blocking HTTP calls to the Aden server).
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS

            from framework.credentials.validation import _presync_aden_tokens

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(get_request_executor(), _presync_aden_tokens, CREDENTIAL_SPECS)
        except Exception as exc:
            logger.warning("Aden token sync after key save failed: %s", exc)

        _invalidate_queen_credentials_cache(request)
        # Aden key save fans out OAuth tokens; broadcast a refresh so the
        # Tool Library re-evaluates every provider's connected state.
        await _publish_credential_event(connected=True, credential_id="aden_api_key", provider=None)
        return web.json_response({"saved": "aden_api_key"}, status=201)

    store = _get_store(request)
    cred = CredentialObject(
        id=credential_id,
        keys={k: CredentialKey(name=k, value=SecretStr(v)) for k, v in keys.items()},
    )
    try:
        store.save_credential(cred)
    except NotImplementedError as exc:
        # Storage backend is read-only — almost always the
        # `with_env_storage()` fallback from app startup, which happens
        # when encrypted creds exist but HIVE_CREDENTIAL_KEY can't be
        # loaded. The self-heal block in app.py should have prevented
        # this on fresh boots; if we still get here it's a runtime
        # transition (e.g. store rebuilt mid-session). Surface a
        # structured 503 so the desktop's retry loop can distinguish
        # this from a transient 500.
        logger.error(
            "save_credential rejected by read-only store for id=%s: %s",
            credential_id,
            exc,
        )
        return web.json_response(
            {
                "error": "credentials_store_locked",
                "detail": "Credential store is read-only (HIVE_CREDENTIAL_KEY missing). Restart hive serve to trigger the self-heal recovery.",
            },
            status=503,
        )
    _reset_credential_adapter_cache()
    _invalidate_queen_credentials_cache(request)
    await _publish_credential_event(
        connected=True,
        credential_id=credential_id,
        provider=_provider_for_credential(credential_id),
    )
    return web.json_response({"saved": credential_id}, status=201)


async def handle_delete_credential(request: web.Request) -> web.Response:
    """DELETE /api/credentials/{credential_id} — delete a credential."""
    credential_id = request.match_info["credential_id"]

    if credential_id == "aden_api_key":
        from framework.credentials.key_storage import delete_aden_api_key

        deleted = delete_aden_api_key()
        if not deleted:
            return web.json_response({"error": "Credential 'aden_api_key' not found"}, status=404)
        # Drop the env var so the next adapter rebuild lands in the
        # non-Aden branch instead of trying to reuse the stale key.
        os.environ.pop("ADEN_API_KEY", None)
        _reset_credential_adapter_cache()
        _invalidate_queen_credentials_cache(request)
        await _publish_credential_event(connected=False, credential_id="aden_api_key", provider=None)
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
    _reset_credential_adapter_cache()
    _invalidate_queen_credentials_cache(request)
    await _publish_credential_event(
        connected=False,
        credential_id=credential_id,
        provider=_provider_for_credential(credential_id),
    )
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
        executor = get_request_executor()
        # _presync_aden_tokens makes blocking HTTP calls to the Aden server.
        await loop.run_in_executor(executor, lambda: _presync_aden_tokens(CREDENTIAL_SPECS, force=True))

        # Re-sync the live framework credential store too, so a manual
        # resync converges the same store agents read from.
        store = request.app.get("credential_store")
        if store is not None and hasattr(store, "enable_aden_sync"):
            await loop.run_in_executor(executor, store.enable_aden_sync)

        # Drop the cached adapter so newly-fetched accounts are visible
        # to the next MCP tool call without waiting for a process restart.
        _reset_credential_adapter_cache()
        _invalidate_queen_credentials_cache(request)

        accounts_by_provider = _collect_accounts_by_provider()
        # Aden resync may have surfaced brand-new providers (the user
        # just authorised an integration on the Aden site). Broadcast
        # a generic refresh so every Tool Library tab re-evaluates
        # provider_connected without polling.
        await _publish_credential_event(connected=True, credential_id="<aden_resync>", provider=None)
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


async def handle_oauth_status(request: web.Request) -> web.Response:
    """GET /api/credentials/oauth-status — live OAuth connections the runtime sees.

    Read-only snapshot of the credential store from the runtime's eye,
    intended for the desktop's DEBUG panel. Does NOT trigger sync_all —
    it just reads from the memoized adapter, so polling is cheap.

    Returns the same ``accounts_by_provider`` shape as ``/resync`` plus
    the local Aden-API-key bit, so the panel can show "connected to
    Aden" independently from per-provider rows.
    """
    try:
        accounts_by_provider = _collect_accounts_by_provider()
        return web.json_response(
            {
                "accounts_by_provider": accounts_by_provider,
                "has_aden_key": bool(os.environ.get("ADEN_API_KEY")),
                "fetched_at": int(__import__("time").time() * 1000),
            }
        )
    except Exception as exc:
        logger.exception("Error collecting oauth status: %s", exc)
        return web.json_response(
            {"error": "Internal server error while collecting oauth status"},
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
            # accounts_by_provider is keyed by the OAuth provider name
            # (e.g. ``notion``), not the credential_id (e.g.
            # ``notion_token``). Prefer aden_provider_name so specs
            # whose two ids diverge — Notion is the canonical example —
            # don't silently report ``accounts=[]``/``available=False``
            # while the user has a live OAuth grant on the Aden side.
            provider_key = getattr(spec, "aden_provider_name", "") or cred_id
            accounts = accounts_by_provider.get(provider_key, [])
            # Pure-OAuth (Aden-only, no direct API key) credentials are
            # authoritative through Aden — the accounts list is the source of
            # truth. Local stores can hold stale cache entries after a remote
            # deletion, so trusting `store.is_available()` here would surface
            # ghost "Connected" rows with no accounts and no add affordance.
            #
            # Specs that support BOTH paths (Notion, etc.) are connected
            # if EITHER an OAuth account exists OR a direct API key has
            # been pasted. The local-store check uses cred_id and would
            # miss the OAuth account because it's filed under the provider
            # name; without the OR-with-accounts the user sees "Disconnected"
            # right after authorising on hive.adenhq.com.
            if spec.aden_supported and not spec.direct_api_key_supported:
                available = len(accounts) > 0
            else:
                available = len(accounts) > 0 or _is_available_for_specs(store, cred_id)
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
                    "api_key_instructions": ("1. Go to hive.adenhq.com\n2. Open Settings > Developers\n3. Copy your API key"),
                    "tools": [],
                    "aden_supported": True,
                    "direct_api_key_supported": True,
                    "credential_key": "api_key",
                    "credential_group": "",
                    "available": has_aden_key,
                },
            )

        # Expose the full provider→accounts map (incl. local/custom accounts)
        # so the frontend can surface manually-added keys on providers that
        # have no backend CredentialSpec (e.g. BYOK catalog placeholders).
        return web.json_response(
            {
                "specs": specs,
                "has_aden_key": has_aden_key,
                "accounts_by_provider": accounts_by_provider,
            }
        )
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
        result = await loop.run_in_executor(get_request_executor(), lambda: checker(api_key))
        return web.json_response(result)

    except Exception as exc:
        logger.warning("LLM key validation failed for %s: %s", provider_id, exc)
        return web.json_response({"valid": None, "message": f"Validation error: {exc}"})


# Field names tried, in order, as the credential's primary/default key when
# the form did not include an explicit "api_key".
_PRIMARY_KEY_HINTS = ("api_key", "token", "access_token", "password", "secret", "value", "key")


async def _save_local_credential(
    credential_id: str,
    account: str,
    keys: dict,
    *,
    run_health_check: bool | None = None,
):
    """Persist a named local credential via LocalCredentialRegistry.

    Shared by the agent's secure-form route and the Integrations page's manual
    "Add credential" flow. Stores every field under its real name (so
    multi-field creds like username+password survive) while ``api_key`` holds
    the primary value so the credential has a resolvable default key. The
    account is aliased (``<credential_id>/<account>``), so it shows up in
    ``browse`` (source='local') and resolves through the adapter's
    local-account fallbacks. Runs a health check when the provider has a
    registered checker (unless ``run_health_check`` is forced).

    Raises ``ValueError`` for empty input. Returns ``(LocalAccountInfo,
    HealthCheckResult | None)``.
    """
    from framework.credentials.local.registry import LocalCredentialRegistry

    keys = {str(k): str(v) for k, v in keys.items() if str(v).strip()}
    if not keys:
        raise ValueError("no non-empty values provided")

    primary_value = next(
        (keys[h] for h in _PRIMARY_KEY_HINTS if h in keys),
        next(iter(keys.values())),
    )
    extra = {k: v for k, v in keys.items() if k != "api_key"}

    if run_health_check is None:
        try:
            from aden_tools.credentials.health_check import HEALTH_CHECKERS

            run_health_check = credential_id in HEALTH_CHECKERS
        except Exception:
            run_health_check = False

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_request_executor(),
        lambda: LocalCredentialRegistry.default().save_account(
            credential_id,
            account,
            primary_value,
            run_health_check=run_health_check,
            extra_keys=extra or None,
        ),
    )


async def _resume_queen_with(session, message: str, correlation_id) -> bool:
    """Inject a NON-secret message into the queen loop to unpark it.

    Mirrors the queen-node lookup in routes_execution.handle_chat. Returns
    True if the message was delivered, False if the queen wasn't live.
    """
    queen_executor = getattr(session, "queen_executor", None)
    if queen_executor is None:
        return False
    node = queen_executor.node_registry.get("queen")
    if node is None or not hasattr(node, "inject_event"):
        return False
    try:
        await node.inject_event(message, is_client_input=True, correlation_id=correlation_id)
        return True
    except Exception:
        logger.exception("credential-form: failed to resume queen loop")
        return False


async def handle_credential_form(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/credential-form — receive a secure
    credential form the agent popped via ``credentials(action="collect")``.

    Body: ``{correlation_id, status, credential_id, account, keys}``

    On ``status="saved"`` the secret ``keys`` are stored encrypted — they
    NEVER travel back to the LLM — and the queen loop is resumed with a
    non-secret confirmation. On ``status="cancelled"`` the loop is resumed
    with a cancel note so the agent can react.
    """
    session, err = resolve_session(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    status = str(body.get("status", "saved")).strip().lower()
    correlation_id = body.get("correlation_id")
    credential_id = str(body.get("credential_id", "")).strip()
    account = str(body.get("account", "") or "default").strip() or "default"

    if status == "cancelled":
        await _resume_queen_with(
            session,
            f"The user cancelled the credential form for '{credential_id or 'the requested credential'}'.",
            correlation_id,
        )
        return web.json_response({"status": "cancelled"})

    keys = body.get("keys")
    if not credential_id or not isinstance(keys, dict) or not keys:
        return web.json_response(
            {"error": "credential_id and non-empty keys are required"},
            status=400,
        )

    try:
        await _save_local_credential(credential_id, account, keys)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("credential-form: failed to save %s/%s", credential_id, account)
        return web.json_response({"error": f"Failed to store credential: {exc}"}, status=500)

    _reset_credential_adapter_cache()
    _invalidate_queen_credentials_cache(request)
    await _publish_credential_event(
        connected=True,
        credential_id=credential_id,
        provider=_provider_for_credential(credential_id),
    )

    key_names = ", ".join(sorted(keys.keys()))
    confirmation = (
        f"✅ Credential '{credential_id}' (account '{account}') was saved "
        f"securely. Fields provided: {key_names}. It is now available — use it "
        f'by passing account="{account}" to the relevant tool. (The secret '
        "values are stored encrypted and are not shown here.)"
    )
    resumed = await _resume_queen_with(session, confirmation, correlation_id)

    return web.json_response(
        {"saved": f"{credential_id}/{account}", "resumed": resumed},
        status=201,
    )


async def handle_save_local_credential(request: web.Request) -> web.Response:
    """POST /api/credentials/local — manually add a named local credential.

    Body: ``{credential_id, account?, keys}``. Powers the Integrations page's
    "Add credential" flow (manual parity with the agent's secure form): any
    provider id (known or custom), an optional account alias for multi-account,
    and one or more key fields. Stored as a health-checked local account.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    credential_id = str(body.get("credential_id", "")).strip()
    account = str(body.get("account", "") or "default").strip() or "default"
    keys = body.get("keys")

    if not credential_id or any(c in credential_id for c in " /\\"):
        return web.json_response({"error": "a valid credential_id is required"}, status=400)
    if any(c in account for c in " /\\"):
        return web.json_response({"error": "account alias must not contain spaces or slashes"}, status=400)
    if not isinstance(keys, dict) or not keys:
        return web.json_response({"error": "non-empty keys are required"}, status=400)

    try:
        info, health = await _save_local_credential(credential_id, account, keys)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("save-local: failed to save %s/%s", credential_id, account)
        return web.json_response({"error": f"Failed to store credential: {exc}"}, status=500)

    _reset_credential_adapter_cache()
    _invalidate_queen_credentials_cache(request)
    await _publish_credential_event(
        connected=True,
        credential_id=credential_id,
        provider=_provider_for_credential(credential_id),
    )
    return web.json_response(
        {
            "saved": f"{credential_id}/{account}",
            "status": info.status,
            "identity": info.identity.to_dict(),
            "valid": (health.valid if health is not None else None),
            "message": (health.message if health is not None else None),
        },
        status=201,
    )


async def handle_delete_local_credential(request: web.Request) -> web.Response:
    """DELETE /api/credentials/local/{credential_id}/{alias} — remove one local account."""
    credential_id = request.match_info["credential_id"]
    alias = request.match_info["alias"]

    from framework.credentials.local.registry import LocalCredentialRegistry

    try:
        deleted = LocalCredentialRegistry.default().delete_account(credential_id, alias)
    except Exception as exc:
        logger.exception("delete-local: failed for %s/%s", credential_id, alias)
        return web.json_response({"error": f"Failed to delete credential: {exc}"}, status=500)

    if not deleted:
        return web.json_response({"error": f"Local account '{credential_id}/{alias}' not found"}, status=404)

    _reset_credential_adapter_cache()
    _invalidate_queen_credentials_cache(request)
    await _publish_credential_event(
        connected=False,
        credential_id=credential_id,
        provider=_provider_for_credential(credential_id),
    )
    return web.json_response({"deleted": True})


def register_routes(app: web.Application) -> None:
    """Register credential routes on the application."""
    # Local-account add/remove — registered before the {credential_id} wildcard.
    app.router.add_post("/api/credentials/local", handle_save_local_credential)
    app.router.add_delete(
        "/api/credentials/local/{credential_id}/{alias}",
        handle_delete_local_credential,
    )
    # specs and check-agent must be registered BEFORE the {credential_id} wildcard
    app.router.add_get("/api/credentials/specs", handle_list_specs)
    app.router.add_get("/api/credentials/oauth-status", handle_oauth_status)
    app.router.add_post("/api/credentials/check-agent", handle_check_agent)
    app.router.add_post("/api/credentials/resync", handle_resync_credentials)
    app.router.add_post("/api/credentials/validate-key", handle_validate_key)
    app.router.add_get("/api/credentials", handle_list_credentials)
    app.router.add_post("/api/credentials", handle_save_credential)
    app.router.add_get("/api/credentials/{credential_id}", handle_get_credential)
    app.router.add_delete("/api/credentials/{credential_id}", handle_delete_credential)
    # Secure form submission for the agent's credentials(action="collect").
    app.router.add_post("/api/sessions/{session_id}/credential-form", handle_credential_form)
