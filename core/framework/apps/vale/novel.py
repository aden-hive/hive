"""The novel: after each night, the host writes the day as a chapter of a real novel.

Not a summary. Two passes, the way a writer works: first a plan (which three to five
moments the day turns on, through whose eyes, how it ends, and the story so far for the
next chapter), then the chapter itself, in prose: scenes, dialogue taken from what was
really said, private thoughts as inner life, the dice as luck and danger. It is written
from the day's record and never invents what happened.

Chapters live in the game's ``novel/`` folder as ``day_NN.md`` with ``day_NN.json``
beside it (title, plan, the story so far). Every word is the story's language.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .host import part_record
from .llm import LLM, parse_json_object
from .world import World

RECORD_LIMIT = 30000  # characters of the day's record a chapter is written from


def folder(run_dir: Path) -> Path:
    return run_dir / "novel"


def chapters(run_dir: Path) -> list[dict[str, Any]]:
    """Every chapter written so far, in order: day, title, text, and its scenes' places and eyes for the pictures."""
    out = []
    for md in sorted(folder(run_dir).glob("day_*.md")):
        day = int(md.stem.split("_")[1])
        meta_path = md.with_suffix(".json")
        meta = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else {}
        scenes = [
            {"place": str(s.get("place") or ""), "pov": str(s.get("pov") or ""), "when": str(s.get("when") or "")}
            for s in (meta.get("plan") or {}).get("scenes") or []
            if isinstance(s, dict)
        ]
        out.append({"day": day, "title": meta.get("title", ""), "text": md.read_text("utf-8"), "scenes": scenes})
    return out


def _cast(world: World, items: list[dict]) -> str:
    """Who appears today, as the reader should picture them."""
    t = world.t
    seen: list[str] = []
    for i in items:
        for aid in [i.get("agent"), *(i.get("present") or []), *(i.get("audience") or [])]:
            if aid in world.agents and aid not in seen:
                seen.append(aid)
    return "\n".join(
        t("novel.cast_line", name=world.agents[a].name, short=world.agents[a].short, role=world.agents[a].role, public=world.agents[a].public)
        for a in seen
    )


def _previous(run_dir: Path, day: int) -> tuple[str, str]:
    """The story so far, and how the last chapter ended."""
    meta = folder(run_dir) / f"day_{day - 1:02d}.json"
    text = folder(run_dir) / f"day_{day - 1:02d}.md"
    synopsis = json.loads(meta.read_text("utf-8")).get("synopsis", "") if meta.exists() else ""
    ending = ""
    if text.exists():
        paragraphs = [p for p in text.read_text("utf-8").split("\n\n") if p.strip() and not p.startswith("#")]
        ending = paragraphs[-1].strip() if paragraphs else ""
    return synopsis, ending


class LLMNovelist:
    """Two model calls per day: the plan, then the chapter.

    ``prepare`` reads the world and must run where the world is safe to read (the game's
    loop); ``compose`` only talks to the model, so it can run in a thread while the vale moves on.
    """

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def prepare(self, world: World, run_dir: Path, day: int, items: list[dict], weather: str = "") -> dict[str, Any]:
        t = world.t
        record, _ = part_record(world, items)
        synopsis, ending = _previous(run_dir, day)
        vale = world.story.get("story", {}).get("vale", world.cfg["vale"]["name"])
        return {
            "t": t,
            "day": day,
            "system": t("novel.system", vale=vale, language=t("host.language"), truth=world.truth),
            "common": {
                "day": day,
                "weather": weather,
                "so_far": synopsis or t("novel.beginning"),
                "ending": ending or t("novel.no_ending"),
                "cast": _cast(world, items),
                "record": record[:RECORD_LIMIT],
            },
        }

    def compose(self, draft: dict[str, Any]) -> dict[str, Any]:
        t, system, common = draft["t"], draft["system"], draft["common"]
        plan = parse_json_object(
            self.llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": t("novel.plan", **common)}], temperature=0.7, max_tokens=2500
            )
        )
        chapter = self.llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": t("novel.write", plan=json.dumps(plan, ensure_ascii=False, indent=1), **common)},
            ],
            temperature=0.85,
            max_tokens=7000,
            json_mode=False,
        )
        title = str(plan.get("title") or "").strip()[:40]
        return {
            "title": title,
            "text": _tidy(chapter, t("novel.heading", n=draft["day"], title=title)),
            "plan": plan,
            "synopsis": str(plan.get("synopsis") or "")[:1200],
        }

    def write(self, world: World, run_dir: Path, day: int, items: list[dict], weather: str = "") -> dict[str, Any]:
        return self.compose(self.prepare(world, run_dir, day, items, weather))


def _tidy(text: str, heading: str) -> str:
    """The chapter as markdown under its own heading, without fences or a heading the model added."""
    text = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
    lines = text.splitlines()
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#")):
        lines.pop(0)
    return f"# {heading}\n\n" + "\n".join(lines).strip() + "\n"


def save(run_dir: Path, day: int, chapter: dict[str, Any]) -> None:
    d = folder(run_dir)
    d.mkdir(exist_ok=True)
    (d / f"day_{day:02d}.md").write_text(chapter["text"], "utf-8")
    meta = {k: chapter[k] for k in ("title", "plan", "synopsis") if k in chapter}
    (d / f"day_{day:02d}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")


def day_items(run_dir: Path, day: int) -> list[dict]:
    """What the page was shown of one day, in order: the novel is written from the same record."""
    path = run_dir / "feed.jsonl"
    if not path.exists():
        return []
    items = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    return [i for i in items if i.get("day") == day and i["type"] not in ("host", "night", "awe")]


class StubNovelist:
    """A chapter without a model, for testing the plumbing."""

    def prepare(self, world: World, run_dir: Path, day: int, items: list[dict], weather: str = "") -> dict[str, Any]:
        said = [d["text"] for i in items if i["type"] == "stir" for d in i.get("deeds") or [] if d["kind"] == "speech"]
        title = world.t("novel.stub_title", n=day)
        return {
            "day": day,
            "title": title,
            "heading": world.t("novel.heading", n=day, title=title),
            "said": said[:6],
            "quiet": world.t("novel.stub_quiet"),
        }

    def compose(self, draft: dict[str, Any]) -> dict[str, Any]:
        body = "\n\n".join(f"“{s}”" for s in draft["said"]) or draft["quiet"]
        return {"title": draft["title"], "text": f"# {draft['heading']}\n\n{body}\n", "plan": {}, "synopsis": ""}

    def write(self, world: World, run_dir: Path, day: int, items: list[dict], weather: str = "") -> dict[str, Any]:
        return self.compose(self.prepare(world, run_dir, day, items, weather))
