"""The host: the voice that runs the table.

After each part of the day the host turns what happened into a script of beats, the way
a good game master runs an evening: open on the moment, cut between places, build each
roll up before the die falls and tell what it brought, let the player overhear what no
villager hears, then turn to the player. The page plays the beats one at a time.

The host retells; it never decides anything. Every check of the part gets its roll beat:
one the host leaves out is put back, so no die is ever skipped. If the model fails, a plain
script is built from the record, so the table never stalls. Every word is the story's language.
"""

from __future__ import annotations

from typing import Any

from . import dice, nature, overgod
from .llm import LLM, parse_json_object
from .world import World

KINDS = ("open", "scene", "roll", "aside", "turn")
SCENES = 7  # scenes and asides in one part, besides the opening, every roll and the turn
TEXT_LIMIT = 700


def _clip(value: Any, limit: int = TEXT_LIMIT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _band(world: World, band: str) -> str:
    return world.t.get("dice.bands").get(band, band)


def _roll_of(world: World, item: dict, ref: str) -> dict:
    """What the page needs to play one roll: the check, who rolled, what for, and what it brought."""
    check = item.get("check") or {}
    return {
        "ref": ref,
        "kind": item["type"],
        "what": item.get("what") or item.get("title") or "",
        "who": world.name(check.get("roller") or item.get("agent")),
        "roller": check.get("roller") or item.get("agent"),
        "place": item.get("place"),
        "outcome": item.get("outcome"),
        "public": item.get("public", ""),
        "check": check,
    }


def part_record(world: World, items: list[dict]) -> tuple[str, dict[str, dict]]:
    """The part's events as the host reads them, and its rolls by reference (R1, R2, ...)."""
    t = world.t
    sep = t("names.list_sep")
    lines: list[str] = []
    rolls: dict[str, dict] = {}
    for i in items:
        kind = i["type"]
        place = world.place_name(i.get("place")) if i.get("place") else ""
        if kind == "omen":
            if i.get("audience"):
                lines.append(t("host.r_felt", who=sep.join(world.name(a) for a in i["audience"]), text=i["text"]))
            else:
                lines.append(t("host.r_omen", place=place, text=i["text"]) if place else t("host.r_omen_all", text=i["text"]))
        elif kind in ("dream", "sign", "prophecy", "boon", "ledger"):
            by = t("host.to_you") if i.get("by") == "overgod" else world.name(i.get("by"))
            lines.append(t(f"host.r_{kind}", by=by, to=world.name(i.get("to")), place=place, text=i["text"]))
        elif kind == "stir":
            a = world.agents.get(i["agent"])
            if a is None:
                continue
            lines.append(t("host.r_stir", name=a.name, id=a.id, role=a.role, place=place, pid=i.get("place") or ""))
            if i.get("thought"):
                lines.append(t("host.r_thought", text=i["thought"]))
            for d in i.get("deeds") or []:
                if d["kind"] == "speech":
                    lines.append(t("host.r_said", to=world.name(d["to"]) if d.get("to") else t("host.everyone"), text=d["text"]))
                elif d["kind"] == "clue":
                    lines.append(t("host.r_found", text=d["text"]))
                else:
                    lines.append(t("host.r_did", text=d["text"]))
            for f in i.get("failures") or []:
                lines.append(t("host.r_failed", text=f))
        elif kind in ("attempt", "undertaking"):
            if not i.get("check"):
                if i.get("outcome") == "unattempted":
                    lines.append(t("host.r_nobody", title=i.get("title", ""), place=place))
                continue
            ref = f"R{len(rolls) + 1}"
            roll = rolls[ref] = _roll_of(world, i, ref)
            line = dice.line(t, roll["check"], roll["who"])
            if kind == "attempt":
                lines.append(
                    t(
                        "host.r_attempt",
                        ref=ref,
                        who=roll["who"],
                        id=roll["roller"],
                        place=place,
                        pid=i.get("place") or "",
                        what=roll["what"],
                        band=_band(world, roll["outcome"]),
                        public=roll["public"],
                        dice=line,
                    )
                )
            else:
                people = sep.join(world.name(a) for a in i.get("present") or [])
                lines.append(
                    t(
                        "host.r_undertaking",
                        ref=ref,
                        title=roll["what"],
                        place=place,
                        pid=i.get("place") or "",
                        people=people,
                        band=_band(world, roll["outcome"]),
                        public=roll["public"],
                        dice=line,
                    )
                )
        elif kind == "proposal":
            when = world.wave_name(i["when"]) if isinstance(i.get("when"), int) else ""
            lines.append(
                t("host.r_proposal", who=world.name(i["agent"]), title=i["title"], goal=i["goal"], place=world.place_name(i.get("site")), when=when)
            )
        elif kind == "prayer":
            to = {"overgod": t("host.to_you"), "master": world.name("outer"), "ullr": world.name("ullr")}.get(i.get("to"), world.name("god"))
            lines.append(t("host.r_prayer", who=world.name(i["agent"]), to=to, text=i["text"]))
        elif kind in ("god", "star", "ullr") and i.get("thought"):
            by = world.name({"god": "god", "star": "outer", "ullr": "ullr"}[kind])
            lines.append(t("host.r_god", by=by, text=_clip(i["thought"], 300)))
        elif kind == "overgod":
            lines.append(t("host.r_you", name=i.get("name", ""), what=i.get("what", "")))
        elif kind == "chapter":
            lines.append(t("host.r_chapter", title=i.get("title", "")))
    return "\n".join(lines) or t("host.none"), rolls


def _context(world: World, last_turn: str) -> dict[str, str]:
    t = world.t
    view = overgod.view(world)
    powers = [
        t("host.power", id=p["id"], name=p["name"], cost=p["cost"]) + ("" if p["affordable"] else t("host.power_short"))
        for p in view["powers"]
        if not p["locked"]
    ]
    chapter = next((f"{c['title']}: {c['goal']}" for c in view["chapters"] if c["status"] == "current"), "")
    return {
        "day": str(world.day),
        "hour": world.wave_name(world.wave),
        "weather": world.hidden.get("weather", ""),
        "state": nature.describe_state(world),
        "awe": f"{view['awe']:g}",
        "tier": view["tier_name"],
        "chapter": chapter,
        "powers": t("names.list_sep").join(powers),
        "last": t("host.last", text=last_turn) if last_turn else "",
        "night": t("host.night") if world.wave == 5 else "",
    }


def _named(world: World, text: str) -> list[str]:
    """The people a beat names, when the host forgot to tag them."""
    return [a.id for a in world.agents.values() if a.short and a.short in text]


def _place_in(world: World, text: str, who: list[str]) -> str | None:
    """The place a beat names, else where the people in it are."""
    named = [pid for pid, p in world.places.items() if p["name"] in text]
    if named:
        return named[0]
    locs = [world.agents[w].loc for w in who if world.agents[w].loc]
    return locs[0] if locs else None


def plain_script(world: World, items: list[dict], rolls: dict[str, dict]) -> dict:
    """A script without the model: the moment, each villager's deeds, every roll, the turn."""
    t = world.t
    beats: list[dict] = []
    for i in items:
        if i["type"] != "stir":
            continue
        said = []
        for d in i.get("deeds") or []:
            if d["kind"] == "speech":
                to = world.name(d["to"]) if d.get("to") else t("host.everyone")
                said.append(t("host.plain_said", who=world.name(i["agent"]), to=to, text=d["text"]))
            elif d["kind"] != "clue":
                said.append(d["text"])
        if said:
            beats.append({"kind": "scene", "place": i.get("place"), "who": [i["agent"]], "text": _clip(" ".join(said))})
    return normalize(world, {"beats": beats[:SCENES]}, rolls)


def normalize(world: World, raw: dict, rolls: dict[str, dict]) -> dict:
    """Keep the beats that make sense, attach each roll's real check, and put back any roll the host left out."""
    t = world.t
    beats: list[dict] = []
    used: set[str] = set()
    for b in raw.get("beats") or []:
        if not isinstance(b, dict) or b.get("kind") not in KINDS:
            continue
        kind = b["kind"]
        if kind == "roll":
            ref = str(b.get("ref") or "").strip().upper()
            if ref not in rolls or ref in used:
                continue
            used.add(ref)
            beats.append(
                {"kind": "roll", "before": _clip(b.get("before")), "after": _clip(b.get("after")) or rolls[ref]["public"], "roll": rolls[ref]}
            )
            continue
        text = _clip(b.get("text"))
        if not text:
            continue
        beat: dict[str, Any] = {"kind": kind, "text": text}
        if kind == "scene":
            who = [w for w in (b.get("who") or []) if w in world.agents] or _named(world, text)
            place = b.get("place") if b.get("place") in world.places else _place_in(world, text, who)
            beat["place"], beat["who"] = place, who[:6]
        elif kind == "aside":
            if b.get("who") not in world.agents:
                continue
            beat["who"] = b["who"]
        elif kind == "turn":
            beat["powers"] = [p for p in (b.get("powers") or []) if p in overgod.powers(world)][:3]
        beats.append(beat)
    turn = [b for b in beats if b["kind"] == "turn"][-1:]
    told = 0
    kept = []
    for b in beats:
        if b["kind"] in ("scene", "aside"):
            told += 1
            if told > SCENES:
                continue
        if b["kind"] != "turn":
            kept.append(b)
    beats = kept
    for ref, roll in rolls.items():  # no die is ever skipped
        if ref not in used:
            beats.append({"kind": "roll", "before": t("host.auto_before", who=roll["who"], what=roll["what"]), "after": roll["public"], "roll": roll})
    if not beats or beats[0]["kind"] != "open":
        weather = world.hidden.get("weather", "")
        beats.insert(0, {"kind": "open", "text": t("host.auto_open", day=world.day, hour=world.wave_name(world.wave), weather=weather)})
    beats += turn or [{"kind": "turn", "text": t("host.auto_turn"), "powers": []}]
    return {"title": _clip(raw.get("title"), 60), "beats": beats}


class LLMHost:
    """One model call per part of the day."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def tell(self, world: World, items: list[dict], last_turn: str = "") -> dict:
        record, rolls = part_record(world, items)
        t = world.t
        vale = world.story.get("story", {}).get("vale", world.cfg["vale"]["name"])
        messages = [
            {
                "role": "system",
                "content": t("host.system", vale=vale, language=t("host.language"), premise=world.story.get("story", {}).get("premise", "")),
            },
            {"role": "user", "content": t("host.user", record=record, refs=", ".join(rolls) or "-", **_context(world, last_turn))},
        ]
        try:
            return normalize(world, parse_json_object(self.llm.chat(messages, temperature=0.8, max_tokens=3000)), rolls)
        except (ValueError, RuntimeError) as exc:
            script = plain_script(world, items, rolls)
            script["error"] = str(exc)[:300]
            return script


class StubHost:
    """The plain script, for testing the plumbing."""

    def tell(self, world: World, items: list[dict], last_turn: str = "") -> dict:
        return plain_script(world, items, part_record(world, items)[1])
