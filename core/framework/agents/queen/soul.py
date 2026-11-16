"""A queen's soul: a short, first-person self-description she revises once a day.

Her profile says who she is meant to be; her memory holds what she knows. The soul is what she has become:
what is on her mind, how she stands with the people around her, what she has promised, what she thinks and
why, and how she has changed. It is hers (a reflection writes it from her conversations, see
``soul_reflection``), small (each section has a character limit), and always in context: it rides her system
prompt right after her identity (:func:`prompt_for`), so it is the same self in every chat and changes there
at most once a day.

It lives in ``queens/<queen_id>/soul/``::

    soul.json            the current version: {"version", "updated_at", "sections": {key: [{"text", "date"}]}}
    history/v<n>.json    every version that has been current
    proposals/<id>.json  the changes one reflection proposed, and what became of them
    log.jsonl            one line per new version: who made it, why, which changes
    state.json           reflection bookkeeping (see ``soul_reflection``)

Configured per queen in ``configuration.json`` (``framework.config.get_soul_config``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from framework.config import HIVE_CONFIG_FILE, QUEENS_DIR, SoulConfig, get_soul_config

logger = logging.getLogger(__name__)

SOUL_FILE = "soul.json"


class SoulError(ValueError):
    """A soul that breaks its configuration (a section over its limit), or a change that no longer applies."""


@dataclass
class Item:
    text: str
    #: The day the item is about (YYYY-MM-DD).
    date: str = ""


@dataclass
class Soul:
    version: int = 0
    updated_at: str = ""
    sections: dict[str, list[Item]] = field(default_factory=dict)

    def items(self, key: str) -> list[Item]:
        return self.sections.get(key, [])

    def is_empty(self) -> bool:
        return not any(self.sections.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "sections": {k: [asdict(i) for i in v] for k, v in self.sections.items()},
        }

    @classmethod
    def from_json(cls, data: Any) -> Soul:
        data = data if isinstance(data, dict) else {}
        sections: dict[str, list[Item]] = {}
        for key, items in (data.get("sections") or {}).items():
            sections[str(key)] = [
                Item(text=str(i.get("text", "")).strip(), date=str(i.get("date", "")))
                for i in items or []
                if isinstance(i, dict) and str(i.get("text", "")).strip()
            ]
        version = data.get("version")
        return cls(version=version if isinstance(version, int) else 0, updated_at=str(data.get("updated_at", "")), sections=sections)


@dataclass
class Edit:
    """One change a reflection proposes."""

    op: Literal["add", "update", "remove"]
    section: str
    #: add/update: the item's new text.
    text: str = ""
    #: update/remove: the item's text when the change was proposed (how it is found again).
    old: str = ""
    #: add/update: the day the item is about.
    date: str = ""
    #: What it rests on: [{"quote": verbatim words, "where": the chat or memory they come from}].
    evidence: list[dict[str, str]] = field(default_factory=list)
    reason: str = ""
    #: remove: dropped because it grew older than its section keeps things, not by her.
    expired: bool = False


@dataclass
class Proposal:
    id: str
    created_at: str
    base_version: int
    edits: list[Edit]
    summary: str = ""
    #: "pending", "applied" (some or all edits) or "dismissed".
    status: str = "pending"
    #: Indexes of the edits that were applied.
    applied: list[int] = field(default_factory=list)
    #: The chats (and memory files) it read.
    sources: list[str] = field(default_factory=list)
    bootstrap: bool = False
    #: Fixed questions answered before and after these changes (``soul_probes``): [{"q", "anchor", "before", "after"}].
    probes: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Proposal:
        edits = [Edit(**{k: v for k, v in e.items() if k in Edit.__dataclass_fields__}) for e in data.get("edits") or []]
        fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "edits"}
        return cls(edits=edits, **fields)


# --- Storage -------------------------------------------------------------------------------------


def soul_dir(queen_id: str) -> Path:
    return QUEENS_DIR / queen_id / "soul"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load(queen_id: str) -> Soul:
    return Soul.from_json(_read_json(soul_dir(queen_id) / SOUL_FILE))


def load_version(queen_id: str, version: int) -> Soul | None:
    data = _read_json(soul_dir(queen_id) / "history" / f"v{version}.json")
    return Soul.from_json(data) if data is not None else None


def section_chars(items: list[Item]) -> int:
    return sum(len(i.text) for i in items)


def problems(cfg: SoulConfig, soul: Soul) -> list[str]:
    """What keeps ``soul`` from being saved under ``cfg``: sections over their limit."""
    out = []
    for section in cfg.sections:
        used = section_chars(soul.items(section.key))
        if used > section.limit:
            out.append(f"{section.title}: {used}/{section.limit} characters")
    return out


def save(queen_id: str, cfg: SoulConfig, sections: dict[str, list[Item]], *, author: str, note: str, edits: list[Edit] | None = None) -> Soul:
    """Make ``sections`` the queen's current soul, as a new version. Raises :class:`SoulError` when over a limit."""
    current = load(queen_id)
    soul = Soul(version=current.version + 1, updated_at=datetime.now().astimezone().isoformat(timespec="seconds"), sections=sections)
    found = problems(cfg, soul)
    if found:
        raise SoulError("; ".join(found))
    root = soul_dir(queen_id)
    _write_json(root / "history" / f"v{soul.version}.json", soul.to_json())
    _write_json(root / SOUL_FILE, soul.to_json())
    entry = {"version": soul.version, "at": soul.updated_at, "author": author, "note": note, "edits": [asdict(e) for e in edits or []]}
    with (root / "log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("soul: %s is now at version %d (%s: %s)", queen_id, soul.version, author, note)
    return soul


def history(queen_id: str) -> list[dict[str, Any]]:
    """Every version, newest first: version, when, who, why, how many changes."""
    path = soul_dir(queen_id) / "log.jsonl"
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        entries.append({k: entry.get(k) for k in ("version", "at", "author", "note")} | {"changes": len(entry.get("edits") or [])})
    return entries[::-1]


def rollback(queen_id: str, cfg: SoulConfig, version: int, *, author: str = "owner") -> Soul:
    old = load_version(queen_id, version)
    if old is None:
        raise SoulError(f"there is no version {version}")
    return save(queen_id, cfg, old.sections, author=author, note=f"back to version {version}")


# --- Proposals -----------------------------------------------------------------------------------


def save_proposal(queen_id: str, proposal: Proposal) -> None:
    _write_json(soul_dir(queen_id) / "proposals" / f"{proposal.id}.json", proposal.to_json())


def load_proposal(queen_id: str, proposal_id: str) -> Proposal | None:
    if "/" in proposal_id or "\\" in proposal_id or proposal_id.startswith("."):
        return None
    data = _read_json(soul_dir(queen_id) / "proposals" / f"{proposal_id}.json")
    return Proposal.from_json(data) if isinstance(data, dict) else None


def pending_proposal(queen_id: str) -> Proposal | None:
    """The newest proposal still waiting for a decision."""
    folder = soul_dir(queen_id) / "proposals"
    for path in sorted(folder.glob("*.json"), reverse=True) if folder.is_dir() else []:
        proposal = load_proposal(queen_id, path.stem)
        if proposal is not None and proposal.status == "pending":
            return proposal
    return None


def apply_edits(soul: Soul, edits: list[Edit]) -> dict[str, list[Item]]:
    """``soul``'s sections with ``edits`` made: removals and updates find their item by its text."""
    sections = {k: list(v) for k, v in soul.sections.items()}
    for n, edit in sorted(enumerate(edits), key=lambda e: e[1].op == "add"):
        items = sections.setdefault(edit.section, [])
        if edit.op == "add":
            items.append(Item(text=edit.text.strip(), date=edit.date))
            continue
        at = next((i for i, item in enumerate(items) if item.text == edit.old), None)
        if at is None:
            raise SoulError(f"change {n + 1} no longer applies: its item has been changed or removed since")
        if edit.op == "remove":
            del items[at]
        else:
            items[at] = Item(text=edit.text.strip(), date=edit.date or items[at].date)
    return sections


def decide(queen_id: str, cfg: SoulConfig, proposal: Proposal, accept: list[int] | None, *, author: str = "owner") -> Soul | None:
    """Apply the accepted edits of ``proposal`` (all when None, none dismisses it); the new soul, if any."""
    chosen = list(range(len(proposal.edits))) if accept is None else sorted({i for i in accept if 0 <= i < len(proposal.edits)})
    soul = None
    if chosen:
        edits = [proposal.edits[i] for i in chosen]
        what = "first draft" if proposal.bootstrap else f"reflection {proposal.id}"
        soul = save(
            queen_id,
            cfg,
            apply_edits(load(queen_id), edits),
            author=author,
            note=f"{what}: {len(edits)} of {len(proposal.edits)} changes",
            edits=edits,
        )
    proposal.status = "applied" if chosen else "dismissed"
    proposal.applied = chosen
    save_proposal(queen_id, proposal)
    return soul


# --- Her prompt ----------------------------------------------------------------------------------


def render(cfg: SoulConfig, soul: Soul) -> str:
    """The soul as it rides her prompt, or "" when it is empty."""
    if soul.is_empty():
        return ""
    lines = ["<soul>", cfg.header]
    for section in cfg.sections:
        items = soul.items(section.key)
        if not items:
            continue
        lines += ["", f"## {section.title}"]
        for item in items:
            lines.append(f"- {item.text}" + (f" ({_short_date(item.date)})" if item.date else ""))
    lines.append("</soul>")
    return "\n".join(lines)


def _short_date(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return day
    return f"{d.month}/{d.day}"


_prompt_cache: dict[str, tuple[tuple[int, int], str]] = {}


def prompt_for(queen_id: str | None) -> str:
    """Her soul for the system prompt; "" without one. Re-read only when the soul or the configuration changed."""
    if not queen_id:
        return ""
    stamp = (_mtime(soul_dir(queen_id) / SOUL_FILE), _mtime(HIVE_CONFIG_FILE))
    cached = _prompt_cache.get(queen_id)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    cfg = get_soul_config(queen_id)
    text = render(cfg, load(queen_id)) if cfg is not None else ""
    _prompt_cache[queen_id] = (stamp, text)
    return text


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
