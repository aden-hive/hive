"""The god beyond gods: the person playing.

Above the world's own gods there is one more power, and it is the player. It spends Awe on
powers in four tiers. Awe returns a little each dawn, and more when the world prays to the
voice above every voice or when the dice turn a story. Chapters set what the world should
come to next; finishing one pays Awe and opens the next tier of power.

Which powers and chapters a world has, what they cost, and what they do are the world's
own data (``rules.toml``: ``[[power]]``, ``[[chapter]]``, ``[awe]``). A power either uses one
of the standard blocks here (``whisper``, ``inscribe``, ``sign``, ``prophecy``, ``reveal``,
``decree``) or runs the world's own steps. What they are called, and what the world sees when
they land, is the story's (``story.toml``: ``[overgod]``), in the story's language.

Every act lands at a safe point between parts of the day (see ``game.py``), never while
villagers are mid-turn. Everything here is plain state in ``world.hidden["overgod"]``.
"""

from __future__ import annotations

from typing import Any

from .rules import AWE, Chapter, Param, Power, rules_for
from .world import World

START_AWE = AWE["start"]
AWE_CAP = AWE["cap"]

__all__ = ["AWE_CAP", "START_AWE", "Chapter", "OvergodError", "Param", "Power"]


class OvergodError(ValueError):
    """An act the One Above cannot do now: unknown, locked, unaffordable or malformed."""


def state(world: World) -> dict[str, Any]:
    """The One Above's own state, created on first use."""
    o = world.hidden.setdefault("overgod", {})
    o.setdefault("awe", float(rules_for(world).awe["start"]))
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


def _cap(world: World) -> float:
    return float(rules_for(world).awe["cap"])


def gods(world: World) -> tuple[str, ...]:
    """The world's gods a decree can bind."""
    return tuple(g["id"] for g in rules_for(world).gods)


# ---------------------------------------------------------------------------- the standard blocks


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
    world.add_signal("sign", x["text"], x["at"], "overgod", strength=2.6)
    return world.t("overgod.signed", place=world.place_name(x["at"]))


def _prophecy(world: World, x: dict) -> str:
    o = state(world)
    world.add_signal("prophecy", x["text"], None, "overgod", audience=list(world.agents), strength=2.8)
    o["known_by"] = sorted(set(o["known_by"]) | set(world.agents))
    return world.t("overgod.prophesied")


def _reveal(world: World, x: dict) -> str:
    a = world.agents[x["who"]]
    where = a.loc or (a.travel or {}).get("to") or a.home
    world.add_signal("omen", _words(world).get("secrets", {})[a.id], where, "overgod", strength=2.8)
    state(world)["revealed"].append(a.id)
    witnesses = [p.short for p in world.present(where) if p.id != a.id]
    t = world.t
    return t("overgod.revealed", name=a.name, place=world.place_name(where)) + (
        t("overgod.revealed_before", who=t("names.list_sep").join(witnesses)) if witnesses else t("overgod.revealed_alone")
    )


def _decree(world: World, x: dict) -> str:
    state(world)["decrees"][x["god"]] = {"text": x["text"], "until": world.day + int(x["days"])}
    title = world.story.get("gods", {}).get("titles", {}).get(x["god"], x["god"])
    return world.t("overgod.decreed", god=title, days=x["days"])


BLOCKS = {"whisper": _whisper, "inscribe": _inscribe, "sign": _sign, "prophecy": _prophecy, "reveal": _reveal, "decree": _decree}


def powers(world: World) -> dict[str, Power]:
    """This world's powers, in the order its rules list them."""
    made = getattr(world, "_powers", None)
    if made is None:
        made = rules_for(world).powers(BLOCKS)
        world._powers = made
    return made


def chapters(world: World) -> tuple[Chapter, ...]:
    made = getattr(world, "_chapters", None)
    if made is None:
        made = rules_for(world).chapters()
        world._chapters = made
    return made


def power_name(world: World, power_id: str) -> str:
    return _words(world).get("powers", {}).get(power_id, [power_id, ""])[0]


def _tier_name(world: World, tier: int) -> str:
    return world.t.get("overgod.tiers")[str(tier)]


# ---------------------------------------------------------------------------- acting


def clean(world: World, power_id: str, args: dict | None) -> tuple[Power, dict]:
    """Check an act against the rules: known, unlocked, affordable, and with sensible arguments."""
    t = world.t
    power = powers(world).get(power_id)
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
            if raw not in gods(world):
                raise OvergodError(t("overgod.err_god", label=label, gods=", ".join(gods(world))))
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
    if power.apply is _reveal and out.get("who") in o["revealed"]:
        raise OvergodError(t("overgod.err_revealed", name=world.name(out["who"])))
    if power.apply is _reveal and out.get("who") not in _words(world).get("secrets", {}):
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


def bound(world: World, god: str) -> bool:
    """Whether the One Above has bound a god for now (the god's ``bound`` rule, if it has one)."""
    cfg = rules_for(world).god(god)
    rules = rules_for(world)
    return bool(cfg.get("bound")) and bool(rules.scope(world).eval(cfg["bound"]))


# ---------------------------------------------------------------------------- the turn of days


def dawn(world: World, yesterday: list[dict]) -> dict:
    """Awe returns each dawn: a little by itself, more for prayers to the voice and for dice that turned a story."""
    awe = rules_for(world).awe
    o = state(world)
    prayers = world.hidden.pop("prayers_overgod", [])
    if prayers:
        o["ever"]["prayed"] = True
    drama = sum(1 for e in yesterday if e.get("ev") == "check" and e.get("band") in ("critical", "fumble"))
    income = {
        "day": world.day,
        "base": float(awe["dawn"]),
        "prayers": float(min(awe["prayers_max"], len(prayers)) * awe["prayer"]),
        "drama": min(float(awe["drama_max"]), awe["drama"] * drama),
    }
    gain = income["base"] + income["prayers"] + income["drama"]
    o["awe"] = round(min(_cap(world), o["awe"] + gain), 3)
    income["total"] = gain
    o["income"] = (o["income"] + [income])[-30:]
    world.log("awe", **income, awe=o["awe"], prayers_heard=[{"agent": q["agent"], "text": q["text"]} for q in prayers])
    return income


def advance_chapters(world: World) -> list[dict]:
    """Close every chapter whose goal now holds, in order: pay its Awe and open the next tier."""
    o = state(world)
    rules_for(world).run(world, "watch")
    if world.hidden.get("prayers_overgod"):
        o["ever"]["prayed"] = True
    done = []
    titles = _words(world).get("chapters", {})
    plan = chapters(world)
    while o["chapter"] < len(plan) and plan[o["chapter"]].check(world):
        ch = plan[o["chapter"]]
        o["chapter"] += 1
        o["awe"] = round(min(_cap(world), o["awe"] + ch.reward), 3)
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
        "cap": _cap(world),
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
            for i, c in enumerate(chapters(world))
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
            for p in powers(world).values()
        ],
        "gods": [{"id": g, "title": world.story.get("gods", {}).get("titles", {}).get(g, g)} for g in gods(world)],
        "known_by": o["known_by"],
        "revealed": o["revealed"],
        "written": o["written"][-5:],
        "decrees": {g: d for g, d in o["decrees"].items() if d["until"] >= world.day},
        "income": o["income"][-7:],
    }
