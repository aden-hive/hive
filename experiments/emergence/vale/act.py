"""Applying what a villager decided: each action becomes signals and state."""

from __future__ import annotations

import re
from typing import Any, Callable

from . import dice
from .lexicon import tags_for
from .world import WAVE_LEN, WAVES, Agent, Project, World


class ActionError(Exception):
    """An action that couldn't happen; the villager is told next time they act."""


WORK = {
    "miller": ({"flour": 2}, "ground a batch of flour"),
    "foreman": ({"ore": 2}, "had the crew haul ore from the new gallery"),
    "herbwife": ({"moonwort": 1, "remedy": 1}, "gathered moonwort and brewed a remedy"),
    "hunter": ({"game": 1}, "came back from the forest with game"),
    "shepherd": ({"wool": 1}, "tended the flock"),
    "trader": ({"coin": 2}, "did a little trade at the stalls"),
    "tavern": ({"ale": 2}, "brewed and served"),
    "steward": ({"coin": 3}, "worked at the accounts"),
    "courier": ({"coin": 1}, "ran an errand for a copper"),
    "scribe": ({"coin": 1}, "wrote a letter for a copper"),
    "prioress": ({}, "led prayers in the chapel"),
    "lord": ({}, "held court"),
    "reeve": ({}, "heard complaints and updated the tally on the green post"),
}

ITEM_ALIASES = {
    "remedies": "remedy", "herb": "herbs", "coins": "coin", "silver": "coin", "silver coin": "coin",
    "copper": "coin", "coppers": "coin", "loaf": "bread", "loaves": "bread", "candle": "candles",
    "paint": "paints", "flours": "flour", "ores": "ore", "ales": "ale",
    "ropes": "rope", "lamp": "lamps", "tool": "tools", "levers": "tools", "lever": "tools", "jar": "jars",
    "covered jars": "jars", "covered jar": "jars", "vessels": "jars", "vessel": "jars", "covered vessels": "jars",
    "covered vessel": "jars", "crocks": "jars", "pots": "jars", "wood": "timber", "timbers": "timber", "beams": "timber",
    "engineers' map": "map", "the map": "map", "old map": "map", "tunnel map": "map", "maps": "map",
}

EVERYONE = {"", "everyone", "all", "everybody", "anyone", "the room", "the crowd", "them", "us", "all here"}


def _text(value: Any, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


KNOWN_ITEMS = {"coin", "flour", "ore", "moonwort", "remedy", "herbs", "game", "wool", "ale", "goods", "bread", "candles", "ink", "paints",
               "timber", "rope", "lamps", "tools", "jars", "map", "water"}

# A longer name for a thing, read as the plain good it is: first match wins, so water beats the jar it is in.
GOODS = tuple((re.compile(pattern), item) for pattern, item in (
    (r"\bwater\b", "water"), (r"\b(jars?|vessels?|crocks?|pots?)\b", "jars"),
    (r"\b(timbers?|beams?|planks?|cribbing|cribs?|braces?|props?|shores?)\b", "timber"), (r"\bropes?\b", "rope"),
    (r"\b(lamps?|lanterns?)\b", "lamps"), (r"\b(tools?|levers?|picks?|crowbars?|shovels?)\b", "tools"),
    (r"\b(remed\w*|draughts?|tonics?|salves?|medicines?)\b", "remedy"), (r"\bmoonwort\b", "moonwort"), (r"\bherbs?\b", "herbs"),
    (r"\bmaps?\b", "map"), (r"\b(coins?|silver|coppers?)\b", "coin"), (r"\b(bread|loaf|loaves)\b", "bread"),
    (r"\bore\b", "ore"), (r"\bwool\b", "wool"), (r"\bflour\b", "flour"), (r"\bale\b", "ale"), (r"\bcandles?\b", "candles"),
))


def _item(value: Any) -> str:
    name = _text(value, 60).lower()
    if name in ITEM_ALIASES:
        return ITEM_ALIASES[name]
    if name not in KNOWN_ITEMS and name.endswith("s") and name[:-1] in KNOWN_ITEMS:
        return name[:-1]
    if name not in KNOWN_ITEMS:
        for pattern, item in GOODS:
            if pattern.search(name):
                return item
    return name[:40]


def goods(value: Any) -> str:
    """The plain good a name means (a "covered jar of clean spring water" is water), or the name itself, kept short."""
    return _item(value)


def _hear(world: World, agent: Agent, sig_id: str) -> None:
    """Everyone present (but the speaker) now carries this in mind."""
    for other in world.present(agent.loc):
        if other.id != agent.id:
            other.heard.append(sig_id)


def say(world: World, a: Agent, x: dict, act: str, loudness: float = 1.0) -> list[str]:
    text = _text(x.get("text"))
    if not text:
        raise ActionError("you opened your mouth and said nothing")
    raw_to = _text(x.get("to"), 60).lower()
    target = None
    note = None
    if raw_to not in EVERYONE:
        here = [p for p in world.present(a.loc) if p.id != a.id]
        target = world.resolve_person(raw_to, among=here)
        if target is None:
            elsewhere = world.resolve_person(raw_to)
            note = f"{elsewhere.name if elsewhere else raw_to} wasn't here, so you said it to whoever was"
    base, _ = world.kind_defaults("directed" if target else "speech")
    sig = world.add_signal("speech", text, a.loc, a.id, cause=act, to=target.id if target else None,
                           strength=round(base * loudness, 3))
    _hear(world, a, sig.id)
    if note:
        a.failures.append(note)
    return [sig.id]


def look(world: World, a: Agent, x: dict, act: str) -> list[str]:
    feature = world.resolve_feature(a.loc, _text(x.get("at"), 60))
    if feature is None:
        raise ActionError(f"there was no '{_text(x.get('at'), 40)}' to look at here")
    who = feature.get("who")
    if who and a.id not in who:
        clue = world.add_signal("clue", feature.get("denied", "You can't get near it."), None, "world",
                                audience=[a.id], cause=act, strength=1.4)
        deed = world.add_signal("deed", f"{a.name} tried to get at {feature['name']} and was turned away.", a.loc, a.id, cause=act)
        a.heard.append(clue.id)
        return [clue.id, deed.id]
    for view in feature.get("view", []):
        if view.get("who") and a.id not in view["who"]:
            continue
        if world.check(view.get("when", [])):
            break
    else:
        raise ActionError(f"you found nothing to see at {feature['name']}")
    if view.get("grants") and view["grants"] not in a.knows:
        a.knows.append(view["grants"])
    clue = world.add_signal("clue", view["text"], None, "world", audience=[a.id], cause=act,
                            tags=sorted(set(tags_for(view["text"]) + tags_for(feature["name"]))))
    deed = world.add_signal("deed", f"{a.name} looked closely at {feature['name']}.", a.loc, a.id, cause=act)
    world.log("look", agent=a.id, feature=feature["id"], text=view["text"], grants=view.get("grants"))
    a.heard.append(clue.id)
    return [clue.id, deed.id]


def post(world: World, a: Agent, x: dict, act: str) -> list[str]:
    text = _text(x.get("text"), 500)
    if not text:
        raise ActionError("you pinned up a blank notice")
    sig = world.add_signal("notice", text, a.loc, a.id, cause=act)
    _hear(world, a, sig.id)
    return [sig.id]


def paint(world: World, a: Agent, x: dict, act: str) -> list[str]:
    if a.profession != "painter":
        raise ActionError("you are no painter; a notice would do instead")
    text = _text(x.get("text"), 600)
    if not text:
        raise ActionError("you stood before a blank canvas")
    sig = world.add_signal("painting", text, a.loc, a.id, cause=act, tags=sorted(set(tags_for(text) + ["art"])))
    _hear(world, a, sig.id)
    return [sig.id]


def pray(world: World, a: Agent, x: dict, act: str) -> list[str]:
    text = _text(x.get("text"), 400)
    if not text:
        raise ActionError("you knelt, but found no words")
    world.counters.setdefault("q", 0)
    to = _text(x.get("to"), 30).lower()
    # Only Bagel has someone else to pray to; the vale's god hears every prayer either way.
    to_master = a.id == "bagel" and any(w in to for w in ("master", "pleiades", "主人"))
    to_ullr = not to_master and any(w in to for w in ("ullr", "old god", "乌勒尔", "古神"))
    prayer = {"id": world.new_id("q"), "day": world.day, "wave": world.wave, "agent": a.id, "place": a.loc, "text": text, "act": act,
              "to": "master" if to_master else "ullr" if to_ullr else "god"}
    world.hidden.setdefault("prayers", []).append(prayer)
    if to_master:
        world.hidden.setdefault("prayers_master", []).append(prayer)
    if to_ullr:
        world.hidden.setdefault("prayers_ullr", []).append(prayer)
    world.log("prayer", **prayer)
    sig = world.add_signal("deed", f"{a.name} knelt and prayed.", a.loc, a.id, cause=act, strength=0.6)
    return [sig.id]


def give(world: World, a: Agent, x: dict, act: str) -> list[str]:
    here = [p for p in world.present(a.loc) if p.id != a.id]
    target = world.resolve_person(_text(x.get("to"), 60), among=here)
    if target is None:
        raise ActionError(f"{_text(x.get('to'), 40) or 'nobody'} wasn't here to take it")
    item = _item(x.get("item"))
    try:
        qty = max(1, int(x.get("qty") or 1))
    except (TypeError, ValueError):
        qty = 1
    if a.items.get(item, 0) < qty:
        raise ActionError(f"you don't have {qty} {item} to give")
    a.items[item] -= qty
    target.items[item] = target.items.get(item, 0) + qty
    target.ties[a.id] = round(min(1.0, target.ties.get(a.id, 0.0) + 0.15), 3)
    sig = world.add_signal("deed", f"{a.name} gave {qty} {item} to {target.name}.", a.loc, a.id, cause=act, to=target.id, strength=1.2)
    return [sig.id]


def work(world: World, a: Agent, x: dict, act: str) -> list[str]:
    if a.profession == "painter":
        raise ActionError("a painter's work is the paint action")
    if a.profession == "healer":
        if a.items.get("moonwort", 0) > 0:
            a.items["moonwort"] -= 1
            made, what = {"remedy": 2}, "brewed two remedies from moonwort"
        elif a.items.get("herbs", 0) > 0:
            a.items["herbs"] -= 1
            made, what = {"remedy": 1}, "made a remedy from her herbs"
        else:
            raise ActionError("you have no herbs or moonwort to make remedies from")
    else:
        made, what = WORK.get(a.profession, ({}, "worked"))
    if a.profession in ("herbwife",) and a.loc != a.home:
        raise ActionError("your herbs and your still are back at your hut")
    if a.profession == "foreman" and a.loc != "mine":
        raise ActionError("your crew and your picks are at Greyfang")
    for item, n in made.items():
        a.items[item] = a.items.get(item, 0) + n
    sig = world.add_signal("deed", f"{a.name} {what}.", a.loc, a.id, cause=act, strength=0.6)
    return [sig.id]


# How far a remedy goes in the tender's hands: (people eased, sickness lifted from the place).
TENDING = {"critical": (3, 0.18), "success": (2, 0.12), "partial": (1, 0.06), "failure": (0, 0.0), "fumble": (0, 0.0)}


def tend(world: World, a: Agent, x: dict, act: str) -> list[str]:
    if a.items.get("remedy", 0) < 1:
        raise ActionError("you had no remedy to give")
    a.items["remedy"] -= 1
    check = dice.roll(world, a, "healing", [])
    dice.record(world, check, kind="tend", ref=act, place=a.loc, what=f"tend the sick at {world.place_name(a.loc)}")
    n, amount = TENDING[check["band"]]
    sick = world.hidden["sickness"]
    if a.loc in sick and amount:
        sick[a.loc] = round(max(0.0, sick[a.loc] - amount), 4)
    eased = [p for p in world.present(a.loc) if p.health > 0][:n]
    for p in eased:
        p.health -= 1
        if p.id != a.id:
            p.ties[a.id] = round(min(1.0, p.ties.get(a.id, 0.0) + 0.2), 3)
    where = world.place_name(a.loc)
    if check["band"] == "fumble":
        text = f"{a.name} went to tend the sick at {where}, but the remedy was spilled and wasted."
    elif not eased:
        text = f"{a.name} tended the sick at {where}, but no fever broke."
    else:
        text = f"{a.name} tended the sick at {where}, easing {', '.join(p.name for p in eased)}."
    sig = world.add_signal("deed", f"{text} [the dice: {dice.line(check, a.short)}]", a.loc, a.id, cause=act, strength=1.2)
    return [sig.id]


def attempt(world: World, a: Agent, x: dict, act: str) -> list[str]:
    """Try something hard, here and now. It is settled by the dice at the end of this part of the day."""
    what = _text(x.get("what") or x.get("text"), 300).rstrip(".")
    if not what:
        raise ActionError("you set out to try something, but never said what")
    if any(q["agent"] == a.id for q in world.attempts):
        raise ActionError("one hard thing at a time: you were already trying something")
    world.counters.setdefault("t", 0)
    world.attempts.append({"id": world.new_id("t"), "agent": a.id, "place": a.loc, "what": what,
                           "using": _text(x.get("with") or x.get("using"), 200), "act": act})
    sig = world.add_signal("deed", f'{a.name} set about something hard: "{what}".', a.loc, a.id, cause=act, strength=0.8)
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
        raise ActionError(f'"{p.title}" is posted at {world.place_name(p.place)}; you must be there, or at {world.place_name(p.site or p.place)} '
                          "where it will be done, to join or oppose it")
    raise ActionError(f"there was no undertaking '{key}' to join here")


def _hour(world: World, raw: Any) -> int:
    """The part of the day named, or the next one if none was."""
    hour = _text(raw, 20).lower()
    if hour in WAVES:
        return WAVES.index(hour)
    return (world.wave + 1) % len(WAVES)


def propose(world: World, a: Agent, x: dict, act: str) -> list[str]:
    title, goal, needs = _text(x.get("title"), 80), _text(x.get("goal"), 300), _text(x.get("needs"), 300)
    if not title:
        raise ActionError("your proposal had no name")
    mine = [p for p in world.projects.values() if p.proposer == a.id and p.status in ("open", "due")]
    if len(mine) >= 2:
        raise ActionError(f'you already have two undertakings waiting for their hour ("{mine[0].title}", "{mine[1].title}")')
    site = world.resolve_place(_text(x.get("at"), 60)) if x.get("at") else None
    site = site or a.loc
    when = _hour(world, x.get("when"))
    due_day = world.day if when > world.wave else world.day + 1
    at = f"{WAVES[when]} {'today' if due_day == world.day else 'tomorrow'}"
    pid = world.new_id("p")
    sig = world.add_signal("project", f"{title}: {goal} Needs: {needs.rstrip('.')}. To be attempted at {world.place_name(site)}, at {at}, "
                           "with whoever comes.", a.loc, a.id, cause=act,
                           project=pid, tags=sorted(set(tags_for(f"{title} {goal} {needs}") + ["gathering"])))
    p = Project(id=pid, title=title, goal=goal, needs=needs, quorum=0, place=a.loc, proposer=a.id, born=world.now,
                signal=sig.id, supporters={a.id: "proposed it"}, status="due", quorum_act=act, site=site, when=when, due_day=due_day)
    world.projects[pid] = p
    world.log("proposal", project=pid, title=title, goal=goal, needs=needs, quorum=0, place=a.loc, proposer=a.id,
              site=site, when=when, due_day=due_day)
    _hear(world, a, sig.id)
    return [sig.id]


def join(world: World, a: Agent, x: dict, act: str) -> list[str]:
    p = _resolve_project(world, a, x.get("project"))
    if a.id in p.supporters:
        raise ActionError(f'you had already joined "{p.title}"')
    p.opposers.pop(a.id, None)
    offer = _text(x.get("offer"), 200)
    p.supporters[a.id] = offer or "themselves"
    sig = world.signals.get(p.signal)
    if sig:  # each recruit makes the proposal louder, like a dance gaining dancers
        sig.strength = round(sig.level(world.now) + 0.6, 3)
        sig.born = world.now
        sig.diffused = False
    deed = world.add_signal("deed", f'{a.name} joined "{p.title}"' + (f", offering {offer}" if offer else "") + ".",
                            a.loc, a.id, cause=act, strength=1.0)
    world.log("join", project=p.id, agent=a.id, offer=offer)
    return [deed.id]


def oppose(world: World, a: Agent, x: dict, act: str) -> list[str]:
    p = _resolve_project(world, a, x.get("project"))
    if a.id == p.proposer:
        raise ActionError("you can't oppose your own proposal")
    p.supporters.pop(a.id, None)
    why = _text(x.get("why"), 200)
    p.opposers[a.id] = why
    sig = world.signals.get(p.signal)
    if sig:  # cross-inhibition: a stop signal quiets the dance
        sig.strength = round(max(0.3, sig.level(world.now) - 0.8), 3)
        sig.born = world.now
    deed = world.add_signal("deed", f'{a.name} spoke against "{p.title}"' + (f": {why}" if why else "") + ".",
                            a.loc, a.id, cause=act, strength=1.2)
    world.log("oppose", project=p.id, agent=a.id, why=why)
    return [deed.id]


def travel(world: World, a: Agent, x: dict, act: str) -> list[str]:
    dest = world.resolve_place(_text(x.get("to"), 60))
    if dest is None:
        raise ActionError(f"you don't know a place called '{_text(x.get('to'), 40)}'")
    if dest == a.loc:
        raise ActionError("you were already there")
    roads = world.places[a.loc]["roads"]
    if dest not in roads:
        names = ", ".join(world.places[r]["name"] for r in roads)
        raise ActionError(f"no road runs from {world.place_name(a.loc)} to {world.place_name(dest)}; roads go to {names}")
    waves, text = 1, f"{a.name} set off toward {world.place_name(dest)}."
    if a.health >= 2:
        check = dice.roll(world, a, "strength", [])
        dice.record(world, check, kind="travel", ref=act, place=a.loc, what=f"walk to {world.place_name(dest)}, fevered")
        waves = {"critical": 1, "success": 1, "partial": 2}.get(check["band"], 3)
        pace = "fevered, but steady on the road" if waves == 1 else "fevered and slow"
        text = f"{a.name} set off toward {world.place_name(dest)}, {pace}. [the dice: {dice.line(check, a.short)}]"
    sig = world.add_signal("deed", text, a.loc, a.id, cause=act, strength=0.6)
    a.travel = {"to": dest, "from": a.loc, "arrive": world.now + waves * WAVE_LEN}
    a.loc = None
    return [sig.id]


HANDLERS: dict[str, Callable[[World, Agent, dict, str], list[str]]] = {
    "say": say, "speak": say, "tell": say, "ask": say,
    "look": look, "inspect": look, "examine": look,
    "post": post, "notice": post,
    "paint": paint,
    "give": give,
    "work": work,
    "tend": tend, "heal": tend,
    "propose": propose,
    "join": join, "support": join,
    "oppose": oppose,
    "travel": travel, "go": travel, "walk": travel,
    "pray": pray,
    "attempt": attempt, "try": attempt,
}


def apply(world: World, a: Agent, reply: dict, act: str, loudness: float = 1.0) -> tuple[list[str], list[str], list[str]]:
    """Carry out a reply's actions in order. Returns (emitted signal ids, summaries, failures)."""
    emitted: list[str] = []
    done: list[str] = []
    failures: list[str] = []
    a.failures = []
    for x in reply.get("actions", []):
        do = _text(x.get("do"), 20).lower()
        handler = HANDLERS.get(do)
        if a.loc is None:
            failures.append("you were already on the road")
            break
        if handler is None:
            failures.append(f"'{do}' is not something you can do")
            continue
        try:
            if handler is say:
                emitted.extend(say(world, a, x, act, loudness))
            else:
                emitted.extend(handler(world, a, x, act))
            done.append(summarize(world, x))
        except ActionError as exc:
            failures.append(str(exc))
    a.failures = failures + a.failures
    when = f"day {world.day} {('dawn', 'morning', 'midday', 'afternoon', 'dusk', 'night')[world.wave]}"
    if done:
        a.recent = (a.recent + [f"({when}) " + "; ".join(done)])[-3:]
    return emitted, done, failures


def summarize(world: World, x: dict) -> str:
    do = _text(x.get("do"), 20).lower()
    if do in ("say", "speak", "tell", "ask"):
        return f"said to {_text(x.get('to'), 40) or 'everyone'}: \"{_text(x.get('text'), 160)}\""
    if do in ("look", "inspect", "examine"):
        return f"looked at {_text(x.get('at'), 40)}"
    if do in ("post", "notice"):
        return f"posted: \"{_text(x.get('text'), 160)}\""
    if do == "paint":
        return f"painted: {_text(x.get('text'), 160)}"
    if do == "give":
        return f"gave {x.get('qty', 1)} {_text(x.get('item'), 30)} to {_text(x.get('to'), 40)}"
    if do in ("propose",):
        return f"proposed \"{_text(x.get('title'), 80)}\""
    if do in ("join", "support"):
        return f"joined {_text(x.get('project'), 40)}"
    if do == "oppose":
        return f"opposed {_text(x.get('project'), 40)}"
    if do in ("travel", "go", "walk"):
        return f"set off to {_text(x.get('to'), 40)}"
    if do == "pray":
        return f"prayed: \"{_text(x.get('text'), 160)}\""
    if do in ("attempt", "try"):
        return f"tried: \"{_text(x.get('what') or x.get('text'), 160)}\""
    return do
