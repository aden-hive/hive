"""World state: places, villagers, signals and undertakings, persisted per game.

A game lives in its own directory: a frozen copy of the world template, ``state.json``
(everything the physics needs between ticks), each villager's ``memory.md``, and an
append-only ``log.jsonl`` of every signal, stirring and outcome.
"""

from __future__ import annotations

import copy
import json
import operator
import random
import re
import shutil
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .lang import Phrases
from .lexicon import compile_lexicon, tags_for

STORIES = Path(__file__).resolve().parent / "stories"
_SLUG = re.compile(r"[a-z0-9_-]+")


def story_dir(story: str = "ashmere", lang: str = "en") -> Path:
    """A story pack in one language: world.toml, story.toml, the people and the truth."""
    path = STORIES / story / lang
    if not (_SLUG.fullmatch(story) and _SLUG.fullmatch(lang) and (path / "world.toml").exists()):
        raise FileNotFoundError(f"no story {story!r} in language {lang!r} under {STORIES}")
    return path


def story_art(story: str) -> dict[str, Any]:
    """How a story's people and places are drawn: the same in every language (empty if the story gives none)."""
    path = STORIES / story / "art.toml"
    return tomllib.loads(path.read_text("utf-8")) if _SLUG.fullmatch(story) and path.exists() else {}


def art_file(story: str, name: str) -> Path | None:
    """A painted picture from a story's art/ folder, never anything outside it."""
    if not _SLUG.fullmatch(story):
        return None
    root = (STORIES / story / "art").resolve()
    path = (root / name).resolve()
    return path if path.is_file() and root in path.parents else None


def stories() -> list[dict[str, Any]]:
    """Every story pack, each with the languages it is written in."""
    out = []
    for sdir in sorted(p for p in STORIES.iterdir() if p.is_dir()):
        langs = {}
        for ldir in sorted(p for p in sdir.iterdir() if (p / "story.toml").exists()):
            head = tomllib.loads((ldir / "story.toml").read_text("utf-8")).get("story", {})
            langs[ldir.name] = {"title": head.get("title", sdir.name), "blurb": head.get("blurb", "")}
        if langs:
            out.append({"id": sdir.name, "langs": langs})
    return out


TEMPLATE = story_dir()
WAVES = ("dawn", "morning", "midday", "afternoon", "dusk", "night")
WAVE_LEN = 1 / len(WAVES)
MEMORY_LIMIT = 1400

_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne}


@dataclass
class Signal:
    """Something perceivable: a word said, a notice, an omen, a painting, a rumour."""

    id: str
    kind: str
    text: str
    loc: str | None  # where it can be perceived; None = only in its audience's heads
    tags: list[str]
    strength: float
    half_life: float  # days
    born: float  # day + wave fraction
    source: str  # villager id, or "world"
    cause: str | None = None  # activation that emitted it (None: the world)
    to: str | None = None  # addressed to
    audience: list[str] | None = None  # private to these villagers
    hops: int = 0
    origin: str | None = None  # first signal of a rumour chain
    project: str | None = None
    diffused: bool = False

    def level(self, now: float) -> float:
        return self.strength * 0.5 ** (max(0.0, now - self.born) / self.half_life)


@dataclass
class Agent:
    id: str
    name: str
    short: str
    role: str
    public: str
    home: str
    loc: str | None
    profession: str
    theta: float
    aliases: list[str]
    interests: dict[str, float]
    base: dict[str, float]
    items: dict[str, int]
    ties: dict[str, float]
    knows: list[str]
    health: int = 0  # 0 well, 1 coughing, 2 fevered
    skills: dict[str, int] = field(default_factory=dict)  # the character sheet, out of 100
    reserve: float = 1.0
    acts_today: int = 0
    last_wave: int = -9
    travel: dict | None = None
    confined: int = 0
    attended: dict[str, int] = field(default_factory=dict)
    heard: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    recent: list[str] = field(default_factory=list)
    mood: str = ""
    total_acts: int = 0


@dataclass
class Project:
    """A common undertaking: posted at a place, attempted at its site and hour with whoever comes."""

    id: str
    title: str
    goal: str
    needs: str
    quorum: int  # 0: none (from the seventh run, every undertaking is attempted at its hour)
    place: str
    proposer: str
    born: float
    signal: str
    supporters: dict[str, str] = field(default_factory=dict)
    opposers: dict[str, str] = field(default_factory=dict)
    status: str = "open"  # open | due | done | abandoned
    quorum_act: str | None = None
    result: dict | None = None
    site: str | None = None  # where the work is done; None means where it was posted
    when: int = 0  # the part of the day it is attempted at, as an index into WAVES
    due_day: int | None = None  # set when it is due; None (older runs) means the next dawn


def _tuplify(state: Any) -> Any:
    return tuple(_tuplify(x) for x in state) if isinstance(state, list) else state


class World:
    def __init__(self, run_dir: Path) -> None:
        self.dir = run_dir
        wdir = run_dir / "world"
        self.cfg = tomllib.loads((wdir / "world.toml").read_text("utf-8"))
        self.truth = (wdir / "truth.md").read_text("utf-8")
        self.rules = (wdir / "rules.md").read_text("utf-8")
        # Only runs made after the god arrived have these.
        self.god_prompt = (wdir / "god.md").read_text("utf-8") if (wdir / "god.md").exists() else ""
        self.god_rules = (wdir / "god_rules.md").read_text("utf-8") if (wdir / "god_rules.md").exists() else ""
        self.outer_prompt = (wdir / "outer_god.md").read_text("utf-8") if (wdir / "outer_god.md").exists() else ""
        self.ullr_prompt = (wdir / "ullr.md").read_text("utf-8") if (wdir / "ullr.md").exists() else ""
        # What even the vale's god cannot see; only fate and the chronicler read it.
        self.truth_deep = (wdir / "truth_deep.md").read_text("utf-8") if (wdir / "truth_deep.md").exists() else ""
        self.params: dict[str, Any] = self.cfg["physics"]
        # The story's own words and lists. Runs made before story packs were all Ashmere, in English.
        story_file = wdir / "story.toml"
        self.story: dict[str, Any] = tomllib.loads((story_file if story_file.exists() else TEMPLATE / "story.toml").read_text("utf-8"))
        self.lang: str = self.story.get("story", {}).get("lang", "en")
        self.t = Phrases(self.lang)
        self.lexicon = compile_lexicon(self.story.get("lexicon", {}))
        self.places: dict[str, dict] = {p["id"]: p for p in self.cfg["place"]}

        state = json.loads((run_dir / "state.json").read_text("utf-8"))
        self.day: int = state["day"]
        self.wave: int = state["wave"]
        self.hidden: dict[str, Any] = state["hidden"]
        self.agents = {k: Agent(**v) for k, v in state["agents"].items()}
        self.signals = {k: Signal(**v) for k, v in state["signals"].items()}
        self.projects = {k: Project(**v) for k, v in state["projects"].items()}
        self.counters: dict[str, int] = state["counters"]
        self.omens: dict[str, int] = state["omens"]
        self.deck_used: list[int] = state["deck_used"]
        self.totals: dict[str, float] = state.get("totals", {})
        self.rng = random.Random()
        self.rng.setstate(_tuplify(state["rng"]))
        self.personas = {aid: (wdir / "agents" / aid / "persona.md").read_text("utf-8") for aid in self.agents}
        self.today: dict[str, Any] = {}
        self.attempts: list[dict] = []  # tried this wave; settled before the next
        self._log = (run_dir / "log.jsonl").open("a", encoding="utf-8")

    # ------------------------------------------------------------------ setup

    @classmethod
    def create(cls, run_dir: Path, *, template: Path = TEMPLATE, seed: int = 7, overrides: dict | None = None) -> World:
        if run_dir.exists():
            raise FileExistsError(f"run {run_dir.name!r} already exists; pick another name or delete {run_dir}")
        shutil.copytree(template, run_dir / "world")
        cfg = tomllib.loads((run_dir / "world" / "world.toml").read_text("utf-8"))
        params = {**cfg["physics"], **(overrides or {})}
        if overrides:
            # Freeze the overrides into the run's own copy of the physics.
            _patch_physics(run_dir / "world" / "world.toml", overrides)

        rng = random.Random(seed)
        agents = {}
        for adir in sorted((run_dir / "world" / "agents").iterdir()):
            sheet = tomllib.loads((adir / "sheet.toml").read_text("utf-8"))
            aid = adir.name
            interests = {k: float(v) for k, v in sheet.get("interests", {}).items()}
            agents[aid] = Agent(
                id=aid,
                name=sheet["name"],
                short=sheet["short"],
                role=sheet["role"],
                public=sheet["public"],
                home=sheet["home"],
                loc=sheet.get("start", sheet["home"]),
                profession=sheet["profession"],
                theta=float(sheet["theta"]),
                aliases=[a.lower() for a in sheet.get("aliases", [])],
                interests=dict(interests),
                base=dict(interests),
                items={k: int(v) for k, v in sheet.get("items", {}).items()},
                ties={k: float(v) for k, v in sheet.get("ties", {}).items()},
                knows=list(sheet.get("knows", [])),
                skills={k: int(v) for k, v in sheet.get("skills", {}).items()},
                health=int(sheet.get("health", 0)),
                reserve=round(float(params["start_reserve"]) + rng.uniform(-0.4, 0.4), 3),
            )
            mem_dir = run_dir / "agents" / aid
            (mem_dir / "history").mkdir(parents=True)
            shutil.copy(adir / "memory.md", mem_dir / "memory.md")
            shutil.copy(adir / "memory.md", mem_dir / "history" / "day_00.md")

        hidden = copy.deepcopy(cfg["state"])
        hidden.setdefault("relief", {})
        hidden["sick_bracket"] = {}
        hidden["events"] = []
        hidden["flags"] = {}
        hidden["weather"] = ""
        state = {
            "day": 0,
            "wave": 0,
            "hidden": hidden,
            "agents": {k: asdict(v) for k, v in agents.items()},
            "signals": {},
            "projects": {},
            "counters": {"s": 0, "a": 0, "p": 0},
            "omens": {},
            "deck_used": [],
            "totals": {"activations": 0, "llm_calls": 0, "tired": 0, "injected": 0.0},
            "rng": rng.getstate(),
        }
        (run_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
        world = cls(run_dir)
        world.log("created", seed=seed, params=params)
        return world

    def save(self) -> None:
        state = {
            "day": self.day,
            "wave": self.wave,
            "hidden": self.hidden,
            "agents": {k: asdict(v) for k, v in self.agents.items()},
            "signals": {k: asdict(v) for k, v in self.signals.items()},
            "projects": {k: asdict(v) for k, v in self.projects.items()},
            "counters": self.counters,
            "omens": self.omens,
            "deck_used": self.deck_used,
            "totals": self.totals,
            "rng": self.rng.getstate(),
        }
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.dir / "state.json")
        self._log.flush()

    def flush(self) -> None:
        self._log.flush()

    def close(self) -> None:
        self._log.close()

    # ------------------------------------------------------------------ basics

    @property
    def now(self) -> float:
        return self.day + self.wave * WAVE_LEN

    def new_id(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}{self.counters[prefix]}"

    def log(self, event: str, /, **data: Any) -> None:
        record = {"ev": event, "day": self.day, "wave": self.wave, **data}
        self._log.write(json.dumps(record, ensure_ascii=False) + "\n")

    def kind_defaults(self, kind: str) -> tuple[float, float]:
        strength, half_life = self.params["kinds"].get(kind, (1.0, 1.0))
        return float(strength), float(half_life)

    def add_signal(
        self,
        kind: str,
        text: str,
        loc: str | None,
        source: str,
        *,
        tags: list[str] | None = None,
        cause: str | None = None,
        to: str | None = None,
        audience: list[str] | None = None,
        strength: float | None = None,
        half_life: float | None = None,
        born: float | None = None,
        hops: int = 0,
        origin: str | None = None,
        project: str | None = None,
    ) -> Signal:
        default_strength, default_half_life = self.kind_defaults("directed" if kind == "speech" and to else kind)
        sig = Signal(
            id=self.new_id("s"),
            kind=kind,
            text=text,
            loc=loc,
            tags=tags if tags is not None else self.tags(text),
            strength=strength if strength is not None else default_strength,
            half_life=half_life if half_life is not None else default_half_life,
            born=born if born is not None else self.now,
            source=source,
            cause=cause,
            to=to,
            audience=audience,
            hops=hops,
            origin=origin,
            project=project,
        )
        self.signals[sig.id] = sig
        self.log("signal", **asdict(sig))
        return sig

    # ------------------------------------------------------------------ lookups

    def tags(self, text: str) -> list[str]:
        """The story's topics this text raises."""
        return tags_for(text, self.lexicon)

    def wave_name(self, wave: int) -> str:
        return self.t.get("time.waves")[wave]

    def present(self, loc: str | None) -> list[Agent]:
        return [a for a in self.agents.values() if loc is not None and a.loc == loc]

    def place_name(self, loc: str | None) -> str:
        return self.places[loc]["name"] if loc in self.places else self.t("names.the_road")

    def name(self, aid: str | None) -> str:
        if aid in self.agents:
            return self.agents[aid].name
        names = self.story.get("gods", {}).get("names") or {
            "world": "the vale",
            "god": "God",
            "outer": "pleiades",
            "ullr": "Ullr",
            "overgod": "the One Above",
        }
        return names.get(aid or "", self.t("names.someone"))

    def resolve_person(self, text: str, among: list[Agent] | None = None) -> Agent | None:
        key = _norm(text)
        pool = among if among is not None else list(self.agents.values())
        for a in pool:
            if key in (a.id, _norm(a.short), _norm(a.name)) or key in a.aliases:
                return a
        for a in pool:  # first names, "old bram", "ser aldric thorne", ...
            names = {_norm(a.short), *_norm(a.name).split(), *a.aliases}
            if any(word in names for word in key.split()):
                return a
        if key and not key.isascii():  # a script without spaces: a name inside the words, or the words inside a name
            for a in pool:
                if any(n and (n in key or key in n) for n in (_norm(a.short), _norm(a.name), *a.aliases)):
                    return a
        return None

    def resolve_place(self, text: str) -> str | None:
        key = _norm(text).replace(" ", "_")
        if key in self.places:
            return key
        plain = _norm(text)
        for pid, place in self.places.items():
            name = _norm(place["name"])
            if plain and (plain in name or name in plain or plain.replace(" ", "_") == pid):
                return pid
        for word, pid in self.story.get("place_aliases", {}).items():
            if word in plain.replace(" ", "_"):
                return pid
        return None

    def resolve_feature(self, loc: str, text: str) -> dict | None:
        key = _norm(text)
        feats = self.places[loc].get("feature", [])
        for f in feats:
            if key in (f["id"], _norm(f["id"]), _norm(f["name"])):
                return f
        for f in feats:
            if key and (key in _norm(f["name"]) or _norm(f["id"]).replace("_", " ") in key):
                return f
        return None

    # ------------------------------------------------------------------ hidden state

    def value(self, var: str) -> float:
        if var == "day":
            return self.day
        node: Any = self.hidden
        for part in var.split("."):
            node = node.get(part, 0) if isinstance(node, dict) else 0
        return float(node or 0)

    def check(self, conditions: list) -> bool:
        return all(_OPS[op](self.value(var), val) for var, op, val in conditions)

    # ------------------------------------------------------------------ memory

    def memory_path(self, aid: str) -> Path:
        return self.dir / "agents" / aid / "memory.md"

    def read_memory(self, aid: str) -> str:
        return self.memory_path(aid).read_text("utf-8").strip()

    def write_memory(self, aid: str, text: str) -> None:
        self.memory_path(aid).write_text(text.strip()[:MEMORY_LIMIT] + "\n", "utf-8")

    def snapshot_memories(self) -> None:
        for aid in self.agents:
            shutil.copy(self.memory_path(aid), self.dir / "agents" / aid / "history" / f"day_{self.day:02d}.md")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9_一-鿿 ]+", "", str(text).lower()).strip()


def _patch_physics(toml_path: Path, overrides: dict) -> None:
    text = toml_path.read_text("utf-8")
    for key, val in overrides.items():
        text, n = re.subn(rf"(?m)^{re.escape(key)}\s*=\s*[^#\n]*", f"{key} = {val}", text, count=1)
        if not n:
            raise KeyError(f"unknown physics parameter {key!r}")
    toml_path.write_text(text, "utf-8")
