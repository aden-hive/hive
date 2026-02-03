"""Agent versioning schemas"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BumpType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class VersionStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class AgentVersion(BaseModel):
    """Versioned snapshot of an agent's graph and goal"""

    version: str
    agent_id: str
    graph_data: dict[str, Any]
    goal_data: dict[str, Any]
    description: str
    created_at: datetime = Field(default_factory=datetime.now)
    created_by: str | None = None
    status: VersionStatus = VersionStatus.ACTIVE
    tags: list[str] = Field(default_factory=list)
    parent_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class VersionDiff(BaseModel):
    """Comparison between two versions showing what changed"""

    from_version: str
    to_version: str
    agent_id: str

    nodes_added: list[str] = Field(default_factory=list)
    nodes_removed: list[str] = Field(default_factory=list)
    nodes_modified: list[dict[str, Any]] = Field(default_factory=list)

    edges_added: list[str] = Field(default_factory=list)
    edges_removed: list[str] = Field(default_factory=list)
    edges_modified: list[dict[str, Any]] = Field(default_factory=list)

    success_criteria_changed: bool = False
    constraints_changed: bool = False
    capabilities_changed: bool = False

    summary: str = ""

    model_config = {"extra": "allow"}


class VersionRegistry(BaseModel):
    """Tracks all versions and tags for an agent"""

    agent_id: str
    versions: list[str] = Field(default_factory=list)
    current_version: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class ABTestConfig(BaseModel):
    """A/B test configuration for comparing two versions"""

    agent_id: str
    version_a: str
    version_b: str
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0)
    metrics: list[str] = Field(default_factory=list)
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class ABTestResult(BaseModel):
    """Results and metrics from an A/B test"""

    config: ABTestConfig
    executions_a: int = 0
    executions_b: int = 0
    metrics_a: dict[str, float] = Field(default_factory=dict)
    metrics_b: dict[str, float] = Field(default_factory=dict)
    winner: str | None = None
    confidence: float | None = None
    notes: str = ""

    model_config = {"extra": "allow"}
