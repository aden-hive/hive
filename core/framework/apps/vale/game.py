"""A game of the vale on Hive: one world, stepped a part of the day at a time, with the player as the One Above.

``GameManager`` keeps games under ``$HIVE_HOME/apps/vale/games/<id>/`` and loads them on
demand. A ``Game`` runs at most one step at a time:

1. the One Above's queued acts land;
2. at dawn, the dawn's work (the hidden world, the gods, undertakings set for dawn) and Awe;
3. arrivals and undertakings whose hour has come;
4. the stirred villagers, each a Hive agent, up to six at once;
5. the dice for whatever was tried alone, and word travelling along the roads;
6. chapters that came true; after night, the day's summary;
7. the host, who turns the part of the day into a script of beats for the table;
8. after night, the host writes the day as a chapter of the novel, in the background.

Every change lands in the run's ``log.jsonl``. The game turns new log lines into feed items
(``feed.jsonl``) and pushes them to whoever is watching as each villager finishes; while
villagers act, their deeds are pushed live as they happen. The page plays the host's beats.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

from framework.host.event_bus import AgentEvent, EventBus, EventType

from . import engine, novel, overgod, physics, villager
from .fate import LLMFate
from .god import LLMGod, ledger_text
from .host import LLMHost
from .lang import Phrases
from .llm import HiveChat, build_provider
from .novel import LLMNovelist
from .outer import LLMOuter
from .ullr import LLMUllr
from .world import WAVES, World, story_art, story_dir

DAYS = 30
# The physics of the later experiments: enough energy, and all three of the vale's gods.
PHYSICS = {"refill": 1.5, "god_grace": 1.0, "outer_god": 1.0, "ullr_agent": 1.0}
CONCURRENT_VILLAGERS = 6
FEED_TAIL = 300

COLORS = {
    "hal": "#c98b2b",
    "maud": "#3f7d6e",
    "aldric": "#7a4b9c",
    "osric": "#9a3b3b",
    "brannoc": "#b4542b",
    "isolde": "#5a6fb0",
    "gytha": "#4f8a3a",
    "bram": "#8a7a52",
    "wynn": "#d16a8f",
    "tobias": "#5e7f9e",
    "marta": "#b07a3c",
    "cedric": "#8f8a2e",
    "elspeth": "#3f8fa0",
    "kell": "#55703a",
    "bagel": "#e89ab8",
}

logger = logging.getLogger(__name__)


class GameError(RuntimeError):
    """Something the game cannot do now (finished, unknown power, ...)."""


def _persona_section(md: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


class Game:
    def __init__(self, gid: str, path: Path, *, powers: engine.Powers | None = None, villager_llm=None, host=None, novelist=None) -> None:
        self.id = gid
        self.dir = path
        self.meta: dict[str, Any] = json.loads((path / "meta.json").read_text("utf-8"))
        self.world = World(path)
        settings = self.meta.get("settings") or {}
        self.chat = HiveChat(settings)
        self.powers = powers or engine.Powers(fate=LLMFate(self.chat), god=LLMGod(self.chat), outer=LLMOuter(self.chat), ullr=LLMUllr(self.chat))
        self._villager_llm = villager_llm
        self.host = host or LLMHost(self.chat)
        self._unhosted: list[dict] = []  # feed items the host has not told yet
        self.novelist = novelist or LLMNovelist(self.chat)
        self.writing: set[int] = set()  # days whose chapter is being written now
        self._chapters: set[asyncio.Task] = set()
        self._settings = settings
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None
        self.phase = ""
        self._stop = False
        self._subscribers: set[asyncio.Queue] = set()
        self._sig_texts: dict[str, dict] = {}
        self.bus = EventBus()
        self.bus.subscribe([EventType.LLM_TURN_COMPLETE], self._on_llm_turn)
        self._snapshot: dict[str, Any] = {}
        self._refresh()

    # ------------------------------------------------------------------ the model

    @property
    def villager_llm(self):
        if self._villager_llm is None:
            self._villager_llm = build_provider(self._settings, temperature=0.95, timeout=60.0)
        return self._villager_llm

    async def _on_llm_turn(self, event: AgentEvent) -> None:
        usage = self.meta.setdefault("usage", {})
        d = event.data or {}
        usage["villager_calls"] = usage.get("villager_calls", 0) + 1
        usage["tokens_in"] = usage.get("tokens_in", 0) + int(d.get("input_tokens") or 0)
        usage["tokens_out"] = usage.get("tokens_out", 0) + int(d.get("output_tokens") or 0)
        usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + float(d.get("cost_usd") or 0.0), 6)

    # ------------------------------------------------------------------ clock and status

    @property
    def clock(self) -> dict[str, int]:
        """The part of the day that runs next."""
        return self.world.hidden.setdefault("clock", {"day": 1, "wave": 0})

    @property
    def finished(self) -> bool:
        return self.clock["day"] > int(self.meta.get("days", DAYS))

    @property
    def status(self) -> str:
        if self.finished:
            return "finished"
        return "running" if (self.task and not self.task.done()) or self.lock.locked() else "idle"

    # ------------------------------------------------------------------ watching

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _publish(self, item: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass  # a stalled watcher misses live items; the feed file still has them

    def feed(self, after: int = 0, limit: int = FEED_TAIL) -> list[dict]:
        path = self.dir / "feed.jsonl"
        if not path.exists():
            return []
        items = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
        items = [i for i in items if i["seq"] > after]
        return items[-limit:]

    def _pump(self) -> list[dict]:
        """Turn the log lines written since last time into feed items, keep them, and push them to watchers."""
        self.world.flush()
        log = self.dir / "log.jsonl"
        offset = int(self.meta.get("log_offset", 0))
        with log.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # only whole lines
        if end <= 0:
            return []
        self.meta["log_offset"] = offset + end
        items = []
        for raw in chunk[:end].decode("utf-8").splitlines():
            if raw.strip():
                item = self._to_feed(json.loads(raw))
                if item:
                    items.append(item)
        seq = int(self.meta.get("feed_seq", 0))
        with (self.dir / "feed.jsonl").open("a", encoding="utf-8") as out:
            for item in items:
                seq += 1
                item["seq"] = seq
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
        self.meta["feed_seq"] = seq
        self._save_meta()
        self._unhosted.extend(i for i in items if i["type"] != "host")
        for item in items:
            self._publish(item)
        return items

    def _to_feed(self, e: dict) -> dict | None:
        """One log event as the player's page shows it, or None for the physics' small talk."""
        ev, base = e["ev"], {"day": e.get("day", 0), "wave": e.get("wave", 0)}
        if ev == "signal":
            self._sig_texts[e["id"]] = {"kind": e["kind"], "text": e["text"], "to": e.get("to"), "source": e["source"]}
            if len(self._sig_texts) > 4000:
                for k in list(self._sig_texts)[:1000]:
                    del self._sig_texts[k]
            src, kind = e["source"], e["kind"]
            if kind == "omen" and src in ("world", "overgod"):
                private = bool(e.get("audience")) and src == "world"  # an ache only its sufferers feel
                return {
                    **base,
                    "type": "omen",
                    "place": e.get("loc"),
                    "text": e["text"],
                    "by": src,
                    "private": private,
                    "audience": e.get("audience") if private else None,
                }
            if kind in ("sign", "prophecy", "dream", "boon") or (kind == "ledger" and src == "overgod"):
                return {
                    **base,
                    "type": kind,
                    "by": src,
                    "place": e.get("loc"),
                    "to": (e.get("audience") or [None])[0] if kind == "dream" else None,
                    "text": e["text"],
                }
            return None
        if ev == "activation":
            said = [self._sig_texts[s] for s in e.get("emitted") or [] if s in self._sig_texts]
            return {
                **base,
                "type": "stir",
                "agent": e["agent"],
                "place": e.get("place"),
                "thought": e.get("thought", ""),
                "done": e.get("done", []),
                "failures": e.get("failures", []),
                "mood": e.get("mood", ""),
                "error": e.get("error"),
                "deeds": [{"kind": s["kind"], "to": s.get("to"), "text": s["text"]} for s in said],
                "parent": e.get("parent"),
            }
        if ev == "outcome":
            return {
                **base,
                "type": "undertaking",
                "title": e["title"],
                "place": e["place"],
                "present": e.get("present", []),
                "outcome": e["outcome"],
                "public": e["public"],
                "check": e.get("check"),
                "applied": e.get("applied", []),
            }
        if ev == "attempt":
            return {
                **base,
                "type": "attempt",
                "agent": e["agent"],
                "place": e["place"],
                "what": e["what"],
                "outcome": e["outcome"],
                "public": e["public"],
                "check": e.get("check"),
                "applied": e.get("applied", []),
            }
        if ev == "proposal":
            return {
                **base,
                "type": "proposal",
                "agent": e["proposer"],
                "title": e["title"],
                "goal": e["goal"],
                "site": e.get("site"),
                "when": e.get("when"),
                "due_day": e.get("due_day"),
            }
        if ev == "prayer":
            return {**base, "type": "prayer", "agent": e["agent"], "to": e.get("to"), "text": e["text"], "place": e.get("place")}
        if ev == "god":
            return {
                **base,
                "type": "god",
                "thought": e.get("thought", ""),
                "acts": e.get("acts", []),
                "ledger": [line["text"] for line in e.get("ledger") or []],
            }
        if ev == "outer":
            return {
                **base,
                "type": "star",
                "thought": e.get("thought", ""),
                "boon": e.get("boon"),
                "public": e.get("public", ""),
                "dream": e.get("dream", ""),
            }
        if ev == "ullr":
            return {**base, "type": "ullr", "thought": e.get("thought", ""), "acts": e.get("acts", []), "awake": e.get("awake")}
        if ev in ("overgod", "chapter", "awe"):
            return {**base, "type": ev, **{k: v for k, v in e.items() if k not in ("ev", "day", "wave")}}
        if ev == "host":
            return {**base, "type": "host", "title": e.get("title", ""), "beats": e.get("beats", []), "error": e.get("error")}
        if ev == "day":
            return {
                **base,
                "type": "night",
                "hidden": e.get("hidden"),
                "health": e.get("health"),
                "activations": e.get("activations"),
                "checks": e.get("checks"),
            }
        return None

    # ------------------------------------------------------------------ stepping

    def _set_now(self) -> None:
        """Make the world's clock the moment about to run, so whatever lands now is born then."""
        w = self.world
        w.day, w.wave = self.clock["day"], self.clock["wave"]
        w.today = w.hidden.get("today") or {"activations": 0, "tired": 0, "rumors": 0, "llm_errors": 0, "checks": 0}

    def _apply_queue(self) -> None:
        o = overgod.state(self.world)
        for x in o.pop("queue", []):
            try:
                overgod.act(self.world, x["power"], x.get("args"))
            except overgod.OvergodError as exc:
                self._publish({"type": "error", "message": f"{x['power']}: {exc}"})

    async def step(self) -> dict:
        """Run one part of the day."""
        async with self.lock:
            if self.finished:
                raise GameError(self.world.t("game.over"))
            w = self.world
            self._set_now()
            day, wave = w.day, w.wave
            self._apply_queue()
            if wave == 0:
                w.today = {"activations": 0, "tired": 0, "rumors": 0, "llm_errors": 0, "checks": 0}
                w.hidden["fired_today"] = []
                self._phase("dawn")
                await asyncio.to_thread(engine.dawn, w, self.powers)
                overgod.dawn(w, self._events_of(day - 1))
            self._phase("wave")
            await asyncio.to_thread(engine.wave_start, w, self.powers)
            self._pump()
            firings = physics.select(w)
            if firings:
                self._publish({"type": "stirred", "day": day, "wave": wave, "agents": [f.agent for f in firings]})
                gate = asyncio.Semaphore(CONCURRENT_VILLAGERS)

                async def one(f: physics.Firing) -> dict:
                    async with gate:
                        record = await villager.run_turn(w, f, self.villager_llm, bus=self.bus, emit=self._live)
                    self._pump()  # their turn reaches the page now, not with everyone else's at the end
                    return record

                await asyncio.gather(*(one(f) for f in firings))
                w.hidden["fired_today"] = w.hidden.get("fired_today", []) + [{"agent": f.agent, "tags": f.tags} for f in firings]
            self._phase("settling")
            await asyncio.to_thread(engine.wave_end, w, self.powers)
            overgod.advance_chapters(w)
            if wave == len(WAVES) - 1:
                fired = [physics.Firing(x["agent"], 0.0, 0.0, [], None, x["tags"]) for x in w.hidden.get("fired_today", [])]
                engine.night(w, fired)
                self.clock.update(day=day + 1, wave=0)
            else:
                self.clock.update(day=day, wave=wave + 1)
            w.hidden["today"] = w.today
            w.save()
            self._pump()
            await self._tell(day, wave)
            if wave == len(WAVES) - 1:
                self.write_chapter(day)
            self._phase("")
            self._refresh()
            self._publish({"type": "state", "status": self.status, "clock": dict(self.clock)})
            return {"day": day, "wave": wave, "stirred": len(firings)}

    async def _tell(self, day: int, wave: int) -> None:
        """The host scripts the part of the day just played, and the script goes out like any other item."""
        w = self.world
        items, self._unhosted = self._unhosted, []
        self._phase("host")
        w.day, w.wave = day, wave
        try:
            script = await asyncio.to_thread(self.host.tell, w, items, w.hidden.get("host_last", ""))
        except Exception as exc:  # the table never stalls on its host
            logger.exception("vale game %s: the host failed", self.id)
            script = {"title": "", "beats": [], "error": str(exc)[:300]}
        turn = [b["text"] for b in script.get("beats", []) if b.get("kind") == "turn"]
        if turn:
            w.hidden["host_last"] = turn[-1]
        w.log("host", title=script.get("title", ""), beats=script.get("beats", []), error=script.get("error"))
        w.save()
        self._pump()

    def write_chapter(self, day: int) -> None:
        """Write a finished day as a chapter of the novel, in the background: the vale does not wait for its author."""
        if day in self.writing:
            raise GameError(self.world.t("game.writing", day=day))
        if not (1 <= day < self.clock["day"]):
            raise GameError(self.world.t("game.not_over", day=day))
        # The record is read here, on the game's loop, where the world is safe to read.
        draft = self.novelist.prepare(self.world, self.dir, day, novel.day_items(self.dir, day), self.world.hidden.get("weather", ""))
        self.writing.add(day)
        self._publish({"type": "novel_writing", "day": day})
        task = asyncio.create_task(self._compose(day, draft))
        self._chapters.add(task)
        task.add_done_callback(self._chapters.discard)

    async def _compose(self, day: int, draft: dict) -> None:
        try:
            chapter = await asyncio.to_thread(self.novelist.compose, draft)
            novel.save(self.dir, day, chapter)
            self._publish({"type": "novel", "day": day, "title": chapter["title"]})
        except Exception as exc:  # a chapter that fails can be written again; the vale goes on
            logger.exception("vale game %s: chapter %d failed", self.id, day)
            self._publish({"type": "novel_error", "day": day, "message": str(exc)[:300]})
        finally:
            self.writing.discard(day)

    def _live(self, item: dict) -> None:
        self._publish({**item, "day": self.world.day, "wave": self.world.wave, "live": True})

    def _phase(self, phase: str) -> None:
        self.phase = phase
        self._publish({"type": "phase", "phase": phase, "clock": dict(self.clock)})

    def _events_of(self, day: int) -> list[dict]:
        self.world.flush()
        out = []
        with (self.dir / "log.jsonl").open(encoding="utf-8") as f:
            for line in f:
                if f'"day": {day},' in line:
                    out.append(json.loads(line))
        return out

    def run(self, waves: int | None = None) -> None:
        """Advance in the background: ``waves`` parts of the day, or until stopped (autoplay)."""
        if self.task and not self.task.done():
            raise GameError(self.world.t("game.moving"))
        if self.finished:
            raise GameError(self.world.t("game.over"))
        self._stop = False
        self.meta["autoplay"] = waves is None
        self.task = asyncio.create_task(self._run(waves))

    def stop(self) -> None:
        """Stop after the part of the day that is running now."""
        self._stop = True
        self.meta["autoplay"] = False

    async def _run(self, waves: int | None) -> None:
        done = 0
        try:
            while not self._stop and not self.finished and (waves is None or done < waves):
                await self.step()
                done += 1
        except Exception as exc:
            logger.exception("vale game %s stopped", self.id)
            self._publish({"type": "error", "message": f"the vale stopped: {exc}"})
        finally:
            self.meta["autoplay"] = False
            self._save_meta()
            self._refresh()
            self._publish({"type": "state", "status": self.status, "clock": dict(self.clock)})

    # ------------------------------------------------------------------ the One Above

    async def act(self, power: str, args: dict | None = None) -> dict:
        """The player's act: now if the vale is still, else at the turn of the next part of the day."""
        overgod.clean(self.world, power, args)  # fail fast on anything unknown, locked or malformed
        o = overgod.state(self.world)
        queued = sum(overgod.POWERS[x["power"]].cost for x in o.get("queue", []))
        if o["awe"] + 1e-9 < queued + overgod.POWERS[power].cost:
            raise overgod.OvergodError(self.world.t("overgod.err_queue", queued=f"{queued:g}"))
        if self.lock.locked() or (self.task and not self.task.done()):
            o.setdefault("queue", []).append({"power": power, "args": args or {}})
            self._publish({"type": "queued", "power": power})
            return {"queued": True, "power": power}
        async with self.lock:
            self._set_now()
            record = overgod.act(self.world, power, args)
            overgod.advance_chapters(self.world)
            self.world.save()
            self._pump()
            self._refresh()
            self._publish({"type": "state", "status": self.status, "clock": dict(self.clock)})
            return record

    # ------------------------------------------------------------------ what the page reads

    def _refresh(self) -> None:
        """Rebuild the snapshot the page reads. Only at safe points: never while the world is mid-change."""
        w = self.world
        h = w.hidden
        villagers = []
        for a in w.agents.values():
            villagers.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "short": a.short,
                    "role": a.role,
                    "public": a.public,
                    "color": COLORS.get(a.id, "#888"),
                    "loc": a.loc,
                    "travel": a.travel,
                    "health": a.health,
                    "mood": a.mood,
                    "reserve": a.reserve,
                    "items": {k: v for k, v in a.items.items() if v > 0},
                    "skills": a.skills,
                    "recent": a.recent,
                    "memory": w.read_memory(a.id),
                    "confined": a.confined,
                }
            )
        due = [
            {"id": p.id, "title": p.title, "site": p.site or p.place, "when": p.when, "due_day": p.due_day, "supporters": list(p.supporters)}
            for p in w.projects.values()
            if p.status == "due"
        ]
        usage = dict(self.meta.get("usage", {}))
        usage.update(world_calls=self.chat.calls, world_cost_usd=round(self.chat.cost_usd, 6))
        self._snapshot = {
            "id": self.id,
            "name": self.meta.get("name", self.id),
            "lang": w.lang,
            "story": {k: w.story.get("story", {}).get(k, "") for k in ("id", "title", "blurb")},
            "waves": list(w.t.get("time.waves")),
            "gods": {g: w.story.get("gods", {}).get("titles", {}).get(g) or w.name(g) for g in ("god", "outer", "ullr", "overgod")},
            "skills": dict(w.t.get("names.skills")),
            "goods": {gid: spec.get("name", gid) for gid, spec in w.story.get("items", {}).items()},
            "art": story_art(self.meta.get("story", "ashmere")),
            "days": int(self.meta.get("days", DAYS)),
            "clock": dict(self.clock),
            "last": {"day": w.day, "wave": w.wave},
            "places": [{k: p[k] for k in ("id", "name", "desc", "x", "y", "roads")} for p in w.places.values()],
            "villagers": villagers,
            "truth": {
                "blight": h["blight"],
                "sickness": h["sickness"],
                "wolves": h["wolves"],
                "shaft_open": h["shaft_open"],
                "stone_raised": h["stone_raised"],
                "ullr_awake": h.get("ullr_awake", 0),
                "stone_hum": h.get("stone_hum", 0),
                "weather": h.get("weather", ""),
                "weather_kind": h.get("weather_kind", ""),
                "winter": h.get("winter_until", 0) >= w.day,
            },
            "ledger": ledger_text(w),
            "undertakings": due,
            "overgod": overgod.view(w),
            "queue": overgod.state(w).get("queue", []),
            "usage": usage,
            "settings": {k: v for k, v in self._settings.items() if k != "api_key"},
        }

    def snapshot(self) -> dict[str, Any]:
        return {**self._snapshot, "status": self.status, "phase": self.phase, "autoplay": bool(self.meta.get("autoplay"))}

    def villager(self, vid: str) -> dict[str, Any]:
        """Everything about one villager, including what nobody in the vale knows: the One Above sees it all."""
        if vid not in self.world.agents:
            raise GameError(self.world.t("game.no_villager", vid=vid))
        persona = self.world.personas[vid]
        heads = {"want": "What you want", "rules": "Rules you live by", "deeper": "Deeper still", **self.world.story.get("persona", {})}
        hist = sorted((self.dir / "agents" / vid / "history").glob("day_*.md"))
        return {
            "id": vid,
            "persona": persona,
            "want": _persona_section(persona, heads["want"]),
            "deeper": _persona_section(persona, heads["deeper"]),
            "rules": [ln[2:].strip() for ln in _persona_section(persona, heads["rules"]).splitlines() if ln.startswith("- ")],
            "history": [{"day": int(p.stem.split("_")[1]), "text": p.read_text("utf-8").strip()} for p in hist],
            "knows": self.world.agents[vid].knows,
        }

    def _save_meta(self) -> None:
        tmp = self.dir / "meta.json.tmp"
        tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.dir / "meta.json")

    async def close(self) -> None:
        self.stop()
        if self.task and not self.task.done():
            try:
                await asyncio.wait_for(self.task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()
        for task in list(self._chapters):  # an unfinished chapter can be written again later
            task.cancel()
        self._save_meta()
        self.world.close()


class GameManager:
    """All the games under one directory, loaded on demand and kept loaded."""

    def __init__(self, root: Path | None = None, *, game_factory=Game) -> None:
        if root is None:
            from framework.config import HIVE_HOME

            root = HIVE_HOME / "apps" / "vale" / "games"
        self.root = root  # made on the first game, so merely mounting the app writes nothing
        self._games: dict[str, Game] = {}
        self._factory = game_factory

    def list(self) -> list[dict[str, Any]]:
        out = []
        for meta_path in sorted(self.root.glob("*/meta.json")):
            meta = json.loads(meta_path.read_text("utf-8"))
            gid = meta_path.parent.name
            live = self._games.get(gid)
            out.append(
                {
                    "id": gid,
                    "name": meta.get("name", gid),
                    "story": meta.get("story", "ashmere"),
                    "lang": meta.get("lang", "en"),
                    "waves": list(Phrases(meta.get("lang", "en")).get("time.waves")),
                    "created": meta.get("created"),
                    "days": meta.get("days", DAYS),
                    "clock": live.snapshot()["clock"] if live else meta.get("clock"),
                    "status": live.status if live else "idle",
                }
            )
        return out

    def create(
        self, name: str = "", *, seed: int | None = None, settings: dict | None = None, days: int = DAYS, story: str = "ashmere", lang: str = "en"
    ) -> Game:
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "vale").lower()).strip("-")[:24] or "vale"
        gid = f"{slug}-{uuid.uuid4().hex[:6]}"
        path = self.root / gid
        template = story_dir(story, lang)  # fails before anything is written if the story has no such language
        self.root.mkdir(parents=True, exist_ok=True)
        World.create(path, template=template, seed=seed if seed is not None else int(time.time()) % 100000, overrides=PHYSICS).close()
        meta = {
            "story": story,
            "lang": lang,
            "name": name or tomllib.loads((template / "story.toml").read_text("utf-8")).get("story", {}).get("title", story),
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "days": int(days),
            "settings": {k: v for k, v in (settings or {}).items() if k in ("model", "api_base", "api_key_env") and v},
        }
        (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        return self.get(gid)

    def get(self, gid: str) -> Game:
        if gid not in self._games:
            path = self.root / gid
            if not (path / "meta.json").exists() or path.parent != self.root:
                raise KeyError(gid)
            self._games[gid] = self._factory(gid, path)
        return self._games[gid]

    async def delete(self, gid: str) -> None:
        game = self._games.pop(gid, None)
        if game:
            await game.close()
        path = self.root / gid
        if path.parent == self.root and (path / "meta.json").exists():
            shutil.rmtree(path)

    async def close(self) -> None:
        for game in list(self._games.values()):
            await game.close()
        self._games.clear()
