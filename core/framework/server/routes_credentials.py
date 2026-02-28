"""Credential CRUD routes."""

import asyncio
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

        return web.json_response({"saved": "aden_api_key"}, status=201)

    store = _get_store(request)
    cred = CredentialObject(
        id=credential_id,
        keys={k: CredentialKey(name=k, value=SecretStr(v)) for k, v in keys.items()},
    )
    store.save_credential(cred)
    return web.json_response({"saved": credential_id}, status=201)


async def handle_delete_credential(request: web.Request) -> web.Response:
    """DELETE /api/credentials/{credential_id} — delete a credential."""
    credential_id = request.match_info["credential_id"]

    if credential_id == "aden_api_key":
        from framework.credentials.key_storage import delete_aden_api_key

        delete_aden_api_key()
        return web.json_response({"deleted": True})

    store = _get_store(request)
    deleted = store.delete_credential(credential_id)
    if not deleted:
        return web.json_response({"error": f"Credential '{credential_id}' not found"}, status=404)
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
        from framework.credentials.setup import load_agent_nodes
        from framework.credentials.validation import (
            ensure_credential_key_env,
            validate_agent_credentials,
        )

        # Load env vars from shell config (same as runtime startup)
        ensure_credential_key_env()

        nodes = load_agent_nodes(agent_path)
        result = validate_agent_credentials(
            nodes, verify=verify, raise_on_error=False, force_refresh=True
        )

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
        return web.json_response({"error": str(e)}, status=500)


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


def register_routes(app: web.Application) -> None:
    """Register credential routes on the application."""
    # check-agent must be registered BEFORE the {credential_id} wildcard
    app.router.add_post("/api/credentials/check-agent", handle_check_agent)
    app.router.add_get("/api/credentials", handle_list_credentials)
    app.router.add_post("/api/credentials", handle_save_credential)
    app.router.add_get("/api/credentials/{credential_id}", handle_get_credential)
    app.router.add_delete("/api/credentials/{credential_id}", handle_delete_credential)
