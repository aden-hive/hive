"""Agent versioning and rollback"""

import hashlib
import json
from pathlib import Path
from typing import Any

from framework.graph import Goal
from framework.graph.edge import GraphSpec
from framework.schemas.version import (
    ABTestConfig,
    ABTestResult,
    AgentVersion,
    BumpType,
    VersionDiff,
    VersionRegistry,
    VersionStatus,
)


class AgentVersionManager:
    """Manages agent versions with semantic versioning and rollback support"""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _agent_dir(self, agent_id: str) -> Path:
        return self.base_path / agent_id

    def _versions_dir(self, agent_id: str) -> Path:
        return self._agent_dir(agent_id) / "versions"

    def _ab_tests_dir(self, agent_id: str) -> Path:
        return self._agent_dir(agent_id) / "ab_tests"

    def _registry_path(self, agent_id: str) -> Path:
        return self._agent_dir(agent_id) / "registry.json"

    def _version_path(self, agent_id: str, version: str) -> Path:
        return self._versions_dir(agent_id) / f"{version}.json"

    def _load_registry(self, agent_id: str) -> VersionRegistry:
        registry_path = self._registry_path(agent_id)
        if not registry_path.exists():
            return VersionRegistry(agent_id=agent_id)

        with open(registry_path, "r") as f:
            data = json.load(f)
            return VersionRegistry(**data)

    def _save_registry(self, registry: VersionRegistry) -> None:
        registry_path = self._registry_path(registry.agent_id)
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        with open(registry_path, "w") as f:
            json.dump(registry.model_dump(), f, indent=2, default=str)

    def _parse_version(self, version: str) -> tuple[int, int, int]:
        parts = version.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version}. Expected X.Y.Z")
        try:
            return int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            raise ValueError(f"Invalid version format: {version}. Parts must be integers")

    def _bump_version(self, current: str, bump: BumpType) -> str:
        major, minor, patch = self._parse_version(current)

        if bump == BumpType.MAJOR:
            return f"{major + 1}.0.0"
        elif bump == BumpType.MINOR:
            return f"{major}.{minor + 1}.0"
        else:
            return f"{major}.{minor}.{patch + 1}"

    def save_version(
        self,
        agent_id: str,
        graph: GraphSpec,
        goal: Goal,
        description: str,
        bump: BumpType | str = BumpType.PATCH,
        created_by: str | None = None,
        tags: list[str] | None = None,
    ) -> AgentVersion:
        """
        Save a new version of an agent.

        Args:
            agent_id: Agent identifier
            graph: GraphSpec to save
            goal: Goal to save
            description: Description of changes
            bump: Version bump type (major, minor, patch)
            created_by: User creating the version
            tags: Optional tags

        Returns:
            AgentVersion object
        """
        if isinstance(bump, str):
            bump = BumpType(bump)

        registry = self._load_registry(agent_id)

        # Determine new version number
        if not registry.versions:
            new_version = "1.0.0"
            parent_version = None
        else:
            current_version = registry.current_version or registry.versions[-1]
            new_version = self._bump_version(current_version, bump)
            parent_version = current_version

        # Create version object
        version = AgentVersion(
            version=new_version,
            agent_id=agent_id,
            graph_data=graph.model_dump(),
            goal_data=goal.model_dump(),
            description=description,
            created_by=created_by,
            tags=tags or [],
            parent_version=parent_version,
        )

        # Save version file
        version_path = self._version_path(agent_id, new_version)
        version_path.parent.mkdir(parents=True, exist_ok=True)

        with open(version_path, "w") as f:
            json.dump(version.model_dump(), f, indent=2, default=str)

        # Update registry
        registry.versions.append(new_version)
        registry.current_version = new_version
        self._save_registry(registry)

        return version

    def load_version(self, agent_id: str, version: str | None = None) -> AgentVersion:
        """
        Load a specific version of an agent.

        Args:
            agent_id: Agent identifier
            version: Version to load (defaults to current)

        Returns:
            AgentVersion object

        Raises:
            ValueError: If version doesn't exist
        """
        registry = self._load_registry(agent_id)

        if version is None:
            if not registry.current_version:
                raise ValueError(f"No versions found for agent: {agent_id}")
            version = registry.current_version

        if version not in registry.versions:
            raise ValueError(f"Version {version} not found for agent {agent_id}")

        version_path = self._version_path(agent_id, version)
        with open(version_path, "r") as f:
            data = json.load(f)
            return AgentVersion(**data)

    def rollback(
        self, agent_id: str, target_version: str
    ) -> tuple[GraphSpec, Goal]:
        """
        Rollback to a specific version.

        Args:
            agent_id: Agent identifier
            target_version: Version to rollback to

        Returns:
            Tuple of (GraphSpec, Goal)

        Raises:
            ValueError: If target version doesn't exist
        """
        version = self.load_version(agent_id, target_version)

        # Update current version in registry
        registry = self._load_registry(agent_id)
        registry.current_version = target_version
        self._save_registry(registry)

        # Reconstruct GraphSpec and Goal
        graph = GraphSpec(**version.graph_data)
        goal = Goal(**version.goal_data)

        return graph, goal

    def list_versions(self, agent_id: str) -> list[AgentVersion]:
        """
        List all versions for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            List of AgentVersion objects in chronological order
        """
        registry = self._load_registry(agent_id)
        versions = []

        for version_str in registry.versions:
            try:
                version = self.load_version(agent_id, version_str)
                versions.append(version)
            except Exception:
                continue

        return versions

    def compare_versions(
        self, agent_id: str, from_version: str, to_version: str
    ) -> VersionDiff:
        """
        Compare two versions and generate a diff.

        Args:
            agent_id: Agent identifier
            from_version: Starting version
            to_version: Target version

        Returns:
            VersionDiff object describing changes
        """
        v1 = self.load_version(agent_id, from_version)
        v2 = self.load_version(agent_id, to_version)

        diff = VersionDiff(
            from_version=from_version,
            to_version=to_version,
            agent_id=agent_id,
        )

        # Compare nodes
        nodes1 = {n["id"]: n for n in v1.graph_data.get("nodes", [])}
        nodes2 = {n["id"]: n for n in v2.graph_data.get("nodes", [])}

        diff.nodes_added = list(set(nodes2.keys()) - set(nodes1.keys()))
        diff.nodes_removed = list(set(nodes1.keys()) - set(nodes2.keys()))

        for node_id in set(nodes1.keys()) & set(nodes2.keys()):
            if nodes1[node_id] != nodes2[node_id]:
                diff.nodes_modified.append(
                    {"id": node_id, "before": nodes1[node_id], "after": nodes2[node_id]}
                )

        # Compare edges
        edges1 = {
            f"{e.get('from_node')}->{e.get('to_node')}": e
            for e in v1.graph_data.get("edges", [])
        }
        edges2 = {
            f"{e.get('from_node')}->{e.get('to_node')}": e
            for e in v2.graph_data.get("edges", [])
        }

        diff.edges_added = list(set(edges2.keys()) - set(edges1.keys()))
        diff.edges_removed = list(set(edges1.keys()) - set(edges2.keys()))

        for edge_id in set(edges1.keys()) & set(edges2.keys()):
            if edges1[edge_id] != edges2[edge_id]:
                diff.edges_modified.append(
                    {"id": edge_id, "before": edges1[edge_id], "after": edges2[edge_id]}
                )

        # Compare goal components
        diff.success_criteria_changed = (
            v1.goal_data.get("success_criteria") != v2.goal_data.get("success_criteria")
        )
        diff.constraints_changed = (
            v1.goal_data.get("constraints") != v2.goal_data.get("constraints")
        )
        diff.capabilities_changed = (
            v1.goal_data.get("required_capabilities")
            != v2.goal_data.get("required_capabilities")
        )

        # Generate summary
        changes = []
        if diff.nodes_added:
            changes.append(f"{len(diff.nodes_added)} nodes added")
        if diff.nodes_removed:
            changes.append(f"{len(diff.nodes_removed)} nodes removed")
        if diff.nodes_modified:
            changes.append(f"{len(diff.nodes_modified)} nodes modified")
        if diff.edges_added:
            changes.append(f"{len(diff.edges_added)} edges added")
        if diff.edges_removed:
            changes.append(f"{len(diff.edges_removed)} edges removed")
        if diff.edges_modified:
            changes.append(f"{len(diff.edges_modified)} edges modified")
        if diff.success_criteria_changed:
            changes.append("success criteria changed")
        if diff.constraints_changed:
            changes.append("constraints changed")
        if diff.capabilities_changed:
            changes.append("capabilities changed")

        diff.summary = "; ".join(changes) if changes else "No changes detected"

        return diff

    def tag_version(self, agent_id: str, version: str, tag: str) -> None:
        registry = self._load_registry(agent_id)

        if version not in registry.versions:
            raise ValueError(f"Version {version} not found for agent {agent_id}")

        registry.tags[tag] = version
        self._save_registry(registry)

    def get_version_by_tag(self, agent_id: str, tag: str) -> str:
        registry = self._load_registry(agent_id)

        if tag not in registry.tags:
            raise ValueError(f"Tag '{tag}' not found for agent {agent_id}")

        return registry.tags[tag]

    def delete_version(self, agent_id: str, version: str) -> None:
        registry = self._load_registry(agent_id)

        if registry.current_version == version:
            raise ValueError("Cannot delete current version. Rollback first.")

        if version not in registry.versions:
            raise ValueError(f"Version {version} not found for agent {agent_id}")

        agent_version = self.load_version(agent_id, version)
        agent_version.status = VersionStatus.ARCHIVED

        version_path = self._version_path(agent_id, version)
        with open(version_path, "w") as f:
            json.dump(agent_version.model_dump(), f, indent=2, default=str)

    def create_ab_test(
        self,
        agent_id: str,
        version_a: str,
        version_b: str,
        traffic_split: float = 0.5,
        metrics: list[str] | None = None,
    ) -> ABTestConfig:
        self.load_version(agent_id, version_a)
        self.load_version(agent_id, version_b)

        config = ABTestConfig(
            agent_id=agent_id,
            version_a=version_a,
            version_b=version_b,
            traffic_split=traffic_split,
            metrics=metrics or [],
        )

        ab_tests_dir = self._ab_tests_dir(agent_id)
        ab_tests_dir.mkdir(parents=True, exist_ok=True)

        test_id = f"test_{len(list(ab_tests_dir.glob('*.json'))) + 1:03d}"
        config_path = ab_tests_dir / f"{test_id}.json"

        with open(config_path, "w") as f:
            json.dump(config.model_dump(), f, indent=2, default=str)

        return config

    def route_ab_test(self, agent_id: str, request_id: str, config: ABTestConfig) -> str:
        hash_value = int(hashlib.md5(request_id.encode()).hexdigest(), 16)
        normalized = (hash_value % 1000) / 1000.0

        if normalized < config.traffic_split:
            return config.version_a
        else:
            return config.version_b
