"""The hidden world: the blight, sickness, the wolves, and what each dawn shows.

None of this is visible to the villagers except through omens, sickness, what they
find when they look closely, and the outcomes of what they attempt together.
"""

from __future__ import annotations

from .lang import fill
from .world import World

# Downstream links of the Hollowbrook: (from, to, how much carries over).
RIVER = (("mine", "mill", 0.9), ("mill", "ashmere", 0.8), ("ashmere", "fenford", 0.75), ("mill", "mirewood", 0.7))
KEEP = {"mill": 0.5, "ashmere": 0.55, "fenford": 0.6, "mirewood": 0.6}

# Deaths a heavy sickness brings, once each: place -> sickness above which it comes. The words are the story's.
DEATHS = {"ashmere": 0.55, "mine": 0.75, "mill": 0.55, "fenford": 0.55}

# What a long blight brings later: (flag, place, from day, sickness above). The words are the story's.
GRIEFS = (
    ("grief_ashmere", "ashmere", 16, 0.7),
    ("grief_pip", "mill", 18, 0.7),
    ("grief_mine", "mine", 20, 0.8),
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
        h["events"].append(("fold", 2.8, world.story["nature"]["wolves_in_fold"]))

    # Villagers drink where they sleep.
    for a in world.agents.values():
        loc = a.loc or a.home
        eff = max(0.0, b.get(loc, 0.0) - relief.get(loc, 0.0))
        if eff > 0.3 and world.rng.random() < 0.25 * eff:
            a.health = min(2, a.health + 1)
        elif eff < 0.2 and a.health > 0 and world.rng.random() < 0.25:
            a.health -= 1

    flags = h["flags"]
    words = world.story.get("nature", {})
    for place, threshold in DEATHS.items():
        if sick.get(place, 0.0) > threshold and not flags.get(f"death_{place}"):
            flags[f"death_{place}"] = world.day
            h["events"].append((place, 3.0, words.get("deaths", {})[place]))
    for flag, place, day, threshold in GRIEFS:
        if world.day >= day and sick.get(place, 0.0) > threshold and not flags.get(flag):
            flags[flag] = world.day
            h["events"].append((place, 3.0, words.get("griefs", {})[flag]))


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
    weathers = world.cfg["vale"]["weathers"]
    pick = world.rng.randrange(len(weathers))  # draws from the dice exactly as choice() did, so old runs replay
    h["weather"] = weathers[pick]
    h["weather_kind"] = (world.cfg["vale"].get("weather_kinds") or [""] * len(weathers))[pick]

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
    eligible = [i for i, card in enumerate(deck) if i not in world.deck_used and day >= card.get("min_day", 1) and world.check(card.get("when", []))]
    if eligible and world.rng.random() < 0.6:
        i = world.rng.choice(eligible)
        world.deck_used.append(i)
        emit(deck[i]["text"], deck[i]["place"], float(deck[i]["strength"]))

    brackets = h["sick_bracket"]
    for place, level in h["sickness"].items():
        bracket = 0 if level < 0.15 else 1 if level < 0.35 else 2 if level < 0.6 else 3
        if bracket and (bracket != brackets.get(place, 0) or day % 2 == 0):
            texts = world.story["nature"]["sick_mine" if place == "mine" else "sick_other"]
            emit(fill(texts[bracket - 1], place=world.place_name(place)), place, 1.0 + 0.6 * bracket)
        brackets[place] = bracket

    for a in world.agents.values():
        if a.health == 1:
            emit(world.story["nature"]["woke_coughing"], None, 1.6, [a.id])
        elif a.health >= 2:
            emit(world.story["nature"]["woke_fevered"], None, 2.0, [a.id])

    return new


def describe_state(world: World) -> str:
    """The hidden state in plain words, for fate, the gods and the chronicler."""
    h = world.hidden
    s = world.story["state"]
    sep = world.t("names.list_sep")

    def level(x: float) -> str:
        return s["levels"][0 if x < 0.12 else 1 if x < 0.3 else 2 if x < 0.55 else 3]

    nights = int(h.get("ullr_awake", 0))
    stone = (s["stone_raised"] if h["stone_raised"] else s["stone_fallen"]) + (
        fill(s["ullr_awake"], n=nights) if nights else s["ullr_asleep"] + (s["ullr_hum"] if h.get("stone_hum") else "")
    )
    lines = [
        s["door_open"] if h["shaft_open"] else s["door_shut"],
        stone + world.t("names.stop"),
        fill(s["water"], levels=sep.join(fill(s["water_level"], place=world.place_name(k), level=level(v)) for k, v in h["blight"].items())),
        fill(s["sickness"], levels=sep.join(fill(s["sick_level"], place=world.place_name(k), n=round(v, 2)) for k, v in h["sickness"].items())),
        fill(s["wolves"], hunger=round(h["wolves"]["hunger"], 2), attacks=h["wolves"]["attacks"]),
    ]
    return "\n".join(lines)
