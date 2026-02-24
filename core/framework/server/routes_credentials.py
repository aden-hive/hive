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
    """POST /api/credentials/check-agent — check which credentials an agent needs.

    Body: {"agent_path": "..."}
    """
    store = _get_store(request)
    body = await request.json()
    agent_path = body.get("agent_path")

    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    try:
        from framework.credentials.setup import (
            CredentialSetupSession,
        )

        session = CredentialSetupSession.from_agent_path(agent_path, missing_only=False)
        required = []
        for mc in session.missing:
            cred_id = mc.credential_id or mc.credential_name
            required.append(
                {
                    "credential_name": mc.credential_name,
                    "credential_id": cred_id,
                    "env_var": mc.env_var,
                    "description": mc.description,
                    "help_url": mc.help_url,
                    "tools": mc.tools,
                    "node_types": mc.node_types,
                    "available": store.is_available(cred_id),
                    "direct_api_key_supported": mc.direct_api_key_supported,
                    "aden_supported": mc.aden_supported,
                    "credential_key": mc.credential_key,
                }
            )
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
