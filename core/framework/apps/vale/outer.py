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
from .overgod import bound, decree_for
from .rules import rules_for
from .world import World


def _cfg(world: World, cfg: dict | None = None) -> dict:
    """This world's patron: its follower, its offerings and boons (rules.toml ``[[god]]`` of kind ``patron``)."""
    return cfg or next((g for g in rules_for(world).gods if g.get("kind") == "patron"), {})


def follower(world: World, cfg: dict | None = None) -> str:
    """The patron's servant: the only one who prays to it, and the only one it sees through."""
    return str(_cfg(world, cfg).get("follower") or world.story.get("gods", {}).get("follower", ""))


def enabled(world: World, cfg: dict | None = None) -> bool:
    switch = _cfg(world, cfg).get("switch")
    return bool(_cfg(world, cfg)) and (not switch or world.params.get(switch, 0) > 0)


def dawn(world: World, outer: Any, verbose: bool = True, cfg: dict | None = None) -> None:
    """If the follower prayed to their patron since the last dawn, or is unwell, the patron answers (or doesn't)."""
    cfg = _cfg(world, cfg)
    h = world.hidden
    key = cfg.get("prayers", f"prayers_{cfg.get('id', 'outer')}")
    prayers = h.get(key) or []
    bagel = world.agents.get(follower(world, cfg))
    # It has no plan for the world; it wakes for its follower's prayers, and for their harm.
    if bound(world, cfg.get("id", "outer")):
        return  # bound by the One Above: the prayers wait until it can hear them again
    if not enabled(world, cfg) or outer is None or bagel is None or not (prayers or bagel.health >= 1):
        h[key] = []
        return
    paintings = _paintings(world, cfg)
    reply = outer.act(world, _view(world, prayers, paintings, cfg))
    record: dict[str, Any] = {"prayers": prayers, "thought": str(reply.get("thought") or "")[:600], "error": reply.get("error")}
    boon = reply.get("boon")
    if isinstance(boon, dict):
        done = _grant(world, bagel, boon, paintings, cfg)
        record.update(done)
    else:
        record["refused"] = "no boon"
    dream = re.sub(r"\s+", " ", str(reply.get("dream") or "")).strip()[:300]
    if dream:
        sig = world.add_signal("dream", dream, None, "outer", to=bagel.id, audience=[bagel.id])
        record["dream"], record["dream_signal"] = dream, sig.id
    h[key] = []
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


def _paintings(world: World, cfg: dict | None = None) -> dict[str, dict]:
    """The follower's offerings (paintings, in Ashmere) that haven't been taken yet, by signal id."""
    from .analysis import load

    world.flush()
    taken = set(world.hidden.get("taken", []))
    return {
        e["id"]: e
        for e in load(world.dir)
        if e["ev"] == "signal"
        and e.get("kind") == _cfg(world, cfg).get("offering", "painting")
        and e.get("source") == follower(world, cfg)
        and e["id"] not in taken
    }


def _view(world: World, prayers: list[dict], paintings: dict[str, dict], cfg: dict | None = None) -> str:
    t = world.t
    sep = t("names.list_sep")
    bagel = world.agents[follower(world, cfg)]
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
    kinds = " | ".join(f'"{k}"' for k in [*_cfg(world, cfg).get("boons", {}), "give"])
    return "\n".join(out) + "\n\n" + t("outer.instructions", people=people, kinds=kinds)


def _grant(world: World, bagel, boon: dict, paintings: dict[str, dict], cfg: dict | None = None) -> dict:
    """Apply a boon if it is well formed and paid for. Returns what happened, for the log.

    The world declares what each kind of boon does (``boons``: kind -> an effect, written as an
    expression over ``here`` and ``who``) and which goods the patron may give (``gifts``).
    """
    cfg = _cfg(world, cfg)
    kind = str(boon.get("kind") or "").lower()
    price = str(boon.get("price") or "").strip("[] ")
    if price not in paintings:
        return {"refused": "no painting to pay with" if not paintings else f"price {price!r} is not one of her paintings"}
    here = {a.id for a in world.present(bagel.loc)}
    who = str(boon.get("who") or "").strip().lower()
    who = who if who in here else bagel.id
    loc = bagel.loc
    boons = cfg.get("boons", {})
    if kind in boons:
        effect = rules_for(world).scope(world, {"here": loc, "who": who}).eval(boons[kind])
    elif kind == "give":
        item = str(boon.get("item") or "").lower().strip()
        item = goods(world, item)
        if item not in set(cfg.get("gifts", [])):
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
    public = re.sub(r"\s+", " ", str(boon.get("public") or "")).strip()[:400] or world.t("outer.unseen")
    sig = world.add_signal("boon", world.t("outer.taken", public=public, name=bagel.short), loc, "outer")
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
