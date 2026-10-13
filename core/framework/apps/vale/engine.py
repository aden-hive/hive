"""The vale's day, in the pieces a game steps through one part of the day at a time.

Dawn: the hidden world advances, undertakings set for dawn are attempted, omens appear,
the gods take their turns, and every villager's reserve is topped up a little: the only
energy that ever enters the system. Then six waves (dawn to night): undertakings whose
hour has come are attempted with whoever came; whoever the physics stirs acts (each a
Hive agent, see ``villager.py``); what anyone tried alone is settled by the dice; strong
signals travel one road. At night, sensitivities drift, faint signals fade, and memories
are snapshotted.

The functions here are synchronous and may block on model calls; ``game.py`` runs them
off the event loop, one at a time, so nothing else touches the world meanwhile.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from . import dice, fate as fates, god as gods, nature, outer as outer_gods, physics, ullr as old_gods
from .fate import apply_effects
from .rules import rules_for
from .world import WAVE_LEN, WAVES, Project, World

logger = logging.getLogger(__name__)


def _say(line: str) -> None:
    logger.info(line)


@dataclass
class Powers:
    """Who answers for the world beyond the villagers: fate, and a model for each standard kind of god.

    ``god`` speaks for a ledger god, ``outer`` for a patron, ``ullr`` for a sleeper; which gods a
    world has, and how each is set up, is the world's own (``rules.toml``: ``[[god]]``).
    """

    fate: Any
    god: Any = None
    outer: Any = None
    ullr: Any = None


# The standard kinds of god: the module that runs each, and which of the Powers speaks for it.
GOD_KINDS = {"ledger": (gods, "god"), "patron": (outer_gods, "outer"), "sleeper": (old_gods, "ullr")}


def _arrive(world: World) -> None:
    for a in world.agents.values():
        if a.travel and a.travel["arrive"] <= world.now + 1e-9:
            dest, origin = a.travel["to"], a.travel["from"]
            a.loc, a.travel = dest, None
            world.add_signal("arrival", world.t("mind.arrived", name=a.name, place=world.place_name(origin)), dest, a.id)


def dawn(world: World, powers: Powers, *, workers: int = 6) -> None:
    """The dawn's whole work, before anyone stirs. ``world.day`` is already the new day."""
    p = world.params
    rules = rules_for(world)
    refill = p["refill"] * rules.refill(world)  # the world's own rule: Ashmere's hard winter halves it
    for a in world.agents.values():
        a.acts_today = 0
        a.last_wave = -9
        a.reserve = round(min(p["reserve_cap"], a.reserve + refill), 3)
        if a.confined:
            a.confined -= 1
    world.totals["injected"] = round(world.totals.get("injected", 0) + refill * len(world.agents), 3)
    if world.day > 1:
        nature.advance(world)
    _resolve_due(world, powers.fate, False, workers)
    nature.dawn(world)
    for cfg in rules.gods:  # in the order the world lists them
        module, speaker = GOD_KINDS[cfg["kind"]]
        module.dawn(world, getattr(powers, speaker), False, cfg)
    nature.lapse(world)  # after the gods' turns, so the night that woke or stirred one still counts


def _keep_appointments(world: World) -> None:
    """Whoever joined an undertaking set for later today walks toward its site, one road a part, so they are there in time.

    At the hour, anyone one road away is gathered in anyway; this brings the rest that close. It spends
    no energy and no model turn: they said they would come. The fevered stay where they are.
    """
    waves = max(1, int(rules_for(world).travel(world)))
    for proj in world.projects.values():
        if proj.status != "due" or proj.due_day != world.day or proj.when <= world.wave:
            continue
        site = proj.site or proj.place
        for aid in proj.supporters:
            a = world.agents.get(aid)
            if a is None or a.loc is None or a.loc == site or a.confined or a.health >= 2:
                continue
            way = world.way(a.loc, site)
            if way is None or way[1] <= 1:
                continue
            step = way[0]
            text = world.t("engine.keeps_appointment", name=a.name, place=world.place_name(step), site=world.place_name(site), title=proj.title)
            world.add_signal("deed", text, a.loc, a.id, strength=0.6)
            world.log("appointment", agent=aid, project=proj.id, to=step, site=site)
            a.travel = {"to": step, "from": a.loc, "arrive": world.now + waves * WAVE_LEN}
            a.loc = None


def wave_start(world: World, powers: Powers, *, workers: int = 6) -> None:
    """The start of a part of the day: travellers arrive, those with an appointment set off, and undertakings whose hour has come are attempted."""
    _arrive(world)
    _keep_appointments(world)
    if world.wave:
        _resolve_due(world, powers.fate, False, workers)  # dawn's were settled with the rest of the dawn


def wave_end(world: World, powers: Powers, *, workers: int = 6) -> None:
    """The end of a part of the day: what was tried alone is settled, and strong words travel."""
    _settle_attempts(world, powers.fate, False, workers)
    world.today["rumors"] = world.today.get("rumors", 0) + physics.diffuse(world)


def night(world: World, fired: list[physics.Firing]) -> dict:
    """The day settles: sensitivities drift, faint signals fade, memories are kept. Returns the day's summary."""
    physics.adapt(world, fired)
    faded = physics.cleanup(world)
    world.snapshot_memories()
    world.totals["activations"] = world.totals.get("activations", 0) + world.today.get("activations", 0)
    world.totals["tired"] = world.totals.get("tired", 0) + world.today.get("tired", 0)
    summary = {
        "day": world.day,
        **world.today,
        "faded": faded,
        "alive_signals": len(world.signals),
        "reserves": {k: a.reserve for k, a in world.agents.items()},
        "hidden": rules_for(world).summary(world),
        "positions": {k: a.loc or (a.travel or {}).get("to") for k, a in world.agents.items()},
        "health": {k: a.health for k, a in world.agents.items()},
        "interests": {k: a.interests for k, a in world.agents.items()},
        "grace": world.hidden.get("grace"),
    }
    world.log("day", **summary)
    return summary


def _ask_all(fate, jobs: list[list[dict[str, str]]], workers: int) -> list[dict]:
    """The game master's plans for several checks at once; the rolls come after, in order."""
    if len(jobs) > 1 and workers > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            return list(pool.map(fate.ask, jobs))
    return [fate.ask(j) for j in jobs]


def _hour_has_come(world: World, proj: Project) -> bool:
    day = proj.due_day if proj.due_day is not None else world.day
    return day < world.day or (day == world.day and proj.when <= world.wave)


def _resolve_due(world: World, fate, verbose: bool, workers: int = 6) -> None:
    """Attempt every undertaking whose hour has come, at its site, with whoever came: even one.

    Undertakings set for the same place and hour are attempted together, by everyone who came for any of them.
    """
    groups: dict[str, list[Project]] = {}
    for proj in world.projects.values():
        if proj.status == "due" and _hour_has_come(world, proj):
            groups.setdefault(proj.site or proj.place, []).append(proj)
    settings, jobs = [], []
    for site, group in groups.items():
        near = {site, *world.places[site]["roads"]}
        present, absent = [], []
        for aid in dict.fromkeys(aid for p in group for aid in p.supporters):
            a = world.agents.get(aid)
            if a and a.loc in near and not a.confined:
                a.loc = site  # one road away is close enough to come in for the appointed hour
                present.append(aid)
            else:
                absent.append(aid)
        settings.append((site, group, present, absent))
        if present:
            jobs.append(fates.project_messages(world, group, present, absent))
    plans = iter(_ask_all(fate, jobs, workers))
    for site, group, present, absent in settings:
        lead = group[0]
        title = " + ".join(p.title for p in group)
        if present:
            result = fates.settle(world, next(plans), present)
            if result["check"]:
                dice.record(world, result["check"], kind="undertaking", ref=lead.id, place=site, what=title)
        else:
            result = {
                "outcome": "unattempted",
                "public": world.t("engine.nobody_came", place=world.place_name(site), wave=world.wave_name(world.wave), title=title),
                "effects": [],
                "secret": "",
                "check": None,
                "might": {},
            }
        applied = apply_effects(world, result["effects"], ref=lead.id, present=present, site=site)
        result["applied"] = applied
        for proj in group:
            proj.result = result
            proj.status = "done"
        world.log(
            "outcome",
            project=lead.id,
            projects=[p.id for p in group],
            title=title,
            place=site,
            supporters=list(dict.fromkeys(aid for p in group for aid in p.supporters)),
            present=present,
            absent=absent,
            **result,
        )
        text = result["public"] + (
            world.t("engine.dice_tail", line=dice.line(world.t, result["check"], world.agents[result["check"]["roller"]].short))
            if result["check"]
            else ""
        )
        sig = world.add_signal("outcome", text, site, "world", cause=lead.quorum_act, project=lead.id)
        for aid in absent:  # they know they didn't go; word of how it went reaches them
            world.agents[aid].heard.append(sig.id)
        for e in applied:
            if e.get("type") == "reveal" and e.get("text"):
                world.add_signal("outcome", str(e["text"]), site, "world", cause=lead.quorum_act, project=lead.id, strength=2.5)
        if verbose:
            roll = f" {dice.line(world.t, result['check'], world.agents[result['check']['roller']].short)}" if result["check"] else ""
            _say(f"  ** [{WAVES[world.wave]} @{world.place_name(site)}] {title} [{result['outcome']}]{roll} {result['public']}")
            if applied:
                _say(f"     effects: {applied}")


def _settle_attempts(world: World, fate, verbose: bool, workers: int) -> None:
    """Everything tried alone this wave comes to something before the next: the dice decide what."""
    pending, world.attempts = world.attempts, []
    if not pending:
        return
    jobs = [fates.attempt_messages(world, world.agents[x["agent"]], x["what"], x["using"], x["place"]) for x in pending]
    for x, plan in zip(pending, _ask_all(fate, jobs, workers), strict=True):
        a = world.agents[x["agent"]]
        result = fates.settle(world, plan, [a.id])
        if result["check"]:
            dice.record(world, result["check"], kind="attempt", ref=x["id"], place=x["place"], what=x["what"])
        applied = apply_effects(world, result["effects"], ref=x["id"], present=[a.id], site=x["place"])
        result["applied"] = applied
        world.log("attempt", **x, **result)
        roll = dice.line(world.t, result["check"], a.short) if result["check"] else "-"
        tail = world.t("engine.dice_tail", line=roll) if result["check"] else ""
        text = world.t("engine.tried_something", name=a.name, what=x["what"], public=result["public"]) + tail
        sig = world.add_signal("outcome", text, x["place"], "world", cause=x["act"], strength=2.2)
        if a.loc != x["place"]:
            a.heard.append(sig.id)
        for e in applied:
            if e.get("type") == "reveal" and e.get("text"):
                world.add_signal("outcome", str(e["text"]), x["place"], "world", cause=x["act"], strength=2.5)
        when = world.t("time.day_wave", day=world.day, wave=world.wave_name(world.wave))
        band = world.t.get("dice.bands").get(result["outcome"], result["outcome"])
        a.recent = (a.recent + [world.t("engine.recent_tried", when=when, what=x["what"], band=band, public=result["public"][:200])])[-3:]
        if verbose:
            _say(f"  ~~ [{WAVES[world.wave]} @{world.place_name(x['place'])}] {a.short} tried: {x['what'][:90]} [{roll}] {result['public']}"[:600])
            if applied:
                _say(f"     effects: {applied}")
