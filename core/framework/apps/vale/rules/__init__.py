"""World rules: how a world evolves, what can change it, and how it is seen. All data.

A world is defined by its story pack. The engine (the kernel) is the same for every world:
signals and the physics of attention, villagers as Hive agents, actions and undertakings,
fate and the dice, the gods' turns, the One Above, the host and the novel. Everything that
makes one world different from another is declared in ``stories/<story>/rules.toml``,
language-free (words are in each language's ``story.toml``):

``[state]``                 the hidden world's starting state, beyond world.toml's
``[constants]``             named data the rules read (tables, ids, thresholds)
``[[night]]``               steps run as each night passes (from the second dawn on)
``[[dawn]]``                steps run each dawn, after the omens, the calendar and the deck
``[[after_gods]]``          steps run after the gods' dawn turns
``[[watch]]``               steps run before the chapters are checked
``refill``                  the share of the dawn's energy that reaches the villagers
``travel``                  how many parts of the day one road takes
``describe``                the hidden world in words, one expression per line
``summary``                 hidden keys kept in each day's record
``[effects.<type>]``        what fate may change, beyond the standard effects
``[[power]]``               the One Above's powers: standard blocks (``use``) or steps
``[[chapter]]``             the One Above's goals
``[awe]``                   the One Above's economy
``[[god]]``                 the gods: standard kinds (ledger, patron, sleeper) and their settings
``[actions.<verb>]``        world-specific villager actions (``tend``)
``[physics]``               overrides of world.toml's physics for games of this world
``[panel]``, ``[scene]``    what the player's truth panel and the pictures show

A step is a table: ``let`` (names, evaluated first), ``when`` (a condition; ``else`` runs a
step instead when it fails), ``for`` (``"place in blight"``; the rest of the step runs per
item), ``set`` (targets to values, in order), ``delete``, ``push`` (append to a list),
``event`` (an omen queued for the next dawn), ``emit`` (a signal now), and ``do`` (sub-steps,
in order). Expressions are described in ``expr.py``. See ``WORLDS.md`` for the whole schema.
"""

from __future__ import annotations

import copy
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .expr import RuleError, Scope, parse

if TYPE_CHECKING:
    from ..world import World

__all__ = ["Chapter", "Param", "Power", "RuleError", "WorldRules", "load_rules", "rules_for"]

PARAM_KINDS = {"to": "person", "who": "person", "at": "place", "text": "text", "god": "god", "days": "days"}
AWE = {"start": 3.0, "cap": 12.0, "dawn": 1.0, "prayer": 1.0, "prayers_max": 3, "drama": 0.5, "drama_max": 2.0}
# Names the kernel keeps in the hidden state for itself: a world's own state may not use them.
RESERVED = {
    "clock", "today", "events", "fired_today", "weather", "weather_kind", "overgod", "ledger", "ledger_pinned",
    "grace", "god_human", "host_last", "prayers", "prayers_overgod", "taken", "counters",
}  # fmt: skip
STEP_KEYS = {"let", "when", "else", "for", "set", "delete", "push", "event", "emit", "do"}
VILLAGER_FIELDS = ("health", "loc", "home", "items", "confined", "ties", "reserve", "skills", "knows")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # person | place | text | god | days


@dataclass(frozen=True)
class Power:
    id: str
    tier: int
    cost: float
    params: tuple[Param, ...]
    apply: Callable[[World, dict], str]


@dataclass(frozen=True)
class Chapter:
    id: str
    check: Callable[[World], bool]
    reward: float
    unlocks: int | None


class _Field:
    """One field of every villager, read and written by id: ``health[who]``, ``items[who].rope``."""

    def __init__(self, world: World, name: str) -> None:
        self.world, self.field = world, name

    def read(self, who: Any) -> Any:
        a = self.world.agents.get(who)
        return getattr(a, self.field) if a is not None else 0

    def write(self, who: Any, value: Any) -> None:
        setattr(self.world.agents[who], self.field, value)


def _check_steps(steps: Any, where: str) -> None:
    """Parse every expression in a list of steps now, so a broken world fails when it loads, not mid-game."""
    for i, step in enumerate(steps if isinstance(steps, list) else [steps]):
        if not isinstance(step, dict):
            raise RuleError(f"{where}[{i}] is not a step")
        unknown = set(step) - STEP_KEYS - {"need", "requires"}
        if unknown:
            raise RuleError(f"{where}[{i}] has unknown keys: {sorted(unknown)}")
        for key in ("when", "requires"):
            if key in step:
                parse(str(step[key]))
        for key in ("let", "set", "push"):
            for target, src in (step.get(key) or {}).items():
                parse(target)
                parse(str(src))
        for target in step.get("delete") or []:
            parse(target)
        if "for" in step:
            names, sep, iterable = str(step["for"]).partition(" in ")
            if not sep:
                raise RuleError(f"{where}[{i}].for must read 'name in expression'")
            parse(names)
            parse(iterable)
        for key in ("event", "emit"):
            for src in (step.get(key) or {}).values():
                parse(str(src))
        if "else" in step:
            _check_steps(step["else"], f"{where}[{i}].else")
        if "do" in step:
            _check_steps(step["do"], f"{where}[{i}].do")


class WorldRules:
    """One world's rules, read from its rules.toml and run against a World."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.constants: dict[str, Any] = spec.get("constants", {})
        self.effects: dict[str, dict] = spec.get("effects", {})
        self.awe = {**AWE, **spec.get("awe", {})}
        self.gods: list[dict[str, Any]] = spec.get("god", [])
        self.actions: dict[str, dict] = spec.get("actions", {})
        self.physics: dict[str, Any] = spec.get("physics", {})
        clash = RESERVED & set(spec.get("state", {}))
        if clash:
            raise RuleError(f"[state] uses names the kernel keeps for itself: {sorted(clash)}; rename them")
        for hook in ("night", "dawn", "after_gods", "watch"):
            _check_steps(spec.get(hook, []), hook)
        for name, eff in self.effects.items():
            _check_steps(eff, f"effects.{name}")
        for src in [*spec.get("describe", []), spec.get("refill", 1.0)]:
            parse(str(src))
        self._power_specs = spec.get("power", [])
        self._chapter_specs = spec.get("chapter", [])
        for p in self._power_specs:
            _check_steps(p.get("steps", []), f"power.{p.get('id')}")
            if "done" in p:
                parse(str(p["done"]))
        for c in self._chapter_specs:
            parse(str(c["when"]))

    # ------------------------------------------------------------------ evaluation

    def scope(self, world: World, local: dict[str, Any] | None = None, *, prev: dict | None = None, source: str = "world") -> Scope:
        """A scope over this world: its state, its villagers, its constants and the rule functions."""
        from .. import overgod
        from ..act import goods
        from ..lang import fill

        fields = {name: _Field(world, name) for name in VILLAGER_FIELDS}

        def resolve(name: str) -> Any:
            if name == ":state":
                return world.hidden
            if name == ":source":
                return source
            if name in self.constants:
                return self.constants[name]
            if name in fields:
                return fields[name]
            special = {
                "day": lambda: world.day,
                "wave": lambda: world.wave,
                "places": lambda: list(world.places),
                "villagers": lambda: list(world.agents),
                "state": lambda: world.hidden,
                "prev": lambda: prev if prev is not None else world.hidden,
                "overgod": lambda: overgod.state(world),
            }
            if name in special:
                return special[name]()
            return world.hidden.get(name, 0)

        def say(key: str, **slots: Any) -> Any:
            node: Any = world.story
            for part in str(key).split("."):
                node = node[part] if isinstance(node, dict) else node[int(part)]
            return fill(node, **{**world.t.world_slots, **slots}) if isinstance(node, str) else node

        def resolve_person(raw: Any) -> str | None:
            a = world.resolve_person(str(raw or ""))
            return a.id if a else None

        functions: dict[str, Callable[..., Any]] = {
            "min": min, "max": max, "abs": abs, "round": round, "int": int, "float": float, "str": str, "len": len,
            "list": list, "sorted": sorted, "sum": sum, "bool": bool, "any": any, "all": all, "set": set,
            "clamp": lambda x, lo=0.0, hi=1.0: max(lo, min(hi, round(x, 4))),
            "rand": lambda: world.rng.random(),
            "chance": lambda p: world.rng.random() < p,
            "pick": lambda items: world.rng.choice(list(items)),
            "bucket": lambda x, *cuts: next((i for i, c in enumerate(cuts) if x < c), len(cuts)),
            "has": lambda name: name in world.hidden,
            "get": lambda d, k, default=0: d.get(k, default) if isinstance(d, dict) else default,
            "present": lambda place: [a.id for a in world.present(place)],
            "here": lambda who: world.agents[who].loc or world.agents[who].home,
            "name": lambda x: world.name(x),
            "short": lambda who: world.agents[who].short,
            "place_name": lambda p: world.place_name(p),
            "join": lambda sep, items: str(sep).join(str(i) for i in items),
            "say": say,
            "t": lambda key, **slots: world.t(key, **slots),
            "fill": lambda template, **slots: fill(template, **slots),
            "pct": lambda x: f"{round(100 * float(x))}%",
            "resolve_place": lambda raw: world.resolve_place(str(raw)),
            "resolve_person": resolve_person,
            "goods": lambda raw: goods(world, raw),
        }  # fmt: skip
        return Scope(resolve, functions, local)

    def run(self, world: World, hook: str) -> None:
        """Run a hook's steps (night, dawn, after_gods, watch), with ``prev`` the state as the hook began."""
        steps = self.spec.get(hook, [])
        if steps:
            scope = self.scope(world, prev=copy.deepcopy(world.hidden))
            for step in steps:
                self.step(world, scope, step)

    def step(self, world: World, scope: Scope, step: dict) -> bool:
        """Run one step; returns whether its condition held (always True without one)."""
        if "for" in step:
            names, _, iterable = str(step["for"]).partition(" in ")
            body = {k: v for k, v in step.items() if k != "for"}
            for item in list(scope.eval(iterable)):
                sub = scope.child()
                sub.bind(names, item)
                self.step(world, sub, body)
                for k in sub.vars:  # lists pushed to inside a loop stay pushed
                    if k in scope.vars and isinstance(scope.vars[k], list):
                        scope.vars[k] = sub.vars[k]
            return True
        for name, src in (step.get("let") or {}).items():
            scope.vars[name] = scope.eval(src)
        if "when" in step and not scope.eval(step["when"]):
            other = step.get("else")
            if other:
                for s in other if isinstance(other, list) else [other]:
                    self.step(world, scope, s)
            return False
        for target, src in (step.get("set") or {}).items():
            scope.assign(target, scope.eval(src))
        for target in step.get("delete") or []:
            scope.delete(target)
        for name, src in (step.get("push") or {}).items():
            value = scope.eval(src)
            if name in scope.vars:
                scope.vars[name] = [*scope.vars[name], value]
            else:
                world.hidden.setdefault(name, []).append(value)
        if step.get("event"):
            ev = step["event"]
            world.hidden.setdefault("events", []).append(
                (scope.eval(ev["place"]), float(scope.eval(ev.get("strength", 2.8))), scope.eval(ev["text"]))
            )
        if step.get("emit"):
            em = step["emit"]
            audience = scope.eval(em["audience"]) if "audience" in em else None
            world.add_signal(
                str(scope.eval(em.get("kind", "'omen'"))),
                scope.eval(em["text"]),
                scope.eval(em["place"]) if "place" in em else None,
                str(scope.eval(em["source"])) if "source" in em else scope.resolve(":source"),
                strength=float(scope.eval(em.get("strength", 2.6))),
                audience=list(audience) if audience is not None else None,
            )
        for sub in step.get("do") or []:
            self.step(world, scope, sub)
        return True

    # ------------------------------------------------------------------ the kernel's questions

    def init_state(self, world: World) -> None:
        for key, value in self.spec.get("state", {}).items():
            world.hidden.setdefault(key, copy.deepcopy(value))

    def describe(self, world: World) -> str:
        scope = self.scope(world)
        lines = (str(scope.eval(src)) for src in self.spec.get("describe", []))
        return "\n".join(line for line in lines if line)

    def refill(self, world: World) -> float:
        return float(self.scope(world).eval(self.spec.get("refill", 1.0)))

    def travel(self, world: World) -> float:
        """How many parts of the day one road takes now (``travel``; 1 if the world says nothing)."""
        return float(self.scope(world).eval(self.spec.get("travel", 1)))

    def summary(self, world: World) -> dict[str, Any]:
        return {k: world.hidden.get(k, 0) for k in self.spec.get("summary", [])}

    def effect(self, world: World, e: dict, *, present: list[str], site: str) -> bool | None:
        """Apply one of the world's own effects. True: applied; False: its condition refused it; None: not one of this world's."""
        spec = self.effects.get(str(e.get("type", "")))
        if spec is None:
            return None
        for name in spec.get("need", []):
            if name not in e:
                raise KeyError(name)
        scope = self.scope(world, {"arg": e, "present": list(present), "site": site})
        for name, src in (spec.get("let") or {}).items():
            scope.vars[name] = scope.eval(src)
        if "requires" in spec and not scope.eval(spec["requires"]):
            return False
        self.step(world, scope, {k: v for k, v in spec.items() if k not in ("need", "let", "requires")})
        return True

    def powers(self, builtins: dict[str, Callable[[World, dict], str]]) -> dict[str, Power]:
        """The One Above's powers in this world: standard blocks by ``use``, or the world's own steps."""
        out: dict[str, Power] = {}
        for p in self._power_specs:
            params = tuple(Param(name, PARAM_KINDS.get(name, "text")) for name in p.get("params", []))
            if p.get("use"):
                apply = builtins[p["use"]]
            else:
                apply = self._steps_power(p)
            out[p["id"]] = Power(p["id"], int(p["tier"]), float(p["cost"]), params, apply)
        return out

    def _steps_power(self, p: dict) -> Callable[[World, dict], str]:
        def apply(world: World, x: dict) -> str:
            scope = self.scope(world, {**x, "arg": x}, source="overgod")
            for step in p.get("steps", []):
                self.step(world, scope, step)
            return str(scope.eval(p.get("done", "''")))

        return apply

    def chapters(self) -> tuple[Chapter, ...]:
        def check(src: str) -> Callable[[World], bool]:
            return lambda world: bool(self.scope(world).eval(src))

        return tuple(Chapter(c["id"], check(str(c["when"])), float(c["reward"]), c.get("unlocks")) for c in self._chapter_specs)

    def panel(self, world: World) -> dict[str, Any]:
        """The player's truth panel: facts (label, text, tone) and bars (label, value 0..1, text, tone)."""
        spec = self.spec.get("panel", {})
        scope = self.scope(world)
        out: dict[str, list] = {"facts": [], "bars": []}
        for kind, key in (("fact", "facts"), ("bar", "bars")):
            for item in spec.get(kind, []):
                for sub in self._each(scope, item):
                    if "when" in item and not sub.eval(item["when"]):
                        continue
                    row = {f: sub.eval(item[f]) for f in ("label", "text", "value", "tone") if f in item}
                    out[key].append(row)
        return out

    def scene(self, world: World) -> dict[str, Any]:
        """What the pictures need: ``water`` and ``glow`` per place (0..1), and the world's ``marks``."""
        spec = self.spec.get("scene", {})
        scope = self.scope(world)
        return {k: scope.eval(spec[k]) if k in spec else {} for k in ("water", "glow", "marks")}

    def _each(self, scope: Scope, item: dict):
        if "for" not in item:
            yield scope
            return
        names, _, iterable = str(item["for"]).partition(" in ")
        for value in list(scope.eval(iterable)):
            sub = scope.child()
            sub.bind(names, value)
            yield sub

    def god(self, gid: str) -> dict[str, Any]:
        return next((g for g in self.gods if g.get("id") == gid), {})


def load_rules(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text("utf-8")) if path.exists() else {}


def rules_for(world: World) -> WorldRules:
    """The world's rules, made once per world."""
    made = getattr(world, "_rules", None)
    if made is None:
        made = WorldRules(world.rules_spec)
        world._rules = made
    return made
