"""Export a run as one JSON document: everything the visual report needs."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .analysis import load, ripples, stats

# Bagel's thoughts that weigh a painting against what the vale needs.
PAINTISH = re.compile(r"paint|brush|colou?r|rainbow|canvas|picture|coils? ", re.I)
# The dice line the villagers read after a rolled deed or outcome; the page draws the dice instead.
DICE_TAIL = re.compile(r"\s*\[the dice: [^\]]*\]$")


def _persona_section(md: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""

COLORS = {
    "hal": "#c98b2b", "maud": "#3f7d6e", "aldric": "#7a4b9c", "osric": "#9a3b3b", "brannoc": "#b4542b",
    "isolde": "#5a6fb0", "gytha": "#4f8a3a", "bram": "#8a7a52", "wynn": "#d16a8f", "tobias": "#5e7f9e",
    "marta": "#b07a3c", "cedric": "#8f8a2e", "elspeth": "#3f8fa0", "kell": "#55703a", "bagel": "#e89ab8",
}


def export(run_dir: Path, out: str | None = None) -> str:
    """Write the run's export JSON (to `out`, or export.json in the run) and return its path."""
    path = Path(out) if out else run_dir / "export.json"
    path.write_text(json.dumps(export_data(run_dir), ensure_ascii=False), "utf-8")
    return str(path)


def export_data(run_dir: Path) -> dict:
    """Everything the visual report needs about one run."""
    events = load(run_dir)
    cfg = tomllib.loads((run_dir / "world" / "world.toml").read_text("utf-8"))
    agents = []
    for adir in sorted((run_dir / "world" / "agents").iterdir()):
        sheet = tomllib.loads((adir / "sheet.toml").read_text("utf-8"))
        aid = adir.name
        history = []
        for snap in sorted((run_dir / "agents" / aid / "history").glob("day_*.md")):
            history.append({"day": int(snap.stem.split("_")[1]), "text": snap.read_text("utf-8").strip()})
        persona = (adir / "persona.md").read_text("utf-8")
        agents.append({
            "id": aid, "name": sheet["name"], "short": sheet["short"], "role": sheet["role"],
            "public": sheet["public"], "home": sheet["home"], "start": sheet.get("start", sheet["home"]),
            "color": COLORS.get(aid, "#888"), "persona": persona,
            "rules": [ln[2:].strip() for ln in _persona_section(persona, "Rules you live by").splitlines() if ln.startswith("- ")],
            "want": _persona_section(persona, "What you want"),
            "deeper": _persona_section(persona, "Deeper still"),
            "base": sheet.get("interests", {}),
            "memory": history,
        })

    signals, acts, looks, outcomes, proposals, joins, opposes, days = {}, [], [], [], [], [], [], []
    god, prayers, outer, ullr, checks, attempts = [], [], [], [], [], []
    for e in events:
        ev = e["ev"]
        if ev == "signal":
            signals[e["id"]] = {k: e.get(k) for k in ("kind", "text", "loc", "source", "to", "born", "cause", "strength", "tags", "origin", "project", "audience", "hops")}
            if e["kind"] == "deed" and e["text"].endswith("knelt and prayed."):
                signals[e["id"]]["prayer"] = True
            if e["kind"] == "deed" and ' set about something hard: "' in e["text"]:
                signals[e["id"]]["attempt"] = True
            if m := DICE_TAIL.search(e["text"] or ""):
                signals[e["id"]]["text"] = e["text"][:m.start()]
                signals[e["id"]]["dice"] = True
        elif ev == "activation":
            acts.append({k: e.get(k) for k in ("id", "day", "wave", "agent", "place", "stimulus", "p", "parent", "contribs", "thought", "done", "failures", "mood", "emitted", "tags")})
            if e["agent"] == "bagel":
                acts[-1]["paintish"] = bool(PAINTISH.search(e.get("thought") or ""))
        elif ev == "look":
            looks.append({k: e.get(k) for k in ("day", "wave", "agent", "feature", "text", "grants")})
        elif ev == "outcome":
            outcomes.append({k: e.get(k) for k in ("day", "wave", "project", "projects", "title", "place", "supporters", "present", "absent", "outcome", "public", "secret", "applied", "check", "might")})
        elif ev == "attempt":
            attempts.append({k: e.get(k) for k in ("day", "wave", "id", "agent", "place", "what", "using", "act", "outcome", "public", "secret", "applied", "check", "might")})
        elif ev == "check":
            checks.append({k: e.get(k) for k in ("day", "wave", "kind", "ref", "place", "what", "skill", "roller", "base", "mods", "target", "fumble", "roll", "band")})
        elif ev == "proposal":
            proposals.append({k: e.get(k) for k in ("day", "wave", "project", "title", "goal", "needs", "quorum", "place", "proposer", "site", "when", "due_day")})
        elif ev == "join":
            joins.append({k: e.get(k) for k in ("day", "wave", "project", "agent", "offer")})
        elif ev == "oppose":
            opposes.append({k: e.get(k) for k in ("day", "wave", "project", "agent", "why")})
        elif ev == "day":
            days.append({k: e.get(k) for k in ("day", "activations", "tired", "rumors", "hidden", "positions", "health", "reserves", "interests", "alive_signals", "grace")})
        elif ev == "god":
            god.append({k: e.get(k) for k in ("day", "grace_before", "grace", "thought", "acts", "dropped", "ledger", "pinned", "struck", "new", "prayers", "error")})
        elif ev == "prayer":
            prayers.append({k: e.get(k) for k in ("id", "day", "wave", "agent", "place", "text", "act", "to")})
        elif ev == "ullr":
            ullr.append({k: e.get(k) for k in ("day", "awake", "stirring", "thought", "acts", "prayers")})
        elif ev == "outer":
            outer.append({k: e.get(k) for k in ("day", "thought", "prayers", "boon", "price", "price_text", "public", "signal", "dream", "dream_signal", "refused")})

    trees, _ = ripples(acts)
    chronicle = (run_dir / "chronicle.md").read_text("utf-8") if (run_dir / "chronicle.md").exists() else ""
    data = {
        "meta": {"run": run_dir.name, "days": len(days), "physics": cfg["physics"], "stats": {k: v for k, v in stats(run_dir).items() if k != "top"}},
        "places": [{k: p[k] for k in ("id", "name", "desc", "x", "y", "roads")} for p in cfg["place"]],
        "agents": agents,
        "days": days,
        "activations": acts,
        "signals": signals,
        "looks": looks,
        "proposals": proposals,
        "joins": joins,
        "opposes": opposes,
        "outcomes": outcomes,
        "ripples": [{k: t[k] for k in ("root", "day", "size", "depth", "agents", "places", "days", "members")} for t in trees],
        "god": god,
        "prayers": prayers,
        "outer": outer,
        "ullr": ullr,
        "checks": checks,
        "attempts": attempts,
        "chronicle": chronicle,
    }
    return data


def displayed_signals(run: dict) -> set[str]:
    """Signals whose words the page shows: deeds, public omens, ripple triggers, paintings, what Bagel's sketches draw."""
    ids: set[str] = set()
    for a in run["activations"]:
        ids.update(a.get("emitted") or [])
        if a.get("paintish"):
            ids.update(c["signal"] for c in (a.get("contribs") or [])[:2])
    for sid, s in run["signals"].items():
        if (s["kind"] == "omen" and s.get("loc") and not s.get("audience")) or s["kind"] == "painting":
            ids.add(sid)
    acts = {a["id"]: a for a in run["activations"]}
    for r in run["ripples"]:
        root = acts.get(r["root"])
        if root and root.get("contribs"):
            ids.add(root["contribs"][0]["signal"])
    return ids & set(run["signals"])


def prune(run: dict) -> None:
    """Drop the words of signals the page never shows (mostly rumours), in place: the page stays a fraction of the size."""
    shown = displayed_signals(run)
    for sid, s in run["signals"].items():
        if sid not in shown:
            s["text"] = ""
