"""The hidden world's turn of days: what the kernel does for every world, and where each world's own rules run.

Every world has weather, omens with conditions, a calendar and a deck of chance events
(``world.toml``), and events its rules queued in the night. Everything else that moves the
hidden world (a river carrying blight, a lighthouse calling boats home) is the world's own,
declared in its ``rules.toml`` and run by the rules kernel (``rules/``) at these hooks:
``night`` as each night passes, ``dawn`` after the omens, ``after_gods`` after the gods' turns.

None of this is visible to the villagers except through omens, what they find when they
look closely, and the outcomes of what they attempt.
"""

from __future__ import annotations

from .rules import rules_for
from .world import World


def advance(world: World) -> None:
    """One night passes in the hidden world: the world's own ``night`` rules."""
    rules_for(world).run(world, "night")


def lapse(world: World) -> None:
    """After the gods' dawn turns: the world's own ``after_gods`` rules."""
    rules_for(world).run(world, "after_gods")


def dawn(world: World) -> list[str]:
    """What the world shows this morning. Returns the new signal ids."""
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

    for place, strength, text in h.get("events", []):
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

    before = set(world.signals)
    rules_for(world).run(world, "dawn")
    new += [sid for sid in world.signals if sid not in before]
    return new


def describe_state(world: World) -> str:
    """The hidden state in plain words, for fate, the gods, the host and the novel."""
    return rules_for(world).describe(world)
