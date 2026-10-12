"""Command line: `python -m vale <command>` from experiments/emergence.

    new <run> [--seed N] [--set key=value]   create a run from the world template
    tick <run> [--stub]                      advance one day (this is what a cron calls)
    run <run> --days N [--every SECONDS]     tick repeatedly: a cron in miniature
    stats <run>                              ripples, branching, activity
    sweep [--days N]                         tune the physics with dice-rolling stand-ins
    chronicle <run>                          have a chronicler write the run up
    export <run>                             the run as one JSON file, for the viewer
    report <out.html> --run NAME:LABEL ...   the visual report, one or more runs
    god <run> dream <who> <text>             play god: a dream, a sign or a Ledger line,
    god <run> sign <place> <text>            delivered at the run's next dawn
    god <run> ledger <text>
"""

from __future__ import annotations

import argparse
import json
import shutil
import time

from . import analysis
from .engine import configure_stdout, tick
from .fate import LLMFate, StubFate
from .god import LLMGod, StubGod
from .llm import LLM
from .mind import LLMMind, StubMind
from .outer import LLMOuter, StubOuter
from .ullr import LLMUllr, StubUllr
from .world import RUNS, World


def _minds(stub: bool, seed: int = 0):
    if stub:
        return StubMind(seed), StubFate(), StubGod(seed), StubOuter(seed), StubUllr(seed)
    llm = LLM()
    return LLMMind(llm), LLMFate(llm), LLMGod(llm), LLMOuter(llm), LLMUllr(llm)


def _overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, _, val = pair.partition("=")
        out[key.strip()] = float(val)
    return out


def cmd_run(name: str, days: int, stub: bool, every: float, workers: int, verbose: bool = True) -> None:
    mind, fate, god, outer, ullr = _minds(stub)
    for i in range(days):
        world = World(RUNS / name)
        try:
            tick(world, mind, fate, god=god, outer=outer, ullr=ullr, workers=workers, verbose=verbose)
        finally:
            world.close()
        if every and i < days - 1:
            time.sleep(every)
    if not stub and verbose:
        llm = mind.llm
        print(f"\nmodel calls: {llm.calls}, ~{llm.chars_in // 4:,} tokens in, ~{llm.chars_out // 4:,} tokens out")


def cmd_sweep(days: int) -> None:
    grid = [(refill, theta) for refill in (0.0, 0.3, 0.6, 1.0) for theta in (1.0, 1.25, 1.6)]
    rows = []
    print(f"{'refill':>6} {'theta':>6} | {'acts/day':>8} {'tired':>6} {'ripples':>7} {'branch':>6} {'mean':>5} {'max':>4} {'depth':>5} {'x-place':>7} | sizes")
    for refill, theta in grid:
        name = f"_sweep/r{refill}_t{theta}"
        shutil.rmtree(RUNS / name, ignore_errors=True)
        World.create(RUNS / name, seed=11, overrides={"refill": refill, "theta_scale": theta}).close()
        cmd_run(name, days, True, 0, 1, verbose=False)
        s = analysis.stats(RUNS / name)
        if not s["activations"]:
            print(f"{refill:>6} {theta:>6} | {'0':>8}")
            continue
        apd = s["activations"] / s["days"]
        rows.append({"refill": refill, "theta": theta, "apd": round(apd, 1), "tired": s["tired"], "branching": s["branching"],
                     "max_size": s["max_size"], "max_depth": s["max_depth"]})
        print(f"{refill:>6} {theta:>6} | {apd:>8.1f} {s['tired']:>6} {s['ripples']:>7} {s['branching']:>6} {s['mean_size']:>5} "
              f"{s['max_size']:>4} {s['max_depth']:>5} {s['multi_place']:>7} | {s['size_hist']}")
    (RUNS / "_sweep" / "sweep.json").write_text(json.dumps({"days": days, "rows": rows}), "utf-8")


def main() -> None:
    configure_stdout()
    ap = argparse.ArgumentParser(prog="vale", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("run")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    for name in ("tick", "run"):
        p = sub.add_parser(name)
        p.add_argument("run")
        p.add_argument("--stub", action="store_true", help="dice instead of a model")
        p.add_argument("--workers", type=int, default=6)
        if name == "run":
            p.add_argument("--days", type=int, default=1)
            p.add_argument("--every", type=float, default=0.0, help="seconds between ticks")
    p = sub.add_parser("stats")
    p.add_argument("run")
    p = sub.add_parser("sweep")
    p.add_argument("--days", type=int, default=20)
    p = sub.add_parser("chronicle")
    p.add_argument("run")
    p = sub.add_parser("export")
    p.add_argument("run")
    p.add_argument("--out")
    p = sub.add_parser("report")
    p.add_argument("out")
    p.add_argument("--run", action="append", required=True, metavar="NAME:LABEL")
    p.add_argument("--lang", default="en", choices=["en", "zh"], help="zh: translate the report with the model (cached)")
    p = sub.add_parser("god")
    p.add_argument("run")
    p.add_argument("do", choices=["dream", "sign", "ledger"])
    p.add_argument("words", nargs="+", help="dream: WHO TEXT...; sign: PLACE TEXT...; ledger: TEXT...")
    args = ap.parse_args()

    if args.cmd == "new":
        World.create(RUNS / args.run, seed=args.seed, overrides=_overrides(args.set)).close()
        print(f"created {RUNS / args.run}")
    elif args.cmd == "tick":
        cmd_run(args.run, 1, args.stub, 0, args.workers)
    elif args.cmd == "run":
        cmd_run(args.run, args.days, args.stub, args.every, args.workers)
    elif args.cmd == "stats":
        s = analysis.stats(RUNS / args.run)
        s.pop("top", None)
        print(json.dumps(s, indent=1))
        edges = analysis.interactions(RUNS / args.run)
        print("strongest ties formed:", edges.most_common(12))
    elif args.cmd == "sweep":
        cmd_sweep(args.days)
    elif args.cmd == "chronicle":
        from .chronicle import write_chronicle

        print(write_chronicle(RUNS / args.run, LLM()))
    elif args.cmd == "export":
        from .export import export

        print(export(RUNS / args.run, args.out))
    elif args.cmd == "report":
        from pathlib import Path

        from .report import build

        pairs = [tuple(r.split(":", 1)) if ":" in r else (r, r) for r in args.run]
        print(build(pairs, Path(args.out), lang=args.lang))
    elif args.cmd == "god":
        world = World(RUNS / args.run)
        try:
            if args.do == "ledger":
                act = {"do": "ledger", "text": " ".join(args.words)}
            elif len(args.words) < 2:
                ap.error(f"god {args.do} needs a {'person' if args.do == 'dream' else 'place'} and some words")
            else:
                key = "to" if args.do == "dream" else "at"
                act = {"do": args.do, key: args.words[0], "text": " ".join(args.words[1:])}
            world.hidden.setdefault("god_queue", []).append(act)
            world.hidden["god_human"] = True
            world.save()
        finally:
            world.close()
        print(f"queued for the dawn of day {world.day + 1}: {act}")


if __name__ == "__main__":
    main()
