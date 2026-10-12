"""Bagel's master: pleiades, an Outer God, who sees the vale only through her.

Optional: a run has him when its physics give `outer_god` > 0. He acts at a dawn only
after Bagel has prayed to him, and knows nothing of the vale but what she painted,
prayed and wrote in her notes. His power is great but reaches the vale only through her
and only for a price: one of her paintings, which leaves the wall it hung on. A boon
lands where she stands. He cannot touch the binding of the stones or the deep door.
"""

from __future__ import annotations

import random
import re
from typing import Any

from .act import carried, goods
from .fate import apply_effects
from .llm import LLM, parse_json_object
from .overgod import decree_for, star_bound
from .world import World

GIFTS = {"jars", "rope", "timber", "tools", "lamps", "remedy"}


def follower(world: World) -> str:
    """The Star God's servant in this story: the only one who prays to him, and the only one he sees through."""
    return world.story.get("gods", {}).get("follower", "bagel")


def enabled(world: World) -> bool:
    return world.params.get("outer_god", 0) > 0


def dawn(world: World, outer: Any, verbose: bool = True) -> None:
    """If Bagel prayed to her master since the last dawn, or she is unwell, he answers (or doesn't)."""
    h = world.hidden
    prayers = h.get("prayers_master") or []
    bagel = world.agents.get(follower(world))
    # He has no plan for the vale; he wakes for her prayers, and for her harm.
    if star_bound(world):
        return  # bound by the One Above: her prayers wait until he can hear them again
    if not enabled(world) or outer is None or bagel is None or not (prayers or bagel.health >= 1):
        h["prayers_master"] = []
        return
    paintings = _paintings(world)
    reply = outer.act(world, _view(world, prayers, paintings))
    record: dict[str, Any] = {"prayers": prayers, "thought": str(reply.get("thought") or "")[:600], "error": reply.get("error")}
    boon = reply.get("boon")
    if isinstance(boon, dict):
        done = _grant(world, bagel, boon, paintings)
        record.update(done)
    else:
        record["refused"] = "no boon"
    dream = re.sub(r"\s+", " ", str(reply.get("dream") or "")).strip()[:300]
    if dream:
        sig = world.add_signal("dream", dream, None, "outer", to=bagel.id, audience=[bagel.id])
        record["dream"], record["dream_signal"] = dream, sig.id
    h["prayers_master"] = []
    world.log("outer", **record)
    if verbose:
        if record.get("boon"):
            print(
                f"  ✷ pleiades: {record['boon']['kind']} at {world.place_name(record['boon']['place'])}: {record.get('public', '')}"[:300], flush=True
            )
        else:
            print(f"  ✷ pleiades: no boon ({record.get('refused')})", flush=True)
        if dream:
            print(f"  ✷ pleiades, in Bagel's dream: {dream}"[:300], flush=True)


def _paintings(world: World) -> dict[str, dict]:
    """Bagel's paintings that haven't been taken yet, by signal id."""
    from .analysis import load

    world.flush()
    taken = set(world.hidden.get("taken", []))
    return {
        e["id"]: e
        for e in load(world.dir)
        if e["ev"] == "signal" and e.get("kind") == "painting" and e.get("source") == follower(world) and e["id"] not in taken
    }


def _view(world: World, prayers: list[dict], paintings: dict[str, dict]) -> str:
    t = world.t
    sep = t("names.list_sep")
    bagel = world.agents[follower(world)]
    health = t.get("health.states")
    place = world.places.get(bagel.loc or "", {})
    with_her = [a for a in world.present(bagel.loc) if a.id != bagel.id]
    out = [t("outer.dawn", day=world.day), "", t("outer.prayers")]
    out += [
        t("outer.prayer", day=q["day"], wave=world.wave_name(q["wave"]), place=world.place_name(q["place"]), text=q["text"]) for q in prayers
    ] or [t("outer.unasked", health=health[bagel.health])]
    out += ["", t("outer.paintings")]
    out += [t("outer.painting", id=sid, day=p["day"], place=world.place_name(p.get("loc")), text=p["text"]) for sid, p in paintings.items()] or [
        t("outer.no_paintings")
    ]
    out += [
        "",
        t("outer.where", place=place.get("name", t("names.the_road")), desc=place.get("desc", "")),
        t(
            "outer.with_her",
            who=sep.join(t("outer.with_person", name=a.name, id=a.id, health=health[a.health]) for a in with_her) or t("names.nobody"),
        ),
        t("outer.she_is", health=health[bagel.health], items=carried(world, bagel) or t("names.nothing")),
        "",
        t("outer.notes"),
        world.read_memory(bagel.id) or t("mind.empty"),
    ]
    people = ", ".join([bagel.id] + [a.id for a in with_her])
    return "\n".join(out) + "\n\n" + t("outer.instructions", people=people)


def _grant(world: World, bagel, boon: dict, paintings: dict[str, dict]) -> dict:
    """Apply a boon if it is well formed and paid for. Returns what happened, for the log."""
    kind = str(boon.get("kind") or "").lower()
    price = str(boon.get("price") or "").strip("[] ")
    if price not in paintings:
        return {"refused": "no painting to pay with" if not paintings else f"price {price!r} is not one of her paintings"}
    here = {a.id for a in world.present(bagel.loc)}
    who = str(boon.get("who") or "").strip().lower()
    who = who if who in here else bagel.id
    loc = bagel.loc
    if kind == "heal":
        effect = {"type": "heal", "place": loc, "amount": 0.3}
    elif kind == "cleanse":
        effect = {"type": "purify", "place": loc, "amount": 0.3}
    elif kind == "mend":
        effect = {"type": "health", "who": who, "change": -1}
    elif kind == "wolves":
        effect = {"type": "wolves", "result": "driven_off"}
    elif kind == "give":
        item = str(boon.get("item") or "").lower().strip()
        item = goods(world, item)
        if item not in GIFTS:
            return {"refused": f"{item!r} is not a thing he gives"}
        try:
            qty = max(1, min(6, int(boon.get("qty") or 1)))
        except (TypeError, ValueError):
            qty = 1
        effect = {"type": "item", "who": who, "item": item, "qty": qty}
    else:
        return {"refused": f"{kind!r} is not a boon"}
    applied = apply_effects(world, [effect], ref="outer", present=[], site=loc)
    if not applied:
        return {"refused": "the boon did not take"}
    painting = paintings[price]
    world.hidden.setdefault("taken", []).append(price)
    world.signals.pop(price, None)
    public = re.sub(r"\s+", " ", str(boon.get("public") or "")).strip()[:400] or "Something unseen moves through the place, and is gone."
    sig = world.add_signal("boon", f"{public} Bagel's painting is gone from where it hung.", loc, "outer")
    return {
        "boon": {"kind": kind, "place": loc, **{k: v for k, v in effect.items() if k != "type"}},
        "price": price,
        "price_text": painting["text"],
        "public": public,
        "signal": sig.id,
    }


class LLMOuter:
    """One model call, only on dawns after Bagel has prayed to him."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def act(self, world: World, view: str) -> dict:
        messages = [{"role": "system", "content": world.outer_prompt + decree_for(world, "outer")}, {"role": "user", "content": view}]
        try:
            return parse_json_object(self.llm.chat(messages, temperature=0.7, max_tokens=900))
        except (ValueError, RuntimeError) as exc:
            return {"error": str(exc)}


class StubOuter:
    """Dice instead of a model, for testing the plumbing."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def act(self, world: World, view: str) -> dict:
        ids = re.findall(r"\[(s\d+)\]", view)
        if not ids:
            return {"thought": "(dice)", "boon": None, "dream": "Paint, little one."}
        return {
            "thought": "(dice)",
            "boon": {
                "kind": "give",
                "who": "bagel",
                "item": "jars",
                "qty": 2,
                "price": ids[0],
                "public": "A cold light folds itself into two covered jars.",
            },
            "dream": "",
        }
