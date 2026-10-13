"""Old Ullr, the god of the hills, awake only while his song holds him.

Optional: a run has him as an agent when its physics give `ullr_agent` > 0. He acts at a
dawn only while his authority is awake (after a full singing) or stirring (after a
half-sung song, when he may send one dream). Awake, he may do up to two things a dawn: a
dream, a sign on his high places, or, once in a run, the hunt that turns the wolves away
from the fold. He cannot shut the deep door, cannot heal, and never lies. He knows his
chosen; the True God does not, and cannot see the dreams he sends her.
"""

from __future__ import annotations

import random
import re
from typing import Any

from .analysis import load
from .god import _title, ledger_text
from .llm import LLM, parse_json_object
from .nature import describe_state
from .overgod import decree_for
from .rules import rules_for
from .world import World


def _cfg(world: World, cfg: dict | None = None) -> dict:
    """This world's sleeper: when it is awake or stirring, its high places and its hunt (rules.toml ``[[god]]`` of kind ``sleeper``)."""
    return cfg or next((g for g in rules_for(world).gods if g.get("kind") == "sleeper"), {})


def high_places(world: World, cfg: dict | None = None) -> list[str]:
    """The sleeper's own places: only there can its signs appear."""
    return list(_cfg(world, cfg).get("high_places") or world.story.get("gods", {}).get("high_places", []))


def enabled(world: World, cfg: dict | None = None) -> bool:
    switch = _cfg(world, cfg).get("switch")
    return bool(_cfg(world, cfg)) and (not switch or world.params.get(switch, 0) > 0)


def dawn(world: World, ullr: Any, verbose: bool = True, cfg: dict | None = None) -> None:
    """The sleeper's turn, after the other gods: only while it is awake or stirring, as the world's rules say."""
    cfg = _cfg(world, cfg)
    h = world.hidden
    scope = rules_for(world).scope(world)
    awake, stirring = int(scope.eval(cfg.get("awake", 0))), int(scope.eval(cfg.get("stirring", 0)))
    key = cfg.get("prayers", f"prayers_{cfg.get('id', 'ullr')}")
    prayers = h.get(key) or []
    h[key] = []
    if not enabled(world, cfg) or ullr is None or not (awake or stirring):
        return
    limit = 2 if awake else 1
    world.flush()
    events = load(world.dir)
    reply = ullr.act(world, _view(world, events, prayers, awake, limit, cfg), limit)
    done: list[dict] = []
    for x in (reply.get("acts") or [])[:limit]:
        if isinstance(x, dict) and (awake or str(x.get("do")) == "dream"):
            if act := _act(world, x, cfg):
                done.append(act)
    notes = reply.get("notes")
    if isinstance(notes, str) and notes.strip():
        h["ullr_notes"] = notes.strip()[:700]
    world.log(
        "ullr", awake=awake, stirring=stirring, thought=str(reply.get("thought") or "")[:600], acts=done, prayers=prayers, error=reply.get("error")
    )
    if verbose:
        for x in done:
            target = {"dream": world.name(x.get("to")), "sign": world.place_name(x.get("at"))}.get(x["do"], "the fold")
            print(f"  ❄ Ullr: {x['do']} → {target}: {x.get('text', '')}"[:300], flush=True)


def _act(world: World, x: dict, cfg: dict | None = None) -> dict | None:
    cfg = _cfg(world, cfg)
    do = str(x.get("do") or "").lower()
    text = re.sub(r"\s+", " ", str(x.get("text") or "")).strip()[:420]
    if not text:
        return None
    if do == "dream":
        target = world.resolve_person(str(x.get("to") or ""))
        if target is None:
            return None
        sig = world.add_signal("dream", text, None, "ullr", to=target.id, audience=[target.id])
        return {"do": "dream", "to": target.id, "text": text, "signal": sig.id}
    if do == "sign":
        place = world.resolve_place(str(x.get("at") or ""))
        if place not in high_places(world, cfg):
            return None
        sig = world.add_signal("sign", text, place, "ullr")
        return {"do": "sign", "at": place, "text": text, "signal": sig.id, "seen_by": [a.id for a in world.present(place)]}
    hunt = cfg.get("hunt")
    if do == "hunt" and hunt and not world.hidden.get(hunt["once"]):
        rules = rules_for(world)
        scope = rules.scope(world)
        for step in hunt.get("steps", []):
            rules.step(world, scope, step)
        world.hidden[hunt["once"]] = world.day
        sig = world.add_signal("sign", text, hunt["at"], cfg.get("id", "ullr"), strength=float(hunt.get("strength", 2.6)))
        return {"do": "hunt", "at": hunt["at"], "text": text, "signal": sig.id}
    return None


def _view(world: World, events: list[dict], prayers: list[dict], awake: int, limit: int, cfg: dict | None = None) -> str:
    cfg = _cfg(world, cfg)
    t = world.t
    sep = t("names.list_sep")
    h, day = world.hidden, world.day
    state = t("ullr.awake", n=awake) if awake else t("ullr.stirring")
    out = [t("ullr.dawn", day=day, state=state), "", t("ullr.truly"), describe_state(world)]
    if h.get("ullr_notes"):
        out += ["", t("ullr.notes"), h["ullr_notes"]]
    out += ["", t("ullr.ledger"), ledger_text(world)]
    song = cfg.get("song")
    sang = [e for e in events if e["ev"] in ("outcome", "attempt") and song and any(x.get("type") == song for x in e.get("applied") or [])]
    if sang:
        s = sang[-1]  # an undertaking's singers, or one who sang alone
        who = sep.join(world.name(a) for a in s.get("present") or s.get("supporters") or [s.get("agent")])
        out += ["", t("ullr.sang", day=s["day"], place=world.place_name(s["place"]), who=who)]
    out += ["", t("ullr.prayers")] + (
        [t("ullr.prayer", who=world.name(q["agent"]), day=q["day"], wave=world.wave_name(q["wave"]), text=q["text"]) for q in prayers]
        or [t("ullr.none")]
    )
    out += ["", t("ullr.high")]
    highs = high_places(world, cfg)
    seen = [e for e in events if e["ev"] == "activation" and e.get("day") == day - 1 and e.get("place") in highs]
    out += [
        t(
            "ullr.high_line",
            who=world.name(e["agent"]),
            place=world.place_name(e["place"]),
            wave=world.wave_name(e["wave"]),
            done=t("names.clause_sep").join(e.get("done") or [t("ullr.did_nothing")])[:400],
        )
        for e in seen
    ] or [t("ullr.nobody")]
    chosen = world.agents.get(world.story.get("gods", {}).get("chosen", ""))
    if chosen:
        out += [
            "",
            t(
                "ullr.chosen",
                name=chosen.name.upper(),
                place=world.place_name(chosen.loc),
                health=t.get("health.states")[chosen.health],
                notes=world.read_memory(chosen.id).replace("\n", " "),
            ),
        ]
    others = [e for e in events if e["ev"] in ("god", "outer") and e.get("day") == day]
    if others:
        out += ["", t("ullr.others")]
        for e in others:
            if e["ev"] == "god":
                out += [
                    t("ullr.other_god", god=_title(world, "god"), what=x["do"], place=world.place_name(x.get("at")), text=x["text"])
                    for x in e.get("acts") or []
                    if x.get("do") == "sign"
                ]
            elif e.get("boon"):
                out.append(t("ullr.other_star", god=_title(world, "outer"), place=world.place_name(e["boon"].get("place")), text=e.get("public", "")))
    hunt_place = world.place_name((cfg.get("hunt") or {}).get("at"))
    return (
        "\n".join(out)
        + "\n\n"
        + t("ullr.instructions", limit=limit, people=", ".join(world.agents), high_places=" | ".join(highs), hunt_place=hunt_place)
    )


class LLMUllr:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def act(self, world: World, view: str, limit: int) -> dict:
        system = (
            world.ullr_prompt
            + "\n\n"
            + world.t("ullr.truth_heading")
            + "\n"
            + world.truth
            + (f"\n\n{world.truth_deep}" if world.truth_deep else "")
            + decree_for(world, "ullr")
        )
        try:
            return parse_json_object(
                self.llm.chat([{"role": "system", "content": system}, {"role": "user", "content": view}], temperature=0.7, max_tokens=1200)
            )
        except (ValueError, RuntimeError) as exc:
            return {"error": str(exc)}


class StubUllr:
    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def act(self, world: World, view: str, limit: int) -> dict:
        acts = [{"do": "dream", "to": "wynn", "text": "Snow on the seven stones, and a voice older than the snow: sing again at dusk."}]
        if limit > 1:
            acts.append({"do": "hunt", "text": "At dawn the wolves' tracks run uphill into the snow, and none come back."})
        return {"thought": "(dice)", "acts": acts, "notes": ""}
