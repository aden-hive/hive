"""HTTP API for the vale game, mounted on the Hive server under ``/api/vale``.

GET    /api/vale/stories                     the story packs and the languages each is written in
GET    /api/vale/art/{story}/{name}          a painted picture from a story's art/ folder
GET    /api/vale/games                       the games
POST   /api/vale/games                       a new game {name, story?, lang?, days?, seed?, settings?: {model, api_base, api_key_env}}
GET    /api/vale/games/{gid}                 the page's snapshot: clock, villagers, the truth, the One Above
DELETE /api/vale/games/{gid}
GET    /api/vale/games/{gid}/feed?after=&limit=   what has happened, oldest first
GET    /api/vale/games/{gid}/events          the same, live (Server-Sent Events)
POST   /api/vale/games/{gid}/advance         {waves: n}: run n parts of the day in the background
POST   /api/vale/games/{gid}/autoplay        {on: bool}
POST   /api/vale/games/{gid}/act             {power, args}: the One Above acts
GET    /api/vale/games/{gid}/villagers/{vid} one villager, all of them
GET    /api/vale/games/{gid}/novel           the novel so far: one chapter per finished day
POST   /api/vale/games/{gid}/novel/{day}     write (or write again) one day's chapter, in the background
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from framework.server.sse import SSEResponse

from . import novel
from .game import GameError, GameManager
from .overgod import OvergodError
from .world import art_file, stories

logger = logging.getLogger(__name__)
KEEPALIVE_SECONDS = 15
VALE = web.AppKey("vale", GameManager)


def _manager(request: web.Request) -> GameManager:
    return request.app[VALE]


def _game(request: web.Request):
    try:
        return _manager(request).get(request.match_info["gid"])
    except KeyError:
        raise web.HTTPNotFound(text='{"error": "no such game"}', content_type="application/json") from None


async def _body(request: web.Request) -> dict:
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text='{"error": "the body is not JSON"}', content_type="application/json") from None
    return data if isinstance(data, dict) else {}


def _refused(exc: Exception, status: int = 409) -> web.Response:
    return web.json_response({"error": str(exc)}, status=status)


async def list_games(request: web.Request) -> web.Response:
    return web.json_response({"games": _manager(request).list()})


async def create_game(request: web.Request) -> web.Response:
    body = await _body(request)
    try:
        days = max(1, min(60, int(body.get("days") or 30)))
        seed = int(body["seed"]) if body.get("seed") not in (None, "") else None
    except (TypeError, ValueError):
        return _refused(ValueError("days and seed are whole numbers"), 400)
    story, lang = str(body.get("story") or "ashmere"), str(body.get("lang") or "en")
    try:
        game = _manager(request).create(
            str(body.get("name") or "")[:80], seed=seed, settings=body.get("settings") or {}, days=days, story=story, lang=lang
        )
    except FileNotFoundError:
        return _refused(ValueError(f"no story {story!r} in language {lang!r}"), 400)
    return web.json_response(game.snapshot(), status=201)


async def list_stories(request: web.Request) -> web.Response:
    return web.json_response({"stories": stories()})


async def get_art(request: web.Request) -> web.StreamResponse:
    path = art_file(request.match_info["story"], request.match_info["name"])
    if path is None:
        raise web.HTTPNotFound(text='{"error": "no such picture"}', content_type="application/json")
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})


async def get_game(request: web.Request) -> web.Response:
    return web.json_response(_game(request).snapshot())


async def delete_game(request: web.Request) -> web.Response:
    _game(request)
    await _manager(request).delete(request.match_info["gid"])
    return web.json_response({"deleted": request.match_info["gid"]})


async def get_feed(request: web.Request) -> web.Response:
    try:
        after = int(request.query.get("after", 0))
        limit = max(1, min(2000, int(request.query.get("limit", 300))))
    except ValueError:
        return _refused(ValueError("after and limit are whole numbers"), 400)
    return web.json_response({"items": _game(request).feed(after, limit)})


async def stream_events(request: web.Request) -> web.StreamResponse:
    game = _game(request)
    sse = SSEResponse()
    resp = await sse.prepare(request)
    q = game.subscribe()
    try:
        await sse.send_event({"type": "state", "status": game.status, "clock": game.snapshot()["clock"]}, event="state")
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_SECONDS)
            except TimeoutError:
                await sse.send_keepalive()
                continue
            await sse.send_event(item, event=item.get("type", "message"))
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        game.unsubscribe(q)
    return resp


async def advance(request: web.Request) -> web.Response:
    game = _game(request)
    body = await _body(request)
    try:
        waves = max(1, min(6 * 31, int(body.get("waves") or 1)))
    except (TypeError, ValueError):
        return _refused(ValueError("waves is a whole number"), 400)
    try:
        game.run(waves)
    except GameError as exc:
        return _refused(exc)
    return web.json_response({"running": True, "waves": waves}, status=202)


async def autoplay(request: web.Request) -> web.Response:
    game = _game(request)
    body = await _body(request)
    if body.get("on"):
        try:
            game.run(None)
        except GameError as exc:
            return _refused(exc)
        return web.json_response({"autoplay": True}, status=202)
    game.stop()
    return web.json_response({"autoplay": False})


async def act(request: web.Request) -> web.Response:
    game = _game(request)
    body = await _body(request)
    try:
        record = await game.act(str(body.get("power") or ""), body.get("args") or {})
    except OvergodError as exc:
        return _refused(exc, 400)
    except GameError as exc:
        return _refused(exc)
    return web.json_response({"result": record, "game": game.snapshot()})


async def get_villager(request: web.Request) -> web.Response:
    try:
        return web.json_response(_game(request).villager(request.match_info["vid"]))
    except GameError as exc:
        return _refused(exc, 404)


async def _close(app: web.Application) -> None:
    await app[VALE].close()


async def get_novel(request: web.Request) -> web.Response:
    game = _game(request)
    return web.json_response({"chapters": novel.chapters(game.dir), "writing": sorted(game.writing)})


async def write_chapter(request: web.Request) -> web.Response:
    game = _game(request)
    try:
        day = int(request.match_info["day"])
        game.write_chapter(day)
    except ValueError:
        return _refused(ValueError("day is a whole number"), 400)
    except GameError as exc:
        return _refused(exc)
    return web.json_response({"writing": day}, status=202)


def register_routes(app: web.Application, manager: GameManager | None = None) -> None:
    """Mount the vale on a Hive server."""
    app[VALE] = manager or GameManager()
    app.on_cleanup.append(_close)
    r = app.router
    r.add_get("/api/vale/stories", list_stories)
    r.add_get("/api/vale/art/{story}/{name:.+}", get_art)
    r.add_get("/api/vale/games", list_games)
    r.add_post("/api/vale/games", create_game)
    r.add_get("/api/vale/games/{gid}", get_game)
    r.add_delete("/api/vale/games/{gid}", delete_game)
    r.add_get("/api/vale/games/{gid}/feed", get_feed)
    r.add_get("/api/vale/games/{gid}/events", stream_events)
    r.add_post("/api/vale/games/{gid}/advance", advance)
    r.add_post("/api/vale/games/{gid}/autoplay", autoplay)
    r.add_post("/api/vale/games/{gid}/act", act)
    r.add_get("/api/vale/games/{gid}/villagers/{vid}", get_villager)
    r.add_get("/api/vale/games/{gid}/novel", get_novel)
    r.add_post("/api/vale/games/{gid}/novel/{day}", write_chapter)
