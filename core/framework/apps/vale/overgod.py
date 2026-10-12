"""The god beyond gods: the person playing.

Above the True God, the Star God and old Ullr there is one more power, and it is the
player. It spends Awe on whispers, omens, wrath and dominion. Awe returns a little each
dawn, and more when the vale prays to the voice above every voice or when the dice turn a
story. Chapters set what the vale should come to next; finishing one pays Awe and opens
the next tier of power.

What each power does is the engine's; what it is called, and what the vale sees when it
lands, is the story's (``story.toml``: ``[overgod]``), in the story's language.

Every act lands at a safe point between parts of the day (see ``game.py``), never while
villagers are mid-turn. Everything here is plain state in ``world.hidden["overgod"]``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .lang import fill
from .world import World

START_AWE = 3.0
AWE_CAP = 12.0
GODS = ("god", "outer", "ullr")


class OvergodError(ValueError):
    """An act the One Above cannot do now: unknown, locked, unaffordable or malformed."""


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # person | place | text | god | days


@dataclass(frozen=True)
class Power:
    id: str
    tier: int
    cost: float
    params: tuple[Param, ...]
    apply: Callable[[World, dict], str]


@dataclass(frozen=True)
class Chapter:
    id: str
    check: Callable[[World], bool]
    reward: float
    unlocks: int | None


def state(world: World) -> dict[str, Any]:
    """The One Above's own state, created on first use."""
    o = world.hidden.setdefault("overgod", {})
    o.setdefault("awe", START_AWE)
    o.setdefault("tier", 1)
    o.setdefault("chapter", 0)
    o.setdefault("known_by", [])
    o.setdefault("written", [])
    o.setdefault("revealed", [])
    o.setdefault("decrees", {})
    o.setdefault("income", [])
    o.setdefault("ever", {})
    return o


def _words(world: World) -> dict[str, Any]:
    return world.story.get("overgod", {})


def _say(world: World, key: str, **slots: Any) -> str:
    """One of the story's lines for the One Above's acts."""
    return fill(_words(world)[key], **slots)


def _names(world: World, people: list[str]) -> str:
    return world.t("names.list_sep").join(people)


# ---------------------------------------------------------------------------- what each power does


def _omen(world: World, text: str, loc: str | None, strength: float = 2.6, audience: list[str] | None = None, kind: str = "omen") -> str:
    return world.add_signal(kind, text, loc, "overgod", strength=strength, audience=audience).id


def _hurt(world: World, place: str, chance: float) -> list[str]:
    hurt = []
    for a in world.present(place):
        if world.rng.random() < chance:
            a.health = min(2, a.health + 1)
            hurt.append(a.short)
    return hurt


def _whisper(world: World, x: dict) -> str:
    o = state(world)
    world.add_signal("dream", x["text"], None, "overgod", audience=[x["to"]], strength=2.8)
    if x["to"] not in o["known_by"]:
        o["known_by"].append(x["to"])
    return world.t("overgod.whispered", name=world.name(x["to"]))


def _inscribe(world: World, x: dict) -> str:
    state(world)["written"].append(x["text"])
    world.add_signal("ledger", x["text"], None, "overgod", audience=list(world.agents), strength=1.6)
    return world.t("overgod.inscribed")


def _sign(world: World, x: dict) -> str:
    _omen(world, x["text"], x["at"], kind="sign")
    return world.t("overgod.signed", place=world.place_name(x["at"]))


def _prophecy(world: World, x: dict) -> str:
    o = state(world)
    world.add_signal("prophecy", x["text"], None, "overgod", audience=list(world.agents), strength=2.8)
    o["known_by"] = sorted(set(o["known_by"]) | set(world.agents))
    return world.t("overgod.prophesied")


def _reveal(world: World, x: dict) -> str:
    a = world.agents[x["who"]]
    where = a.loc or (a.travel or {}).get("to") or a.home
    _omen(world, _words(world).get("secrets", {})[a.id], where, strength=2.8)
    state(world)["revealed"].append(a.id)
    witnesses = [p.short for p in world.present(where) if p.id != a.id]
    t = world.t
    return t("overgod.revealed", name=a.name, place=world.place_name(where)) + (
        t("overgod.revealed_before", who=_names(world, witnesses)) if witnesses else t("overgod.revealed_alone")
    )


def _collector(world: World, x: dict) -> str:
    world.hidden.setdefault("events", []).append(("thornkeep", 2.8, _say(world, "collector_keep")))
    _omen(world, _say(world, "collector_word"), None, strength=2.2, audience=list(world.agents))
    return _say(world, "collector_done")


def _flood(world: World, x: dict) -> str:
    h = world.hidden
    b, sick = h["blight"], h["sickness"]
    b["mirewood"] = round(max(b["mirewood"], 0.9 * b["mill"]), 4)
    b["fenford"] = round(min(1.0, b["fenford"] + 0.2 * b["mill"] + 0.05), 4)
    for place in ("ashmere", "fenford", "mirewood"):
        sick[place] = round(min(1.0, sick.get(place, 0.0) + 0.1), 4)
        h["relief"].pop(place, None)
    _omen(world, _say(world, "flood"), None, strength=2.6, audience=list(world.agents))
    return _say(world, "flood_done")


def _earthquake(world: World, x: dict) -> str:
    h = world.hidden
    what = []
    if not h["shaft_open"] and world.rng.random() < 0.5:
        h["shaft_open"] = 1
        what.append(_say(world, "quake_seal"))
    else:
        h["blight"]["mine"] = round(min(1.0, h["blight"]["mine"] + 0.2), 4)
    if h["stone_raised"] and world.rng.random() < 0.4:
        h["stone_raised"] = 0
        what.append(_say(world, "quake_stone"))
    hurt = [n for place in ("mine", "chapel", "barrow_hill") for n in _hurt(world, place, 0.5)]
    _omen(world, _say(world, "quake"), None, strength=2.8, audience=list(world.agents))
    t = world.t
    return (
        _say(world, "quake_done")
        + (t("names.colon") + t("names.clause_sep").join(what) if what else "")
        + (_say(world, "hurt", who=_names(world, hurt)) if hurt else t("names.stop"))
    )


def _wildfire(world: World, x: dict) -> str:
    w = world.hidden["wolves"]
    w["hunger"] = round(min(1.0, w["hunger"] + 0.4), 4)
    hurt = _hurt(world, "mirewood", 0.5)
    _omen(world, _say(world, "fire"), None, strength=2.6, audience=list(world.agents))
    return _say(world, "fire_done") + (_say(world, "hurt", who=_names(world, hurt)) if hurt else ".")


def _plague(world: World, x: dict) -> str:
    sick = world.hidden["sickness"]
    if x["at"] in sick:
        sick[x["at"]] = round(min(1.0, sick[x["at"]] + 0.35), 4)
    hurt = _hurt(world, x["at"], 0.5)
    place = world.place_name(x["at"])
    _omen(world, _say(world, "plague", place=place), x["at"], strength=2.8)
    return _say(world, "plague_done", place=place) + (_say(world, "fevered", who=_names(world, hurt)) if hurt else ".")


def _winter(world: World, x: dict) -> str:
    world.hidden["winter_until"] = world.day + 3
    _omen(world, _say(world, "winter"), None, strength=2.4, audience=list(world.agents))
    return _say(world, "winter_done")


def _raiders(world: World, x: dict) -> str:
    taken = []
    for a in world.present(x["at"]):
        for item in ("coin", "goods", "ore", "flour", "game", "ale", "wool"):
            n = a.items.get(item, 0)
            if n > 0:
                a.items[item] = n // 2
                taken.append(a.short)
    hurt = _hurt(world, x["at"], 0.3)
    place = world.place_name(x["at"])
    _omen(world, _say(world, "raiders", place=place), x["at"], strength=2.8)
    return (
        _say(world, "raiders_done", place=place)
        + (_say(world, "robbed", who=_names(world, sorted(set(taken)))) if taken else "")
        + (_say(world, "hurt_semi", who=_names(world, hurt)) if hurt else ".")
    )


def _decree(world: World, x: dict) -> str:
    state(world)["decrees"][x["god"]] = {"text": x["text"], "until": world.day + int(x["days"])}
    title = world.story.get("gods", {}).get("titles", {}).get(x["god"], x["god"])
    return world.t("overgod.decreed", god=title, days=x["days"])


def _wake_ullr(world: World, x: dict) -> str:
    world.hidden["ullr_awake"] = max(int(world.hidden.get("ullr_awake", 0)), 3)
    _omen(world, _say(world, "wake"), "barrow_hill", strength=2.8)
    return _say(world, "wake_done")


def _bind_star(world: World, x: dict) -> str:
    state(world)["star_bound_until"] = world.day + int(x["days"])
    return world.t("overgod.star_bound", days=x["days"])


def _heal(world: World, x: dict) -> str:
    if x["at"] in world.hidden["sickness"]:
        world.hidden["sickness"][x["at"]] = 0.0
    for a in world.present(x["at"]):
        a.health = 0
    place = world.place_name(x["at"])
    _omen(world, _say(world, "healed", place=place), x["at"], strength=3.0)
    return _say(world, "healed_done", place=place)


def _cleanse(world: World, x: dict) -> str:
    if x["at"] in world.hidden["blight"]:
        world.hidden["blight"][x["at"]] = 0.0
    place = world.place_name(x["at"])
    _omen(world, _say(world, "cleansed", place=place), x["at"], strength=3.0)
    return _say(world, "cleansed_done", place=place)


def _raise_stone(world: World, x: dict) -> str:
    world.hidden["stone_raised"] = 1
    _omen(world, _say(world, "stone"), "barrow_hill", strength=3.0)
    return _say(world, "stone_done")


P_TO, P_AT, P_TEXT = Param("to", "person"), Param("at", "place"), Param("text", "text")
POWERS: dict[str, Power] = {
    p.id: p
    for p in (
        Power("whisper", 1, 1, (P_TO, P_TEXT), _whisper),
        Power("inscribe", 1, 1, (P_TEXT,), _inscribe),
        Power("sign", 2, 2, (P_AT, P_TEXT), _sign),
        Power("prophecy", 2, 3, (P_TEXT,), _prophecy),
        Power("reveal", 2, 3, (Param("who", "person"),), _reveal),
        Power("collector", 2, 3, (), _collector),
        Power("flood", 3, 5, (), _flood),
        Power("plague", 3, 4, (P_AT,), _plague),
        Power("wildfire", 3, 4, (), _wildfire),
        Power("raiders", 3, 4, (P_AT,), _raiders),
        Power("winter", 3, 4, (), _winter),
        Power("earthquake", 3, 6, (), _earthquake),
        Power("decree", 4, 6, (Param("god", "god"), P_TEXT, Param("days", "days")), _decree),
        Power("wake_ullr", 4, 8, (), _wake_ullr),
        Power("bind_star", 4, 5, (Param("days", "days"),), _bind_star),
        Power("heal", 4, 7, (P_AT,), _heal),
        Power("cleanse", 4, 7, (P_AT,), _cleanse),
        Power("raise_stone", 4, 10, (), _raise_stone),
    )
}


def _prayed_to_you(world: World) -> bool:
    return bool(state(world)["ever"].get("prayed"))


CHAPTERS = (
    Chapter("voice", _prayed_to_you, 3, 2),
    Chapter("wound", lambda w: not w.hidden["shaft_open"], 5, 3),
    Chapter("song", lambda w: bool(w.hidden.get("stones_sung") or state(w)["ever"].get("hummed")), 5, 4),
    Chapter("waking", lambda w: int(w.hidden.get("ullr_awake", 0)) > 0, 5, None),
)


def power_name(world: World, power_id: str) -> str:
    return _words(world).get("powers", {}).get(power_id, [power_id, ""])[0]


def _tier_name(world: World, tier: int) -> str:
    return world.t.get("overgod.tiers")[str(tier)]


# ---------------------------------------------------------------------------- acting


def clean(world: World, power_id: str, args: dict | None) -> tuple[Power, dict]:
    """Check an act against the rules: known, unlocked, affordable, and with sensible arguments."""
    t = world.t
    power = POWERS.get(power_id)
    if power is None:
        raise OvergodError(t("overgod.err_unknown", power=power_id))
    o = state(world)
    name = power_name(world, power.id)
    if power.tier > o["tier"]:
        raise OvergodError(t("overgod.err_locked", power=name, tier=_tier_name(world, power.tier)))
    if o["awe"] + 1e-9 < power.cost:
        raise OvergodError(t("overgod.err_cost", power=name, cost=f"{power.cost:g}", awe=f"{o['awe']:g}"))
    args = dict(args or {})
    labels = t.get("overgod.param")
    out: dict[str, Any] = {}
    for prm in power.params:
        raw = args.get(prm.name)
        label = labels.get(prm.name, prm.name)
        if prm.kind == "person":
            who = world.resolve_person(str(raw or ""))
            if who is None:
                raise OvergodError(t("overgod.err_person", label=label, raw=raw))
            out[prm.name] = who.id
        elif prm.kind == "place":
            place = world.resolve_place(str(raw or ""))
            if place is None:
                raise OvergodError(t("overgod.err_place", label=label, raw=raw))
            out[prm.name] = place
        elif prm.kind == "god":
            if raw not in GODS:
                raise OvergodError(t("overgod.err_god", label=label, gods=", ".join(GODS)))
            out[prm.name] = raw
        elif prm.kind == "days":
            try:
                out[prm.name] = max(1, min(7, int(raw or 3)))
            except (TypeError, ValueError):
                raise OvergodError(t("overgod.err_days", label=label)) from None
        else:
            text = " ".join(str(raw or "").split())[:600]
            if not text:
                raise OvergodError(t("overgod.err_text", label=label))
            out[prm.name] = text
    if power.id == "reveal" and out["who"] in o["revealed"]:
        raise OvergodError(t("overgod.err_revealed", name=world.name(out["who"])))
    return power, out


def act(world: World, power_id: str, args: dict | None = None) -> dict:
    """Do it now: pay the Awe, change the world, and log it. Call only between parts of the day."""
    power, x = clean(world, power_id, args)
    o = state(world)
    o["awe"] = round(o["awe"] - power.cost, 3)
    what = power.apply(world, x)
    record = {"power": power.id, "name": power_name(world, power.id), "args": x, "cost": power.cost, "what": what, "awe": o["awe"]}
    world.log("overgod", **record)
    return record


def decree_for(world: World, god: str) -> str:
    """A standing decree from the One Above, for a god's prompt, or an empty string."""
    d = state(world)["decrees"].get(god)
    if not d or d["until"] < world.day:
        return ""
    return world.t("overgod.decree", until=d["until"] + 1, text=d["text"])


def star_bound(world: World) -> bool:
    return state(world).get("star_bound_until", 0) >= world.day


# ---------------------------------------------------------------------------- the turn of days


def dawn(world: World, yesterday: list[dict]) -> dict:
    """Awe returns each dawn: a little by itself, more for prayers to the voice and for dice that turned a story."""
    o = state(world)
    prayers = world.hidden.pop("prayers_overgod", [])
    if prayers:
        o["ever"]["prayed"] = True
    drama = sum(1 for e in yesterday if e.get("ev") == "check" and e.get("band") in ("critical", "fumble"))
    income = {"day": world.day, "base": 1.0, "prayers": float(min(3, len(prayers))), "drama": min(2.0, 0.5 * drama)}
    gain = income["base"] + income["prayers"] + income["drama"]
    o["awe"] = round(min(AWE_CAP, o["awe"] + gain), 3)
    income["total"] = gain
    o["income"] = (o["income"] + [income])[-30:]
    world.log("awe", **income, awe=o["awe"], prayers_heard=[{"agent": q["agent"], "text": q["text"]} for q in prayers])
    return income


def advance_chapters(world: World) -> list[dict]:
    """Close every chapter whose goal now holds, in order: pay its Awe and open the next tier."""
    o = state(world)
    if world.hidden.get("stone_hum"):
        o["ever"]["hummed"] = True
    if world.hidden.get("prayers_overgod"):
        o["ever"]["prayed"] = True
    done = []
    titles = _words(world).get("chapters", {})
    while o["chapter"] < len(CHAPTERS) and CHAPTERS[o["chapter"]].check(world):
        ch = CHAPTERS[o["chapter"]]
        o["chapter"] += 1
        o["awe"] = round(min(AWE_CAP, o["awe"] + ch.reward), 3)
        if ch.unlocks:
            o["tier"] = max(o["tier"], ch.unlocks)
        record = {"chapter": ch.id, "title": titles.get(ch.id, [ch.id])[0], "reward": ch.reward, "tier": o["tier"], "awe": o["awe"]}
        world.log("chapter", **record)
        done.append(record)
    return done


def view(world: World) -> dict[str, Any]:
    """Everything the player's panel shows, in the story's language: Awe, tier, chapters and every power with its state."""
    o = state(world)
    words = _words(world)
    titles = words.get("chapters", {})
    labels = world.t.get("overgod.param")
    return {
        "awe": o["awe"],
        "cap": AWE_CAP,
        "tier": o["tier"],
        "tier_name": _tier_name(world, o["tier"]),
        "chapters": [
            {
                "id": c.id,
                "title": titles.get(c.id, [c.id, ""])[0],
                "goal": titles.get(c.id, [c.id, ""])[1],
                "reward": c.reward,
                "unlocks": c.unlocks and _tier_name(world, c.unlocks),
                "status": "done" if i < o["chapter"] else "current" if i == o["chapter"] else "later",
            }
            for i, c in enumerate(CHAPTERS)
        ],
        "powers": [
            {
                "id": p.id,
                "tier": p.tier,
                "tier_name": _tier_name(world, p.tier),
                "cost": p.cost,
                "name": power_name(world, p.id),
                "blurb": words.get("powers", {}).get(p.id, ["", ""])[1],
                "params": [{"name": prm.name, "kind": prm.kind, "label": labels.get(prm.name, prm.name)} for prm in p.params],
                "locked": p.tier > o["tier"],
                "affordable": o["awe"] + 1e-9 >= p.cost,
            }
            for p in POWERS.values()
        ],
        "known_by": o["known_by"],
        "revealed": o["revealed"],
        "written": o["written"][-5:],
        "decrees": {g: d for g, d in o["decrees"].items() if d["until"] >= world.day},
        "income": o["income"][-7:],
    }
