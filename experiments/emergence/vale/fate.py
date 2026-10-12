"""What actually happens when villagers try something, together or alone.

The only place the hidden truth meets the villagers' plans. Fate is the game master:
impartial and narrow. For each attempt it sets a d100 check (which skill, whose, what
helps and what hinders, how wild it is) and writes every outcome before the dice fall;
the engine rolls, and only that outcome happens, through the listed effects.
"""

from __future__ import annotations

from typing import Any

from . import dice
from .act import goods
from .llm import LLM, parse_json_object
from .nature import describe_state
from .world import WAVES, Agent, Project, World

KNOWS = {
    "verse1": "knows the first verse of the stone-song by heart",
    "verse2": "has read the second verse cut on the barrow stones",
    "tune": "knows the tune of the stone-song",
    "deep_door": "has seen the carved wall in the deep gallery",
    "ledger": "has read Osric's ledger",
    "book": "has read the chapel book's account of the Red Year",
    "stones_lock": "knows the stones are a lock on something old",
    "old_script": "reads Old Script",
    "literate": "can read",
    "wyrm_iron": "has heard the ore called wyrm-iron",
    # the second layer: what they can do, if they choose to
    "adventurer": "was once Bram Ironhand, a famed adventurer: knows how to raise a fallen standing stone with levers, ropes and six strong backs under his direction, and has killed a dire wolf",
    "high_magic": "was a high mage before her vows: can still work great magic (seal a breach, lift a stone, cleanse water for days), but her great spells go badly wrong about one time in three",
    "knight": "a trained knight",
    "men_at_arms": "commands four strong, loyal men-at-arms at the keep",
    "signet": "wears a signet ring with the Thorne arms, left with him as a foundling",
    "mage_blood": "has a mage's blood: old carved words speak to him",
    "strength_draught": "can brew a bitter draught that lets a coughing sick person work hard for one day",
    "true_voice": "is old Ullr's chosen child, though nobody knows it, she least of all: when she sings the shepherd's song among the stones, his authority wakes through her and holds far longer",
    "muster": "as reeve, can call a muster of twenty able villagers for a day's common work",
    "healing_hands": "has healing hands: can draw a fever out of the very sick into herself",
    "tunnel_map": "has the old engineers' map of the tunnels under Greyfang, with a dry adit that reaches the deep workings safely from above the water",
    "sapper": "was a royal sapper: knows how to shore a gallery and seal a breach with timber cribbing and rubble",
    "hidden_stores": "has timber, rope, tools and lamps set aside in Thornkeep's undercroft",
    "locks": "a retired master burglar: can open any lock and climb any wall",
    "market": "keeps rope, timber and covered jars for sale at his Fenford stalls",
    "archer": "the best archer in the west vales; knows where the wolves den, and with two steady companions can kill or drive off the pack",
    "outer_god": "serves pleiades, an Outer God, who can grant boons through her",
}

SYSTEM = """You are the Vale of Ashmere itself: the impartial physics and fate of a living medieval world, and the game master for the people in it. You know the hidden truth below. Someone is trying something, now. You set the check and write what each fall of the dice would bring; then the dice are rolled, and only that outcome happens.

THE CHECK (d100, rolled under a skill):
- Every attempt is rolled; the dice are never skipped. Choose the one skill it rests on most (strength, craft, lore, song, healing, hunting, arms, magic, persuade, stealth, trade or notice), and who rolls it: whoever taking part has the best fitting skill. Their number is on their sheet; you do not set it.
- Routine things a capable person simply does are rolled too, but made easy: keeping watch, sitting with the sick and keeping up care that is already working, carrying a manageable load, ordinary chores, looking at what is in plain view, writing something down. Give them +20 to +40 for being routine and set the fumble number to 100. Their failure is small (time lost, the work to do again), and their fumble falls only on whoever does the work (a spill, a burn, a cut hand), never on anyone being cared for.
- Add a modifier for each thing that bears on it, with a short reason: a helper who brings a fitting skill or a strong back (+5 to +10 each); fitting tools, goods, knowledge or preparation (+5 to +20); the hidden truth, the place, the weather and the hour; and whatever is missing or against it: too few hands, no tools, unknown ground, someone opposing (-10 to -40). Leave out health: it is counted for you.
- The dice: skill plus modifiers is the target, held between 5 and 95. A roll at or under a fifth of the target is a critical; at or under the target a success; up to 20 over it a partial; higher a failure. A roll at or over the fumble number is a fumble, whatever the target.
- The fumble number is 100 for routine work and 96 for ordinary work. Set it lower when the attempt is dangerous: about 91 for unsafe ground, deep water, fire or wolves; about 81 for a great risk; 67 for great magic, which goes badly wrong one time in three.

THE OUTCOMES: write all five before the dice fall, honestly and in proportion.
- critical: better than they hoped. success: done, as fully as these people with what they have could plausibly do it; never a miracle. partial: half done, or done at a price. failure: it does not work; something is spent or learned. fumble: it goes wrong: someone is hurt, something is lost or broken, or matters are made worse. A fumble falls on the people doing the work and on what they risk; someone being cared for is harmed by it only if the care itself is a dangerous act (cutting, drawing out a fever, moving the gravely hurt).
- Follow cause and effect and the hidden truth. A missing skill, tool or pair of hands makes success less likely and smaller; it never stops the attempt.
- Precautions in a plan (an examination first, a guard, "only if it is safe") are intentions, not laws of nature. An unmet precaution never stops the attempt; it makes it more dangerous.
- Each outcome: two to four vivid, concrete sentences of what the people there see, and the effects that follow from it. Reveal hidden truth only as far as they would see it. Never decide anyone's feelings, words or later choices.
- The world changes only through the effects listed; leave the effects empty when nothing changes. Nobody dies.

THE HIDDEN TRUTH:
{truth}"""

EFFECTS = """  {"type": "seal_shaft"}  -- the breach in the deep gallery is shut again
  {"type": "reopen_shaft"}
  {"type": "raise_stone"}  -- the fallen stone on Barrow Hill stands again
  {"type": "sing", "verses": 1 or 2}  -- the shepherd's song is sung among the stones (with both verses and the stone raised, old Ullr's authority wakes for a while)
  {"type": "purify", "place": "<place id>", "amount": 0.05 to 0.3}  -- the water there is eased for a while
  {"type": "heal", "place": "<place id>", "amount": 0.05 to 0.4}  -- the sick there are eased
  {"type": "wolves", "result": "driven_off" | "killed" | "failed"}
  {"type": "item", "who": "<person id>", "item": "<water (a jar of clean water), jars, timber, rope, lamps, tools, remedy, herbs, moonwort, map, coin, bread, ore, wool, flour, ale or game>", "qty": <positive gains, negative loses>}
  {"type": "health", "who": "<person id>", "change": 1 (worse) or -1 (better)}
  {"type": "confine", "who": "<person id>", "days": 1 to 3}  -- locked up at Thornkeep
  {"type": "tie", "a": "<person id>", "b": "<person id>", "change": -0.5 to 0.5}  -- how a now feels about b
  {"type": "reveal", "text": "<something now plain to everyone at the place>"}"""

USER_PROJECT = """THE VALE NOW (day {day}, {hour}):
{state}

AN UNDERTAKING, attempted now at {place}, at {hour}. {setting}
{purposes}
Taking part (here now):
{participants}
Pledged, but not here: {absent}
Opposed by: {opposers}

Place ids: {places}. Person ids: {people}.

EFFECTS YOU MAY USE:
{effects}

{reply}"""

USER_ATTEMPT = """THE VALE NOW (day {day}, {hour}):
{state}

ONE PERSON TRIES SOMETHING, now, at {place}. {setting}
{actor}
What they try: "{what}"
What they use: "{using}"
Also here: {others}

Place ids: {places}. Person ids: {people}.

EFFECTS YOU MAY USE:
{effects}

{reply}"""

REPLY = """Reply with JSON only, and write every outcome before you know the roll:
{"skill": "<strength, craft, lore, song, healing, hunting, arms, magic, persuade, stealth, trade or notice>",
 "roller": "<person id of whoever rolls>",
 "modifiers": [{"why": "<short reason>", "mod": <whole number: plus helps, minus hinders>}],
 "fumble": <100 for routine work, 96 for ordinary work, lower for a dangerous attempt>,
 "outcomes": {
   "critical": {"public": "<what everyone there sees happen>", "effects": [...]},
   "success": {"public": "...", "effects": [...]},
   "partial": {"public": "...", "effects": [...]},
   "failure": {"public": "...", "effects": [...]},
   "fumble": {"public": "...", "effects": [...]}
 },
 "secret": "<anything true that nobody saw, or an empty string>"}"""

# If the game master left a band out, the nearest one stands in for it.
NEAREST = {"critical": ("success",), "success": ("critical", "partial"), "partial": ("success", "failure"),
           "failure": ("partial", "fumble"), "fumble": ("failure",)}
PLAIN = {"critical": "It went better than anyone hoped.", "success": "It worked.", "partial": "It half worked.",
         "failure": "It did not work.", "fumble": "It went wrong."}


def _skills(a: Agent) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(a.skills.items(), key=lambda kv: -kv[1]) if v > 0) or "none written down"


def _person(world: World, aid: str, offer: str | None = None) -> str:
    a = world.agents[aid]
    knows = "; ".join(KNOWS[k] for k in a.knows if k in KNOWS) or "nothing special"
    items = ", ".join(f"{k} x{v}" for k, v in a.items.items() if v > 0) or "nothing"
    notes = world.read_memory(aid).replace("\n", " ")[:500]
    health = ("well", "coughing", "fevered")[a.health]
    offered = f' Offered: "{offer}".' if offer is not None else ""
    return (
        f"- {a.name} [{aid}], {a.role}; {health}; carries {items}; skills: {_skills(a)}; {knows}.{offered} "
        f'Their own notes: "{notes}"'
    )


def _setting(world: World, loc: str) -> str:
    place = world.places[loc]
    things = ", ".join(f["name"] for f in place.get("feature", []))
    return f"The place: {place['desc']}" + (f" Things here: {things}." if things else "")


def _system(world: World) -> dict[str, str]:
    truth = world.truth + (f"\n\n{world.truth_deep}" if world.truth_deep else "")
    return {"role": "system", "content": SYSTEM.format(truth=truth)}


def project_messages(world: World, group: list[Project], present: list[str], absent: list[str]) -> list[dict[str, str]]:
    """The check for one or more undertakings set for the same place and hour, attempted together."""
    site = group[0].site or group[0].place
    offers = {aid: offer for p in group for aid, offer in p.supporters.items()}
    purposes = "\n".join(
        f'[{p.id}] "{p.title}", proposed by {world.name(p.proposer)}: {p.goal} Needs, as proposed: {p.needs}' for p in group
    )
    if len(group) > 1:
        purposes = f"{len(group)} undertakings were set for this place and hour; those who came attempt them together:\n{purposes}"
    opposers = {aid: why for p in group for aid, why in p.opposers.items()}
    user = USER_PROJECT.format(
        day=world.day, hour=WAVES[world.wave], state=describe_state(world), place=world.place_name(site), setting=_setting(world, site),
        purposes=purposes, participants="\n".join(_person(world, aid, offers.get(aid, "")) for aid in present),
        absent=", ".join(world.name(aid) for aid in absent) or "nobody",
        opposers=", ".join(f"{world.name(aid)} ({why or 'no reason given'})" + (" -- here now" if world.agents[aid].loc == site else "")
                           for aid, why in opposers.items()) or "nobody",
        places=", ".join(world.places), people=", ".join(world.agents), effects=EFFECTS, reply=REPLY,
    )
    return [_system(world), {"role": "user", "content": user}]


def attempt_messages(world: World, a: Agent, what: str, using: str, place: str) -> list[dict[str, str]]:
    """The check for one person trying something hard, here and now."""
    others = [o for o in world.present(place) if o.id != a.id]
    user = USER_ATTEMPT.format(
        day=world.day, hour=WAVES[world.wave], state=describe_state(world), place=world.place_name(place), setting=_setting(world, place),
        actor=_person(world, a.id), what=what, using=using or "nothing in particular",
        others=", ".join(f"{o.name} ({o.role}, {('well', 'coughing', 'fevered')[o.health]})" for o in others) or "nobody",
        places=", ".join(world.places), people=", ".join(world.agents), effects=EFFECTS, reply=REPLY,
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
    chosen = written.get(band) or next((written[b] for b in NEAREST[band] if b in written), None) or {"public": PLAIN[band], "effects": []}
    return {
        "outcome": band,
        "public": str(chosen["public"]).strip(),
        "effects": chosen.get("effects") or [],
        "secret": str(chosen.get("secret") or plan.get("secret") or ""),
        "check": check,
        "might": {b: str(o["public"]).strip() for b, o in written.items() if b != band},
    }


def apply_effects(world: World, effects: list[Any], *, ref: str, present: list[str], site: str) -> list[dict]:
    """Apply the effects of the outcome the dice chose; anything malformed is dropped (and logged)."""
    h = world.hidden
    applied: list[dict] = []
    for e in effects if isinstance(effects, list) else []:
        if not isinstance(e, dict):
            continue
        t = str(e.get("type", ""))
        try:
            if t == "seal_shaft":
                h["shaft_open"] = 0
            elif t == "reopen_shaft":
                h["shaft_open"] = 1
            elif t == "raise_stone":
                h["stone_raised"] = 1
            elif t == "sing":
                if int(e.get("verses", 1)) >= 2 and h["stone_raised"]:
                    if "ullr_awake" in h:
                        # Old Ullr wakes for a while: three nights, seven if his chosen sings among them.
                        wynn = world.agents.get("wynn")
                        chosen = "wynn" in present and wynn is not None and wynn.loc == site
                        h["ullr_awake"] = max(int(h["ullr_awake"]), 7 if chosen else 3)
                        h["stones_sung"] = int(h.get("stones_sung", 0)) + 1
                    else:
                        h["stones_sung"] = 1  # runs from before Ullr: a permanent binding
                else:
                    h["stone_hum"] = min(2, int(h.get("stone_hum", 0)) + 1)
            elif t == "purify":
                place = world.resolve_place(str(e["place"]))
                amount = max(0.05, min(0.3, float(e.get("amount", 0.1))))
                if place in h["blight"]:
                    h["relief"][place] = max(h["relief"].get(place, 0.0), amount)
                else:
                    continue
            elif t == "heal":
                place = world.resolve_place(str(e["place"]))
                amount = max(0.05, min(0.4, float(e.get("amount", 0.1))))
                if place in h["sickness"]:
                    h["sickness"][place] = round(max(0.0, h["sickness"][place] - amount), 4)
                for a in world.present(place):
                    a.health = max(0, a.health - 1)
            elif t == "wolves":
                result = str(e.get("result"))
                if result in ("driven_off", "killed"):
                    h["wolves"]["hunger"] = 0.0
                    h["wolves"]["driven"] = int(h["wolves"].get("driven", 0)) + 1
                    if result == "killed":
                        h["wolves"]["killed"] = 1
            elif t == "item":
                a = world.agents[str(e["who"])]
                item, qty = goods(e["item"]), int(e["qty"])
                e["item"] = item
                a.items[item] = max(0, a.items.get(item, 0) + qty)
            elif t == "health":
                a = world.agents[str(e["who"])]
                a.health = max(0, min(2, a.health + (1 if int(e["change"]) > 0 else -1)))
            elif t == "confine":
                a = world.agents[str(e["who"])]
                a.confined = max(1, min(3, int(e.get("days", 1))))
                a.loc, a.travel = "thornkeep", None
            elif t == "tie":
                a, b = world.agents[str(e["a"])], str(e["b"])
                if b in world.agents:
                    change = max(-0.5, min(0.5, float(e["change"])))
                    a.ties[b] = round(max(-1.0, min(1.0, a.ties.get(b, 0.0) + change)), 3)
            elif t == "reveal":
                pass  # rendered as its own signal by the engine
            else:
                continue
        except (KeyError, TypeError, ValueError):
            world.log("bad_effect", ref=ref, effect=e)
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
        return {"skill": "craft", "modifiers": [{"why": "stub", "mod": 0}], "fumble": 96,
                "outcomes": {b: {"public": f"({b}) They tried. The dice decided.", "effects": []} for b in dice.BANDS}, "secret": ""}
