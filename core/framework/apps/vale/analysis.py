"""Reading a run back: ripples, branching, who talked to whom.

A ripple is a tree of stirrings: an activation's parent is the activation that
emitted the strongest signal that stirred it. Roots are stirrings the world itself
caused (an omen, a fever, a market day). Ripples can span days: an undertaking
proposed today is attempted at its hour, perhaps tomorrow, and whatever its outcome
stirs is still the same ripple.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


def load(run_dir: Path) -> list[dict]:
    events = []
    with (run_dir / "log.jsonl").open(encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a line still being written by a running tick
    return events


def ripples(acts: list[dict]) -> tuple[list[dict], dict[str, str | None]]:
    by_id = {a["id"]: a for a in acts}
    parent = {a["id"]: (a.get("parent") if a.get("parent") in by_id else None) for a in acts}
    children: dict[str, list[str]] = defaultdict(list)
    for aid, par in parent.items():
        if par:
            children[par].append(aid)
    trees = []
    for root in (aid for aid, par in parent.items() if par is None):
        members, depth, stack = [], 0, [(root, 1)]
        while stack:
            node, d = stack.pop()
            members.append(node)
            depth = max(depth, d)
            stack.extend((c, d + 1) for c in children[node])
        agents = {by_id[m]["agent"] for m in members}
        places = {by_id[m].get("place") for m in members}
        days = {by_id[m]["day"] for m in members}
        trees.append(
            {
                "root": root,
                "day": by_id[root]["day"],
                "size": len(members),
                "depth": depth,
                "agents": sorted(agents),
                "places": sorted(p for p in places if p),
                "days": sorted(days),
                "members": members,
            }
        )
    trees.sort(key=lambda t: -t["size"])
    return trees, parent


def stats(run_dir: Path) -> dict:
    events = load(run_dir)
    acts = [e for e in events if e["ev"] == "activation"]
    days = [e for e in events if e["ev"] == "day"]
    if not acts:
        return {"days": len(days), "activations": 0}
    trees, parent = ripples(acts)
    n = len(acts)
    per_day = Counter(a["day"] for a in acts)
    sizes = [t["size"] for t in trees]
    return {
        "days": len(days),
        "activations": n,
        "per_day": [per_day.get(d["day"], 0) for d in days],
        "tired": sum(d.get("tired", 0) for d in days),
        "ripples": len(trees),
        "branching": round((n - len(trees)) / n, 3),
        "mean_size": round(mean(sizes), 2),
        "max_size": max(sizes),
        "max_depth": max(t["depth"] for t in trees),
        "size_hist": dict(sorted(Counter(min(s, 20) for s in sizes).items())),
        "multi_place": sum(1 for t in trees if len(t["places"]) > 1),
        "multi_day": sum(1 for t in trees if len(t["days"]) > 1),
        "top": trees[:3],
    }


def interactions(run_dir: Path) -> Counter:
    """Directed speech, gifts and shared undertakings: who reached whom."""
    events = load(run_dir)
    edges: Counter = Counter()
    sigs = {e["id"]: e for e in events if e["ev"] == "signal"}
    for e in events:
        if e["ev"] == "activation":
            for sid in e.get("emitted", []):
                s = sigs.get(sid)
                if s and s.get("to"):
                    edges[(e["agent"], s["to"])] += 1
        elif e["ev"] == "outcome":
            sup = e.get("supporters", [])
            for i, a in enumerate(sup):
                for b in sup[i + 1 :]:
                    edges[(a, b)] += 1
    return edges
