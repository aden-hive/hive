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
from .god import ledger_text
from .llm import LLM, parse_json_object
from .nature import describe_state
from .world import WAVES, World

HIGH_PLACES = ("barrow_hill", "fold", "mirewood")
HEALTH = ("well", "coughing red", "fevered")

INSTRUCTIONS = """Reply with JSON only:
{
  "thought": "your private reasoning, one to three sentences",
  "acts": [
    {"do": "dream", "to": "<person id>", "text": "<what they dream, under sixty words>"},
    {"do": "sign", "at": "barrow_hill | fold | mirewood", "text": "<what everyone there sees>"},
    {"do": "hunt", "text": "<what the fold sees at dawn>"}
  ],
  "notes": "your private notes for tomorrow's dawn, under eighty words"
}
You may do at most LIMIT of these. An empty list is a fine answer. Person ids: PEOPLE."""


def enabled(world: World) -> bool:
    return world.params.get("ullr_agent", 0) > 0


def dawn(world: World, ullr: Any, verbose: bool = True) -> None:
    """Ullr's turn, after the other gods: only while his song holds him awake or stirring."""
    h = world.hidden
    awake, stirring = int(h.get("ullr_awake", 0)), int(h.get("stone_hum", 0))
    prayers = h.get("prayers_ullr") or []
    h["prayers_ullr"] = []
    if not enabled(world) or ullr is None or not (awake or stirring):
        return
    limit = 2 if awake else 1
    world.flush()
    events = load(world.dir)
    reply = ullr.act(world, _view(world, events, prayers, awake, limit), limit)
    done: list[dict] = []
    for x in (reply.get("acts") or [])[:limit]:
        if isinstance(x, dict) and (awake or str(x.get("do")) == "dream"):
            if act := _act(world, x):
                done.append(act)
    notes = reply.get("notes")
    if isinstance(notes, str) and notes.strip():
        h["ullr_notes"] = notes.strip()[:700]
    world.log("ullr", awake=awake, stirring=stirring, thought=str(reply.get("thought") or "")[:600], acts=done,
              prayers=prayers, error=reply.get("error"))
    if verbose:
        for x in done:
            target = {"dream": world.name(x.get("to")), "sign": world.place_name(x.get("at"))}.get(x["do"], "the fold")
            print(f"  ❄ Ullr: {x['do']} → {target}: {x.get('text', '')}"[:300], flush=True)


def _act(world: World, x: dict) -> dict | None:
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
        if place not in HIGH_PLACES:
            return None
        sig = world.add_signal("sign", text, place, "ullr")
        return {"do": "sign", "at": place, "text": text, "signal": sig.id, "seen_by": [a.id for a in world.present(place)]}
    if do == "hunt" and not world.hidden.get("ullr_hunted"):
        w = world.hidden["wolves"]
        w["hunger"], w["driven"] = 0.0, int(w.get("driven", 0)) + 1
        world.hidden["ullr_hunted"] = world.day
        sig = world.add_signal("sign", text, "fold", "ullr", strength=2.6)
        return {"do": "hunt", "at": "fold", "text": text, "signal": sig.id}
    return None


def _view(world: World, events: list[dict], prayers: list[dict], awake: int, limit: int) -> str:
    h, day = world.hidden, world.day
    state = (f"You are awake for {awake} more night(s)." if awake
             else "A half-sung song has stirred you in your sleep; you can send one dream, no more.")
    out = [f"DAWN OF DAY {day}. {state}", "", "THE VALE AS IT TRULY STANDS:", describe_state(world)]
    if h.get("ullr_notes"):
        out += ["", "YOUR NOTES FROM LAST DAWN:", h["ullr_notes"]]
    out += ["", "THE LEDGER OF THE WORLD (what everyone in the vale knows today):", ledger_text(world)]
    sang = [e for e in events if e["ev"] in ("outcome", "attempt") and any(x.get("type") == "sing" for x in e.get("applied") or [])]
    if sang:
        s = sang[-1]  # an undertaking's singers, or one who sang alone
        out += ["", f"WHO SANG TO YOU LAST (day {s['day']}, at {world.place_name(s['place'])}): "
                + ", ".join(world.name(a) for a in s.get("present") or s.get("supporters") or [s.get("agent")])]
    out += ["", "PRAYERS TO YOU:"] + ([f'- {world.name(q["agent"])}, day {q["day"]} {WAVES[q["wave"]]}: "{q["text"]}"' for q in prayers] or ["(none)"])
    out += ["", "ON YOUR HIGH PLACES, YESTERDAY:"]
    seen = [e for e in events if e["ev"] == "activation" and e.get("day") == day - 1 and e.get("place") in HIGH_PLACES]
    out += [f'- {world.name(e["agent"])} at {world.place_name(e["place"])}, {WAVES[e["wave"]]}: ' + "; ".join(e.get("done") or ["(did nothing)"])[:400]
            for e in seen] or ["(nobody)"]
    wynn = world.agents.get("wynn")
    if wynn:
        out += ["", f"YOUR CHOSEN, WYNN: at {world.place_name(wynn.loc)}; {HEALTH[wynn.health]}. Her notes: "
                + world.read_memory("wynn").replace("\n", " ")]
    others = [e for e in events if e["ev"] in ("god", "outer") and e.get("day") == day]
    if others:
        out += ["", "THE OTHER GODS, THIS DAWN:"]
        for e in others:
            if e["ev"] == "god":
                out += [f"- The True God: {x['do']} at {world.place_name(x.get('at'))}: {x['text']}" for x in e.get("acts") or [] if x.get("do") == "sign"]
            elif e.get("boon"):
                out.append(f"- The Star God eased {world.place_name(e['boon'].get('place'))}: {e.get('public', '')}")
    people = ", ".join(world.agents)
    return "\n".join(out) + "\n\n" + INSTRUCTIONS.replace("LIMIT", str(limit)).replace("PEOPLE", people)


class LLMUllr:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def act(self, world: World, view: str, limit: int) -> dict:
        system = world.ullr_prompt + "\n\nTHE HIDDEN TRUTH:\n" + world.truth + (f"\n\n{world.truth_deep}" if world.truth_deep else "")
        try:
            return parse_json_object(self.llm.chat([{"role": "system", "content": system}, {"role": "user", "content": view}],
                                                   temperature=0.7, max_tokens=1200))
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
