"""Probes: fixed questions put to a queen with her soul as it stands and as a proposal would make it.

A reflection that drifts her (flatter, more generic, more eager to please) shows in how she answers the
same questions before and after. ``probes.json`` in her soul folder lists them, each with an optional
anchor, a reply of hers that sounds most like her::

    [{"q": "[Ann(42)]: are you in a good mood today?", "anchor": "..."}]

:func:`probe` answers each question twice, on her own model, with her identity and the soul before and
after the proposal's changes, and stores the answers in the proposal for the dashboard to show side by side.
A person judges them: model judges recognise a character far less reliably than people do.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from framework.agents.queen import soul as soul_store
from framework.agents.queen.soul import Proposal, Soul
from framework.config import SoulConfig, get_aux_max_tokens

logger = logging.getLogger(__name__)

PROBES_FILE = "probes.json"
_CONCURRENCY = 4

_probing: set[str] = set()


def load_probes(queen_id: str) -> list[dict[str, str]]:
    data = soul_store._read_json(soul_store.soul_dir(queen_id) / PROBES_FILE)
    out = []
    for entry in data if isinstance(data, list) else []:
        if isinstance(entry, dict) and str(entry.get("q") or "").strip():
            out.append({"q": str(entry["q"]).strip(), "anchor": str(entry.get("anchor") or "").strip()})
    return out


def is_probing(queen_id: str) -> bool:
    return queen_id in _probing


def _system(identity: str, cfg: SoulConfig, soul: Soul) -> str:
    rendered = soul_store.render(cfg, soul)
    return f"{identity}\n\n{rendered}" if rendered else identity


_SPEAKER_ID_RE = re.compile(r"\[[^\[\]\n]*?\((\d{5,})\)\]:")
_RELATED_MEMORIES = 3


def related_memories(queen_id: str, question: str) -> str:
    """Her memory files that mention the speaker's id, as recall would bring them: who that person is to her.

    Live, recall puts such files beside the message; without them a probe meets people as strangers.
    """
    from framework.agents.queen.queen_memory_v2 import global_memory_dir, queen_memory_dir

    ids = _SPEAKER_ID_RE.findall(question)
    if not ids:
        return ""
    found = []
    for folder in (queen_memory_dir(queen_id), global_memory_dir()):
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(i in text for i in ids):
                found.append(f"### {path.name}\n{text.strip()}")
            if len(found) >= _RELATED_MEMORIES:
                break
        if len(found) >= _RELATED_MEMORIES:
            break
    return "<recalled_memories>\n" + "\n\n".join(found) + "\n</recalled_memories>" if found else ""


async def probe(queen_id: str, cfg: SoulConfig, llm: Any, proposal: Proposal) -> list[dict[str, str]]:
    """Answer every probe with the soul before and after ``proposal``; stored in the proposal and returned."""
    from framework.agents.queen.soul_reflection import _identity

    probes = load_probes(queen_id)
    if not probes:
        return []
    _probing.add(queen_id)
    try:
        _, identity = _identity(queen_id)
        current = soul_store.load(queen_id)
        after = Soul(version=current.version + 1, sections=soul_store.apply_edits(current, proposal.edits))
        systems = {"before": _system(identity, cfg, current), "after": _system(identity, cfg, after)}
        gate = asyncio.Semaphore(_CONCURRENCY)

        async def ask(system: str, question: str) -> str:
            async with gate:
                try:
                    resp = await llm.acomplete(messages=[{"role": "user", "content": question}], system=system, max_tokens=get_aux_max_tokens())
                except Exception as e:
                    logger.warning("soul: probe failed for %s", queen_id, exc_info=True)
                    return f"(failed: {e})"
                return (resp.content or "").strip()

        def with_memories(system: str, question: str) -> str:
            memories = related_memories(queen_id, question)
            return f"{system}\n\n{memories}" if memories else system

        answers = await asyncio.gather(*(ask(with_memories(systems[side], p["q"]), p["q"]) for p in probes for side in ("before", "after")))
        results = [{**p, "before": answers[2 * i], "after": answers[2 * i + 1]} for i, p in enumerate(probes)]
        fresh = soul_store.load_proposal(queen_id, proposal.id) or proposal
        fresh.probes = results
        soul_store.save_proposal(queen_id, fresh)
        logger.info("soul: probed %s's proposal %s with %d questions", queen_id, proposal.id, len(probes))
        return results
    finally:
        _probing.discard(queen_id)
