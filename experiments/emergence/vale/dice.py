"""Tabletop dice: a d100 rolled under a skill from the villager's character sheet.

The engine rolls, never a model. Fate, as game master, only sets the check (which
skill, whose, what helps and what hinders, how wild it is) and writes every outcome
before the dice fall; the roll then picks one. Health counts by itself.
"""

from __future__ import annotations

from .world import Agent, World

SKILLS = ("strength", "craft", "lore", "song", "healing", "hunting", "arms", "magic", "persuade", "stealth", "trade", "notice")
BANDS = ("critical", "success", "partial", "failure", "fumble")
FUMBLE = 96  # ordinary work: a roll of 96 or more goes wrong, whatever the odds
SICKNESS = {1: ("coughing", -10), 2: ("fevered", -20)}

# What the game master may call a skill, and which one we mean.
SKILL_ALIASES = {
    "might": "strength", "labour": "strength", "labor": "strength", "athletics": "strength", "endurance": "strength",
    "building": "craft", "engineering": "craft", "carpentry": "craft", "masonry": "craft", "smithing": "craft", "sapping": "craft",
    "knowledge": "lore", "history": "lore", "reading": "lore", "scholarship": "lore", "old script": "lore",
    "singing": "song", "music": "song", "voice": "song",
    "medicine": "healing", "herbalism": "healing", "first aid": "healing",
    "tracking": "hunting", "survival": "hunting", "archery": "hunting", "woodcraft": "hunting",
    "fighting": "arms", "combat": "arms", "weapons": "arms",
    "sorcery": "magic", "spellcraft": "magic", "high magic": "magic",
    "persuasion": "persuade", "diplomacy": "persuade", "charm": "persuade", "leadership": "persuade", "command": "persuade",
    "lockpicking": "stealth", "sneaking": "stealth", "climbing": "stealth", "burglary": "stealth",
    "bargaining": "trade", "haggling": "trade", "commerce": "trade",
    "perception": "notice", "search": "notice", "spot": "notice", "insight": "notice", "awareness": "notice",
}


def skill_name(raw: object) -> str | None:
    key = str(raw or "").strip().lower()
    return key if key in SKILLS else SKILL_ALIASES.get(key)


def band(roll: int, target: int, fumble: int = FUMBLE) -> str:
    """Where a d100 roll falls against a target: the fumble range overrides everything."""
    if roll >= fumble:
        return "fumble"
    if roll <= max(1, target // 5):
        return "critical"
    if roll <= target:
        return "success"
    if roll <= target + 20:
        return "partial"
    return "failure"


def roll(world: World, roller: Agent, skill: str, mods: list[dict], *, fumble: int = FUMBLE) -> dict:
    """Roll d100 under the roller's skill plus modifiers. Nothing hard is ever certain: 5 to 95."""
    mods = list(mods)
    if roller.health in SICKNESS:
        what, mod = SICKNESS[roller.health]
        mods.append({"why": f"{roller.short} is {what}", "mod": mod})
    base = int(roller.skills.get(skill, 0))
    target = max(5, min(95, base + sum(m["mod"] for m in mods)))
    fumble = max(60, min(100, int(fumble)))
    r = world.rng.randint(1, 100)
    return {"skill": skill, "roller": roller.id, "base": base, "mods": mods, "target": target,
            "fumble": fumble, "roll": r, "band": band(r, target, fumble)}


def line(check: dict, name: str) -> str:
    """One check as a tabletop player would read it out: `craft · Brannoc 80 +10 −20 = 70 · rolled 37 · success`."""
    mods = "".join(f" {'+' if m['mod'] >= 0 else '−'}{abs(m['mod'])}" for m in check["mods"])
    fumble = f" (fumbles on {check['fumble']}+)" if check["fumble"] < FUMBLE else ""
    return f"{check['skill']} · {name} {check['base']}{mods} = {check['target']}{fumble} · rolled {check['roll']} · {check['band']}"


def record(world: World, check: dict, *, kind: str, ref: str, place: str | None, what: str) -> None:
    """Every roll goes in the log, so the report can show the dice."""
    world.today["checks"] = world.today.get("checks", 0) + 1
    world.log("check", kind=kind, ref=ref, place=place, what=what, **check)
