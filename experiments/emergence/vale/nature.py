"""The hidden world: the blight, sickness, the wolves, and what each dawn shows.

None of this is visible to the villagers except through omens, sickness, what they
find when they look closely, and the outcomes of what they attempt together.
"""

from __future__ import annotations

from .world import World

# Downstream links of the Hollowbrook: (from, to, how much carries over).
RIVER = (("mine", "mill", 0.9), ("mill", "ashmere", 0.8), ("ashmere", "fenford", 0.75), ("mill", "mirewood", 0.7))
KEEP = {"mill": 0.5, "ashmere": 0.55, "fenford": 0.6, "mirewood": 0.6}

SICK_TEXT = {
    "mine": {
        1: "Some of the miners at Greyfang cough at the shaft head.",
        2: "Half of Greyfang's crew cough red; two can't work.",
        3: "Fever at Greyfang: the crew lie grey-lipped in the bunkhouse.",
    },
    "*": {
        1: "In {place} a few people have a dry cough, and some say the water tastes of iron.",
        2: "Coughing in many houses in {place}: red in the spit, and a child with grey lips.",
        3: "Fever in {place}: whole households abed and grey-lipped. People are frightened.",
    },
}

DEATHS = {
    "ashmere": "Old Widow Agnes, who lived by the well, died in the night, grey-lipped. Her daughter is keening on the green.",
    "mine": "Cob, of Brannoc's crew, died in the night with red on his lips.",
    "mill": "Hal's old mare lay down in the mill pasture and did not get up.",
    "fenford": "Old Wat the ferryman was found dead in his boat at dawn, grey-lipped; the boatmen will not cross.",
}

# What a long blight brings later: (flag, place, from day, sickness above, text).
GRIEFS = (
    ("grief_ashmere", "ashmere", 16, 0.7, "Two more died in Ashmere in the night, the cooper and his old mother. The green is full of keening."),
    ("grief_pip", "mill", 18, 0.7, "Pip, Hal's boy, is grey-lipped and burning with fever; Gytha says the very young go fast."),
    ("grief_mine", "mine", 20, 0.8, "Ned, of Brannoc's crew, died in the night; the crew carried him down to the chapel, coughing."),
)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, round(x, 4)))


def advance(world: World) -> None:
    """One night passes in the hidden world."""
    h = world.hidden
    b = h["blight"]
    prev = dict(b)
    delta = 0.09 if h["shaft_open"] else -0.06
    # While old Ullr's authority is awake the blood sleeps; it lapses unless the song is sung again.
    # (Runs made before Ullr had `stones_sung` as a permanent binding instead.)
    awake = int(h.get("ullr_awake", 0)) or (1 if h.get("stones_sung") and "ullr_awake" not in h else 0)
    if awake:
        delta -= 0.12
    elif h.get("stone_hum"):
        delta -= 0.03 * h["stone_hum"]
    b["mine"] = _clamp(prev["mine"] + delta)
    for src, dst, carry in RIVER:
        b[dst] = _clamp(KEEP[dst] * prev[dst] + (1 - KEEP[dst]) * carry * prev[src])
    if awake and not h["shaft_open"]:
        for k in b:
            b[k] = _clamp(b[k] * 0.7)

    relief = h["relief"]
    for k in list(relief):
        relief[k] = round(relief[k] - 0.08, 3)
        if relief[k] <= 0:
            del relief[k]

    sick = h["sickness"]
    for k in b:
        eff = max(0.0, b[k] - relief.get(k, 0.0))
        sick[k] = _clamp(sick.get(k, 0.0) * 0.85 + 0.35 * max(0.0, eff - 0.15))

    w = h["wolves"]
    if b["mirewood"] > 0.12:
        w["hunger"] = _clamp(w["hunger"] + (0.04 if w.get("killed") else 0.12))
    else:
        w["hunger"] = _clamp(w["hunger"] - 0.05)
    if w["hunger"] > 0.65:
        w["attacks"] += 1
        w["hunger"] = _clamp(w["hunger"] - 0.25)
        h["events"].append(("fold", 2.8, "Wolves got into the fold in the night: two ewes torn, and one of Bram's dogs bloodied."))

    # Villagers drink where they sleep.
    for a in world.agents.values():
        loc = a.loc or a.home
        eff = max(0.0, b.get(loc, 0.0) - relief.get(loc, 0.0))
        if eff > 0.3 and world.rng.random() < 0.25 * eff:
            a.health = min(2, a.health + 1)
        elif eff < 0.2 and a.health > 0 and world.rng.random() < 0.25:
            a.health -= 1

    flags = h["flags"]
    for place, text in DEATHS.items():
        threshold = 0.75 if place == "mine" else 0.55
        if sick.get(place, 0.0) > threshold and not flags.get(f"death_{place}"):
            flags[f"death_{place}"] = world.day
            h["events"].append((place, 3.0, text))
    for flag, place, day, threshold, text in GRIEFS:
        if world.day >= day and sick.get(place, 0.0) > threshold and not flags.get(flag):
            flags[flag] = world.day
            h["events"].append((place, 3.0, text))


def lapse(world: World) -> None:
    """After old Ullr's dawn turn: his waking runs down a night, and a half-sung song fades."""
    h = world.hidden
    if "ullr_awake" in h:
        h["ullr_awake"] = max(0, int(h["ullr_awake"]) - 1)
        if h.get("stone_hum"):
            h["stone_hum"] = max(0, int(h["stone_hum"]) - 1)


def dawn(world: World) -> list[str]:
    """What the vale shows this morning. Returns the new signal ids."""
    h = world.hidden
    day = world.day
    new: list[str] = []
    h["weather"] = world.rng.choice(world.cfg["vale"]["weathers"])

    def emit(text: str, loc: str | None, strength: float, audience: list[str] | None = None) -> None:
        sig = world.add_signal("omen", text, loc, "world", strength=strength, audience=audience)
        new.append(sig.id)

    for place, strength, text in h["events"]:
        emit(text, place, strength)
    h["events"] = []

    for om in world.cfg.get("omen", []):
        if not world.check(om.get("when", [])):
            continue
        last = world.omens.get(om["id"])
        every = om.get("every")
        if last is not None and (not every or day - last < every):
            continue
        world.omens[om["id"]] = day
        emit(om["text"], om.get("place"), float(om["strength"]), om.get("who"))

    for ev in world.cfg.get("calendar", []):
        if ev["day"] == day:
            places = list(world.places) if ev["place"] == "*" else [ev["place"]]
            for pl in places:
                emit(ev["text"], pl, float(ev["strength"]))

    deck = world.cfg.get("deck", [])
    eligible = [
        i for i, card in enumerate(deck)
        if i not in world.deck_used and day >= card.get("min_day", 1) and world.check(card.get("when", []))
    ]
    if eligible and world.rng.random() < 0.6:
        i = world.rng.choice(eligible)
        world.deck_used.append(i)
        emit(deck[i]["text"], deck[i]["place"], float(deck[i]["strength"]))

    brackets = h["sick_bracket"]
    for place, level in h["sickness"].items():
        bracket = 0 if level < 0.15 else 1 if level < 0.35 else 2 if level < 0.6 else 3
        if bracket and (bracket != brackets.get(place, 0) or day % 2 == 0):
            texts = SICK_TEXT.get(place, SICK_TEXT["*"])
            emit(texts[bracket].format(place=world.place_name(place)), place, 1.0 + 0.6 * bracket)
        brackets[place] = bracket

    for a in world.agents.values():
        if a.health == 1:
            emit("You woke coughing, and there was red in your spit.", None, 1.6, [a.id])
        elif a.health >= 2:
            emit("You are fevered and weak this morning; your lips feel cold, and walking far is beyond you.", None, 2.0, [a.id])

    return new


def describe_state(world: World) -> str:
    """The hidden state in plain words, for the adjudicator and the chronicler."""
    h = world.hidden

    def level(x: float) -> str:
        return "clean" if x < 0.12 else "faintly tainted" if x < 0.3 else "tainted" if x < 0.55 else "heavily tainted"

    stone = f"The fallen stone on Barrow Hill is {'raised again' if h['stone_raised'] else 'still fallen'}; "
    if "ullr_awake" in h:
        nights = int(h["ullr_awake"])
        stone += (f"old Ullr's authority is awake for {nights} more night(s), and the blood sleeps" if nights
                  else "old Ullr's authority sleeps") + (f"; a half-sung song has slowed the blight a little" if h.get("stone_hum") and not nights else "")
    else:
        stone += (f"the stones have {'been sung with both verses' if h['stones_sung'] else 'not been fully sung'}"
                  + (f" (a partial singing has slowed the blight {h['stone_hum']}x)" if h.get("stone_hum") and not h["stones_sung"] else ""))
    lines = [
        f"The deep door under Greyfang is {'OPEN: the wyrm-blood seeps out' if h['shaft_open'] else 'shut again'}.",
        stone + ".",
        "The water: " + "; ".join(f"{world.place_name(k)} {level(v)}" for k, v in h["blight"].items()) + ".",
        "Sickness: " + "; ".join(f"{world.place_name(k)} {round(v, 2)}" for k, v in h["sickness"].items()) + " (0 none, 1 everyone).",
        f"Wolves: hunger {round(h['wolves']['hunger'], 2)}, attacks on the fold so far {h['wolves']['attacks']}.",
    ]
    return "\n".join(lines)
