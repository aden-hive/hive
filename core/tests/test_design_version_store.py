"""Tests for DesignVersionStore — save, load, list, prune, promote, restore."""

import json

import pytest

from framework.schemas.design_version import (
    DesignLifecycleState,
    DesignVersion,
    DesignVersionIndex,
)
from framework.storage.design_version_store import DesignVersionStore


def _sample_graph_spec() -> dict:
    return {
        "id": "test-graph",
        "goal_id": "test-goal",
        "version": "1.0.0",
        "entry_node": "start",
        "terminal_nodes": ["end"],
        "nodes": [
            {"id": "start", "name": "Start", "description": "Entry", "node_type": "event_loop"},
            {"id": "end", "name": "End", "description": "Exit", "node_type": "event_loop"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "end", "condition": "on_success"},
        ],
    }


def _sample_goal() -> dict:
    return {
        "id": "test-goal",
        "name": "Test Goal",
        "description": "A test goal",
        "success_criteria": [],
        "constraints": [],
    }


def _make_version(
    lifecycle_state: DesignLifecycleState = DesignLifecycleState.DRAFT,
    description: str = "test",
) -> DesignVersion:
    return DesignVersion.create(
        graph_spec=_sample_graph_spec(),
        goal=_sample_goal(),
        lifecycle_state=lifecycle_state,
        description=description,
    )


class TestDesignVersionStoreSaveLoad:
    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        version = _make_version()
        await store.save_version(version)
        loaded = await store.load_version(version.version_id)
        assert loaded is not None
        assert loaded.version_id == version.version_id
        assert loaded.checksum == version.checksum
        assert loaded.verify() is True

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        loaded = await store.load_version("v_nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_creates_index(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        version = _make_version()
        await store.save_version(version)
        index = await store.load_index()
        assert index is not None
        assert index.total_versions == 1
        assert index.latest_version_id == version.version_id


class TestDesignVersionStoreList:
    @pytest.mark.asyncio
    async def test_list_versions(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        v1 = _make_version(description="first")
        v2 = _make_version(description="second")
        await store.save_version(v1)
        await store.save_version(v2)
        versions = await store.list_versions()
        assert len(versions) == 2

    @pytest.mark.asyncio
    async def test_list_by_state(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        v1 = _make_version(lifecycle_state=DesignLifecycleState.DRAFT)
        v2 = _make_version(lifecycle_state=DesignLifecycleState.CANDIDATE)
        await store.save_version(v1)
        await store.save_version(v2)
        drafts = await store.list_versions(lifecycle_state=DesignLifecycleState.DRAFT)
        assert len(drafts) == 1
        assert drafts[0].version_id == v1.version_id

    @pytest.mark.asyncio
    async def test_list_starred(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        v1 = _make_version()
        v1.starred = True
        v2 = _make_version()
        await store.save_version(v1)
        await store.save_version(v2)
        starred = await store.list_versions(starred=True)
        assert len(starred) == 1


class TestDesignVersionStorePromote:
    @pytest.mark.asyncio
    async def test_promote_forward(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        version = _make_version(lifecycle_state=DesignLifecycleState.DRAFT)
        await store.save_version(version)
        result = await store.promote_version(version.version_id, DesignLifecycleState.CANDIDATE)
        assert result is True
        loaded = await store.load_version(version.version_id)
        assert loaded.lifecycle_state == DesignLifecycleState.CANDIDATE

    @pytest.mark.asyncio
    async def test_promote_backward_rejected(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        version = _make_version(lifecycle_state=DesignLifecycleState.CANDIDATE)
        await store.save_version(version)
        result = await store.promote_version(version.version_id, DesignLifecycleState.DRAFT)
        assert result is False
        loaded = await store.load_version(version.version_id)
        assert loaded.lifecycle_state == DesignLifecycleState.CANDIDATE

    @pytest.mark.asyncio
    async def test_promote_invalid_transition_rejected(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        version = _make_version(lifecycle_state=DesignLifecycleState.DRAFT)
        await store.save_version(version)
        result = await store.promote_version(version.version_id, DesignLifecycleState.VALIDATED)
        assert result is False


class TestDesignVersionStoreRestore:
    @pytest.mark.asyncio
    async def test_restore_writes_agent_json(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        version = _make_version()
        await store.save_version(version)
        agent_json_path = tmp_path / "agent.json"
        await store.restore_version(version.version_id, agent_json_path)
        assert agent_json_path.exists()
        data = json.loads(agent_json_path.read_text(encoding="utf-8"))
        assert data["graph"] == version.graph_spec
        assert data["goal"] == version.goal

    @pytest.mark.asyncio
    async def test_restore_nonexistent_returns_false(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        result = await store.restore_version("v_nope", tmp_path / "agent.json")
        assert result is False


class TestDesignVersionStorePrune:
    @pytest.mark.asyncio
    async def test_prune_removes_old_unstarred(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        v1 = _make_version(description="old")
        v2 = _make_version(description="new")
        await store.save_version(v1)
        await store.save_version(v2)
        deleted = await store.prune_versions(max_age_days=-1, keep_starred=True)
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_prune_keeps_starred(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        v1 = _make_version()
        v1.starred = True
        await store.save_version(v1)
        deleted = await store.prune_versions(max_age_days=-1, keep_starred=True)
        assert deleted == 0
        loaded = await store.load_version(v1.version_id)
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_prune_with_empty_store(self, tmp_path):
        store = DesignVersionStore(tmp_path)
        deleted = await store.prune_versions(max_age_days=-1)
        assert deleted == 0
