"""Tests for the RegistryClient skill registry client."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from framework.skills.registry import RegistryClient, _CACHE_TTL_SECONDS

_SAMPLE_INDEX = {
    "version": 1,
    "skills": [
        {
            "name": "deep-research",
            "description": "Multi-step web research with source verification.",
            "version": "1.0.0",
            "author": "anthropics",
            "license": "MIT",
            "tags": ["research", "web"],
            "git_url": "https://github.com/anthropics/skills",
            "subdirectory": "deep-research",
            "trust_tier": "official",
        },
        {
            "name": "code-review",
            "description": "Automated code review for style and correctness.",
            "version": "0.9.0",
            "author": "contributor",
            "tags": ["code", "review"],
            "git_url": "https://github.com/contributor/code-review",
            "subdirectory": None,
            "trust_tier": "community",
        },
    ],
    "packs": [
        {
            "name": "research-starter",
            "description": "Research-focused skill bundle",
            "skills": ["deep-research"],
        }
    ],
}


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "registry_cache"


@pytest.fixture
def client(cache_dir):
    return RegistryClient(registry_url="https://example.com/skill_index.json", cache_dir=cache_dir)


class TestFetchIndex:
    def test_returns_none_on_network_error(self, client):
        with patch.object(client, "_http_fetch", return_value=None):
            result = client.fetch_index()
        assert result is None

    def test_returns_none_on_url_error(self, client):
        with patch("framework.skills.registry.urlopen", side_effect=URLError("connection refused")):
            result = client.fetch_index()
        assert result is None

    def test_fetches_and_caches_index(self, client):
        raw = json.dumps(_SAMPLE_INDEX).encode()
        with patch.object(client, "_http_fetch", return_value=raw):
            result = client.fetch_index()
        assert result is not None
        assert len(result["skills"]) == 2
        # Cache should be written
        assert client._index_path.exists()

    def test_uses_fresh_cache_without_network(self, client, cache_dir):
        # Write fresh cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "skill_index.json").write_text(json.dumps(_SAMPLE_INDEX))
        meta = {"last_fetched": datetime.now(tz=UTC).isoformat()}
        (cache_dir / "metadata.json").write_text(json.dumps(meta))

        fetch_called = []
        with patch.object(client, "_http_fetch", side_effect=lambda *a, **kw: fetch_called.append(1)):
            result = client.fetch_index()

        assert not fetch_called, "Should not hit network when cache is fresh"
        assert result is not None

    def test_refreshes_when_cache_is_stale(self, client, cache_dir):
        # Write stale cache (older than TTL)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "skill_index.json").write_text(json.dumps(_SAMPLE_INDEX))
        old_time = (datetime.now(tz=UTC) - timedelta(seconds=_CACHE_TTL_SECONDS + 60)).isoformat()
        meta = {"last_fetched": old_time}
        (cache_dir / "metadata.json").write_text(json.dumps(meta))

        raw = json.dumps(_SAMPLE_INDEX).encode()
        with patch.object(client, "_http_fetch", return_value=raw) as mock_fetch:
            client.fetch_index()
        mock_fetch.assert_called_once()

    def test_force_refresh_bypasses_fresh_cache(self, client, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "skill_index.json").write_text(json.dumps(_SAMPLE_INDEX))
        meta = {"last_fetched": datetime.now(tz=UTC).isoformat()}
        (cache_dir / "metadata.json").write_text(json.dumps(meta))

        raw = json.dumps(_SAMPLE_INDEX).encode()
        with patch.object(client, "_http_fetch", return_value=raw) as mock_fetch:
            client.fetch_index(force_refresh=True)
        mock_fetch.assert_called_once()

    def test_falls_back_to_stale_cache_on_network_error(self, client, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "skill_index.json").write_text(json.dumps(_SAMPLE_INDEX))
        # No metadata → stale

        with patch.object(client, "_http_fetch", return_value=None):
            result = client.fetch_index()

        assert result is not None
        assert result["version"] == 1


class TestSearch:
    def test_filters_by_name(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            results = client.search("deep")
        assert len(results) == 1
        assert results[0]["name"] == "deep-research"

    def test_filters_by_description(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            results = client.search("source verification")
        assert any(r["name"] == "deep-research" for r in results)

    def test_filters_by_tag(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            results = client.search("review")
        assert any(r["name"] == "code-review" for r in results)

    def test_case_insensitive(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            results = client.search("DEEP")
        assert len(results) == 1

    def test_returns_empty_when_unavailable(self, client):
        with patch.object(client, "fetch_index", return_value=None):
            results = client.search("anything")
        assert results == []

    def test_returns_empty_on_no_match(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            results = client.search("xyzzy-no-match")
        assert results == []


class TestGetSkillEntry:
    def test_finds_by_exact_name(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            entry = client.get_skill_entry("deep-research")
        assert entry is not None
        assert entry["name"] == "deep-research"

    def test_returns_none_when_not_found(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            entry = client.get_skill_entry("nonexistent")
        assert entry is None

    def test_returns_none_when_index_unavailable(self, client):
        with patch.object(client, "fetch_index", return_value=None):
            entry = client.get_skill_entry("deep-research")
        assert entry is None


class TestGetPack:
    def test_returns_skill_names(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            skills = client.get_pack("research-starter")
        assert skills == ["deep-research"]

    def test_returns_none_when_pack_not_found(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            result = client.get_pack("nonexistent-pack")
        assert result is None

    def test_returns_none_when_index_unavailable(self, client):
        with patch.object(client, "fetch_index", return_value=None):
            result = client.get_pack("research-starter")
        assert result is None


class TestResolveGitUrl:
    def test_returns_git_url_and_subdirectory(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            result = client.resolve_git_url("deep-research")
        assert result == ("https://github.com/anthropics/skills", "deep-research")

    def test_returns_none_subdirectory_when_absent(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            result = client.resolve_git_url("code-review")
        git_url, subdir = result
        assert subdir is None

    def test_returns_none_when_not_in_registry(self, client):
        with patch.object(client, "fetch_index", return_value=_SAMPLE_INDEX):
            result = client.resolve_git_url("not-there")
        assert result is None


class TestCacheAtomicWrite:
    def test_atomic_write_uses_tmp_then_replace(self, client, cache_dir, monkeypatch):
        written_paths = []
        original_write = Path.write_text

        def tracking_write(self, data, encoding=None):
            written_paths.append(str(self))
            return original_write(self, data, encoding=encoding or "utf-8")

        monkeypatch.setattr(Path, "write_text", tracking_write)
        client._save_cache(_SAMPLE_INDEX)

        # .tmp file should have been written (then replaced — may not exist now)
        assert any(".tmp" in p for p in written_paths)
        # Final index file should exist
        assert client._index_path.exists()

    def test_save_and_load_round_trip(self, client):
        client._save_cache(_SAMPLE_INDEX)
        loaded = client._load_cache()
        assert loaded == _SAMPLE_INDEX

    def test_load_returns_none_when_absent(self, client):
        result = client._load_cache()
        assert result is None
