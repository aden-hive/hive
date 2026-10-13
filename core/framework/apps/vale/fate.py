"""What actually happens when villagers try something, together or alone.

The only place the hidden truth meets the villagers' plans. Fate is the game master:
impartial and narrow. For each attempt it sets a d100 check (which skill, whose, what
helps and what hinders, how wild it is) and writes every outcome before the dice fall;
the engine rolls, and only that outcome happens, through the listed effects.
"""

from __future__ import annotations

from typing import Any

from . import dice
from .act import carried, goods
from .llm import LLM, parse_json_object
from .nature import describe_state
from .rules import rules_for
from .world import Agent, Project, World

# If the game master left a band out, the nearest one stands in for it.
NEAREST = {
    "critical": ("success",),
    "success": ("critical", "partial"),
    "partial": ("success", "failure"),
    "failure": ("partial", "fumble"),
    "fumble": ("failure",),
}


def knows_text(world: World, a: Agent, hidden: frozenset[str] | set[str] = frozenset()) -> str:
    """What someone knows, as the story describes it to fate and the gods."""
    known = world.story.get("knows", {})
    return world.t("names.clause_sep").join(known[k] for k in a.knows if k in known and k not in hidden) or world.t("fate.knows_nothing")


def _skills(world: World, a: Agent) -> str:
    names = world.t.get("names.skills")
    return world.t("names.list_sep").join(f"{names.get(k, k)} {v}" for k, v in sorted(a.skills.items(), key=lambda kv: -kv[1]) if v > 0) or world.t(
        "fate.no_skills"
    )


def _person(world: World, aid: str, offer: str | None = None) -> str:
    t = world.t
    a = world.agents[aid]
    return t(
        "fate.person",
        name=a.name,
        id=aid,
        role=a.role,
        health=t.get("health.short")[a.health],
        items=carried(world, a) or t("names.nothing"),
        skills=_skills(world, a),
        knows=knows_text(world, a),
        offered=t("fate.offered", offer=offer) if offer is not None else "",
        notes=world.read_memory(aid).replace("\n", " ")[:500],
    )


def _setting(world: World, loc: str) -> str:
    place = world.places[loc]
    things = world.t("names.list_sep").join(f["name"] for f in place.get("feature", []))
    return world.t("fate.setting", desc=place["desc"]) + (world.t("fate.things_here", things=things) if things else "")


def _system(world: World) -> dict[str, str]:
    truth = world.truth + (f"\n\n{world.truth_deep}" if world.truth_deep else "")
    vale = world.story.get("story", {}).get("vale", world.cfg["vale"]["name"])
    return {"role": "system", "content": world.t("fate.system", vale=vale, truth=truth)}


def _common(world: World, place: str) -> dict[str, str]:
    return {
        "day": str(world.day),
        "hour": world.wave_name(world.wave),
        "state": describe_state(world),
        "place": world.place_name(place),
        "setting": _setting(world, place),
        "places": ", ".join(world.places),
        "people": ", ".join(world.agents),
        "effects": world.story.get("fate", {}).get("effects", ""),
        "reply": world.t("fate.reply"),
    }


def project_messages(world: World, group: list[Project], present: list[str], absent: list[str]) -> list[dict[str, str]]:
    """The check for one or more undertakings set for the same place and hour, attempted together."""
    t = world.t
    sep = t("names.list_sep")
    site = group[0].site or group[0].place
    offers = {aid: offer for p in group for aid, offer in p.supporters.items()}
    purposes = "\n".join(t("fate.purpose", id=p.id, title=p.title, who=world.name(p.proposer), goal=p.goal, needs=p.needs) for p in group)
    if len(group) > 1:
        purposes = t("fate.purposes_together", n=len(group), list=purposes)
    opposers = {aid: why for p in group for aid, why in p.opposers.items()}
    user = t(
        "fate.user_project",
        **_common(world, site),
        purposes=purposes,
        participants="\n".join(_person(world, aid, offers.get(aid, "")) for aid in present),
        absent=sep.join(world.name(aid) for aid in absent) or t("names.nobody"),
        opposers=sep.join(
            t("fate.opposer", who=world.name(aid), why=why or t("fate.no_reason")) + (t("fate.here_now") if world.agents[aid].loc == site else "")
            for aid, why in opposers.items()
        )
        or t("names.nobody"),
    )
    return [_system(world), {"role": "user", "content": user}]


def attempt_messages(world: World, a: Agent, what: str, using: str, place: str) -> list[dict[str, str]]:
    """The check for one person trying something hard, here and now."""
    t = world.t
    others = [o for o in world.present(place) if o.id != a.id]
    user = t(
        "fate.user_attempt",
        **_common(world, place),
        actor=_person(world, a.id),
        what=what,
        using=using or t("fate.nothing_in_particular"),
        others=t("names.list_sep").join(t("fate.other", name=o.name, role=o.role, health=t.get("health.short")[o.health]) for o in others)
        or t("names.nobody"),
    )
    return [_system(world), {"role": "user", "content": user}]


def _outcome(raw: object) -> dict | None:
    if isinstance(raw, dict) and str(raw.get("public") or "").strip():
        return raw
    if isinstance(raw, str) and raw.strip():
        return {"public": raw, "effects": []}
    return None


def settle(world: World, plan: dict, people: list[str]) -> dict:
    """Roll the check the game master set, among the people taking part, and pick its outcome.

    Every attempt is rolled; routine work is made easy by the game master, never left unrolled.
    """
    outcomes = plan.get("outcomes") if isinstance(plan.get("outcomes"), dict) else {}
    written = {b: o for b in dice.BANDS if (o := _outcome(outcomes.get(b)))}
    skill = dice.skill_name(plan.get("skill")) or "notice"
    roller = str(plan.get("roller") or "")
    if roller not in people:
        roller = max(people, key=lambda aid: world.agents[aid].skills.get(skill, 0))
    mods = []
    for m in plan.get("modifiers") or []:
        try:
            mod = round(float(m.get("mod", 0)))
        except (AttributeError, TypeError, ValueError):
            continue
        mods.append({"why": str(m.get("why") or "")[:140], "mod": max(-50, min(40, mod))})
    try:
        fumble = int(plan.get("fumble") or dice.FUMBLE)
    except (TypeError, ValueError):
        fumble = dice.FUMBLE
    check = dice.roll(world, world.agents[roller], skill, mods, fumble=fumble)
    band = check["band"]
    chosen = (
        written.get(band)
        or next((written[b] for b in NEAREST[band] if b in written), None)
        or {"public": world.t.get("fate.plain")[band], "effects": []}
    )
    return {
        "outcome": band,
        "public": str(chosen["public"]).strip(),
        "effects": chosen.get("effects") or [],
        "secret": str(chosen.get("secret") or plan.get("secret") or ""),
        "check": check,
        "might": {b: str(o["public"]).strip() for b, o in written.items() if b != band},
    }


def apply_effects(world: World, effects: list[Any], *, ref: str, present: list[str], site: str) -> list[dict]:
    """Apply the effects of the outcome the dice chose; anything malformed is dropped (and logged).

    The standard effects every world has are here: goods, health, confinement, ties and
    reveals. Every other effect type is the world's own, declared in its rules.toml.
    """
    rules = rules_for(world)
    applied: list[dict] = []
    for e in effects if isinstance(effects, list) else []:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type", ""))
        try:
            if t == "item":
                a = world.agents[str(e["who"])]
                item, qty = goods(world, e["item"]), int(e["qty"])
                e["item"] = item
                a.items[item] = max(0, a.items.get(item, 0) + qty)
            elif t == "health":
                a = world.agents[str(e["who"])]
                a.health = max(0, min(2, a.health + (1 if int(e["change"]) > 0 else -1)))
            elif t == "confine":
                a = world.agents[str(e["who"])]
                a.confined = max(1, min(3, int(e.get("days", 1))))
                jail = rules.constants.get("jail")
                if jail:
                    a.loc, a.travel = jail, None
            elif t == "tie":
                a, b = world.agents[str(e["a"])], str(e["b"])
                if b in world.agents:
                    change = max(-0.5, min(0.5, float(e["change"])))
                    a.ties[b] = round(max(-1.0, min(1.0, a.ties.get(b, 0.0) + change)), 3)
            elif t == "reveal":
                pass  # rendered as its own signal by the engine
            elif not rules.effect(world, e, present=present, site=site):
                continue  # not one of this world's effects, or its condition refused it
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            world.log("bad_effect", ref=ref, effect=e, error=str(exc)[:200])
            continue
        applied.append(e)
    return applied


class LLMFate:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def ask(self, messages: list[dict[str, str]]) -> dict:
        """The game master's plan for one check; an empty plan still gets rolled."""
        for attempt in range(2):
            try:
                return parse_json_object(self.llm.chat(messages, temperature=0.4, max_tokens=1800))
            except (ValueError, RuntimeError) as exc:
                error = str(exc)
                if attempt == 0:
                    messages = messages + [{"role": "user", "content": "Reply with the JSON object only."}]
        return {"error": error}


class StubFate:
    def ask(self, messages: list[dict[str, str]]) -> dict:
        return {
            "skill": "craft",
            "modifiers": [{"why": "stub", "mod": 0}],
            "fumble": 96,
            "outcomes": {b: {"public": f"({b}) They tried. The dice decided.", "effects": []} for b in dice.BANDS},
            "secret": "",
        }
