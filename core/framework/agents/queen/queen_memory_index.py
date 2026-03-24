"""Structured index for queen episodic memory entries.

Attaches rich metadata, embedding vectors, cross-reference links, and
retrieval counts to every diary entry.  The index lives at:

    ~/.hive/queen/memories/index.json

It is a *sidecar* to the existing markdown diary files — those files are
never modified by this module.

Configuration
-------------
Set ``HIVE_EMBED_MODEL`` to an embedding model name supported by litellm
(e.g. ``text-embedding-3-small``) to enable semantic search.  When unset
the system degrades gracefully: enrichment (keywords/tags/category) still
works via the consolidation LLM, and recall_diary falls back to substring
matching.

Phases implemented
------------------
Phase 1 - Index I/O + semantic enrichment (keywords, category, tags)
Phase 2 - Embedding storage + semantic search via cosine similarity
Phase 3 - Cross-reference linking (bidirectional related[] links)
Phase 4 - Importance tracking (retrieval counts + recency decay)
Phase 5 - Memory evolution (LLM-driven neighbour metadata refinement)
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category vocabulary — fixed to prevent unbounded drift
# ---------------------------------------------------------------------------
_CATEGORIES = [
    "agent_build",
    "infrastructure",
    "user_preference",
    "communication_style",
    "diagnostic_learning",
    "milestone",
    "pipeline",
    "data_processing",
    "other",
]

# ---------------------------------------------------------------------------
# MemoryEntry dataclass
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """Rich metadata record for a single diary section (one ### HH:MM block)."""

    # Identity — "YYYY-MM-DD:HH:MM" matches the diary ### timestamp
    id: str
    date: str        # "YYYY-MM-DD"
    timestamp: str   # "HH:MM"

    # Content preview (not full prose — just enough for search result context)
    summary: str     # first 300 chars of the section's prose

    # Phase 1 — semantic enrichment
    keywords: list[str] = field(default_factory=list)
    category: str = "other"
    tags: list[str] = field(default_factory=list)

    # Phase 3 — cross-reference links
    related: list[str] = field(default_factory=list)

    # Phase 4 — importance tracking
    retrieval_count: int = 0
    last_retrieved: str | None = None   # ISO-format datetime string

    # Phase 2 — embedding vector (None when HIVE_EMBED_MODEL is unset)
    embedding: list[float] | None = None

    # Whether enrichment has been applied (used to skip re-enrichment)
    enriched: bool = False


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------

_EMPTY_INDEX: dict[str, Any] = {
    "version": 1,
    "embed_model": None,
    "embed_dim": None,
    "entries": {},
}


def _queen_memories_dir() -> Path:
    return Path.home() / ".hive" / "queen" / "memories"


def index_path() -> Path:
    return _queen_memories_dir() / "index.json"


def load_index() -> dict[str, Any]:
    """Load the index from disk.  Returns a fresh empty index on any error."""
    p = index_path()
    if not p.exists():
        return {**_EMPTY_INDEX, "entries": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "entries" not in data:
            raise ValueError("Malformed index")
        return data
    except Exception as exc:
        logger.warning("queen_memory_index: index.json unreadable (%s), starting fresh", exc)
        return {**_EMPTY_INDEX, "entries": {}}


def save_index(index: dict[str, Any]) -> None:
    """Atomically write the index to disk (tmp file → rename)."""
    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def get_entry(index: dict[str, Any], entry_id: str) -> MemoryEntry | None:
    """Deserialise one entry from the index dict, or None if missing."""
    raw = index.get("entries", {}).get(entry_id)
    if raw is None:
        return None
    try:
        return MemoryEntry(**{k: raw[k] for k in MemoryEntry.__dataclass_fields__ if k in raw})
    except Exception as exc:
        logger.warning("queen_memory_index: failed to deserialise entry %s: %s", entry_id, exc)
        return None


def put_entry(index: dict[str, Any], entry: MemoryEntry) -> None:
    """Serialise and insert/overwrite one entry in the index dict (mutates in place)."""
    index.setdefault("entries", {})[entry.id] = asdict(entry)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def get_embed_model() -> str | None:
    """Return the configured embedding model (e.g. 'openai/text-embedding-3-small').

    Reads from the ``embedding`` section of ~/.hive/configuration.json.
    Falls back to the ``HIVE_EMBED_MODEL`` env var for backward compatibility.
    """
    from framework.config import get_embed_model as _cfg_get_embed_model

    return _cfg_get_embed_model()


def embeddings_enabled() -> bool:
    return bool(get_embed_model())


def _detect_model_change(index: dict[str, Any]) -> bool:
    """Return True if the stored embed model differs from the current env var."""
    current = get_embed_model()
    stored = index.get("embed_model")
    return current != stored


def _clear_embeddings(index: dict[str, Any]) -> None:
    """Clear all stored vectors when the embedding model has changed."""
    for raw in index.get("entries", {}).values():
        raw["embedding"] = None
    index["embed_model"] = get_embed_model()
    index["embed_dim"] = None
    logger.info("queen_memory_index: embedding model changed — cleared cached vectors")


# ---------------------------------------------------------------------------
# Embedding calls (Phase 2)
# ---------------------------------------------------------------------------


def _embed_kwargs() -> dict[str, Any]:
    """Build the kwargs dict for litellm.aembedding() from configuration."""
    from framework.config import get_embed_api_base, get_embed_api_key

    kwargs: dict[str, Any] = {}
    api_key = get_embed_api_key()
    if api_key:
        kwargs["api_key"] = api_key
    api_base = get_embed_api_base()
    if api_base:
        kwargs["api_base"] = api_base
    return kwargs


async def embed_text(text: str) -> list[float] | None:
    """Embed *text* via litellm.aembedding().

    Returns None (with a WARNING log) on any failure or when no embedding
    model is configured.
    """
    model = get_embed_model()
    if not model:
        return None
    try:
        import litellm  # already a project dependency

        logger.info("queen_memory_index: embedding text (%d chars) via %s", len(text), model)
        resp = await litellm.aembedding(model=model, input=[text], **_embed_kwargs())
        vec: list[float] = resp.data[0]["embedding"]
        logger.info("queen_memory_index: embedding complete (dim=%d)", len(vec))
        return vec
    except Exception as exc:
        logger.warning("queen_memory_index: embed_text failed (%s)", exc)
        return None


async def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Embed a list of texts, returning a parallel list of vectors (or None)."""
    model = get_embed_model()
    if not model:
        return [None] * len(texts)
    try:
        import litellm

        logger.info(
            "queen_memory_index: batch embedding %d text(s) via %s", len(texts), model
        )
        resp = await litellm.aembedding(model=model, input=texts, **_embed_kwargs())
        vecs = [item["embedding"] for item in resp.data]
        logger.info(
            "queen_memory_index: batch embedding complete (dim=%d)", len(vecs[0]) if vecs else 0
        )
        return vecs
    except Exception as exc:
        logger.warning("queen_memory_index: embed_batch failed (%s), retrying individually", exc)
        # Fall back to individual calls
        results: list[list[float] | None] = []
        for t in texts:
            results.append(await embed_text(t))
        return results


# ---------------------------------------------------------------------------
# Vector math (Phase 2)
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    """Return cosine similarity in [0, 1].  Returns 0.0 on null or zero-norm inputs."""
    if not a or not b:
        return 0.0
    try:
        import numpy as np  # already a project dependency

        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        norm_a = float(np.linalg.norm(va))
        norm_b = float(np.linalg.norm(vb))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))
    except Exception:
        return 0.0


def find_knn(
    query_vec: list[float],
    index: dict[str, Any],
    k: int = 5,
    exclude_id: str | None = None,
) -> list[tuple[str, float]]:
    """Return up to *k* nearest neighbours as (entry_id, similarity) pairs, descending."""
    scores: list[tuple[str, float]] = []
    for entry_id, raw in index.get("entries", {}).items():
        if entry_id == exclude_id:
            continue
        vec = raw.get("embedding")
        if not vec:
            continue
        sim = cosine_similarity(query_vec, vec)
        scores.append((entry_id, sim))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:k]


# ---------------------------------------------------------------------------
# Semantic search (Phase 2)
# ---------------------------------------------------------------------------


async def semantic_search(
    query: str,
    index: dict[str, Any],
    *,
    k: int = 20,
    date_range: tuple[str, str] | None = None,
) -> list[tuple[str, float]]:
    """Embed *query* and return top-k (entry_id, score) pairs.

    Returns [] if embeddings are disabled or the embed call fails.
    date_range is an inclusive (YYYY-MM-DD, YYYY-MM-DD) filter applied
    before ranking.
    """
    if not embeddings_enabled():
        return []

    query_vec = await embed_text(query)
    if query_vec is None:
        return []

    candidates: list[tuple[str, float]] = []
    for entry_id, raw in index.get("entries", {}).items():
        if date_range:
            d = raw.get("date", "")
            if d < date_range[0] or d > date_range[1]:
                continue
        vec = raw.get("embedding")
        if not vec:
            continue
        sim = cosine_similarity(query_vec, vec)
        candidates.append((entry_id, sim))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[:k]


# ---------------------------------------------------------------------------
# Importance tracking (Phase 4)
# ---------------------------------------------------------------------------


def importance_score(entry: MemoryEntry, now: datetime | None = None) -> float:
    """Composite importance: log1p(count) * recency decay (half-life 30 days).

    Returns 0.0 for entries that have never been retrieved.
    """
    if entry.retrieval_count == 0:
        return 0.0
    count_score = math.log1p(entry.retrieval_count)
    if entry.last_retrieved:
        try:
            last = datetime.fromisoformat(entry.last_retrieved)
            days_since = ((now or datetime.now()) - last).total_seconds() / 86400
            decay = math.exp(-days_since / 30)
        except ValueError:
            decay = 0.0
    else:
        decay = 0.0
    return count_score * decay


def record_retrieval(
    index: dict[str, Any],
    entry_ids: list[str],
    *,
    auto_save: bool = True,
) -> None:
    """Increment retrieval_count and update last_retrieved for each entry_id."""
    now_str = datetime.now().isoformat()
    entries = index.get("entries", {})
    for eid in entry_ids:
        if eid in entries:
            entries[eid]["retrieval_count"] = entries[eid].get("retrieval_count", 0) + 1
            entries[eid]["last_retrieved"] = now_str
    if auto_save:
        try:
            save_index(index)
        except Exception as exc:
            logger.warning("queen_memory_index: failed to save index after retrieval: %s", exc)


# ---------------------------------------------------------------------------
# Hybrid re-ranking (Phase 4)
# ---------------------------------------------------------------------------


def hybrid_search(
    query: str,
    index: dict[str, Any],
    candidate_ids: list[str],
    semantic_scores: dict[str, float],
    *,
    keyword_weight: float = 0.3,
    semantic_weight: float = 0.7,
) -> list[tuple[str, float]]:
    """Re-rank candidates combining semantic cosine, keyword overlap, and importance.

    Combined score = semantic_weight * cosine
                   + keyword_weight * keyword_overlap
                   + 0.1 * normalised_importance

    keyword_overlap = |query_terms ∩ entry.keywords| / max(1, |entry.keywords|)
    normalised_importance is scaled to [0, 1] relative to the highest importance
    in the candidate set.
    """
    query_terms = set(re.findall(r"\w+", query.lower()))
    now = datetime.now()

    raw_scores: list[tuple[str, float]] = []
    imp_values: list[float] = []
    for eid in candidate_ids:
        entry = get_entry(index, eid)
        if entry is None:
            continue
        sem = semantic_scores.get(eid, 0.0)
        kw_list = [k.lower() for k in entry.keywords]
        overlap = len(query_terms & set(kw_list)) / max(1, len(kw_list))
        imp = importance_score(entry, now)
        imp_values.append(imp)
        raw_scores.append((eid, sem, overlap, imp))

    # Normalise importance to [0, 1]
    max_imp = max(imp_values) if imp_values else 1.0
    if max_imp == 0.0:
        max_imp = 1.0

    ranked: list[tuple[str, float]] = []
    for eid, sem, overlap, imp in raw_scores:
        score = (
            semantic_weight * sem
            + keyword_weight * overlap
            + 0.1 * (imp / max_imp)
        )
        ranked.append((eid, score))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Cross-reference linking (Phase 3)
# ---------------------------------------------------------------------------


def link_entry(
    index: dict[str, Any],
    entry_id: str,
    similarity_threshold: float = 0.85,
) -> list[str]:
    """Discover k-NN above threshold and add bidirectional related[] links.

    Mutates the index dict in place.  Returns the list of newly linked
    neighbour ids (may be empty).
    """
    entries = index.get("entries", {})
    raw = entries.get(entry_id)
    if not raw or not raw.get("embedding"):
        return []

    neighbours = find_knn(raw["embedding"], index, k=10, exclude_id=entry_id)
    linked: list[str] = []
    for nid, sim in neighbours:
        if sim < similarity_threshold:
            break  # sorted descending, so we can stop early
        linked.append(nid)
        # Update entry
        if nid not in raw.setdefault("related", []):
            raw["related"].append(nid)
        # Update neighbour
        neighbour = entries.get(nid)
        if neighbour is not None and entry_id not in neighbour.setdefault("related", []):
            neighbour["related"].append(entry_id)

    return linked


# ---------------------------------------------------------------------------
# Prompt constants for LLM calls
# ---------------------------------------------------------------------------

_ENRICHMENT_SYSTEM = """\
Analyse the following diary entry from an AI assistant's episodic memory.
Extract structured metadata and return it as a JSON object with exactly these keys:
  "keywords": list of 5-8 important terms (nouns, verbs, proper names)
  "category": exactly one string from this list: agent_build, infrastructure,
    user_preference, communication_style, diagnostic_learning, milestone,
    pipeline, data_processing, other
  "tags": list of 3-5 freeform topic labels (short phrases)

Return ONLY the JSON object. No explanation, no code fences.
"""

_EVOLUTION_SYSTEM = """\
You are refining the metadata of an older memory entry based on a newly discovered
related memory entry.

Given the TWO entries below, decide if the OLDER entry's tags or category should be
updated to better reflect the thematic connection.

Rules:
- Only suggest changes if the connection reveals a clearly missing tag or a category
  correction.  When in doubt, return {}.
- You may only modify "tags" and "category" — never the prose, never keywords.
- Return a JSON object with only the keys you are changing: {"tags": [...], "category": "..."}
  or {} if no change is warranted.

Return ONLY the JSON object.  No explanation, no code fences.
"""


# ---------------------------------------------------------------------------
# Phase 1 — enrichment helpers
# ---------------------------------------------------------------------------


def _parse_diary_sections(content: str) -> list[tuple[str, str]]:
    """Return (timestamp, prose) pairs from a diary file's ### HH:MM blocks.

    The date heading (# ...) is stripped.  Non-timestamped content before the
    first ### block is ignored.
    """
    sections: list[tuple[str, str]] = []
    # Split on ### HH:MM markers
    parts = re.split(r"###\s*(\d{2}:\d{2})\b", content)
    # parts = [pre_text, ts1, prose1, ts2, prose2, ...]
    i = 1
    while i + 1 < len(parts):
        ts = parts[i].strip()
        prose = parts[i + 1].strip()
        if prose:
            sections.append((ts, prose))
        i += 2
    return sections


def index_entry_from_diary_section(
    date_str: str,
    timestamp: str,
    prose: str,
) -> MemoryEntry:
    """Construct a bare MemoryEntry (no enrichment, no embedding) from a diary section."""
    entry_id = f"{date_str}:{timestamp}"
    summary = prose[:300].replace("\n", " ")
    return MemoryEntry(
        id=entry_id,
        date=date_str,
        timestamp=timestamp,
        summary=summary,
    )


async def enrich_entry(
    entry_text: str,
    llm: object,
) -> tuple[list[str], str, list[str]]:
    """Call the consolidation LLM to extract keywords, category, and tags.

    Returns ([], "other", []) on any failure so the caller can continue.
    """
    try:
        resp = await llm.acomplete(
            messages=[{"role": "user", "content": entry_text}],
            system=_ENRICHMENT_SYSTEM,
            max_tokens=256,
            json_mode=True,
        )
        data = json.loads(resp.content)
        keywords = [str(k) for k in data.get("keywords", [])][:8]
        raw_cat = str(data.get("category", "other"))
        category = raw_cat if raw_cat in _CATEGORIES else "other"
        tags = [str(t) for t in data.get("tags", [])][:5]
        return keywords, category, tags
    except Exception as exc:
        logger.warning("queen_memory_index: enrich_entry failed (%s)", exc)
        return [], "other", []


# ---------------------------------------------------------------------------
# Phase 5 — memory evolution
# ---------------------------------------------------------------------------


async def maybe_evolve_neighbors(
    new_entry_id: str,
    neighbor_ids: list[str],
    index: dict[str, Any],
    llm: object,
    *,
    max_neighbors_to_evolve: int = 2,
) -> None:
    """Potentially refine the tags/category of neighbour entries.

    Only mutates metadata (tags, category) — never prose, never embeddings.
    Failures are logged and silently skipped.
    """
    if not neighbor_ids:
        return

    new_raw = index.get("entries", {}).get(new_entry_id)
    if not new_raw:
        return

    for nid in neighbor_ids[:max_neighbors_to_evolve]:
        neighbor_raw = index.get("entries", {}).get(nid)
        if not neighbor_raw:
            continue
        try:
            prompt = (
                f"NEWER entry ({new_entry_id}):\n"
                f"Summary: {new_raw.get('summary', '')}\n"
                f"Keywords: {', '.join(new_raw.get('keywords', []))}\n"
                f"Tags: {', '.join(new_raw.get('tags', []))}\n\n"
                f"OLDER entry ({nid}):\n"
                f"Summary: {neighbor_raw.get('summary', '')}\n"
                f"Keywords: {', '.join(neighbor_raw.get('keywords', []))}\n"
                f"Tags: {', '.join(neighbor_raw.get('tags', []))}\n"
                f"Category: {neighbor_raw.get('category', 'other')}"
            )
            resp = await llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system=_EVOLUTION_SYSTEM,
                max_tokens=128,
                json_mode=True,
            )
            updates = json.loads(resp.content)
            if not updates:
                continue
            if "tags" in updates and isinstance(updates["tags"], list):
                neighbor_raw["tags"] = [str(t) for t in updates["tags"]][:5]
            if "category" in updates:
                raw_cat = str(updates["category"])
                neighbor_raw["category"] = raw_cat if raw_cat in _CATEGORIES else "other"
            logger.debug("queen_memory_index: evolved metadata for entry %s", nid)
        except Exception as exc:
            logger.warning("queen_memory_index: evolution failed for %s: %s", nid, exc)


# ---------------------------------------------------------------------------
# Index rebuild / backfill
# ---------------------------------------------------------------------------


async def rebuild_index_for_date(
    date_str: str,
    llm: object | None = None,
) -> int:
    """Parse today's diary file and index any sections not yet in the index.

    Optionally enriches new entries via LLM if *llm* is provided.
    Returns the count of new entries added.
    """
    from framework.agents.queen.queen_memory import episodic_memory_path
    from datetime import date as _date

    try:
        year, month, day = map(int, date_str.split("-"))
        d = _date(year, month, day)
    except ValueError:
        logger.warning("queen_memory_index: invalid date_str %r", date_str)
        return 0

    ep_path = episodic_memory_path(d)
    if not ep_path.exists():
        return 0

    content = ep_path.read_text(encoding="utf-8")
    sections = _parse_diary_sections(content)
    if not sections:
        return 0

    index = load_index()

    # Detect embedding model change and clear stale vectors
    if embeddings_enabled() and _detect_model_change(index):
        _clear_embeddings(index)

    added = 0
    for ts, prose in sections:
        entry_id = f"{date_str}:{ts}"
        existing = get_entry(index, entry_id)

        if existing is None:
            entry = index_entry_from_diary_section(date_str, ts, prose)
        elif existing.enriched:
            # Already fully processed; update embedding only if missing
            entry = existing
        else:
            entry = existing

        # Enrich if LLM provided and not yet enriched
        if llm is not None and not entry.enriched:
            keywords, category, tags = await enrich_entry(prose, llm)
            entry.keywords = keywords
            entry.category = category
            entry.tags = tags
            entry.enriched = True

        # Embed if model is configured and vector is missing
        if embeddings_enabled() and entry.embedding is None:
            vec = await embed_text(prose[:1500])  # cap input length
            if vec is not None:
                entry.embedding = vec
                index["embed_model"] = get_embed_model()
                index["embed_dim"] = len(vec)

        put_entry(index, entry)
        if existing is None:
            added += 1

    save_index(index)
    logger.debug(
        "queen_memory_index: indexed %d section(s) for %s, %d new", len(sections), date_str, added
    )
    return added


async def backfill_index(
    llm: object | None = None,
    embed: bool = True,
) -> dict[str, int]:
    """Walk all MEMORY-YYYY-MM-DD.md files and index unindexed entries.

    This is a one-shot utility — call it once after initial deployment to
    catch up historical diary files.  Not called automatically.

    Usage:
        uv run python -c "
        import asyncio
        from framework.agents.queen.queen_memory_index import backfill_index
        print(asyncio.run(backfill_index()))
        "
    """
    memories_dir = _queen_memories_dir()
    if not memories_dir.exists():
        return {"dates_processed": 0, "entries_added": 0}

    total_added = 0
    dates_processed = 0
    for md_file in sorted(memories_dir.glob("MEMORY-????-??-??.md")):
        date_str = md_file.stem.removeprefix("MEMORY-")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            continue
        added = await rebuild_index_for_date(date_str, llm=llm)
        total_added += added
        dates_processed += 1

    logger.info(
        "queen_memory_index: backfill complete — %d dates, %d entries added",
        dates_processed,
        total_added,
    )
    return {"dates_processed": dates_processed, "entries_added": total_added}


# ---------------------------------------------------------------------------
# Resolve full prose from diary file by entry_id
# ---------------------------------------------------------------------------


def resolve_prose(entry_id: str) -> str:
    """Read the source diary file and return the full prose for *entry_id*.

    Returns the summary from the index as a fallback if the file section
    cannot be found.
    """
    from framework.agents.queen.queen_memory import episodic_memory_path
    from datetime import date as _date

    try:
        date_str, ts = entry_id.split(":", 1)
        year, month, day = map(int, date_str.split("-"))
        d = _date(year, month, day)
    except ValueError:
        return ""

    ep_path = episodic_memory_path(d)
    if not ep_path.exists():
        return ""

    content = ep_path.read_text(encoding="utf-8")
    sections = _parse_diary_sections(content)
    for section_ts, prose in sections:
        if section_ts == ts:
            return prose
    return ""
