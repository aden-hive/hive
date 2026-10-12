"""What a stirred villager sees.

The physics chose *who* acts; the villager's own Hive agent (``villager.py``) decides
*what*. Its identity is the villager's persona, the shared rules of the world, the places
and the people (``system_prompt``); its first message is the moment: where they are, who
is with them, what stirred them, what's still on their mind, and their own notes.
Every word is the story's language (``world.t``).
"""

from __future__ import annotations

from .act import carried
from .god import has_god, ledger_text
from .physics import Firing
from .world import Agent, Signal, World


def system_prompt(world: World, agent: Agent) -> str:
    t = world.t
    places = []
    for pid, place in world.places.items():
        roads = t("names.list_sep").join(world.places[r]["name"] for r in place["roads"])
        places.append(t("mind.place_line", name=place["name"], id=pid, desc=place["desc"], roads=roads))
    people = [t("mind.person_line", name=a.name, public=a.public) for a in world.agents.values() if a.id != agent.id]
    river = world.story.get("story", {}).get("river", "")
    return "\n\n".join(
        [
            world.personas[agent.id].strip(),
            world.rules.strip(),
            t("mind.places_heading") + "\n" + "\n".join(places) + (f"\n{river}" if river else ""),
            t("mind.people_heading") + "\n" + "\n".join(people),
            *([world.god_rules.strip()] if has_god(world) and world.god_rules else []),
        ]
    )


def ago(world: World, born: float) -> str:
    age = world.now - born
    if age < 0.2:
        return world.t("time.just_now")
    if age < 1:
        return world.t("time.earlier_today")
    days = int(age + 0.5)
    return world.t("time.yesterday") if days <= 1 else world.t("time.days_ago", n=days)


def project_line(world: World, pid: str) -> str:
    t = world.t
    p = world.projects[pid]
    sep = t("names.list_sep")
    joined = sep.join(world.agents[a].short for a in p.supporters)
    opposed = sep.join(world.agents[a].short for a in p.opposers) or t("names.nobody")
    wave = world.wave_name(p.when)
    if p.status == "due" and p.due_day is not None:
        wave = t("time.wave_on", wave=wave, day=t("time.today") if p.due_day == world.day else t("time.tomorrow"))
    when = t("mind.project_when", place=world.place_name(p.site or p.place), wave=wave)
    if p.status == "done":
        return t("mind.project_done", id=p.id, who=world.name(p.proposer), title=p.title, result=(p.result or {}).get("public", ""))
    return t(
        "mind.project_line",
        id=p.id,
        place=world.place_name(p.place),
        who=world.name(p.proposer),
        title=p.title,
        goal=p.goal,
        needs=p.needs,
        when=when,
        joined=joined,
        opposed=opposed,
    )


def describe(world: World, agent: Agent, sig: Signal) -> str:
    t = world.t
    who, when, text = world.name(sig.source), ago(world, sig.born), sig.text
    if sig.kind == "speech":
        if sig.to == agent.id:
            return t("mind.said_to_you", who=who, when=when, text=text)
        if sig.to:
            return t("mind.said_to_other", who=who, to=world.name(sig.to), when=when, text=text)
        return t("mind.said_to_all", who=who, when=when, text=text)
    if sig.kind == "project" and sig.project in world.projects:
        return project_line(world, sig.project)
    if sig.kind in ("notice", "painting", "clue", "outcome", "prophecy"):
        return t(f"mind.{sig.kind}", who=who, when=when, text=text)
    if sig.kind == "dream":
        key = {"overgod": "mind.dream_overgod", "ullr": "mind.dream_ullr", "outer": "mind.dream_outer"}.get(sig.source, "mind.dream")
        return t(key, text=text)
    if sig.kind == "sign" and sig.source == "overgod":
        return t("mind.sign_overgod", when=when, text=text)
    if sig.kind in ("sign", "boon"):
        return t("mind.wonder", when=when, text=text)
    if sig.kind == "ledger":
        return t("mind.ledger_overgod" if sig.source == "overgod" else "mind.ledger", text=text)
    if sig.kind == "omen" and sig.audience:
        return text
    if sig.kind == "omen":
        return t("mind.omen", text=text)
    return text


def moment(world: World, agent: Agent, firing: Firing) -> str:
    """What a stirred villager sees now."""
    t = world.t
    sep = t("names.list_sep")
    place = world.places[agent.loc]
    lines = [
        t("mind.day_line", day=world.day, wave=world.wave_name(world.wave).upper(), weather=world.hidden.get("weather", "")),
        t("mind.you_are_at", place=place["name"], desc=place["desc"]),
    ]
    here = [a for a in world.present(agent.loc) if a.id != agent.id]
    lines.append(t("mind.here_with_you", who=sep.join(t("mind.here_person", name=a.name, role=a.role) for a in here) or t("names.nobody")))
    feats = place.get("feature", [])
    if feats:
        lines.append(t("mind.could_look", things=sep.join(t("mind.thing", name=f["name"], id=f["id"]) for f in feats)))
    lines.append(t("mind.roads_from", roads=sep.join(t("mind.road", name=world.places[r]["name"], id=r) for r in place["roads"])))

    lines.append("\n" + t("mind.stirs"))
    shown = set()
    for sid, _ in firing.contribs[:7]:
        sig = world.signals.get(sid)
        if sig:
            lines.append(f"- {describe(world, agent, sig)}")
            shown.add(sid)
    pending = [p for p in world.projects.values() if p.status in ("open", "due")]
    mine = [p for p in pending if agent.id in p.supporters]
    if mine:
        lines.append("\n" + t("mind.your_projects"))
        lines.extend(f"- {project_line(world, p.id)}" for p in mine)
    projects = [p for p in pending if agent.loc in (p.place, p.site) and p.signal not in shown and p not in mine]
    if projects:
        lines.append("\n" + t("mind.other_projects"))
        lines.extend(f"- {project_line(world, p.id)}" for p in projects)
    on_mind = [world.signals[h] for h in agent.heard if h in world.signals and h not in shown][-4:]
    if on_mind:
        lines.append("\n" + t("mind.on_mind"))
        lines.extend(f"- {describe(world, agent, s)}" for s in on_mind)
    if agent.recent:
        lines.append("\n" + t("mind.did_last"))
        lines.extend(f"- {r}" for r in agent.recent[-3:])

    lines.append("\n" + t("mind.you_line", health=t.get("health.you")[agent.health], items=carried(world, agent) or t("mind.nothing_of_note")))
    if agent.skills:
        names = t.get("names.skills")
        sheet = sep.join(f"{names.get(k, k)} {v}" for k, v in sorted(agent.skills.items(), key=lambda kv: -kv[1]))
        lines.append(t("mind.skills_line", skills=sheet))
    if agent.failures:
        lines.append(t("mind.failed_line", fails=t("names.clause_sep").join(agent.failures[-3:])))
    if has_god(world):
        lines.append("\n" + t("mind.ledger_heading") + "\n" + ledger_text(world))
    light = world.hidden.get("overgod", {}).get("written", [])
    if light:
        lines.append("\n" + t("mind.light_heading") + "\n" + "\n".join(f"- {x}" for x in light[-5:]))
    lines.append("\n" + t("mind.notes_heading") + "\n" + (world.read_memory(agent.id) or t("mind.empty")))
    return "\n".join(lines)
