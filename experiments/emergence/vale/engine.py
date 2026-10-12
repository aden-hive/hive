"""One tick = one day in the vale. The cron's whole job is to call `tick`.

Dawn: the hidden world advances, undertakings set for dawn are attempted, omens
appear, and every villager's reserve is topped up a little — the only energy that
ever enters the system. Then six waves (dawn to night): undertakings whose hour has
come are attempted with whoever came; whoever the physics stirs acts, all in the same
wave at once, like a generation of the Game of Life; what anyone tried alone is
settled by the dice; their words and deeds become signals for the next wave. Strong
signals travel one road per wave. At night, sensitivities drift, faint signals fade,
and memories are snapshotted.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from . import act as actions
from . import dice, nature, physics
from . import fate as fates
from . import god as gods
from . import outer as outer_gods
from . import ullr as old_gods
from .fate import apply_effects
from .world import WAVES, Project, World


def _say(line: str) -> None:
    print(line, flush=True)


def _arrive(world: World) -> None:
    for a in world.agents.values():
        if a.travel and a.travel["arrive"] <= world.now + 1e-9:
            dest, origin = a.travel["to"], a.travel["from"]
            a.loc, a.travel = dest, None
            world.add_signal("arrival", f"{a.name} arrived from {world.place_name(origin)}.", dest, a.id)


def _dawn(world: World, fate, god, outer, ullr, verbose: bool, workers: int) -> None:
    p = world.params
    for a in world.agents.values():
        a.acts_today = 0
        a.last_wave = -9
        a.reserve = round(min(p["reserve_cap"], a.reserve + p["refill"]), 3)
        if a.confined:
            a.confined -= 1
    world.totals["injected"] = round(world.totals.get("injected", 0) + p["refill"] * len(world.agents), 3)
    if world.day > 1:
        nature.advance(world)
    _resolve_due(world, fate, verbose, workers)
    nature.dawn(world)
    gods.dawn(world, god, verbose)
    outer_gods.dawn(world, outer, verbose)
    old_gods.dawn(world, ullr, verbose)
    nature.lapse(world)  # after Ullr's turn, so the night that woke or stirred him still counts


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
            result = {"outcome": "unattempted", "public": f'Nobody came to {world.place_name(site)} at {WAVES[world.wave]} for "{title}", so it was never tried.',
                      "effects": [], "secret": "", "check": None, "might": {}}
        applied = apply_effects(world, result["effects"], ref=lead.id, present=present, site=site)
        result["applied"] = applied
        for proj in group:
            proj.result = result
            proj.status = "done"
        world.log("outcome", project=lead.id, projects=[p.id for p in group], title=title, place=site,
                  supporters=list(dict.fromkeys(aid for p in group for aid in p.supporters)), present=present, absent=absent, **result)
        text = result["public"] + (f" [the dice: {dice.line(result['check'], world.agents[result['check']['roller']].short)}]" if result["check"] else "")
        sig = world.add_signal("outcome", text, site, "world", cause=lead.quorum_act, project=lead.id)
        for aid in absent:  # they know they didn't go; word of how it went reaches them
            world.agents[aid].heard.append(sig.id)
        for e in applied:
            if e.get("type") == "reveal" and e.get("text"):
                world.add_signal("outcome", str(e["text"]), site, "world", cause=lead.quorum_act, project=lead.id, strength=2.5)
        if verbose:
            roll = f" {dice.line(result['check'], world.agents[result['check']['roller']].short)}" if result["check"] else ""
            _say(f"  ** [{WAVES[world.wave]} @{world.place_name(site)}] {title} [{result['outcome']}]{roll} {result['public']}")
            if applied:
                _say(f"     effects: {applied}")


def _settle_attempts(world: World, fate, verbose: bool, workers: int) -> None:
    """Everything tried alone this wave comes to something before the next: the dice decide what."""
    pending, world.attempts = world.attempts, []
    if not pending:
        return
    jobs = [fates.attempt_messages(world, world.agents[x["agent"]], x["what"], x["using"], x["place"]) for x in pending]
    for x, plan in zip(pending, _ask_all(fate, jobs, workers)):
        a = world.agents[x["agent"]]
        result = fates.settle(world, plan, [a.id])
        if result["check"]:
            dice.record(world, result["check"], kind="attempt", ref=x["id"], place=x["place"], what=x["what"])
        applied = apply_effects(world, result["effects"], ref=x["id"], present=[a.id], site=x["place"])
        result["applied"] = applied
        world.log("attempt", **x, **result)
        roll = dice.line(result["check"], a.short) if result["check"] else "no roll needed"
        tail = f" [the dice: {roll}]" if result["check"] else ""
        sig = world.add_signal("outcome", f'{a.name} tried something: "{x["what"]}". {result["public"]}{tail}', x["place"], "world",
                               cause=x["act"], strength=2.2)
        if a.loc != x["place"]:
            a.heard.append(sig.id)
        for e in applied:
            if e.get("type") == "reveal" and e.get("text"):
                world.add_signal("outcome", str(e["text"]), x["place"], "world", cause=x["act"], strength=2.5)
        a.recent = (a.recent + [f'(day {world.day} {WAVES[world.wave]}) tried: "{x["what"]}", and it came out {result["outcome"]}: {result["public"][:200]}'])[-3:]
        if verbose:
            _say(f"  ~~ [{WAVES[world.wave]} @{world.place_name(x['place'])}] {a.short} tried: {x['what'][:90]} [{roll}] {result['public']}"[:600])
            if applied:
                _say(f"     effects: {applied}")


def tick(world: World, mind, fate, *, god=None, outer=None, ullr=None, workers: int = 6, verbose: bool = True) -> dict:
    """Advance the vale by one day. Returns that day's summary."""
    world.day += 1
    world.wave = 0
    world.today = {"activations": 0, "tired": 0, "rumors": 0, "llm_errors": 0, "checks": 0}
    if verbose:
        _say(f"\n=== DAY {world.day} ===")
    _dawn(world, fate, god, outer, ullr, verbose, workers)
    if verbose:
        _say(f"  {world.hidden['weather']}")

    fired: list[physics.Firing] = []
    for wave in range(len(WAVES)):
        world.wave = wave
        _arrive(world)
        if wave:
            _resolve_due(world, fate, verbose, workers)  # dawn's were settled with the rest of the dawn
        firings = physics.select(world)
        if firings:
            jobs = [mind.prepare(world, world.agents[f.agent], f) for f in firings]
            if len(jobs) > 1 and workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    replies = list(pool.map(mind.run, jobs))
            else:
                replies = [mind.run(j) for j in jobs]
            # Everyone in a wave decided at once; apply in a fixed order.
            for f, reply in sorted(zip(firings, replies), key=lambda fr: fr[0].agent):
                _activate(world, f, reply, verbose)
            fired.extend(firings)
            _settle_attempts(world, fate, verbose, workers)
        world.today["rumors"] += physics.diffuse(world)

    # Night: the day settles.
    physics.adapt(world, fired)
    faded = physics.cleanup(world)
    world.snapshot_memories()
    world.totals["activations"] = world.totals.get("activations", 0) + world.today["activations"]
    world.totals["tired"] = world.totals.get("tired", 0) + world.today["tired"]
    summary = {
        "day": world.day,
        **world.today,
        "faded": faded,
        "alive_signals": len(world.signals),
        "reserves": {k: a.reserve for k, a in world.agents.items()},
        "hidden": {k: world.hidden.get(k, 0) for k in ("blight", "sickness", "wolves", "shaft_open", "stone_raised", "stones_sung", "ullr_awake", "stone_hum")},
        "positions": {k: a.loc or (a.travel or {}).get("to") for k, a in world.agents.items()},
        "health": {k: a.health for k, a in world.agents.items()},
        "interests": {k: a.interests for k, a in world.agents.items()},
        "grace": world.hidden.get("grace"),
    }
    world.log("day", **summary)
    world.save()
    if verbose:
        _say(f"  -- day {world.day}: {world.today['activations']} stirrings, {world.today['tired']} too tired, "
             f"{world.today['rumors']} rumours, {len(world.signals)} live signals")
    return summary


def _activate(world: World, f: physics.Firing, reply: dict, verbose: bool) -> None:
    agent = world.agents[f.agent]
    act_id = world.new_id("a")
    where = agent.loc
    emitted, done, failures = actions.apply(world, agent, reply, act_id, physics.arousal(f.stimulus))
    if reply.get("memory"):
        world.write_memory(agent.id, reply["memory"])
    agent.mood = reply.get("mood", "") or agent.mood
    world.today["activations"] += 1
    if reply.get("error"):
        world.today["llm_errors"] += 1
    contribs = []
    for sid, c in f.contribs:
        sig = world.signals.get(sid)
        contribs.append({"signal": sid, "c": c, "cause": sig.cause if sig else None, "kind": sig.kind if sig else None})
    world.log(
        "activation", id=act_id, agent=agent.id, place=where, stimulus=f.stimulus, p=f.p, parent=f.parent,
        contribs=contribs, tags=f.tags, thought=reply.get("thought", ""), actions=reply.get("actions", []),
        done=done, failures=failures, emitted=emitted, mood=agent.mood, memory=reply.get("memory"),
        error=reply.get("error"), reserve=agent.reserve,
    )
    if verbose:
        what = " | ".join(done) if done else "(did nothing)"
        _say(f"  {WAVES[world.wave]:<9} {agent.short:<8} @{world.place_name(where)[:14]:<14} S={f.stimulus:4.1f} :: {what}"[:400])
        for fail in failures:
            _say(f"  {'':<9} {'':<8}   ! {fail}"[:300])


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
