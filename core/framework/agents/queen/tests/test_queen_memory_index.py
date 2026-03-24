"""Unit tests for queen_memory_index.py.

All tests run without HIVE_EMBED_MODEL set.  Embedding behaviour is tested
via a lightweight mock that injects deterministic fixed vectors.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from framework.agents.queen.queen_memory_index import (
    MemoryEntry,
    _CATEGORIES,
    _parse_diary_sections,
    backfill_index,
    cosine_similarity,
    embed_text,
    embeddings_enabled,
    enrich_entry,
    find_knn,
    get_embed_model,
    get_entry,
    hybrid_search,
    importance_score,
    index_entry_from_diary_section,
    index_path,
    link_entry,
    load_index,
    maybe_evolve_neighbors,
    put_entry,
    rebuild_index_for_date,
    record_retrieval,
    resolve_prose,
    save_index,
    semantic_search,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(*entries: MemoryEntry) -> dict:
    idx = {"version": 1, "embed_model": None, "embed_dim": None, "entries": {}}
    for e in entries:
        put_entry(idx, e)
    return idx


def _entry(
    date_str: str = "2026-03-01",
    ts: str = "10:00",
    summary: str = "test summary",
    keywords: list[str] | None = None,
    tags: list[str] | None = None,
    category: str = "other",
    embedding: list[float] | None = None,
    retrieval_count: int = 0,
    last_retrieved: str | None = None,
    related: list[str] | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id=f"{date_str}:{ts}",
        date=date_str,
        timestamp=ts,
        summary=summary,
        keywords=keywords or [],
        tags=tags or [],
        category=category,
        embedding=embedding,
        retrieval_count=retrieval_count,
        last_retrieved=last_retrieved,
        related=related or [],
    )


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        # cosine of 180° = -1, but our vectors are floats so it can be -1
        result = cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert result == pytest.approx(-1.0)

    def test_none_inputs(self):
        assert cosine_similarity(None, [1.0]) == 0.0
        assert cosine_similarity([1.0], None) == 0.0
        assert cosine_similarity(None, None) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_known_similarity(self):
        # [1, 1] vs [1, 0] → cos(45°) ≈ 0.707
        result = cosine_similarity([1.0, 1.0], [1.0, 0.0])
        assert result == pytest.approx(math.sqrt(2) / 2, abs=1e-4)


# ---------------------------------------------------------------------------
# find_knn
# ---------------------------------------------------------------------------


class TestFindKnn:
    def test_returns_sorted_descending(self):
        e1 = _entry("2026-03-01", "09:00", embedding=[1.0, 0.0])
        e2 = _entry("2026-03-01", "10:00", embedding=[0.9, 0.1])
        e3 = _entry("2026-03-01", "11:00", embedding=[0.0, 1.0])
        idx = _make_index(e1, e2, e3)
        results = find_knn([1.0, 0.0], idx, k=3)
        ids = [r[0] for r in results]
        scores = [r[1] for r in results]
        assert ids[0] == "2026-03-01:09:00"  # exact match
        assert scores[0] == pytest.approx(1.0)
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    def test_excludes_self(self):
        e1 = _entry("2026-03-01", "09:00", embedding=[1.0, 0.0])
        idx = _make_index(e1)
        results = find_knn([1.0, 0.0], idx, k=5, exclude_id="2026-03-01:09:00")
        assert results == []

    def test_skips_null_embeddings(self):
        e1 = _entry("2026-03-01", "09:00", embedding=None)
        e2 = _entry("2026-03-01", "10:00", embedding=[1.0, 0.0])
        idx = _make_index(e1, e2)
        results = find_knn([1.0, 0.0], idx, k=5)
        ids = [r[0] for r in results]
        assert "2026-03-01:09:00" not in ids
        assert "2026-03-01:10:00" in ids

    def test_respects_k(self):
        entries = [_entry("2026-03-01", f"0{i}:00", embedding=[float(i), 0.0]) for i in range(5)]
        idx = _make_index(*entries)
        results = find_knn([1.0, 0.0], idx, k=2)
        assert len(results) <= 2


# ---------------------------------------------------------------------------
# load_index / save_index (round-trip and atomic write)
# ---------------------------------------------------------------------------


class TestIndexIO:
    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        idx = _make_index(_entry())
        idx["embed_model"] = "test-model"
        save_index(idx)
        loaded = load_index()
        assert loaded["embed_model"] == "test-model"
        assert "2026-03-01:10:00" in loaded["entries"]

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        idx = load_index()
        assert idx["entries"] == {}
        assert idx["version"] == 1

    def test_corrupt_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        (tmp_path / "index.json").write_text("not json at all", encoding="utf-8")
        idx = load_index()
        assert idx["entries"] == {}

    def test_atomic_write_uses_tmp_then_rename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        idx = _make_index()
        save_index(idx)
        # tmp file should be gone after rename
        assert not (tmp_path / "index.json.tmp").exists()
        assert (tmp_path / "index.json").exists()


# ---------------------------------------------------------------------------
# get_entry / put_entry
# ---------------------------------------------------------------------------


class TestGetPutEntry:
    def test_put_and_get_roundtrip(self):
        e = _entry(keywords=["foo", "bar"], tags=["t1"], category="milestone")
        idx = _make_index()
        put_entry(idx, e)
        loaded = get_entry(idx, e.id)
        assert loaded is not None
        assert loaded.keywords == ["foo", "bar"]
        assert loaded.category == "milestone"

    def test_get_missing_returns_none(self):
        idx = _make_index()
        assert get_entry(idx, "no-such-id") is None

    def test_put_overwrites_existing(self):
        e = _entry(summary="original")
        idx = _make_index(e)
        e2 = _entry(summary="updated")
        put_entry(idx, e2)
        loaded = get_entry(idx, e.id)
        assert loaded.summary == "updated"


# ---------------------------------------------------------------------------
# index_entry_from_diary_section
# ---------------------------------------------------------------------------


class TestIndexEntryFromDiarySection:
    def test_id_format(self):
        e = index_entry_from_diary_section("2026-03-01", "14:30", "Some prose here.")
        assert e.id == "2026-03-01:14:30"
        assert e.date == "2026-03-01"
        assert e.timestamp == "14:30"

    def test_summary_truncated_to_300(self):
        prose = "x" * 500
        e = index_entry_from_diary_section("2026-03-01", "14:30", prose)
        assert len(e.summary) == 300

    def test_defaults_empty_enrichment(self):
        e = index_entry_from_diary_section("2026-03-01", "14:30", "text")
        assert e.keywords == []
        assert e.tags == []
        assert e.category == "other"
        assert e.embedding is None
        assert not e.enriched


# ---------------------------------------------------------------------------
# _parse_diary_sections
# ---------------------------------------------------------------------------


class TestParseDiarySections:
    def test_parses_two_sections(self):
        content = "# March 1, 2026\n\n### 09:00\n\nFirst entry.\n\n### 14:30\n\nSecond entry."
        sections = _parse_diary_sections(content)
        assert len(sections) == 2
        assert sections[0] == ("09:00", "First entry.")
        assert sections[1] == ("14:30", "Second entry.")

    def test_ignores_content_before_first_timestamp(self):
        content = "# Heading\n\nIntro text.\n\n### 10:00\n\nEntry."
        sections = _parse_diary_sections(content)
        assert len(sections) == 1
        assert sections[0][0] == "10:00"

    def test_empty_content(self):
        assert _parse_diary_sections("") == []

    def test_no_timestamp_sections(self):
        assert _parse_diary_sections("# Just a heading\n\nSome text.") == []


# ---------------------------------------------------------------------------
# record_retrieval
# ---------------------------------------------------------------------------


class TestRecordRetrieval:
    def test_increments_count(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        e = _entry(retrieval_count=2)
        idx = _make_index(e)
        record_retrieval(idx, [e.id], auto_save=False)
        assert idx["entries"][e.id]["retrieval_count"] == 3

    def test_sets_last_retrieved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        e = _entry()
        idx = _make_index(e)
        record_retrieval(idx, [e.id], auto_save=False)
        assert idx["entries"][e.id]["last_retrieved"] is not None

    def test_ignores_missing_ids(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "framework.agents.queen.queen_memory_index._queen_memories_dir",
            lambda: tmp_path,
        )
        idx = _make_index()
        # Should not raise
        record_retrieval(idx, ["nonexistent:00:00"], auto_save=False)


# ---------------------------------------------------------------------------
# importance_score
# ---------------------------------------------------------------------------


class TestImportanceScore:
    def test_zero_for_never_retrieved(self):
        e = _entry(retrieval_count=0)
        assert importance_score(e) == 0.0

    def test_positive_for_retrieved_recently(self):
        now = datetime.now()
        e = _entry(retrieval_count=5, last_retrieved=now.isoformat())
        score = importance_score(e, now=now)
        assert score > 0.0

    def test_decays_over_time(self):
        from datetime import timedelta

        now = datetime.now()
        recent = _entry("2026-03-01", "10:00", retrieval_count=5,
                        last_retrieved=now.isoformat())
        old = _entry("2026-03-01", "11:00", retrieval_count=5,
                     last_retrieved=(now - timedelta(days=60)).isoformat())
        assert importance_score(recent, now=now) > importance_score(old, now=now)

    def test_higher_count_higher_score(self):
        now = datetime.now()
        low = _entry("2026-03-01", "10:00", retrieval_count=1,
                     last_retrieved=now.isoformat())
        high = _entry("2026-03-01", "11:00", retrieval_count=10,
                      last_retrieved=now.isoformat())
        assert importance_score(high, now=now) > importance_score(low, now=now)


# ---------------------------------------------------------------------------
# link_entry (Phase 3)
# ---------------------------------------------------------------------------


class TestLinkEntry:
    def test_links_above_threshold(self):
        # Two nearly identical vectors should be linked
        e1 = _entry("2026-03-01", "09:00", embedding=[1.0, 0.0, 0.0])
        e2 = _entry("2026-03-01", "10:00", embedding=[0.99, 0.01, 0.0])
        idx = _make_index(e1, e2)
        linked = link_entry(idx, e1.id, similarity_threshold=0.90)
        assert e2.id in linked

    def test_bidirectional_links(self):
        e1 = _entry("2026-03-01", "09:00", embedding=[1.0, 0.0])
        e2 = _entry("2026-03-01", "10:00", embedding=[1.0, 0.0])
        idx = _make_index(e1, e2)
        link_entry(idx, e1.id, similarity_threshold=0.90)
        assert e2.id in idx["entries"][e1.id]["related"]
        assert e1.id in idx["entries"][e2.id]["related"]

    def test_does_not_link_below_threshold(self):
        e1 = _entry("2026-03-01", "09:00", embedding=[1.0, 0.0])
        e2 = _entry("2026-03-01", "10:00", embedding=[0.0, 1.0])
        idx = _make_index(e1, e2)
        linked = link_entry(idx, e1.id, similarity_threshold=0.90)
        assert linked == []

    def test_skips_entry_without_embedding(self):
        e1 = _entry("2026-03-01", "09:00", embedding=None)
        idx = _make_index(e1)
        linked = link_entry(idx, e1.id)
        assert linked == []


# ---------------------------------------------------------------------------
# hybrid_search (Phase 4)
# ---------------------------------------------------------------------------


class TestHybridSearch:
    def test_semantic_score_dominates(self):
        e_high = _entry("2026-03-01", "09:00", keywords=["unrelated"])
        e_low = _entry("2026-03-01", "10:00", keywords=["pipeline", "agent"])
        idx = _make_index(e_high, e_low)
        sem_scores = {e_high.id: 0.95, e_low.id: 0.40}
        ranked = hybrid_search("pipeline", idx, [e_high.id, e_low.id], sem_scores)
        # e_high has much higher semantic score, should still rank first
        assert ranked[0][0] == e_high.id

    def test_keyword_overlap_breaks_tie(self):
        e_kw = _entry("2026-03-01", "09:00", keywords=["pipeline", "agent", "workflow"])
        e_no_kw = _entry("2026-03-01", "10:00", keywords=["unrelated", "other"])
        idx = _make_index(e_kw, e_no_kw)
        # Equal semantic scores
        sem_scores = {e_kw.id: 0.80, e_no_kw.id: 0.80}
        ranked = hybrid_search("pipeline agent", idx, [e_kw.id, e_no_kw.id], sem_scores)
        assert ranked[0][0] == e_kw.id

    def test_returns_sorted_descending(self):
        entries = [_entry("2026-03-01", f"0{i}:00") for i in range(3)]
        idx = _make_index(*entries)
        sem_scores = {e.id: float(i) / 10 for i, e in enumerate(entries)}
        ids = [e.id for e in entries]
        ranked = hybrid_search("query", idx, ids, sem_scores)
        scores = [s for _, s in ranked]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


# ---------------------------------------------------------------------------
# embeddings_enabled / get_embed_model
# ---------------------------------------------------------------------------


class TestEmbeddingsEnabled:
    def test_disabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("HIVE_EMBED_MODEL", raising=False)
        assert not embeddings_enabled()
        assert get_embed_model() is None

    def test_enabled_when_env_set(self, monkeypatch):
        monkeypatch.setenv("HIVE_EMBED_MODEL", "text-embedding-3-small")
        assert embeddings_enabled()
        assert get_embed_model() == "text-embedding-3-small"


# ---------------------------------------------------------------------------
# embed_text — mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmbedText:
    async def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("HIVE_EMBED_MODEL", raising=False)
        result = await embed_text("hello")
        assert result is None

    async def test_returns_vector_when_enabled(self, monkeypatch):
        monkeypatch.setenv("HIVE_EMBED_MODEL", "text-embedding-3-small")
        fake_vec = [0.1, 0.2, 0.3]
        mock_resp = MagicMock()
        mock_resp.data = [{"embedding": fake_vec}]
        with patch("litellm.aembedding", new=AsyncMock(return_value=mock_resp)):
            result = await embed_text("hello world")
        assert result == fake_vec

    async def test_returns_none_on_api_failure(self, monkeypatch):
        monkeypatch.setenv("HIVE_EMBED_MODEL", "text-embedding-3-small")
        with patch("litellm.aembedding", new=AsyncMock(side_effect=RuntimeError("API down"))):
            result = await embed_text("hello")
        assert result is None


# ---------------------------------------------------------------------------
# semantic_search — mocked embeddings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSemanticSearch:
    async def test_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.delenv("HIVE_EMBED_MODEL", raising=False)
        idx = _make_index(_entry(embedding=[1.0, 0.0]))
        results = await semantic_search("query", idx)
        assert results == []

    async def test_finds_nearest_neighbours(self, monkeypatch):
        monkeypatch.setenv("HIVE_EMBED_MODEL", "text-embedding-3-small")
        e1 = _entry("2026-03-01", "09:00", embedding=[1.0, 0.0])
        e2 = _entry("2026-03-01", "10:00", embedding=[0.0, 1.0])
        idx = _make_index(e1, e2)
        query_vec = [1.0, 0.0]
        mock_resp = MagicMock()
        mock_resp.data = [{"embedding": query_vec}]
        with patch("litellm.aembedding", new=AsyncMock(return_value=mock_resp)):
            results = await semantic_search("query", idx, k=2)
        assert results[0][0] == e1.id  # closest to [1.0, 0.0]

    async def test_date_range_filter(self, monkeypatch):
        monkeypatch.setenv("HIVE_EMBED_MODEL", "text-embedding-3-small")
        e_in = _entry("2026-03-15", "09:00", embedding=[1.0, 0.0])
        e_out = _entry("2026-02-01", "09:00", embedding=[1.0, 0.0])
        idx = _make_index(e_in, e_out)
        mock_resp = MagicMock()
        mock_resp.data = [{"embedding": [1.0, 0.0]}]
        with patch("litellm.aembedding", new=AsyncMock(return_value=mock_resp)):
            results = await semantic_search(
                "query", idx, k=10, date_range=("2026-03-01", "2026-03-31")
            )
        ids = [r[0] for r in results]
        assert e_in.id in ids
        assert e_out.id not in ids


# ---------------------------------------------------------------------------
# enrich_entry — mocked LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnrichEntry:
    async def test_parses_llm_response(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(
            {"keywords": ["pipeline", "agent"], "category": "pipeline", "tags": ["build", "test"]}
        )
        mock_llm.acomplete = AsyncMock(return_value=mock_resp)
        kw, cat, tags = await enrich_entry("Some diary text", mock_llm)
        assert "pipeline" in kw
        assert cat == "pipeline"
        assert "build" in tags

    async def test_rejects_invalid_category(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(
            {"keywords": [], "category": "invented_category", "tags": []}
        )
        mock_llm.acomplete = AsyncMock(return_value=mock_resp)
        _, cat, _ = await enrich_entry("text", mock_llm)
        assert cat == "other"

    async def test_returns_defaults_on_failure(self):
        mock_llm = MagicMock()
        mock_llm.acomplete = AsyncMock(side_effect=RuntimeError("LLM down"))
        kw, cat, tags = await enrich_entry("text", mock_llm)
        assert kw == []
        assert cat == "other"
        assert tags == []


# ---------------------------------------------------------------------------
# maybe_evolve_neighbors — mocked LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMaybeEvolveNeighbors:
    async def test_updates_tags_on_non_empty_response(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({"tags": ["new_tag", "updated"]})
        mock_llm.acomplete = AsyncMock(return_value=mock_resp)

        new_e = _entry("2026-03-01", "10:00", keywords=["new"], tags=["tag_a"])
        old_e = _entry("2026-03-01", "09:00", keywords=["old"], tags=["old_tag"])
        idx = _make_index(new_e, old_e)

        await maybe_evolve_neighbors(new_e.id, [old_e.id], idx, mock_llm)
        assert "new_tag" in idx["entries"][old_e.id]["tags"]

    async def test_no_op_on_empty_response(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({})
        mock_llm.acomplete = AsyncMock(return_value=mock_resp)

        new_e = _entry("2026-03-01", "10:00")
        old_e = _entry("2026-03-01", "09:00", tags=["original"])
        idx = _make_index(new_e, old_e)

        await maybe_evolve_neighbors(new_e.id, [old_e.id], idx, mock_llm)
        # Tags unchanged
        assert idx["entries"][old_e.id]["tags"] == ["original"]

    async def test_silently_handles_llm_failure(self):
        mock_llm = MagicMock()
        mock_llm.acomplete = AsyncMock(side_effect=RuntimeError("down"))

        new_e = _entry("2026-03-01", "10:00")
        old_e = _entry("2026-03-01", "09:00")
        idx = _make_index(new_e, old_e)

        # Must not raise
        await maybe_evolve_neighbors(new_e.id, [old_e.id], idx, mock_llm)

    async def test_respects_max_neighbors_cap(self):
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({})
        mock_llm.acomplete = AsyncMock(return_value=mock_resp)

        new_e = _entry("2026-03-01", "10:00")
        neighbors = [_entry("2026-03-01", f"0{i}:00") for i in range(5)]
        idx = _make_index(new_e, *neighbors)

        await maybe_evolve_neighbors(
            new_e.id, [n.id for n in neighbors], idx, mock_llm, max_neighbors_to_evolve=2
        )
        assert mock_llm.acomplete.call_count == 2


# ---------------------------------------------------------------------------
# recall_diary — semantic path and fallback (integration-style)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecallDiary:
    async def test_substring_fallback_when_embeddings_disabled(
        self, tmp_path, monkeypatch
    ):
        """When HIVE_EMBED_MODEL is not set, recall_diary uses substring matching."""
        monkeypatch.delenv("HIVE_EMBED_MODEL", raising=False)

        # Write a fake diary file
        memories_dir = tmp_path / ".hive" / "queen" / "memories"
        memories_dir.mkdir(parents=True)
        today_str = "2026-03-24"
        (memories_dir / f"MEMORY-{today_str}.md").write_text(
            "# March 24, 2026\n\n### 09:00\n\nWorked on the pipeline agent today.\n",
            encoding="utf-8",
        )

        # Patch the path functions
        import framework.agents.queen.queen_memory as qm
        monkeypatch.setattr(qm, "episodic_memory_path", lambda d=None: memories_dir / f"MEMORY-{today_str}.md")

        from framework.tools.queen_memory_tools import recall_diary

        result = await recall_diary(query="pipeline", days_back=1)
        assert "pipeline agent" in result

    async def test_no_results_message(self, monkeypatch):
        """Returns a helpful message when nothing matches."""
        monkeypatch.delenv("HIVE_EMBED_MODEL", raising=False)

        import framework.agents.queen.queen_memory as qm
        # Point to a non-existent path
        monkeypatch.setattr(
            qm, "episodic_memory_path", lambda d=None: Path("/nonexistent/MEMORY.md")
        )

        from framework.tools.queen_memory_tools import recall_diary

        result = await recall_diary(query="nonexistent topic", days_back=1)
        assert "No diary entries" in result
