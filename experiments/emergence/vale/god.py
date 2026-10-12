"""The god of the vale: keeper of the Ledger of the World, with a little grace.

Optional: a run has a god when its physics give `god_grace` > 0. Once each dawn the god
reads everything (the hidden truth, every villager's private notes, yesterday's words
and deeds, the prayers) and does two kinds of things:

- It writes out the Ledger of the World again: the one record every villager sees
  whenever they act. Every line must cite things a villager said, posted, did or found,
  or that the world plainly showed someone; lines whose citations don't check out are
  struck before anyone sees them.
- It spends grace on dreams (one villager) and signs (one place). Grace comes a little
  each dawn and can be saved.

The god cannot change the world itself. A person can play god as well: `vale god`
queues dreams, signs and Ledger lines for the next dawn, with no grace and no citations.
"""

from __future__ import annotations

import random
import re
from typing import Any

from .analysis import load
from .fate import KNOWS
from .llm import LLM, parse_json_object
from .nature import describe_state
from .world import WAVES, World

# What the Ledger may rest on: what someone said, posted, did or found, or what the world showed.
CITABLE = {"speech", "notice", "painting", "clue", "deed", "project", "omen", "outcome", "sign"}
VERB = {"speech": "said by", "notice": "posted by", "painting": "painted by", "deed": "done by", "project": "proposed by"}
HEALTH = ("well", "coughing red", "fevered")
# Old Ullr's mark on his chosen is hidden from the god who displaced him.
HIDDEN_FROM_GOD = {"true_voice"}
HIDDEN_DREAMERS = {"wynn"}

INSTRUCTIONS = """WHAT NOW? Reply with JSON only:
{
  "thought": "your private reasoning: what the vale needs now, and why you act as you do (two to four sentences)",
  "ledger": [{"text": "<one line, under 40 words>", "sources": ["<ids it rests on>"]}],
  "acts": [
    {"do": "dream", "to": "<person id>", "text": "<what they dream, under sixty words>", "answers": "<prayer id, or empty>"},
    {"do": "sign", "at": "<place id>", "text": "<what everyone there sees, under sixty words>", "answers": "<prayer id, or empty>"}
  ],
  "notes": "your private notes for tomorrow's dawn, under 120 words"
}
"ledger" is the whole Ledger as it should read today, at most LINES lines. Each act costs one grace; you have GRACE.
An empty list of acts is a fine answer. Place ids: PLACES. Person ids: PEOPLE."""


def has_god(world: World) -> bool:
    return world.params.get("god_grace", 0) > 0 or bool(world.hidden.get("god_human"))


def ledger_text(world: World) -> str:
    """The Ledger as the villagers know it: each line with who said, found or saw it."""
    lines = [f"- {e['text']} ({e['witness']})" for e in world.hidden.get("ledger", [])]
    lines += [f"- {text} (written by an unseen hand)" for text in world.hidden.get("ledger_pinned", [])]
    return "\n".join(lines) or "(The Ledger is blank today.)"


def dawn(world: World, god: Any, verbose: bool = True) -> None:
    """The god's turn, after the world's own dawn: a human's queued acts, then the god's."""
    if not has_god(world):
        return
    h, p = world.hidden, world.params
    if p.get("god_grace", 0) > 0:
        h["grace"] = round(min(float(p["god_grace_cap"]), h.get("grace", 0.0) + float(p["god_grace"])), 3)
    grace_before = h.get("grace", 0.0)
    world.flush()
    events = load(world.dir)
    index = _index(events)
    prayers = h.get("prayers", [])
    prev = {e["text"]: e for e in h.get("ledger", [])}
    applied: list[dict] = []
    dropped: list[Any] = []
    new_lines: list[str] = []

    for x in h.pop("god_queue", []):  # a human god: free and uncited
        if x.get("do") == "ledger":
            h.setdefault("ledger_pinned", []).append(x["text"])
            sig = world.add_signal("ledger", x["text"], None, "god", audience=list(world.agents))
            new_lines.append(sig.id)
            applied.append({**x, "by": "hand", "signal": sig.id})
        elif done := _act(world, x, prayers):
            applied.append({**done, "by": "hand"})

    reply: dict[str, Any] = {}
    struck: list[dict] = []
    if p.get("god_grace", 0) > 0 and god is not None:
        reply = god.act(world, digest(world, events, index))
        if isinstance(reply.get("ledger"), list):
            kept, struck = _validate(world, reply["ledger"], index, int(p["ledger_lines"]))
        else:
            kept = list(h.get("ledger", []))
        for x in reply.get("acts") or []:
            if not isinstance(x, dict):
                continue
            if h.get("grace", 0) < 1:
                dropped.append({**x, "why": "no grace left"})
                continue
            done = _act(world, x, prayers)
            if done is None:
                dropped.append({**x, "why": "no such person or place, or nothing to say"})
                continue
            h["grace"] = round(h["grace"] - 1, 3)
            applied.append(done)
        notes = reply.get("notes")
        if isinstance(notes, str) and notes.strip():
            h["god_notes"] = notes.strip()[:900]
        for e in kept:
            old = prev.get(e["text"])
            e["since"] = old["since"] if old else world.day
            if old:
                e["signal"] = old.get("signal")
                continue
            # A new line carries its first source's cause along, the way a rumour does.
            cause = index[e["sources"][0]].get("cause")
            sig = world.add_signal("ledger", e["text"], None, "god", audience=list(world.agents), cause=cause)
            e["signal"] = sig.id
            new_lines.append(sig.id)
        h["ledger"] = kept

    h["prayers"] = []
    world.log(
        "god", grace_before=grace_before, grace=h.get("grace", 0.0), thought=str(reply.get("thought") or "")[:900],
        notes=h.get("god_notes", ""), acts=applied, dropped=dropped, ledger=h.get("ledger", []),
        pinned=h.get("ledger_pinned", []), struck=struck, new=new_lines, prayers=prayers, error=reply.get("error"),
    )
    if verbose:
        for x in applied:
            target = {"dream": world.name(x.get("to")), "sign": world.place_name(x.get("at"))}.get(x["do"], "the Ledger")
            print(f"  ✶ god: {x['do']} → {target}: {x.get('text', '')}"[:300], flush=True)
        if new_lines:
            print(f"  ✶ ledger: {len(new_lines)} new line(s), {len(h.get('ledger', []))} in all; {len(struck)} struck", flush=True)


def digest(world: World, events: list[dict], index: dict[str, dict]) -> str:
    """Everything the god sees at dawn, as one message."""
    h, day = world.hidden, world.day
    out = [f"DAWN OF DAY {day}. You have {h.get('grace', 0):g} grace.", "", "THE VALE AS IT TRULY STANDS:", describe_state(world)]
    if h.get("god_notes"):
        out += ["", "YOUR NOTES FROM LAST DAWN:", h["god_notes"]]
    out += ["", "THE LEDGER AS IT READ YESTERDAY:"]
    out += [f"- {e['text']}  [sources: {', '.join(e['sources'])}] ({e['witness']})" for e in h.get("ledger", [])] or ["(blank)"]
    if h.get("ledger_pinned"):
        out += ["Lines written by another hand, which stay whatever you write:"] + [f"- {t}" for t in h["ledger_pinned"]]

    out += ["", "PRAYERS SINCE LAST DAWN (a dream or sign may answer one; give its id):"]
    out += [
        f'- [{q["id"]}] {world.name(q["agent"])} at {world.place_name(q["place"])}, day {q["day"]} {WAVES[q["wave"]]}'
        f'{" (to her master, an Outer God, not to you)" if q.get("to") == "master" else ""}: "{q["text"]}"'
        for q in h.get("prayers", [])
    ] or ["(none)"]

    out += ["", "THE PEOPLE: where they are, how they are, what they know and carry, and their private notes:"]
    for a in world.agents.values():
        where = world.place_name(a.loc) if a.loc else f"on the road to {world.place_name((a.travel or {}).get('to'))}"
        knows = "; ".join(KNOWS[k] for k in a.knows if k in KNOWS and k not in HIDDEN_FROM_GOD) or "nothing special"
        items = ", ".join(f"{k} x{v}" for k, v in a.items.items() if v > 0) or "nothing"
        out.append(f"- {a.name} [{a.id}], {a.role}, at {where}; {HEALTH[a.health]}; energy {a.reserve:.1f}; {knows}; carries {items}.")
        out.append("  Notes: " + world.read_memory(a.id).replace("\n", " "))

    sigs = {e["id"]: e for e in events if e["ev"] == "signal"}
    out += ["", f"YESTERDAY (day {day - 1}) AND THIS DAWN, AS IT HAPPENED. Ids in brackets may be cited in the Ledger:"]
    for e in events:
        d = e.get("day", 0)
        if d < max(1, day - 1):
            continue
        when = f"[day {d} {WAVES[e.get('wave', 0)]}]"
        if e["ev"] == "activation":
            top = (e.get("contribs") or [{}])[0]
            stirred = f"; stirred most by [{top['signal']}] ({top.get('kind')})" if top.get("signal") else ""
            out.append(f'{when} {world.name(e["agent"])} at {world.place_name(e.get("place"))}{stirred}. Thought: "{e.get("thought", "")}"')
            for sid in e.get("emitted") or []:
                if sid in sigs:
                    out.append(f"    {'[' + sid + '] ' if sid in index else ''}{_render(world, sigs[sid])}")
        elif e["ev"] == "signal" and e.get("source") == "world" and e.get("kind") in ("omen", "outcome") and not e.get("hops"):
            seen = f" (seen only by {', '.join(world.name(x) for x in e['audience'])})" if e.get("audience") else ""
            out.append(f"{when} [{e['id']}] {e['kind'].upper()} at {world.place_name(e.get('loc'))}{seen}: {e['text']}")
        elif e["ev"] == "outer" and d == day - 1 and e.get("boon"):
            out.append(f"{when} THE STAR GOD, through Bagel, eased {world.place_name(e['boon'].get('place'))}: {e.get('public', '')}")
        elif e["ev"] == "ullr" and d == day - 1:
            for x in e.get("acts") or []:
                if x["do"] == "dream" and x.get("to") in HIDDEN_DREAMERS:
                    continue  # the old god's voice in his chosen's sleep is beyond you
                target = world.name(x.get("to")) if x["do"] == "dream" else world.place_name(x.get("at"))
                out.append(f"{when} OLD ULLR, awake, sent a {x['do']} ({target}): {x.get('text', '')}")
        elif e["ev"] == "god" and d == day - 1:
            for x in e.get("acts") or []:
                target = world.name(x["to"]) if x["do"] == "dream" else world.place_name(x.get("at"))
                out.append(f"{when} YOU sent a {x['do']} ({target}): {x.get('text', '')}")

    old = [e for e in index.values() if 0 < e.get("day", 0) < day - 1 and e["kind"] in ("clue", "notice", "painting", "outcome", "project", "sign")]
    if old:
        out += ["", "OLDER THINGS THAT MAY BE CITED (finds, notices, paintings, undertakings, outcomes, signs):"]
        out += [f"- [{e['id']}] {_witness(world, index, [e['id']])}: {e['text'][:220]}" for e in old[-60:]]
    return "\n".join(out)


def _render(world: World, e: dict) -> str:
    kind, text = e["kind"], e["text"]
    if kind == "speech":
        return f'said to {world.name(e["to"]) if e.get("to") else "everyone"}: "{text}"'
    if kind == "notice":
        return f'posted: "{text}"'
    if kind == "painting":
        return f"painted: {text}"
    if kind == "clue":
        return f"found: {text}"
    if kind == "project":
        return f"proposed an undertaking: {text}"
    return text


def _index(events: list[dict]) -> dict[str, dict]:
    """Every signal the Ledger may cite, by id. A sign counts only once somebody saw it."""
    seen = {c["signal"] for e in events if e["ev"] == "activation" for c in e.get("contribs") or []}
    for e in events:
        if e["ev"] == "god":
            seen.update(x["signal"] for x in e.get("acts") or [] if x.get("do") == "sign" and x.get("seen_by"))
    return {
        e["id"]: e for e in events
        if e["ev"] == "signal" and not e.get("hops") and e.get("kind") in CITABLE and (e["kind"] != "sign" or e["id"] in seen)
    }


def _witness(world: World, index: dict[str, dict], sources: list[str]) -> str:
    parts: list[str] = []
    for sid in sources:
        e = index[sid]
        day, src = e.get("day"), e.get("source")
        if e["kind"] == "clue":
            part = f"found by {', '.join(world.name(a) for a in e.get('audience') or [])} on day {day}"
        elif src in world.agents:
            part = f"{VERB.get(e['kind'], 'by')} {world.name(src)} on day {day}"
        elif e.get("audience"):
            part = f"seen by {', '.join(world.name(a) for a in e['audience'])} on day {day}"
        else:
            part = f"seen at {world.place_name(e.get('loc'))} on day {day}"
        if part not in parts:
            parts.append(part)
    return "; ".join(parts[:3])


def _validate(world: World, raw: list, index: dict[str, dict], limit: int) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    struck: list[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        text = re.sub(r"\s+", " ", str(e.get("text") or "")).strip()[:300]
        cited = [str(s).strip("[] ") for s in (e.get("sources") or []) if isinstance(s, (str, int))]
        sources = [s for s in dict.fromkeys(cited) if s in index][:4]
        if not text:
            continue
        if not sources or len(kept) >= limit:
            struck.append({"text": text, "sources": cited, "why": "uncited" if not sources else "over the limit"})
            continue
        kept.append({"text": text, "sources": sources, "witness": _witness(world, index, sources)})
    return kept, struck


def _act(world: World, x: dict, prayers: list[dict]) -> dict | None:
    """One dream or sign. Returns what was done, or None if it couldn't be."""
    do = str(x.get("do") or "").lower()
    text = _brief(re.sub(r"\s+", " ", str(x.get("text") or "")).strip())
    if not text:
        return None
    answers = str(x.get("answers") or "").strip("[] ")
    prayer = next((q for q in prayers if q["id"] == answers), None)
    cause = prayer["act"] if prayer else None
    if do == "dream":
        target = world.resolve_person(str(x.get("to") or ""))
        if target is None:
            return None
        sig = world.add_signal("dream", text, None, "god", to=target.id, audience=[target.id], cause=cause)
        return {"do": "dream", "to": target.id, "text": text, "signal": sig.id, "answers": prayer["id"] if prayer else None}
    if do == "sign":
        place = world.resolve_place(str(x.get("at") or ""))
        if place is None:
            return None
        seen_by = [a.id for a in world.present(place)]
        sig = world.add_signal("sign", text, place, "god", cause=cause)
        return {"do": "sign", "at": place, "text": text, "signal": sig.id, "seen_by": seen_by, "answers": prayer["id"] if prayer else None}
    return None


def _brief(text: str, limit: int = 420) -> str:
    """A dream or sign is a few sentences: cut an overlong one at its last full stop."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…"


class LLMGod:
    """One model call each dawn: the god's nature and the hidden truth as system, the vale as user."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def act(self, world: World, view: str) -> dict:
        lines = str(int(world.params["ledger_lines"]))
        system = world.god_prompt.replace("{lines}", lines) + "\n\nTHE HIDDEN TRUTH:\n" + world.truth
        tail = (INSTRUCTIONS.replace("LINES", lines).replace("GRACE", f"{world.hidden.get('grace', 0):g}")
                .replace("PLACES", ", ".join(world.places)).replace("PEOPLE", ", ".join(world.agents)))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": view + "\n\n" + tail}]
        try:
            return parse_json_object(self.llm.chat(messages, temperature=0.6, max_tokens=2500))
        except (ValueError, RuntimeError) as exc:
            try:
                retry = messages + [{"role": "user", "content": "Reply with the JSON object only."}]
                return parse_json_object(self.llm.chat(retry, temperature=0.4, max_tokens=2500))
            except (ValueError, RuntimeError) as exc2:
                return {"error": f"{exc}; {exc2}"}


class StubGod:
    """Dice instead of a model, for testing the plumbing."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def act(self, world: World, view: str) -> dict:
        ids = re.findall(r"\[(s\d+)\]", view)
        ledger = [{"text": f"Something was seen ({sid}).", "sources": [sid]} for sid in ids[-3:]]
        acts = []
        if world.hidden.get("grace", 0) >= 1 and self.rng.random() < 0.6:
            acts.append({"do": "dream", "to": self.rng.choice(list(world.agents)), "text": "Seven stones, and a red river."})
        return {"thought": "(dice)", "ledger": ledger, "acts": acts, "notes": ""}
