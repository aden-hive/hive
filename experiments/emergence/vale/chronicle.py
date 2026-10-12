"""A chronicler writes the run up from the log: what was said and done, day by day.

The chronicler is not a villager and stirs nothing; it reads the record afterwards.
It is shown the hidden truth too, so it can name what the villagers never knew,
but it may not invent events.
"""

from __future__ import annotations

import tomllib
from collections import defaultdict
from pathlib import Path

from .analysis import load
from .dice import line as dice_line
from .llm import LLM
from .world import WAVES

SYSTEM = """You are the chronicler of the Vale of Ashmere, writing after the fact. You have the full record of what every villager said and did, day by day, and you know the hidden truth beneath the vale (below).

Write "The Chronicle of the Vale of Ashmere": a vivid, faithful account in the voice of an old chronicle, but readable — plain modern English with an old cadence. Rules:
- Never invent events, words or outcomes that are not in the record. You may compress, select and connect.
- Quote villagers' own words sparingly, where they matter.
- Where the villagers believed something false, or didn't know what you know, say so plainly, as a chronicler's aside.
- Give each day a short heading. Follow threads across days: who carried which word to whom, what grew out of what.
- If the record shows GOD acting (lines in the Ledger of the World, dreams, signs), those are real events of this world: every villager knew the Ledger, the dreamer knew the dream, those present saw the sign. Nobody in the vale saw God's private thoughts; you may.
- The same holds for PLEIADES, Bagel's master, an Outer God from beyond this world: his boons were seen by those present; his dreams were Bagel's alone.
- And for ULLR, the old god, when his song held him awake: his signs were seen by those present, his dreams known only to the dreamer.
- Where the record shows THE DICE, every hard thing tried, alone or together, was settled by a roll (a d100 under a skill, as in a tabletop game), and the outcome followed the roll. Where luck turned the story, you may say so.
{shape}

THE HIDDEN TRUTH:
{truth}"""


def record(run_dir: Path, days: set[int] | None = None) -> str:
    """The log as a plain day-by-day record of public events (of only `days`, if given)."""
    events = load(run_dir)
    names = {}
    for adir in (run_dir / "world" / "agents").iterdir():
        names[adir.name] = tomllib.loads((adir / "sheet.toml").read_text("utf-8"))["name"]
    places = {p["id"]: p["name"] for p in tomllib.loads((run_dir / "world" / "world.toml").read_text("utf-8"))["place"]}

    by_day: dict[int, list[str]] = defaultdict(list)
    for e in events:
        d = e.get("day", 0)
        if e["ev"] == "signal" and e.get("kind") == "omen":
            where = places.get(e.get("loc"), "")
            who = f" (seen only by {', '.join(names.get(a, a) for a in e['audience'])})" if e.get("audience") else ""
            if e.get("audience") and e["text"].startswith("You "):
                continue  # private aches; the activations carry what mattered
            by_day[d].append(f"[{WAVES[e['wave']]}] OMEN at {where}{who}: {e['text']}")
        elif e["ev"] == "activation":
            who = names.get(e["agent"], e["agent"])
            where = places.get(e.get("place"), "")
            if e.get("done"):
                by_day[d].append(f"[{WAVES[e['wave']]}] {who} at {where}: " + " | ".join(e["done"]))
            if e.get("thought"):
                by_day[d].append(f"    ({who} privately thought: {e['thought'][:220]})")
        elif e["ev"] == "look":
            by_day[d].append(f"    -> {names.get(e['agent'], e['agent'])} found: {e['text'][:260]}")
        elif e["ev"] == "quorum":
            by_day[d].append(f"[{WAVES[e['wave']]}] QUORUM: '{e['title']}' will be attempted at dawn (joined: {', '.join(names.get(a, a) for a in e['supporters'])})")
        elif e["ev"] == "outcome":
            came = f" by {', '.join(names.get(a, a) for a in e['present'])}" if e.get("present") else ""
            roll = f" (THE DICE: {dice_line(e['check'], names.get(e['check']['roller'], ''))})" if e.get("check") else ""
            by_day[d].append(f"[{WAVES[e['wave']]}] ATTEMPTED '{e['title']}' at {places.get(e['place'], e['place'])}{came} -> {e['outcome'].upper()}: {e['public']}"
                             + roll + (f" (unseen: {e['secret']})" if e.get("secret") else ""))
        elif e["ev"] == "attempt":
            who = names.get(e["agent"], e["agent"])
            by_day[d].append(f"[{WAVES[e['wave']]}] {who} TRIED ALONE at {places.get(e['place'], '')}: \"{e['what']}\" -> {e['outcome'].upper()}: {e['public']}"
                             + (f" (THE DICE: {dice_line(e['check'], who)})" if e.get("check") else " (no roll needed)")
                             + (f" (unseen: {e['secret']})" if e.get("secret") else ""))
        elif e["ev"] == "check" and e.get("kind") in ("tend", "travel"):
            who = names.get(e["roller"], e["roller"])
            by_day[d].append(f"    -> {who}, {e['what']}: {e['band'].upper()} (THE DICE: {dice_line(e, who)})")
        elif e["ev"] == "abandoned":
            by_day[d].append(f"PROPOSAL ABANDONED: '{e['title']}'")
        elif e["ev"] == "prayer":
            to = {"master": " (to her master, pleiades)", "ullr": " (to old Ullr)"}.get(e.get("to"), "")
            by_day[d].append(f"[{WAVES[e['wave']]}] PRAYER{to} by {names.get(e['agent'], e['agent'])} at {places.get(e['place'], '')}: {e['text']}")
        elif e["ev"] == "ullr":
            if e.get("thought"):
                by_day[d].append(f"[dawn] (OLD ULLR, {'awake' if e.get('awake') else 'stirring in his sleep'}, privately thought: {e['thought'][:300]})")
            for x in e.get("acts") or []:
                if x["do"] == "dream":
                    by_day[d].append(f"[dawn] ULLR sent {names.get(x['to'], x['to'])} a dream: {x['text']}")
                elif x["do"] == "hunt":
                    by_day[d].append(f"[dawn] ULLR's hunt turned the wolves from the fold: {x['text']}")
                else:
                    by_day[d].append(f"[dawn] ULLR showed a sign at {places.get(x.get('at'), '')}: {x['text']}")
        elif e["ev"] == "outer":
            if e.get("thought"):
                by_day[d].append(f"[dawn] (PLEIADES, Bagel's master, an Outer God, privately thought: {e['thought'][:300]})")
            if e.get("boon"):
                by_day[d].append(f"[dawn] PLEIADES granted a boon ({e['boon'].get('kind')}) at {places.get(e['boon'].get('place'), '')}, taking Bagel's painting \"{(e.get('price_text') or '')[:120]}\": {e.get('public', '')}")
            elif e.get("refused"):
                by_day[d].append(f"[dawn] PLEIADES granted nothing ({e['refused']}).")
            if e.get("dream"):
                by_day[d].append(f"[dawn] PLEIADES spoke to Bagel in a dream: {e['dream']}")
        elif e["ev"] == "god":
            if e.get("thought"):
                by_day[d].append(f"[dawn] (GOD privately thought: {e['thought'][:400]})")
            for x in e.get("acts") or []:
                if x["do"] == "dream":
                    by_day[d].append(f"[dawn] GOD sent {names.get(x['to'], x['to'])} a dream: {x['text']}")
                elif x["do"] == "sign":
                    by_day[d].append(f"[dawn] GOD showed a sign at {places.get(x['at'], x['at'])}: {x['text']}")
                elif x["do"] == "ledger":
                    by_day[d].append(f"[dawn] AN UNSEEN HAND wrote in the Ledger: {x['text']}")
            for line in e.get("ledger") or []:
                if line.get("since") == d:
                    by_day[d].append(f"[dawn] NEW IN THE LEDGER OF THE WORLD: {line['text']} ({line['witness']})")
    out = []
    for d in sorted(k for k in by_day if k > 0 and (days is None or k in days)):
        out.append(f"\n=== DAY {d} ===")
        out.extend(by_day[d])
    return "\n".join(out)


WHOLE = """- End with a short section, "What no one planned", naming the things that happened in the vale that no single villager set out to make happen.
- 1200 to 1800 words."""
FIRST = """- This is the first part of a longer chronicle: cover only the days in this record and stop where they stop. Leave any closing section for later.
- 1500 to 2200 words."""
LAST = """- This continues a chronicle already begun (given below): pick up where it stopped. Do not repeat its title or retell its days.
- End with a short section, "What no one planned", naming the things that happened in the vale, across the whole chronicle, that no single villager set out to make happen.
- 1500 to 2200 words."""


def write_chronicle(run_dir: Path, llm: LLM) -> str:
    """Write the chronicle; a run longer than sixteen days is written in two halves, the second continuing the first."""
    truth = (run_dir / "world" / "truth.md").read_text("utf-8")
    deep = run_dir / "world" / "truth_deep.md"
    if deep.exists():
        truth += "\n\n" + deep.read_text("utf-8")
    n = sum(1 for e in load(run_dir) if e["ev"] == "day")
    halves = [(set(range(1, n + 1)), WHOLE)] if n <= 16 else [(set(range(1, n // 2 + 1)), FIRST), (set(range(n // 2 + 1, n + 1)), LAST)]
    text = ""
    for days, shape in halves:
        so_far = f"THE CHRONICLE SO FAR:\n{text}\n\n" if text else ""
        piece = llm.chat(
            [
                {"role": "system", "content": SYSTEM.format(truth=truth, shape=shape)},
                {"role": "user", "content": so_far + f"THE RECORD OF DAYS {min(days)} TO {max(days)}:\n" + record(run_dir, days) + "\n\nWrite the chronicle now."},
            ],
            temperature=0.7,
            max_tokens=5000,
            json_mode=False,
        )
        text = f"{text}\n\n{piece.strip()}".strip()
    (run_dir / "chronicle.md").write_text(text + "\n", "utf-8")
    return text
