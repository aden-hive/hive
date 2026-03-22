"""
Design Version Schema — Agent design snapshots for reproducibility.

Captures the complete agent definition (GraphSpec + Goal + flowchart)
at a point in time, enabling version history, rollback, and lifecycle
governance for self-evolving agents.

Follows the Checkpoint/CheckpointSummary/CheckpointIndex pattern
from framework.schemas.checkpoint.
"""

import hashlib
import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DesignLifecycleState(StrEnum):
    """Lifecycle state of an agent design version.

    Forward-only transitions:
        DRAFT → CANDIDATE → VALIDATED → PROMOTED → ARCHIVED
        CANDIDATE → ARCHIVED (abandoned)
    """

    DRAFT = "draft"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PROMOTED = "promoted"
    ARCHIVED = "archived"


ALLOWED_TRANSITIONS: dict[DesignLifecycleState, set[DesignLifecycleState]] = {
    DesignLifecycleState.DRAFT: {DesignLifecycleState.CANDIDATE},
    DesignLifecycleState.CANDIDATE: {
        DesignLifecycleState.VALIDATED,
        DesignLifecycleState.ARCHIVED,
    },
    DesignLifecycleState.VALIDATED: {DesignLifecycleState.PROMOTED},
    DesignLifecycleState.PROMOTED: {DesignLifecycleState.ARCHIVED},
    DesignLifecycleState.ARCHIVED: set(),
}


def _compute_checksum(graph_spec: dict[str, Any], goal: dict[str, Any]) -> str:
    """Compute deterministic checksum from graph_spec and goal."""
    content = json.dumps(graph_spec, sort_keys=True) + json.dumps(goal, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class DesignVersion(BaseModel):
    """Full design snapshot. Stored as individual JSON files."""

    version_id: str
    parent_version_id: str | None = None
    lifecycle_state: DesignLifecycleState = DesignLifecycleState.DRAFT
    created_at: str
    description: str = ""

    graph_spec: dict[str, Any]
    goal: dict[str, Any]
    flowchart: dict[str, Any] | None = None

    quality_metrics: dict[str, Any] = Field(default_factory=dict)
    starred: bool = False

    checksum: str

    model_config = {"extra": "allow"}

    @classmethod
    def create(
        cls,
        graph_spec: dict[str, Any],
        goal: dict[str, Any],
        lifecycle_state: DesignLifecycleState = DesignLifecycleState.DRAFT,
        description: str = "",
        parent_version_id: str | None = None,
        flowchart: dict[str, Any] | None = None,
    ) -> "DesignVersion":
        """Create with auto-generated ID, timestamp, and checksum."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return cls(
            version_id=f"v_{timestamp}_{short_uuid}",
            parent_version_id=parent_version_id,
            lifecycle_state=lifecycle_state,
            created_at=datetime.now().isoformat(),
            description=description,
            graph_spec=graph_spec,
            goal=goal,
            flowchart=flowchart,
            checksum=_compute_checksum(graph_spec, goal),
        )

    def verify(self) -> bool:
        """Verify integrity of stored design."""
        return self.checksum == _compute_checksum(self.graph_spec, self.goal)


class DesignVersionSummary(BaseModel):
    """Lightweight metadata for index listings."""

    version_id: str
    lifecycle_state: DesignLifecycleState
    created_at: str
    description: str = ""
    parent_version_id: str | None = None
    starred: bool = False
    checksum: str = ""

    model_config = {"extra": "allow"}

    @classmethod
    def from_version(cls, version: DesignVersion) -> "DesignVersionSummary":
        """Create summary from full version."""
        return cls(
            version_id=version.version_id,
            lifecycle_state=version.lifecycle_state,
            created_at=version.created_at,
            description=version.description,
            parent_version_id=version.parent_version_id,
            starred=version.starred,
            checksum=version.checksum,
        )


class DesignVersionIndex(BaseModel):
    """Manifest of all versions for an agent."""

    agent_id: str
    versions: list[DesignVersionSummary] = Field(default_factory=list)
    latest_version_id: str | None = None
    current_promoted_id: str | None = None
    total_versions: int = 0

    model_config = {"extra": "allow"}

    def add_version(self, version: DesignVersion) -> None:
        """Add a version to the index."""
        summary = DesignVersionSummary.from_version(version)
        self.versions.append(summary)
        self.latest_version_id = version.version_id
        self.total_versions = len(self.versions)
        if version.lifecycle_state == DesignLifecycleState.PROMOTED:
            self.current_promoted_id = version.version_id

    def get_version_summary(self, version_id: str) -> DesignVersionSummary | None:
        """Get summary by ID."""
        for s in self.versions:
            if s.version_id == version_id:
                return s
        return None

    def filter_by_state(self, state: DesignLifecycleState) -> list[DesignVersionSummary]:
        """Filter versions by lifecycle state."""
        return [v for v in self.versions if v.lifecycle_state == state]

    def get_starred(self) -> list[DesignVersionSummary]:
        """Get all starred versions."""
        return [v for v in self.versions if v.starred]
