"""What a stirred villager sees, and what they decide to do.

The physics chose *who* acts; the mind decides *what*. A villager's prompt holds
their persona (the system prompt), the shared rules of the world, and the moment:
where they are, who is with them, what stirred them, what's still on their mind,
and their own memory file, which they rewrite every time they act.
"""

from __future__ import annotations

import random
from typing import Any

from .god import has_god, ledger_text
from .lexicon import LEXICON
from .llm import LLM, parse_json_object
from .physics import Firing
from .world import WAVES, Agent, Signal, World

WORK_HINT = {
    "miller": "grind flour at the mill",
    "reeve": "hear complaints and keep the tally",
    "lord": "hold court and see to the keep",
    "steward": "keep the accounts",
    "foreman": "mine ore at Greyfang with your crew",
    "prioress": "lead prayers and keep the chapel",
    "herbwife": "gather moonwort and brew remedies at your hut",
    "shepherd": "tend the flock",
    "courier": "run errands for coin",
    "scribe": "write letters and copy pages for coin",
    "tavern": "brew and serve",
    "trader": "buy and sell at the stalls",
    "healer": "make remedies from herbs or moonwort",
    "hunter": "hunt the forest",
    "painter": "paint (use the paint action)",
}

HEALTH_TEXT = {0: "You are well", 1: "You have a cough with red in it", 2: "You are fevered and weak"}

INSTRUCTIONS = """WHAT NOW?
Decide what {short} does in this part of the day. Reply with JSON only:
{{
  "thought": "your private thinking, one or two sentences, in your own voice",
  "actions": [up to three actions, in the order you do them],
  "memory": "your private notes, rewritten in full: what you know, what you suspect, what you mean to do, what you owe. Under 130 words. Keep what matters; drop what doesn't.",
  "mood": "one word"
}}
Actions:
  {{"do": "say", "to": "<name of someone here, or everyone>", "text": "<what you say>"}}
  {{"do": "look", "at": "<id of a thing here>"}}
  {{"do": "post", "text": "<a notice to leave here>"}}
  {{"do": "give", "to": "<name of someone here>", "item": "<something you carry>", "qty": 1}}
  {{"do": "work"}}  -- {work}
  {{"do": "tend"}}  -- use a remedy to ease the sick here
  {{"do": "attempt", "what": "<something you set out to do here and now>", "with": "<the skill, tools or goods you use>"}}  -- the vale settles it at once: everything is rolled for, routine work easily; one attempt at a time
  {{"do": "propose", "title": "<short name>", "goal": "<what it is for>", "needs": "<who and what it needs>", "at": "<place id where it is done; leave out for here>", "when": "<dawn, morning, midday, afternoon, dusk or night>"}}  -- attempted at that hour (today if still to come, else tomorrow) with whoever joined and came, even if only you
  {{"do": "join", "project": "<id of an undertaking posted here, or to be done here>", "offer": "<what you bring>"}}  -- then be at its place, or one road from it, at its hour
  {{"do": "oppose", "project": "<id of an undertaking posted here, or to be done here>", "why": "<why>"}}
  {{"do": "travel", "to": "<place id>"}}  -- always your last action{paint}{pray}
An empty list of actions is a fine answer too."""

PAINT_LINE = '\n  {"do": "paint", "text": "<what the painting shows>"}  -- it hangs where you are, for anyone who comes by'
PRAY_LINE = '\n  {"do": "pray", "text": "<your prayer>"}  -- only God hears it, if anyone does'
PRAY_TO_MASTER_LINE = '\n  {"do": "pray", "to": "master" or "God", "text": "<your prayer>"}  -- master answers only you, and only for one of your paintings'
PRAY_TO_ANY_LINE = '\n  {"do": "pray", "to": "God" or "Ullr", "text": "<your prayer>"}  -- the True God, or the old god of the hills, if you hold with him'


def system_prompt(world: World, agent: Agent) -> str:
    places = []
    for pid, place in world.places.items():
        roads = ", ".join(world.places[r]["name"] for r in place["roads"])
        places.append(f"- {place['name']} [{pid}]: {place['desc']} Roads to: {roads}.")
    people = [f"- {a.name}: {a.public}." for a in world.agents.values() if a.id != agent.id]
    return "\n\n".join([
        world.personas[agent.id].strip(),
        world.rules.strip(),
        "## Places and roads\n" + "\n".join(places)
        + "\nThe Hollowbrook flows from Greyfang Mine past the Mill and Ashmere down to Fenford; in flood it spills into the Mirewood.",
        "## People of the vale (what everyone knows)\n" + "\n".join(people),
        *([world.god_rules.strip()] if has_god(world) and world.god_rules else []),
    ])


def _ago(now: float, born: float) -> str:
    age = now - born
    if age < 0.2:
        return "just now"
    if age < 1:
        return "earlier today"
    days = int(age + 0.5)
    return "yesterday" if days <= 1 else f"{days} days ago"


def project_line(world: World, pid: str) -> str:
    p = world.projects[pid]
    joined = ", ".join(world.agents[a].short for a in p.supporters)
    opposed = ", ".join(world.agents[a].short for a in p.opposers) or "nobody"
    when = f"at {world.place_name(p.site or p.place)}, at {WAVES[p.when]}"
    if p.status == "due" and p.due_day is not None:
        when += " today" if p.due_day == world.day else " tomorrow"
    if p.status == "done":
        return f'Undertaking [{p.id}] by {world.name(p.proposer)}: "{p.title}". It has been attempted: {(p.result or {}).get("public", "")}'
    return (
        f'Undertaking [{p.id}] posted at {world.place_name(p.place)} by {world.name(p.proposer)}: "{p.title}". {p.goal} Needs: {p.needs}. '
        f"To be attempted {when}, with whoever comes. Taking part so far: {joined}. Opposed: {opposed}."
    )


def describe(world: World, agent: Agent, sig: Signal) -> str:
    who, when = world.name(sig.source), _ago(world.now, sig.born)
    if sig.kind == "speech":
        if sig.to == agent.id:
            return f'{who} said to you ({when}): "{sig.text}"'
        if sig.to:
            return f'{who} said to {world.name(sig.to)} ({when}): "{sig.text}"'
        return f'{who} said to everyone here ({when}): "{sig.text}"'
    if sig.kind == "notice":
        return f'A notice posted here by {who} ({when}): "{sig.text}"'
    if sig.kind == "painting":
        return f"A painting by {who} hangs here ({when}). It shows: {sig.text}"
    if sig.kind == "clue":
        return f"What you found when you looked: {sig.text}"
    if sig.kind == "project" and sig.project in world.projects:
        return project_line(world, sig.project)
    if sig.kind == "outcome":
        return f"What came of it ({when}): {sig.text}"
    if sig.kind == "dream" and sig.source == "ullr":
        return f"In the night you dreamed, and the dream was cold and very old: {sig.text}"
    if sig.kind == "dream" and sig.source == "outer":
        return f"In the night, master spoke to you in a dream: {sig.text}"
    if sig.kind == "dream":
        return f"In the night you dreamed: {sig.text}"
    if sig.kind in ("sign", "boon"):
        return f"A wonder, here, {when}: {sig.text}"
    if sig.kind == "ledger":
        return f"New in the Ledger of the World today: {sig.text}"
    if sig.kind == "omen" and sig.audience:
        return sig.text
    if sig.kind == "omen":
        return f"This morning: {sig.text}"
    return sig.text


def moment(world: World, agent: Agent, firing: Firing) -> str:
    place = world.places[agent.loc]
    lines = [
        f"DAY {world.day}, {WAVES[world.wave].upper()}. {world.hidden.get('weather', '')}",
        f"You are at {place['name']}: {place['desc']}",
    ]
    here = [a for a in world.present(agent.loc) if a.id != agent.id]
    lines.append("Here with you: " + (", ".join(f"{a.name} ({a.role})" for a in here) if here else "nobody") + ".")
    feats = place.get("feature", [])
    if feats:
        lines.append("You could look closer at: " + ", ".join(f"{f['name']} [{f['id']}]" for f in feats) + ".")
    lines.append("Roads from here: " + ", ".join(f"{world.places[r]['name']} [{r}]" for r in place["roads"]) + ".")

    lines.append("\nWHAT STIRS YOU NOW, strongest first:")
    shown = set()
    for sid, _ in firing.contribs[:7]:
        sig = world.signals.get(sid)
        if sig:
            lines.append(f"- {describe(world, agent, sig)}")
            shown.add(sid)
    pending = [p for p in world.projects.values() if p.status in ("open", "due")]
    mine = [p for p in pending if agent.id in p.supporters]
    if mine:
        lines.append("\nUNDERTAKINGS YOU ARE PART OF (be at the place, or one road from it, at the hour):")
        lines.extend(f"- {project_line(world, p.id)}" for p in mine)
    projects = [p for p in pending if agent.loc in (p.place, p.site) and p.signal not in shown and p not in mine]
    if projects:
        lines.append("\nOTHER UNDERTAKINGS POSTED HERE OR TO BE DONE HERE:")
        lines.extend(f"- {project_line(world, p.id)}" for p in projects)
    on_mind = [world.signals[h] for h in agent.heard if h in world.signals and h not in shown][-4:]
    if on_mind:
        lines.append("\nSTILL ON YOUR MIND:")
        lines.extend(f"- {describe(world, agent, s)}" for s in on_mind)
    if agent.recent:
        lines.append("\nWHAT YOU DID LAST:")
        lines.extend(f"- {r}" for r in agent.recent[-3:])

    items = ", ".join(f"{k} x{v}" for k, v in agent.items.items() if v > 0) or "nothing of note"
    lines.append(f"\nYOU: {HEALTH_TEXT[agent.health]}. You carry: {items}.")
    if agent.skills:
        sheet = ", ".join(f"{k} {v}" for k, v in sorted(agent.skills.items(), key=lambda kv: -kv[1]))
        lines.append(f"Your skills, out of 100 (the dice roll under them when you try something hard): {sheet}.")
    if agent.failures:
        lines.append("What didn't work last time: " + "; ".join(agent.failures[-3:]) + ".")
    if has_god(world):
        lines.append("\nTHE LEDGER OF THE WORLD, as it reads today:\n" + ledger_text(world))
    lines.append("\nYOUR NOTES (your private memory file, as you last wrote it):\n" + (world.read_memory(agent.id) or "(empty)"))
    lines.append(
        "\n" + INSTRUCTIONS.format(
            short=agent.short,
            work=WORK_HINT.get(agent.profession, "do your trade"),
            paint=PAINT_LINE if agent.profession == "painter" else "",
            pray=(PRAY_TO_MASTER_LINE if agent.id == "bagel" and world.params.get("outer_god", 0) > 0
                  else PRAY_TO_ANY_LINE if world.params.get("ullr_agent", 0) > 0
                  else PRAY_LINE if has_god(world) else ""),
        )
    )
    return "\n".join(lines)


def _clean_reply(obj: dict) -> dict:
    actions = obj.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    actions = [a for a in actions if isinstance(a, dict)][:3]
    memory = obj.get("memory")
    return {
        "thought": str(obj.get("thought") or "")[:600],
        "actions": actions,
        "memory": memory.strip() if isinstance(memory, str) and memory.strip() else None,
        "mood": str(obj.get("mood") or "")[:24],
    }


class LLMMind:
    """Each stirring is one model call: persona + rules as system, the moment as user."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def prepare(self, world: World, agent: Agent, firing: Firing) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt(world, agent)},
            {"role": "user", "content": moment(world, agent, firing)},
        ]

    def run(self, job: list[dict[str, str]]) -> dict:
        try:
            raw = self.llm.chat(job, temperature=0.95, max_tokens=900)
            return {**_clean_reply(parse_json_object(raw)), "raw": raw}
        except (ValueError, RuntimeError) as exc:
            try:
                retry = job + [{"role": "user", "content": "Reply with the JSON object only."}]
                raw = self.llm.chat(retry, temperature=0.7, max_tokens=900)
                return {**_clean_reply(parse_json_object(raw)), "raw": raw}
            except (ValueError, RuntimeError) as exc2:
                return {"thought": "", "actions": [], "memory": None, "mood": "", "error": f"{exc}; {exc2}"}


class StubMind:
    """Dice instead of a model: for tuning the physics without spending tokens."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def prepare(self, world: World, agent: Agent, firing: Firing) -> dict[str, Any]:
        rng = self.rng
        tags = list(firing.tags) or list(agent.interests)
        words = " and ".join(LEXICON[t][0] for t in rng.sample(tags, min(2, len(tags))) if t in LEXICON) or "things"
        here = [a for a in world.present(agent.loc) if a.id != agent.id]
        actions: list[dict] = []
        if rng.random() < 0.85:
            to = rng.choice(here).short if here and rng.random() < 0.5 else "everyone"
            actions.append({"do": "say", "to": to, "text": f"Have you heard about the {words}?"})
        if rng.random() < 0.15:
            actions.append({"do": "post", "text": f"Mind the {words}."})
        feats = world.places[agent.loc].get("feature", [])
        if feats and rng.random() < 0.15:
            actions.append({"do": "look", "at": rng.choice(feats)["id"]})
        if rng.random() < 0.3:
            roads = world.places[agent.loc]["roads"]
            dest = agent.home if agent.loc != agent.home and agent.home in roads and rng.random() < 0.5 else rng.choice(roads)
            actions.append({"do": "travel", "to": dest})
        return {"thought": "", "actions": actions, "memory": None, "mood": "stub"}

    def run(self, job: dict[str, Any]) -> dict:
        return job
