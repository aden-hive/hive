"""A queen's soul (``framework.agents.queen.soul``) from the dashboard.

- ``GET  /api/queen/{queen_id}/soul``: the soul by section, its limits, the waiting proposal, the history.
- ``PUT  /api/queen/{queen_id}/soul``: replace it by hand, ``{"sections": {key: [{"text", "date"}]}}``.
- ``POST /api/queen/{queen_id}/soul/proposals/{proposal_id}/decide``: ``{"accept": [indexes] | null}``
  applies those changes (null: all; []: dismisses the proposal).
- ``POST /api/queen/{queen_id}/soul/rollback``: ``{"version": n}`` makes version n current again.
- ``POST /api/queen/{queen_id}/soul/reflect``: ``{"bootstrap": bool}`` runs a reflection now, in the background.
- ``POST /api/queen/{queen_id}/soul/proposals/{proposal_id}/probe``: answers her probe questions (``soul_probes``)
  before and after the proposal's changes, in the background; the answers land in the proposal.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from aiohttp import web

from framework.agents.queen import soul as soul_store, soul_probes, soul_reflection
from framework.agents.queen.queen_profiles import load_queen_profile
from framework.agents.queen.soul import Item, SoulError
from framework.config import SoulConfig, get_soul_config

logger = logging.getLogger(__name__)


def _queen(request: web.Request) -> tuple[str, SoulConfig | None, web.Response | None]:
    queen_id = request.match_info["queen_id"]
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return queen_id, None, web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)
    cfg = get_soul_config(queen_id)
    if cfg is None:
        return queen_id, None, web.json_response({"error": f"Queen '{queen_id}' has no soul (configuration.json: soul.queens)"}, status=409)
    return queen_id, cfg, None


def _view(queen_id: str, cfg: SoulConfig) -> dict[str, Any]:
    soul = soul_store.load(queen_id)
    proposal = soul_store.pending_proposal(queen_id)
    state = soul_reflection.load_state(queen_id)
    return {
        "queen_id": queen_id,
        "enabled": True,
        "mode": cfg.mode,
        "hour": cfg.hour,
        "version": soul.version,
        "updated_at": soul.updated_at,
        "sections": [
            {
                "key": s.key,
                "title": s.title,
                "limit": s.limit,
                "used": soul_store.section_chars(soul.items(s.key)),
                "max_age_days": s.max_age_days,
                "evidence": s.evidence,
                "items": [{"text": i.text, "date": i.date} for i in soul.items(s.key)],
            }
            for s in cfg.sections
        ],
        "proposal": proposal.to_json() if proposal else None,
        "history": soul_store.history(queen_id)[:50],
        "reflecting": soul_reflection.is_reflecting(queen_id),
        "probes": len(soul_probes.load_probes(queen_id)),
        "probing": soul_probes.is_probing(queen_id),
        "last_run": state.get("last_run"),
        "last_result": state.get("last_result"),
    }


async def _json(request: web.Request) -> dict[str, Any] | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


async def handle_get_soul(request: web.Request) -> web.Response:
    queen_id = request.match_info["queen_id"]
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)
    cfg = get_soul_config(queen_id)
    if cfg is None:
        return web.json_response({"queen_id": queen_id, "enabled": False})
    return web.json_response(_view(queen_id, cfg))


async def handle_put_soul(request: web.Request) -> web.Response:
    queen_id, cfg, error = _queen(request)
    if error is not None:
        return error
    body = await _json(request)
    raw = body.get("sections") if body else None
    if not isinstance(raw, dict):
        return web.json_response({"error": "Body must be {'sections': {key: [{'text', 'date'}]}}"}, status=400)
    keys = {s.key for s in cfg.sections}
    unknown = sorted(set(raw) - keys)
    if unknown:
        return web.json_response({"error": f"Unknown sections: {', '.join(unknown)}"}, status=400)
    sections: dict[str, list[Item]] = {}
    for key, items in raw.items():
        if not isinstance(items, list):
            return web.json_response({"error": f"Section {key} must be a list"}, status=400)
        sections[key] = []
        for entry in items:
            text = str((entry or {}).get("text") or "").strip() if isinstance(entry, dict) else ""
            if not text:
                continue
            day = str(entry.get("date") or "")
            try:
                day = date.fromisoformat(day).isoformat() if day else ""
            except ValueError:
                return web.json_response({"error": f"Bad date {day!r}: use YYYY-MM-DD"}, status=400)
            sections[key].append(Item(text=" ".join(text.split()), date=day))
    try:
        soul_store.save(queen_id, cfg, sections, author="owner", note="edited by hand")
    except SoulError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response(_view(queen_id, cfg))


async def handle_decide(request: web.Request) -> web.Response:
    queen_id, cfg, error = _queen(request)
    if error is not None:
        return error
    proposal = soul_store.load_proposal(queen_id, request.match_info["proposal_id"])
    if proposal is None:
        return web.json_response({"error": "No such proposal"}, status=404)
    if proposal.status != "pending":
        return web.json_response({"error": f"This proposal was already {proposal.status}"}, status=409)
    body = await _json(request) or {}
    accept = body.get("accept")
    if accept is not None and not (isinstance(accept, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in accept)):
        return web.json_response({"error": "'accept' must be a list of change indexes, or null for all"}, status=400)
    try:
        soul_store.decide(queen_id, cfg, proposal, accept)
    except SoulError as e:
        return web.json_response({"error": str(e)}, status=409)
    return web.json_response(_view(queen_id, cfg))


async def handle_rollback(request: web.Request) -> web.Response:
    queen_id, cfg, error = _queen(request)
    if error is not None:
        return error
    body = await _json(request) or {}
    version = body.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return web.json_response({"error": "'version' must be a version number"}, status=400)
    try:
        soul_store.rollback(queen_id, cfg, version)
    except SoulError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response(_view(queen_id, cfg))


async def handle_reflect(request: web.Request) -> web.Response:
    queen_id, cfg, error = _queen(request)
    if error is not None:
        return error
    if soul_reflection.is_reflecting(queen_id):
        return web.json_response({"error": "She is reflecting already"}, status=409)
    if soul_store.pending_proposal(queen_id) is not None:
        return web.json_response({"error": "Decide on the waiting proposal first"}, status=409)
    body = await _json(request) or {}
    manager = request.app["manager"]

    async def run() -> None:
        try:
            await soul_reflection.reflect(queen_id, cfg, soul_reflection.llm_for(queen_id, cfg, manager), bootstrap=bool(body.get("bootstrap")))
        except Exception:
            logger.warning("soul: %s's reflection (from the dashboard) failed", queen_id, exc_info=True)

    manager.spawn_background(run())
    return web.json_response({"started": True}, status=202)


async def handle_probe(request: web.Request) -> web.Response:
    queen_id, cfg, error = _queen(request)
    if error is not None:
        return error
    proposal = soul_store.load_proposal(queen_id, request.match_info["proposal_id"])
    if proposal is None or proposal.status != "pending":
        return web.json_response({"error": "No pending proposal by that id"}, status=404)
    if not soul_probes.load_probes(queen_id):
        return web.json_response({"error": f"No probe questions: add them to {soul_probes.PROBES_FILE} in her soul folder"}, status=409)
    if soul_probes.is_probing(queen_id):
        return web.json_response({"error": "Already trying her out"}, status=409)
    manager = request.app["manager"]

    async def run() -> None:
        try:
            await soul_probes.probe(queen_id, cfg, soul_reflection.llm_for(queen_id, cfg, manager), proposal)
        except Exception:
            logger.warning("soul: probing %s failed", queen_id, exc_info=True)

    manager.spawn_background(run())
    return web.json_response({"started": True}, status=202)


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/queen/{queen_id}/soul", handle_get_soul)
    app.router.add_put("/api/queen/{queen_id}/soul", handle_put_soul)
    app.router.add_post("/api/queen/{queen_id}/soul/proposals/{proposal_id}/decide", handle_decide)
    app.router.add_post("/api/queen/{queen_id}/soul/rollback", handle_rollback)
    app.router.add_post("/api/queen/{queen_id}/soul/reflect", handle_reflect)
    app.router.add_post("/api/queen/{queen_id}/soul/proposals/{proposal_id}/probe", handle_probe)
