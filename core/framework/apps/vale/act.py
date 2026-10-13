"""Applying what a villager decided: each action becomes signals and state.

Every word a villager reads back comes from the world's language (``world.t``) or its
story pack (``world.story``): what each trade makes, what goods are called, and so on.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import cache
from typing import Any

from . import dice
from .rules import rules_for
from .world import WAVE_LEN, WAVES, Agent, Project, World


class ActionError(Exception):
    """An action that couldn't happen; the villager is told next time they act."""


def _text(value: Any, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


@cache
def _goods_table(items_key: str, items: tuple) -> tuple[dict[str, str], tuple[tuple[re.Pattern[str], str], ...]]:
    """Every name a good goes by, and the words that mean it inside a longer name, from a story's items."""
    names: dict[str, str] = {}
    patterns = []
    for gid, spec in items:
        spec = dict(spec)
        names[gid] = gid
        names[str(spec.get("name", gid)).lower()] = gid
        for alias in spec.get("aliases", []):
            names[str(alias).lower()] = gid
        for pattern in spec.get("match", []):
            patterns.append((re.compile(pattern, re.IGNORECASE), gid))
    return names, tuple(patterns)


def _goods(world: World):
    items = world.story.get("items", {})
    frozen = tuple((gid, tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in spec.items())) for gid, spec in items.items())
    return _goods_table(world.story.get("story", {}).get("id", ""), frozen)


def goods(world: World, value: Any) -> str:
    """The plain good a name means (a "covered jar of clean spring water" is water), or the name itself, kept short."""
    name = _text(value, 60).lower()
    names, patterns = _goods(world)
    if name in names:
        return names[name]
    if name.endswith("s") and name[:-1] in names:
        return names[name[:-1]]
    for pattern, gid in patterns:
        if pattern.search(name):
            return gid
    return name[:40]


def item_name(world: World, gid: str) -> str:
    """What villagers call a good, in the story's language."""
    return str(world.story.get("items", {}).get(gid, {}).get("name", gid))


def carried(world: World, a: Agent) -> str:
    """What someone carries, as they would list it, or an empty string."""
    return world.t("names.list_sep").join(f"{item_name(world, k)} ×{v}" for k, v in a.items.items() if v > 0)


def _hear(world: World, agent: Agent, sig_id: str) -> None:
    """Everyone present (but the speaker) now carries this in mind."""
    for other in world.present(agent.loc):
        if other.id != agent.id:
            other.heard.append(sig_id)


def say(world: World, a: Agent, x: dict, act: str, loudness: float = 1.0) -> list[str]:
    t = world.t
    text = _text(x.get("text"))
    if not text:
        raise ActionError(t("act.say_empty"))
    raw_to = _text(x.get("to"), 60).lower()
    target = None
    note = None
    if raw_to not in t.get("names.everyone_words"):
        here = [p for p in world.present(a.loc) if p.id != a.id]
        target = world.resolve_person(raw_to, among=here)
        if target is None:
            elsewhere = world.resolve_person(raw_to)
            note = t("act.say_absent", who=elsewhere.name if elsewhere else raw_to)
    base, _ = world.kind_defaults("directed" if target else "speech")
    sig = world.add_signal("speech", text, a.loc, a.id, cause=act, to=target.id if target else None, strength=round(base * loudness, 3))
    _hear(world, a, sig.id)
    if note:
        a.failures.append(note)
    return [sig.id]


def look(world: World, a: Agent, x: dict, act: str) -> list[str]:
    t = world.t
    feature = world.resolve_feature(a.loc, _text(x.get("at"), 60))
    if feature is None:
        raise ActionError(t("act.look_none", what=_text(x.get("at"), 40)))
    who = feature.get("who")
    if who and a.id not in who:
        clue = world.add_signal("clue", feature.get("denied", t("act.look_denied")), None, "world", audience=[a.id], cause=act, strength=1.4)
        deed = world.add_signal("deed", t("act.look_turned_away", name=a.name, thing=feature["name"]), a.loc, a.id, cause=act)
        a.heard.append(clue.id)
        return [clue.id, deed.id]
    for view in feature.get("view", []):
        if view.get("who") and a.id not in view["who"]:
            continue
        if world.check(view.get("when", [])):
            break
    else:
        raise ActionError(t("act.look_nothing", thing=feature["name"]))
    if view.get("grants") and view["grants"] not in a.knows:
        a.knows.append(view["grants"])
    clue = world.add_signal(
        "clue", view["text"], None, "world", audience=[a.id], cause=act, tags=sorted(set(world.tags(view["text"]) + world.tags(feature["name"])))
    )
    deed = world.add_signal("deed", t("act.looked", name=a.name, thing=feature["name"]), a.loc, a.id, cause=act)
    world.log("look", agent=a.id, feature=feature["id"], text=view["text"], grants=view.get("grants"))
    a.heard.append(clue.id)
    return [clue.id, deed.id]


def post(world: World, a: Agent, x: dict, act: str) -> list[str]:
    text = _text(x.get("text"), 500)
    if not text:
        raise ActionError(world.t("act.post_empty"))
    sig = world.add_signal("notice", text, a.loc, a.id, cause=act)
    _hear(world, a, sig.id)
    return [sig.id]


def paint(world: World, a: Agent, x: dict, act: str) -> list[str]:
    if a.profession != "painter":
        raise ActionError(world.t("act.paint_not_painter"))
    text = _text(x.get("text"), 600)
    if not text:
        raise ActionError(world.t("act.paint_empty"))
    sig = world.add_signal("painting", text, a.loc, a.id, cause=act, tags=sorted(set(world.tags(text) + ["art"])))
    _hear(world, a, sig.id)
    return [sig.id]


def pray(world: World, a: Agent, x: dict, act: str) -> list[str]:
    text = _text(x.get("text"), 400)
    if not text:
        raise ActionError(world.t("act.pray_empty"))
    world.counters.setdefault("q", 0)
    words = world.story.get("gods", {})
    to = _text(x.get("to"), 30).lower()
    # A prayer goes to the first of the world's gods whose words it uses (a patron hears only its
    # follower); to the One Above only from those who have heard the voice; else to the world's god.
    target = next(
        (
            cfg
            for cfg in rules_for(world).gods
            if cfg.get("words") and cfg.get("follower", a.id) == a.id and any(w in to for w in words.get(cfg["words"], []))
        ),
        None,
    )
    to_above = target is None and a.id in world.hidden.get("overgod", {}).get("known_by", []) and any(w in to for w in words.get("above_words", []))
    prayer = {
        "id": world.new_id("q"),
        "day": world.day,
        "wave": world.wave,
        "agent": a.id,
        "place": a.loc,
        "text": text,
        "act": act,
        "to": target.get("to", target["id"]) if target else "overgod" if to_above else "god",
    }
    world.hidden.setdefault("prayers", []).append(prayer)
    if target:
        world.hidden.setdefault(target.get("prayers", f"prayers_{target['id']}"), []).append(prayer)
    if to_above:
        world.hidden.setdefault("prayers_overgod", []).append(prayer)
    world.log("prayer", **prayer)
    sig = world.add_signal("deed", world.t("act.prayed", name=a.name), a.loc, a.id, cause=act, strength=0.6)
    return [sig.id]


def give(world: World, a: Agent, x: dict, act: str) -> list[str]:
    t = world.t
    here = [p for p in world.present(a.loc) if p.id != a.id]
    target = world.resolve_person(_text(x.get("to"), 60), among=here)
    if target is None:
        raise ActionError(t("act.give_absent", who=_text(x.get("to"), 40) or t("names.nobody")))
    item = goods(world, x.get("item"))
    try:
        qty = max(1, int(x.get("qty") or 1))
    except (TypeError, ValueError):
        qty = 1
    if a.items.get(item, 0) < qty:
        raise ActionError(t("act.give_lack", qty=qty, item=item_name(world, item)))
    a.items[item] -= qty
    target.items[item] = target.items.get(item, 0) + qty
    target.ties[a.id] = round(min(1.0, target.ties.get(a.id, 0.0) + 0.15), 3)
    sig = world.add_signal(
        "deed",
        t("act.gave", name=a.name, qty=qty, item=item_name(world, item), target=target.name),
        a.loc,
        a.id,
        cause=act,
        to=target.id,
        strength=1.2,
    )
    return [sig.id]


def work(world: World, a: Agent, x: dict, act: str) -> list[str]:
    """Each trade's work, as its story declares: what it makes, what it uses, and where it must be done."""
    t = world.t
    if a.profession == "painter":
        raise ActionError(t("act.work_painter"))
    trade = world.story.get("professions", {}).get(a.profession, {})
    where = trade.get("at")
    if where and a.loc != (a.home if where == "home" else where):
        raise ActionError(trade.get("away") or t("act.look_nothing", thing=world.place_name(a.home if where == "home" else where)))
    made: dict[str, int] = dict(trade.get("makes", {}))
    what = trade.get("deed") or t("act.worked_plain")
    if trade.get("recipes"):
        for recipe in trade["recipes"]:
            if all(a.items.get(k, 0) >= n for k, n in recipe.get("uses", {}).items()):
                for k, n in recipe.get("uses", {}).items():
                    a.items[k] -= n
                made, what = dict(recipe.get("makes", {})), recipe.get("deed", what)
                break
        else:
            raise ActionError(trade.get("nothing") or t("act.worked_plain"))
    for item, n in made.items():
        a.items[item] = a.items.get(item, 0) + n
    sig = world.add_signal("deed", t("act.worked", name=a.name, what=what), a.loc, a.id, cause=act, strength=0.6)
    return [sig.id]


def tend(world: World, a: Agent, x: dict, act: str) -> list[str]:
    """Care for the sick where you are, using up one of the world's remedies (rules.toml ``[actions.tend]``).

    The dice decide how many people are eased (``by_band``: band -> [people, amount]); the
    world's own steps decide what else the care changes, with ``here`` and ``amount`` in scope.
    """
    t = world.t
    rules = rules_for(world)
    cfg = rules.actions.get("tend")
    if not cfg:
        raise ActionError(t("act.unknown", act="tend"))
    item = cfg.get("item", "remedy")
    if a.items.get(item, 0) < 1:
        raise ActionError(t("act.tend_none"))
    a.items[item] -= 1
    where = world.place_name(a.loc)
    check = dice.roll(world, a, cfg.get("skill", "healing"), [])
    dice.record(world, check, kind="tend", ref=act, place=a.loc, what=t("act.tend_what", place=where))
    n, amount = cfg["by_band"][check["band"]]
    scope = rules.scope(world, {"here": a.loc, "amount": amount, "who": a.id, "band": check["band"]})
    for step in cfg.get("steps", []):
        rules.step(world, scope, step)
    eased = [p for p in world.present(a.loc) if p.health > 0][:n]
    for p in eased:
        p.health -= 1
        if p.id != a.id:
            p.ties[a.id] = round(min(1.0, p.ties.get(a.id, 0.0) + 0.2), 3)
    if check["band"] == "fumble":
        text = t("act.tend_spilled", name=a.name, place=where)
    elif not eased:
        text = t("act.tend_no_break", name=a.name, place=where)
    else:
        text = t("act.tend_eased", name=a.name, place=where, who=t("names.list_sep").join(p.name for p in eased))
    sig = world.add_signal("deed", text + t("engine.dice_tail", line=dice.line(world.t, check, a.short)), a.loc, a.id, cause=act, strength=1.2)
    return [sig.id]


def attempt(world: World, a: Agent, x: dict, act: str) -> list[str]:
    """Set out to do something, here and now. It is settled at the end of this part of the day."""
    t = world.t
    what = _text(x.get("what") or x.get("text"), 300).rstrip(".。")
    if not what:
        raise ActionError(t("act.attempt_empty"))
    if any(q["agent"] == a.id for q in world.attempts):
        raise ActionError(t("act.attempt_busy"))
    world.counters.setdefault("t", 0)
    world.attempts.append(
        {"id": world.new_id("t"), "agent": a.id, "place": a.loc, "what": what, "using": _text(x.get("with") or x.get("using"), 200), "act": act}
    )
    sig = world.add_signal("deed", t("act.attempt_deed", name=a.name, what=what), a.loc, a.id, cause=act, strength=0.8)
    return [sig.id]


def _resolve_project(world: World, a: Agent, raw: Any) -> Project:
    key = _text(raw, 80).lower().strip("[] ")
    here = [p for p in world.projects.values() if p.status in ("open", "due") and a.loc in (p.place, p.site)]
    for p in here:
        if key == p.id or key == p.title.lower():
            return p
    for p in here:
        if key and (key in p.title.lower() or p.title.lower() in key):
            return p
    elsewhere = [p for p in world.projects.values() if key in (p.id, p.title.lower()) and p.status in ("open", "due")]
    if elsewhere:
        p = elsewhere[0]
        raise ActionError(world.t("act.project_elsewhere", title=p.title, place=world.place_name(p.place), site=world.place_name(p.site or p.place)))
    raise ActionError(world.t("act.project_none", key=key))


def hour(world: World, raw: Any) -> int:
    """The part of the day named (in the story's language, or English), or the next one if none was."""
    name = _text(raw, 20).lower()
    for names in (world.t.get("time.waves"), ("dawn", "morning", "midday", "afternoon", "dusk", "night")):
        if name in names:
            return list(names).index(name)
    return (world.wave + 1) % 6


def propose(world: World, a: Agent, x: dict, act: str) -> list[str]:
    t = world.t
    title, goal, needs = _text(x.get("title"), 80), _text(x.get("goal"), 300), _text(x.get("needs"), 300)
    if not title:
        raise ActionError(t("act.propose_empty"))
    mine = [p for p in world.projects.values() if p.proposer == a.id and p.status in ("open", "due")]
    if len(mine) >= 2:
        raise ActionError(t("act.propose_too_many", a=mine[0].title, b=mine[1].title))
    site = world.resolve_place(_text(x.get("at"), 60)) if x.get("at") else None
    site = site or a.loc
    when = hour(world, x.get("when"))
    due_day = world.day if when > world.wave else world.day + 1
    # Never sooner than the proposer can be there: they set off next part, and one road away is close enough.
    way = world.way(a.loc, site) if site != a.loc else None
    if way and way[1] > 1:
        need = (way[1] - 1) * max(1, int(rules_for(world).travel(world)))
        if due_day == world.day and when < world.wave + 1 + need:
            when = world.wave + 1 + need
            if when >= len(WAVES):
                due_day, when = world.day + 1, min(need, len(WAVES) - 1)
        elif due_day > world.day and when < need:
            when = min(need, len(WAVES) - 1)
    at = t("time.wave_on", wave=world.wave_name(when), day=t("time.today") if due_day == world.day else t("time.tomorrow"))
    if goal and goal[-1] not in ".!?。！？":
        goal += t("names.stop")
    pid = world.new_id("p")
    sig = world.add_signal(
        "project",
        t("act.project_text", title=title, goal=goal, needs=needs.rstrip(".。"), place=world.place_name(site), when=at),
        a.loc,
        a.id,
        cause=act,
        project=pid,
        tags=sorted(set(world.tags(f"{title} {goal} {needs}") + ["gathering"])),
    )
    p = Project(
        id=pid,
        title=title,
        goal=goal,
        needs=needs,
        quorum=0,
        place=a.loc,
        proposer=a.id,
        born=world.now,
        signal=sig.id,
        supporters={a.id: t("act.proposed_it")},
        status="due",
        quorum_act=act,
        site=site,
        when=when,
        due_day=due_day,
    )
    world.projects[pid] = p
    world.log(
        "proposal", project=pid, title=title, goal=goal, needs=needs, quorum=0, place=a.loc, proposer=a.id, site=site, when=when, due_day=due_day
    )
    _hear(world, a, sig.id)
    return [sig.id]


def join(world: World, a: Agent, x: dict, act: str) -> list[str]:
    t = world.t
    p = _resolve_project(world, a, x.get("project"))
    if a.id in p.supporters:
        raise ActionError(t("act.join_again", title=p.title))
    p.opposers.pop(a.id, None)
    offer = _text(x.get("offer"), 200)
    p.supporters[a.id] = offer or t("act.themselves")
    sig = world.signals.get(p.signal)
    if sig:  # each recruit makes the proposal louder, like a dance gaining dancers
        sig.strength = round(sig.level(world.now) + 0.6, 3)
        sig.born = world.now
        sig.diffused = False
    text = t("act.joined", name=a.name, title=p.title, offer=t("act.joined_offer", offer=offer.rstrip(".。")) if offer else "")
    deed = world.add_signal("deed", text, a.loc, a.id, cause=act, strength=1.0)
    world.log("join", project=p.id, agent=a.id, offer=offer)
    return [deed.id]


def oppose(world: World, a: Agent, x: dict, act: str) -> list[str]:
    t = world.t
    p = _resolve_project(world, a, x.get("project"))
    if a.id == p.proposer:
        raise ActionError(t("act.oppose_own"))
    p.supporters.pop(a.id, None)
    why = _text(x.get("why"), 200)
    p.opposers[a.id] = why
    sig = world.signals.get(p.signal)
    if sig:  # cross-inhibition: a stop signal quiets the dance
        sig.strength = round(max(0.3, sig.level(world.now) - 0.8), 3)
        sig.born = world.now
    text = t("act.opposed", name=a.name, title=p.title, why=t("act.opposed_why", why=why.rstrip(".。")) if why else "")
    deed = world.add_signal("deed", text, a.loc, a.id, cause=act, strength=1.2)
    world.log("oppose", project=p.id, agent=a.id, why=why)
    return [deed.id]


def travel(world: World, a: Agent, x: dict, act: str) -> list[str]:
    t = world.t
    dest = world.resolve_place(_text(x.get("to"), 60))
    if dest is None:
        raise ActionError(t("act.travel_unknown", what=_text(x.get("to"), 40)))
    if dest == a.loc:
        raise ActionError(t("act.travel_here"))
    roads = world.places[a.loc]["roads"]
    if dest not in roads:
        names = t("names.list_sep").join(world.places[r]["name"] for r in roads)
        raise ActionError(t("act.travel_no_road", here=world.place_name(a.loc), there=world.place_name(dest), roads=names))
    # Snow sent by the One Above makes every road take twice as long.
    waves = max(1, int(rules_for(world).travel(world)))  # the world's rule: Ashmere's hard winter slows the roads
    text = t("act.set_off", name=a.name, place=world.place_name(dest))
    if a.health >= 2:
        check = dice.roll(world, a, "strength", [])
        dice.record(world, check, kind="travel", ref=act, place=a.loc, what=t("act.travel_what", place=world.place_name(dest)))
        waves = {"critical": 1, "success": 1, "partial": 2}.get(check["band"], 3)
        pace = t("act.pace_steady") if waves == 1 else t("act.pace_slow")
        text = t("act.set_off_fevered", name=a.name, place=world.place_name(dest), pace=pace) + t(
            "engine.dice_tail", line=dice.line(world.t, check, a.short)
        )
    sig = world.add_signal("deed", text, a.loc, a.id, cause=act, strength=0.6)
    a.travel = {"to": dest, "from": a.loc, "arrive": world.now + waves * WAVE_LEN}
    a.loc = None
    return [sig.id]


HANDLERS: dict[str, Callable[[World, Agent, dict, str], list[str]]] = {
    "say": say,
    "look": look,
    "post": post,
    "paint": paint,
    "give": give,
    "work": work,
    "tend": tend,
    "propose": propose,
    "join": join,
    "oppose": oppose,
    "travel": travel,
    "pray": pray,
    "attempt": attempt,
}


def summarize(world: World, x: dict) -> str:
    """One line for what someone did, as their own recent memory keeps it."""
    t = world.t
    do = _text(x.get("do"), 20).lower()
    if do == "say":
        return t("sum.say", to=_text(x.get("to"), 40) or t("names.everyone"), text=_text(x.get("text"), 160))
    if do == "look":
        return t("sum.look", at=_text(x.get("at"), 40))
    if do in ("post", "paint", "pray"):
        return t(f"sum.{do}", text=_text(x.get("text"), 160))
    if do == "give":
        return t("sum.give", qty=x.get("qty", 1), item=_text(x.get("item"), 30), to=_text(x.get("to"), 40))
    if do == "propose":
        return t("sum.propose", title=_text(x.get("title"), 80))
    if do in ("join", "oppose"):
        return t(f"sum.{do}", project=_text(x.get("project"), 40))
    if do == "travel":
        return t("sum.travel", to=_text(x.get("to"), 40))
    if do == "attempt":
        return t("sum.attempt", what=_text(x.get("what") or x.get("text"), 160))
    return do
