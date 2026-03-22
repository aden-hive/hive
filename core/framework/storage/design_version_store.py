"""
Design Version Store — Manages versioned agent design snapshots.

Handles saving, loading, listing, promoting, restoring, and pruning
of design versions for agent reproducibility.

Follows the CheckpointStore pattern from framework.storage.checkpoint_store.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from framework.schemas.design_version import (
    ALLOWED_TRANSITIONS,
    DesignLifecycleState,
    DesignVersion,
    DesignVersionIndex,
    DesignVersionSummary,
)
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


class DesignVersionStore:
    """
    Manages design version storage with atomic writes.

    Directory structure:
        versions/
            index.json                      # Version manifest
            v_{timestamp}_{uuid}.json       # Individual versions
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.versions_dir = self.base_path / "versions"
        self.index_path = self.versions_dir / "index.json"
        self._index_lock = asyncio.Lock()

    async def save_version(self, version: DesignVersion) -> None:
        """Atomically save version and update index."""

        def _write():
            self.versions_dir.mkdir(parents=True, exist_ok=True)
            version_path = self.versions_dir / f"{version.version_id}.json"
            with atomic_write(version_path) as f:
                f.write(version.model_dump_json(indent=2))
            logger.debug("Saved design version %s", version.version_id)

        await asyncio.to_thread(_write)

        async with self._index_lock:
            await self._update_index_add(version)

    async def load_version(self, version_id: str) -> DesignVersion | None:
        """Load version by ID."""

        def _read() -> DesignVersion | None:
            version_path = self.versions_dir / f"{version_id}.json"
            if not version_path.exists():
                return None
            try:
                return DesignVersion.model_validate_json(version_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Failed to load version %s: %s", version_id, e)
                return None

        return await asyncio.to_thread(_read)

    async def load_index(self) -> DesignVersionIndex | None:
        """Load version index."""

        def _read() -> DesignVersionIndex | None:
            if not self.index_path.exists():
                return None
            try:
                return DesignVersionIndex.model_validate_json(
                    self.index_path.read_text(encoding="utf-8")
                )
            except Exception as e:
                logger.error("Failed to load version index: %s", e)
                return None

        return await asyncio.to_thread(_read)

    async def list_versions(
        self,
        lifecycle_state: DesignLifecycleState | None = None,
        starred: bool | None = None,
    ) -> list[DesignVersionSummary]:
        """List versions with optional filters."""
        index = await self.load_index()
        if not index:
            return []

        versions = index.versions

        if lifecycle_state is not None:
            versions = [v for v in versions if v.lifecycle_state == lifecycle_state]

        if starred is not None:
            versions = [v for v in versions if v.starred == starred]

        return versions

    async def promote_version(
        self,
        version_id: str,
        target_state: DesignLifecycleState,
    ) -> bool:
        """Forward-only state transition with validation."""
        version = await self.load_version(version_id)
        if version is None:
            logger.warning("Version %s not found", version_id)
            return False

        allowed = ALLOWED_TRANSITIONS.get(version.lifecycle_state, set())
        if target_state not in allowed:
            logger.warning(
                "Transition %s → %s not allowed for %s",
                version.lifecycle_state,
                target_state,
                version_id,
            )
            return False

        version.lifecycle_state = target_state
        if target_state == DesignLifecycleState.PROMOTED:
            version.starred = True

        def _write():
            version_path = self.versions_dir / f"{version_id}.json"
            with atomic_write(version_path) as f:
                f.write(version.model_dump_json(indent=2))

        await asyncio.to_thread(_write)

        async with self._index_lock:
            index = await self.load_index()
            if index:
                for s in index.versions:
                    if s.version_id == version_id:
                        s.lifecycle_state = target_state
                        s.starred = version.starred
                        break
                if target_state == DesignLifecycleState.PROMOTED:
                    index.current_promoted_id = version_id
                await self._write_index(index)

        logger.info("Promoted %s to %s", version_id, target_state)
        return True

    async def restore_version(
        self,
        version_id: str,
        agent_json_path: Path,
    ) -> bool:
        """Restore agent.json from a versioned snapshot."""
        version = await self.load_version(version_id)
        if version is None:
            return False

        def _write():
            agent_data = {"graph": version.graph_spec, "goal": version.goal}
            with atomic_write(agent_json_path) as f:
                json.dump(agent_data, f, indent=2)

        await asyncio.to_thread(_write)
        logger.info("Restored %s to %s", version_id, agent_json_path)
        return True

    async def prune_versions(
        self,
        max_age_days: int = 30,
        keep_starred: bool = True,
    ) -> int:
        """Prune old unstarred versions."""
        index = await self.load_index()
        if not index or not index.versions:
            return 0

        cutoff = datetime.now() - timedelta(days=max_age_days)
        to_delete = []

        for s in index.versions:
            if keep_starred and s.starred:
                continue
            try:
                created = datetime.fromisoformat(s.created_at)
                if created < cutoff:
                    to_delete.append(s.version_id)
            except Exception:
                continue

        deleted = 0
        for vid in to_delete:
            if await self._delete_version_file(vid):
                deleted += 1

        if deleted > 0:
            async with self._index_lock:
                index = await self.load_index()
                if index:
                    index.versions = [v for v in index.versions if v.version_id not in to_delete]
                    index.total_versions = len(index.versions)
                    if index.latest_version_id in to_delete:
                        index.latest_version_id = (
                            index.versions[-1].version_id if index.versions else None
                        )
                    await self._write_index(index)
            logger.info("Pruned %d versions older than %d days", deleted, max_age_days)

        return deleted

    async def _delete_version_file(self, version_id: str) -> bool:
        def _delete() -> bool:
            path = self.versions_dir / f"{version_id}.json"
            if not path.exists():
                return False
            path.unlink()
            return True

        return await asyncio.to_thread(_delete)

    async def _update_index_add(self, version: DesignVersion) -> None:
        index = await self.load_index()
        if not index:
            index = DesignVersionIndex(agent_id=self.base_path.name)
        index.add_version(version)
        await self._write_index(index)

    async def _write_index(self, index: DesignVersionIndex) -> None:
        def _write():
            self.versions_dir.mkdir(parents=True, exist_ok=True)
            with atomic_write(self.index_path) as f:
                f.write(index.model_dump_json(indent=2))

        await asyncio.to_thread(_write)
