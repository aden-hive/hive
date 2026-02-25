"""Credential CRUD routes."""

import logging

from aiohttp import web
from pydantic import SecretStr

from framework.credentials.models import CredentialKey, CredentialObject
from framework.credentials.store import CredentialStore

logger = logging.getLogger(__name__)


def _get_store(request: web.Request) -> CredentialStore:
    return request.app["credential_store"]


def _credential_to_dict(cred: CredentialObject) -> dict:
    """Serialize a CredentialObject to JSON — never include secret values."""
    return {
        "credential_id": cred.id,
        "credential_type": str(cred.credential_type),
        "key_names": list(cred.keys.keys()),
        "created_at": cred.created_at.isoformat() if cred.created_at else None,
        "updated_at": cred.updated_at.isoformat() if cred.updated_at else None,
    }


async def handle_list_credentials(request: web.Request) -> web.Response:
    """GET /api/credentials — list all credential metadata (no secrets)."""
    store = _get_store(request)
    cred_ids = store.list_credentials()
    credentials = []
    for cid in cred_ids:
        cred = store.get_credential(cid, refresh_if_needed=False)
        if cred:
            credentials.append(_credential_to_dict(cred))
    return web.json_response({"credentials": credentials})


async def handle_get_credential(request: web.Request) -> web.Response:
    """GET /api/credentials/{credential_id} — get single credential metadata."""
    credential_id = request.match_info["credential_id"]
    store = _get_store(request)
    cred = store.get_credential(credential_id, refresh_if_needed=False)
    if cred is None:
        return web.json_response({"error": f"Credential '{credential_id}' not found"}, status=404)
    return web.json_response(_credential_to_dict(cred))


async def handle_save_credential(request: web.Request) -> web.Response:
    """POST /api/credentials — store a credential.

    Body: {"credential_id": "...", "keys": {"key_name": "value", ...}}
    """
    store = _get_store(request)
    body = await request.json()

    credential_id = body.get("credential_id")
    keys = body.get("keys")

    if not credential_id or not keys or not isinstance(keys, dict):
        return web.json_response({"error": "credential_id and keys are required"}, status=400)

    cred = CredentialObject(
        id=credential_id,
        keys={k: CredentialKey(name=k, value=SecretStr(v)) for k, v in keys.items()},
    )
    store.save_credential(cred)
    return web.json_response({"saved": credential_id}, status=201)


async def handle_delete_credential(request: web.Request) -> web.Response:
    """DELETE /api/credentials/{credential_id} — delete a credential."""
    credential_id = request.match_info["credential_id"]
    store = _get_store(request)
    deleted = store.delete_credential(credential_id)
    if not deleted:
        return web.json_response({"error": f"Credential '{credential_id}' not found"}, status=404)
    return web.json_response({"deleted": True})


async def handle_check_agent(request: web.Request) -> web.Response:
    """POST /api/credentials/check-agent — check and validate agent credentials.

    Uses the same two-phase validation as agent startup:
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
        import os

        from framework.credentials.setup import CredentialSetupSession
        from framework.credentials.storage import CompositeStorage, EncryptedFileStorage, EnvVarStorage
        from framework.credentials.validation import _presync_aden_tokens, ensure_credential_key_env

        # Load env vars from shell config (same as runtime startup)
        ensure_credential_key_env()

        # Build a proper store with env + encrypted storage (same as validate_agent_credentials)
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS
        except ImportError:
            CREDENTIAL_SPECS = {}

        if os.environ.get("ADEN_API_KEY") and CREDENTIAL_SPECS:
            _presync_aden_tokens(CREDENTIAL_SPECS)

        env_mapping = {
            (spec.credential_id or name): spec.env_var
            for name, spec in CREDENTIAL_SPECS.items()
        }
        env_storage = EnvVarStorage(env_mapping=env_mapping)
        if os.environ.get("HIVE_CREDENTIAL_KEY"):
            storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
        else:
            storage = env_storage
        store = CredentialStore(storage=storage)

        # Detect required credentials from agent graph
        session = CredentialSetupSession.from_agent_path(agent_path, missing_only=False)

        # Health check function (may not be available)
        check_health = None
        if verify:
            try:
                from aden_tools.credentials import check_credential_health
                check_health = check_credential_health
            except ImportError:
                pass

        required = []
        for mc in session.missing:
            cred_id = mc.credential_id or mc.credential_name
            available = store.is_available(cred_id)

            entry = {
                "credential_name": mc.credential_name,
                "credential_id": cred_id,
                "env_var": mc.env_var,
                "description": mc.description,
                "help_url": mc.help_url,
                "tools": mc.tools,
                "node_types": mc.node_types,
                "available": available,
                "direct_api_key_supported": mc.direct_api_key_supported,
                "aden_supported": mc.aden_supported,
                "credential_key": mc.credential_key,
                "valid": None,  # null = not checked
                "validation_message": None,
            }

            # Phase 2: health check for available credentials
            if available and verify and check_health:
                spec = CREDENTIAL_SPECS.get(mc.credential_name)
                if spec and spec.health_check_endpoint:
                    value = store.get(cred_id)
                    if value:
                        try:
                            result = check_health(
                                mc.credential_name,
                                value,
                                health_check_endpoint=spec.health_check_endpoint,
                                health_check_method=spec.health_check_method,
                            )
                            entry["valid"] = result.valid
                            entry["validation_message"] = result.message
                        except Exception as exc:
                            entry["valid"] = False
                            entry["validation_message"] = f"Health check error: {exc}"

            required.append(entry)
        return web.json_response({"required": required})
    except Exception as e:
        logger.exception(f"Error checking agent credentials: {e}")
        return web.json_response({"error": str(e)}, status=500)


def register_routes(app: web.Application) -> None:
    """Register credential routes on the application."""
    # check-agent must be registered BEFORE the {credential_id} wildcard
    app.router.add_post("/api/credentials/check-agent", handle_check_agent)
    app.router.add_get("/api/credentials", handle_list_credentials)
    app.router.add_post("/api/credentials", handle_save_credential)
    app.router.add_get("/api/credentials/{credential_id}", handle_get_credential)
    app.router.add_delete("/api/credentials/{credential_id}", handle_delete_credential)
