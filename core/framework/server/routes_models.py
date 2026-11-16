"""The Models page: which model each slot uses, where models come from, and changing either.

- GET /api/models/overview -- every slot, the queens with a model of their own, the catalog's
  providers, the endpoints (Magpie and others) and detected subscriptions, in one answer
- PUT /api/models/slots/{slot} -- a slot (``llm``, ``worker_llm``, ``vision_fallback`` or
  ``queen:<id>``) set to a catalog model or an endpoint's model; DELETE returns it to its default
- GET /api/models/endpoints/{name}/models -- an endpoint's models, live
- PUT /api/models/endpoints/{name} -- add an endpoint, or change its address or key; DELETE removes it

A slot is always written whole, from what was picked: a change of provider or endpoint leaves the
old key and ``extra_body`` behind, so a key never follows a model to another vendor. Keys never
appear in an answer. Subscriptions are switched with ``PUT /api/config/llm`` (and are at the
user's own risk: running a plan unattended for agents may break its terms).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from framework.llm import endpoints as model_endpoints

logger = logging.getLogger(__name__)

_ROLE_SLOTS = ("llm", "worker_llm", "vision_fallback")
_QUEEN_PREFIX = "queen:"


async def handle_overview(request: web.Request) -> web.Response:
    from framework.config import get_hive_config
    from framework.server.routes_config import MODELS_CATALOGUE, SUBSCRIPTIONS, _detect_subscriptions, _resolve_api_key

    config = get_hive_config()
    endpoints = model_endpoints.endpoints()
    names = list(endpoints)
    running, has_key = await asyncio.gather(
        asyncio.gather(*(asyncio.to_thread(model_endpoints.probe, n) for n in names)),
        asyncio.gather(*(asyncio.to_thread(model_endpoints.stored_key, n) for n in names)),
    )
    detected = set(await asyncio.to_thread(_detect_subscriptions))
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    judge = config.get("judge") if isinstance(config.get("judge"), dict) else {}
    queen_sections = config.get("queen_llm") if isinstance(config.get("queen_llm"), dict) else {}
    return web.json_response(
        {
            "slots": {role: _summary(config.get(role)) for role in _ROLE_SLOTS},
            "judge": {
                "configured": bool(judge.get("api_base") and judge.get("api_key")),
                "model": judge.get("model"),
                "api_base": judge.get("api_base"),
            },
            "queens": [
                {"id": queen_id, "name": _queen_name(queen_id), **(_summary(section) or {})}
                for queen_id, section in queen_sections.items()
                if _summary(section) is not None
            ],
            "providers": [
                {
                    "id": provider,
                    "connected": bool(_resolve_api_key(provider, request)),
                    "models": [
                        {
                            "id": m["id"],
                            "label": m.get("label") or m["id"],
                            "recommended": bool(m.get("recommended")),
                            "max_context_tokens": m.get("max_context_tokens"),
                            "supports_vision": m.get("supports_vision", True),
                        }
                        for m in models
                    ],
                }
                for provider, models in MODELS_CATALOGUE.items()
            ],
            "endpoints": [
                {
                    "name": e.name,
                    "api_base": e.api_base,
                    "builtin": e.builtin,
                    "has_key": key is not None,
                    "running": up,
                }
                for e, up, key in zip(endpoints.values(), running, has_key, strict=True)
            ],
            "subscriptions": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "description": s["description"],
                    "model": s["default_model"],
                    "detected": s["id"] in detected,
                    "active": bool(llm.get(s["flag"])),
                    # Running a plan unattended, for agents, may break its terms: the user's own risk.
                    "own_risk": True,
                }
                for s in SUBSCRIPTIONS
            ],
        }
    )


async def handle_put_slot(request: web.Request) -> web.Response:
    from framework.server.routes_config import (
        PROVIDER_ENV_VARS,
        _find_model_info,
        _get_api_base_for_provider,
        _resolve_api_key,
        _validate_provider_key,
    )

    slot = request.match_info["slot"]
    problem = _slot_problem(slot)
    if problem:
        return web.json_response({"error": problem}, status=404 if slot.startswith(_QUEEN_PREFIX) else 400)
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "The body isn't JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "The body must be a JSON object"}, status=400)
    source, model = body.get("source"), str(body.get("model") or "").strip()
    if not model:
        return web.json_response({"error": "'model' is required"}, status=400)

    if source == "catalog":
        provider = str(body.get("provider") or "").strip()
        info = _find_model_info(provider, model)
        if info is None:
            return web.json_response({"error": f"{model} isn't one of {provider or '?'}'s models in the catalog"}, status=400)
        api_key = _resolve_api_key(provider, request)
        if not api_key:
            return web.json_response({"error": f"There's no API key for {provider}: add one on the Models page"}, status=400)
        api_base = _get_api_base_for_provider(provider)
        check = await _validate_provider_key(provider, api_key, api_base=api_base, model=model)
        if check.get("valid") is False:
            return web.json_response({"error": f"{provider} refused the key: {check.get('message', 'unknown error')}"}, status=400)
        section: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "max_tokens": info["max_tokens"],
            "max_context_tokens": info["max_context_tokens"],
        }
        if PROVIDER_ENV_VARS.get(provider.lower()):
            section["api_key_env_var"] = PROVIDER_ENV_VARS[provider.lower()]
        if api_base:
            section["api_base"] = api_base
    elif source == "endpoint":
        name = str(body.get("endpoint") or "")
        endpoint = model_endpoints.get(name)
        if endpoint is None:
            return web.json_response({"error": f"There's no endpoint {name!r}"}, status=400)
        try:
            models = await asyncio.to_thread(model_endpoints.list_models, name)
        except model_endpoints.EndpointError as e:
            return web.json_response({"error": str(e)}, status=400)
        found = next((m for m in models if m["id"] == model), None)
        if found is None:
            return web.json_response({"error": f"{name} has no model {model!r}"}, status=400)
        section = {"provider": "openai", "endpoint": name, "model": model, "api_base": endpoint.api_base}
        if found["max_context_tokens"]:
            section["max_context_tokens"] = found["max_context_tokens"]
    else:
        return web.json_response(
            {"error": '\'source\' must be "catalog" or "endpoint" (a subscription is switched with PUT /api/config/llm)'},
            status=400,
        )

    # Within one provider or endpoint, fields only it understands (a reasoning effort, say) carry over.
    previous = _section_of(slot)
    if (
        previous
        and previous.get("extra_body")
        and (previous.get("provider"), previous.get("endpoint"))
        == (
            section["provider"],
            section.get("endpoint"),
        )
    ):
        section["extra_body"] = previous["extra_body"]
    return await _write_slot(request, slot, section)


async def handle_delete_slot(request: web.Request) -> web.Response:
    slot = request.match_info["slot"]
    problem = _slot_problem(slot)
    if problem:
        return web.json_response({"error": problem}, status=404 if slot.startswith(_QUEEN_PREFIX) else 400)
    if slot == "llm":
        return web.json_response({"error": "The main model can be changed, not removed"}, status=400)
    return await _write_slot(request, slot, None)


async def handle_endpoint_models(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if model_endpoints.get(name) is None:
        return web.json_response({"error": f"There's no endpoint {name!r}"}, status=404)
    try:
        models = await asyncio.to_thread(model_endpoints.list_models, name, fresh=request.query.get("fresh") == "1")
    except model_endpoints.EndpointError as e:
        return web.json_response({"error": str(e)}, status=502)
    return web.json_response({"models": models})


async def handle_put_endpoint(request: web.Request) -> web.Response:
    from framework.config import get_hive_config
    from framework.server.routes_config import _write_config_atomic

    name = request.match_info["name"]
    if not model_endpoints.valid_name(name):
        return web.json_response({"error": "An endpoint's name is lowercase letters, digits, '_' and '-'"}, status=400)
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "The body isn't JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "The body must be a JSON object"}, status=400)
    existing = model_endpoints.get(name)
    api_base = str(body.get("api_base") or (existing.api_base if existing else "")).strip().rstrip("/")
    if not api_base.startswith(("http://", "https://")):
        return web.json_response({"error": "'api_base' must be an http:// or https:// address"}, status=400)

    if "api_key" in body:
        problem = _store_key(request, name, body.get("api_key"))
        if problem:
            return web.json_response({"error": problem}, status=503)

    config = get_hive_config()
    entries = config.get("model_endpoints") if isinstance(config.get("model_endpoints"), dict) else {}
    if name == model_endpoints.MAGPIE and api_base == model_endpoints.MAGPIE_API_BASE:
        entries.pop(name, None)  # Magpie at its own address needs no entry
    else:
        entries[name] = {"api_base": api_base}
    if entries:
        config["model_endpoints"] = entries
    else:
        config.pop("model_endpoints", None)
    # Slots served from it follow it to its new address.
    moved = [slot for slot, section in _slots_using(config, name) if section.get("api_base") != api_base]
    for _, section in _slots_using(config, name):
        section["api_base"] = api_base
    _write_config_atomic(config)
    model_endpoints.forget(name)
    if "llm" in moved:
        _swap_main_model(request, config["llm"])
    return web.json_response(
        {
            "name": name,
            "api_base": api_base,
            "builtin": name == model_endpoints.MAGPIE,
            "has_key": model_endpoints.stored_key(name) is not None,
        }
    )


async def handle_delete_endpoint(request: web.Request) -> web.Response:
    from framework.config import get_hive_config
    from framework.server.routes_config import _write_config_atomic

    name = request.match_info["name"]
    if model_endpoints.get(name) is None:
        return web.json_response({"error": f"There's no endpoint {name!r}"}, status=404)
    config = get_hive_config()
    users = [slot for slot, _ in _slots_using(config, name)]
    if users:
        return web.json_response({"error": f"{name} serves {', '.join(users)}: pick another model there first"}, status=409)
    entries = config.get("model_endpoints") if isinstance(config.get("model_endpoints"), dict) else {}
    entries.pop(name, None)
    if entries:
        config["model_endpoints"] = entries
    else:
        config.pop("model_endpoints", None)
    _write_config_atomic(config)
    _store_key(request, name, None)
    model_endpoints.forget(name)
    return web.json_response({"deleted": name})


# ----------------------------------------------------------------------


def _summary(section: Any) -> dict[str, Any] | None:
    """What a slot uses, for the page: never its key."""
    from framework.server.routes_config import MODELS_CATALOGUE, SUBSCRIPTIONS

    if not isinstance(section, dict) or not section.get("model"):
        return None
    subscription = next((s["id"] for s in SUBSCRIPTIONS if section.get(s["flag"])), None)
    provider = section.get("provider")
    if section.get("endpoint"):
        source = "endpoint"
    elif subscription:
        source = "subscription"
    elif section.get("api_base") and provider not in MODELS_CATALOGUE:
        source = "custom"
    else:
        source = "catalog"
    return {
        "source": source,
        "provider": provider,
        "model": section.get("model"),
        "endpoint": section.get("endpoint"),
        "subscription": subscription,
        "api_base": section.get("api_base"),
        "max_context_tokens": section.get("max_context_tokens"),
        "has_extra_body": bool(section.get("extra_body")),
    }


def _queen_name(queen_id: str) -> str:
    from framework.agents.queen.queen_profiles import load_queen_profile

    try:
        return str(load_queen_profile(queen_id).get("name") or queen_id)
    except FileNotFoundError:
        return queen_id


def _slot_problem(slot: str) -> str | None:
    """Why ``slot`` isn't one to set, or None."""
    from framework.agents.queen.queen_profiles import load_queen_profile

    if slot in _ROLE_SLOTS:
        return None
    if slot.startswith(_QUEEN_PREFIX):
        try:
            load_queen_profile(slot[len(_QUEEN_PREFIX) :])
        except FileNotFoundError:
            return f"There's no queen {slot[len(_QUEEN_PREFIX) :]!r}"
        return None
    return f"There's no slot {slot!r}: it is one of {', '.join(_ROLE_SLOTS)}, or queen:<id>"


def _section_of(slot: str) -> dict[str, Any] | None:
    from framework.config import get_hive_config

    config = get_hive_config()
    if slot.startswith(_QUEEN_PREFIX):
        sections = config.get("queen_llm") if isinstance(config.get("queen_llm"), dict) else {}
        section = sections.get(slot[len(_QUEEN_PREFIX) :])
    else:
        section = config.get(slot)
    return section if isinstance(section, dict) else None


def _slots_using(config: dict[str, Any], name: str) -> list[tuple[str, dict[str, Any]]]:
    """The slots (and queens) served from endpoint ``name``, with their sections."""
    found = [(role, config[role]) for role in _ROLE_SLOTS if isinstance(config.get(role), dict) and config[role].get("endpoint") == name]
    queens = config.get("queen_llm") if isinstance(config.get("queen_llm"), dict) else {}
    found += [(f"{_QUEEN_PREFIX}{q}", s) for q, s in queens.items() if isinstance(s, dict) and s.get("endpoint") == name]
    return found


async def _write_slot(request: web.Request, slot: str, section: dict[str, Any] | None) -> web.Response:
    from framework.config import get_hive_config
    from framework.server import queen_models
    from framework.server.routes_config import _write_config_atomic

    config = get_hive_config()
    switched = 0
    if slot.startswith(_QUEEN_PREFIX):
        queen_id = slot[len(_QUEEN_PREFIX) :]
        sections = config.get("queen_llm") if isinstance(config.get("queen_llm"), dict) else {}
        if section is None:
            sections.pop(queen_id, None)
        else:
            sections[queen_id] = section
        if sections:
            config["queen_llm"] = sections
        else:
            config.pop("queen_llm", None)
        _write_config_atomic(config)
        manager = request.app["manager"]
        switched = sum(
            1
            for s in manager.list_sessions()
            if getattr(s, "queen_name", None) == queen_id and queen_models.apply(s.llm, queen_id, default_model=getattr(manager, "_model", None))
        )
    else:
        if section is None:
            config.pop(slot, None)
        else:
            config[slot] = section
        _write_config_atomic(config)
        if slot == "llm" and section is not None:
            switched = _swap_main_model(request, section)
    logger.info("Model slot %s set to %s; %d running session(s) switched", slot, _summary(section) or "its default", switched)
    return web.json_response({"slot": slot, "summary": _summary(section), "sessions_switched": switched})


def _swap_main_model(request: web.Request, section: dict[str, Any]) -> int:
    """Switch running sessions to the main model just written, with its key, address and extra_body."""
    from framework.config import get_api_base, get_api_key, section_model
    from framework.server.routes_config import _hot_swap_sessions

    return _hot_swap_sessions(request, section_model(section), get_api_key(), get_api_base(), extra_body=section.get("extra_body"))


def _store_key(request: web.Request, name: str, key: Any) -> str | None:
    """Save (a non-empty string) or remove (anything else) endpoint ``name``'s key; why it failed, or None."""
    from pydantic import SecretStr

    from framework.credentials.models import CredentialKey, CredentialObject

    store = request.app.get("credential_store")
    if store is None:
        return "The credential store isn't available, so the key can't be kept"
    credential = model_endpoints.credential_id(name)
    try:
        if isinstance(key, str) and key.strip():
            store.save_credential(CredentialObject(id=credential, keys={"api_key": CredentialKey(name="api_key", value=SecretStr(key.strip()))}))
        else:
            store.delete_credential(credential)
    except NotImplementedError:
        return "The credential store is read-only here (is HIVE_CREDENTIAL_KEY set?), so the key can't be kept"
    model_endpoints.forget(name)
    return None


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/models/overview", handle_overview)
    app.router.add_put("/api/models/slots/{slot}", handle_put_slot)
    app.router.add_delete("/api/models/slots/{slot}", handle_delete_slot)
    app.router.add_get("/api/models/endpoints/{name}/models", handle_endpoint_models)
    app.router.add_put("/api/models/endpoints/{name}", handle_put_endpoint)
    app.router.add_delete("/api/models/endpoints/{name}", handle_delete_endpoint)
