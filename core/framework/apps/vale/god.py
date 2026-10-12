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

from .act import carried
from .analysis import load
from .fate import knows_text
from .llm import LLM, parse_json_object
from .nature import describe_state
from .overgod import decree_for
from .world import World

# What the Ledger may rest on: what someone said, posted, did or found, or what the world showed.
CITABLE = {"speech", "notice", "painting", "clue", "deed", "project", "omen", "outcome", "sign"}


def _hidden(world: World) -> tuple[set[str], set[str]]:
    """What the god who displaced old Ullr cannot see: his mark on his chosen, and his dreams to her."""
    gods = world.story.get("gods", {})
    return set(gods.get("hidden_from_god", [])), {gods["chosen"]} if gods.get("chosen") else set()


def has_god(world: World) -> bool:
    return world.params.get("god_grace", 0) > 0 or bool(world.hidden.get("god_human"))


def ledger_text(world: World) -> str:
    """The Ledger as the villagers know it: each line with who said, found or saw it."""
    lines = [f"- {e['text']} ({e['witness']})" for e in world.hidden.get("ledger", [])]
    lines += [f"- {text} ({world.t('god.unseen_hand')})" for text in world.hidden.get("ledger_pinned", [])]
    return "\n".join(lines) or world.t("god.ledger_blank")


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
        "god",
        grace_before=grace_before,
        grace=h.get("grace", 0.0),
        thought=str(reply.get("thought") or "")[:900],
        notes=h.get("god_notes", ""),
        acts=applied,
        dropped=dropped,
        ledger=h.get("ledger", []),
        pinned=h.get("ledger_pinned", []),
        struck=struck,
        new=new_lines,
        prayers=prayers,
        error=reply.get("error"),
    )
    if verbose:
        for x in applied:
            target = {"dream": world.name(x.get("to")), "sign": world.place_name(x.get("at"))}.get(x["do"], "the Ledger")
            print(f"  ✶ god: {x['do']} → {target}: {x.get('text', '')}"[:300], flush=True)
        if new_lines:
            print(f"  ✶ ledger: {len(new_lines)} new line(s), {len(h.get('ledger', []))} in all; {len(struck)} struck", flush=True)


def digest(world: World, events: list[dict], index: dict[str, dict]) -> str:
    """Everything the god sees at dawn, as one message."""
    t = world.t
    sep = t("names.list_sep")
    h, day = world.hidden, world.day
    hidden_knows, hidden_dreamers = _hidden(world)
    out = [t("god.dawn", day=day, grace=f"{h.get('grace', 0):g}"), "", t("god.truly"), describe_state(world)]
    if h.get("god_notes"):
        out += ["", t("god.notes"), h["god_notes"]]
    out += ["", t("god.ledger_yesterday")]
    out += [t("god.ledger_cited", text=e["text"], sources=", ".join(e["sources"]), witness=e["witness"]) for e in h.get("ledger", [])] or [
        t("god.blank")
    ]
    if h.get("ledger_pinned"):
        out += [t("god.pinned")] + [f"- {x}" for x in h["ledger_pinned"]]

    out += ["", t("god.prayers")]
    out += [
        t(
            "god.prayer",
            id=q["id"],
            who=world.name(q["agent"]),
            place=world.place_name(q["place"]),
            day=q["day"],
            wave=world.wave_name(q["wave"]),
            note=t("god.prayer_to_master") if q.get("to") == "master" else "",
            text=q["text"],
        )
        for q in h.get("prayers", [])
    ] or [t("god.none")]

    out += ["", t("god.people")]
    for a in world.agents.values():
        where = world.place_name(a.loc) if a.loc else t("god.on_road", place=world.place_name((a.travel or {}).get("to")))
        out.append(
            t(
                "god.person",
                name=a.name,
                id=a.id,
                role=a.role,
                where=where,
                health=t.get("health.states")[a.health],
                energy=f"{a.reserve:.1f}",
                knows=knows_text(world, a, hidden_knows),
                items=carried(world, a) or t("names.nothing"),
            )
        )
        out.append(t("god.person_notes", notes=world.read_memory(a.id).replace("\n", " ")))

    sigs = {e["id"]: e for e in events if e["ev"] == "signal"}
    out += ["", t("god.yesterday", day=day - 1)]
    for e in events:
        d = e.get("day", 0)
        if d < max(1, day - 1):
            continue
        when = f"[{t('time.day_wave', day=d, wave=world.wave_name(e.get('wave', 0)))}]"
        if e["ev"] == "activation":
            top = (e.get("contribs") or [{}])[0]
            stirred = t("god.stirred_by", id=top["signal"], kind=top.get("kind")) if top.get("signal") else ""
            out.append(
                t(
                    "god.activation",
                    when=when,
                    name=world.name(e["agent"]),
                    place=world.place_name(e.get("place")),
                    stirred=stirred,
                    thought=e.get("thought", ""),
                )
            )
            for sid in e.get("emitted") or []:
                if sid in sigs:
                    out.append(f"    {'[' + sid + '] ' if sid in index else ''}{_render(world, sigs[sid])}")
        elif e["ev"] == "signal" and e.get("source") == "world" and e.get("kind") in ("omen", "outcome") and not e.get("hops"):
            seen = t("god.seen_only", who=sep.join(world.name(x) for x in e["audience"])) if e.get("audience") else ""
            out.append(
                t("god.world_event", when=when, id=e["id"], kind=e["kind"].upper(), place=world.place_name(e.get("loc")), seen=seen, text=e["text"])
            )
        elif e["ev"] == "outer" and d == day - 1 and e.get("boon"):
            out.append(t("god.star_eased", when=when, place=world.place_name(e["boon"].get("place")), text=e.get("public", "")))
        elif e["ev"] == "ullr" and d == day - 1:
            for x in e.get("acts") or []:
                if x["do"] == "dream" and x.get("to") in hidden_dreamers:
                    continue  # the old god's voice in his chosen's sleep is beyond you
                target = world.name(x.get("to")) if x["do"] == "dream" else world.place_name(x.get("at"))
                out.append(t("god.ullr_act", when=when, what=x["do"], target=target, text=x.get("text", "")))
        elif e["ev"] == "overgod" and d >= day - 1:
            words = e.get("args", {}).get("text")
            out.append(t("god.above", when=when, what=e.get("what", "")) + (f' "{words}"' if words else ""))
        elif e["ev"] == "god" and d == day - 1:
            for x in e.get("acts") or []:
                target = world.name(x["to"]) if x["do"] == "dream" else world.place_name(x.get("at"))
                out.append(t("god.you_sent", when=when, what=x["do"], target=target, text=x.get("text", "")))

    old = [e for e in index.values() if 0 < e.get("day", 0) < day - 1 and e["kind"] in ("clue", "notice", "painting", "outcome", "project", "sign")]
    if old:
        out += ["", t("god.older")]
        out += [t("god.old_line", id=e["id"], witness=_witness(world, index, [e["id"]]), text=e["text"][:220]) for e in old[-60:]]
    return "\n".join(out)


def _render(world: World, e: dict) -> str:
    t = world.t
    kind, text = e["kind"], e["text"]
    if kind == "speech":
        return t("god.render_speech", to=world.name(e["to"]) if e.get("to") else t("names.everyone"), text=text)
    if kind in ("notice", "painting", "clue", "project"):
        return t(f"god.render_{kind}", text=text)
    return text


def _index(events: list[dict]) -> dict[str, dict]:
    """Every signal the Ledger may cite, by id. A sign counts only once somebody saw it."""
    seen = {c["signal"] for e in events if e["ev"] == "activation" for c in e.get("contribs") or []}
    for e in events:
        if e["ev"] == "god":
            seen.update(x["signal"] for x in e.get("acts") or [] if x.get("do") == "sign" and x.get("seen_by"))
    return {
        e["id"]: e
        for e in events
        if e["ev"] == "signal" and not e.get("hops") and e.get("kind") in CITABLE and (e["kind"] != "sign" or e["id"] in seen)
    }


def _witness(world: World, index: dict[str, dict], sources: list[str]) -> str:
    t = world.t
    sep = t("names.list_sep")
    parts: list[str] = []
    for sid in sources:
        e = index[sid]
        day, src = e.get("day"), e.get("source")
        if e["kind"] == "clue":
            part = t("god.found_by", who=sep.join(world.name(a) for a in e.get("audience") or []), day=day)
        elif src in world.agents:
            part = t("god.by_on_day", verb=t.get("god.verb").get(e["kind"], t("god.by")), who=world.name(src), day=day)
        elif e.get("audience"):
            part = t("god.seen_by", who=sep.join(world.name(a) for a in e["audience"]), day=day)
        else:
            part = t("god.seen_at", place=world.place_name(e.get("loc")), day=day)
        if part not in parts:
            parts.append(part)
    return t("names.clause_sep").join(parts[:3])


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
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), *(cut.rfind(c) for c in "。！？"))
    return cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…"


class LLMGod:
    """One model call each dawn: the god's nature and the hidden truth as system, the vale as user."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def act(self, world: World, view: str) -> dict:
        lines = str(int(world.params["ledger_lines"]))
        system = world.god_prompt.replace("{lines}", lines) + "\n\n" + world.t("god.truth_heading") + "\n" + world.truth + decree_for(world, "god")
        tail = world.t(
            "god.instructions", lines=lines, grace=f"{world.hidden.get('grace', 0):g}", places=", ".join(world.places), people=", ".join(world.agents)
        )
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
