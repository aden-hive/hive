"""Compatibility validator for agent graphs and runtime components.

This module provides comprehensive validation to check that evolved agent graphs
are compatible with the existing runtime environment, tools, and memory schemas.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type, Set

from pydantic import BaseModel, ValidationError, field_validator

from .version_utils import parse_version


class CompatibilityResult(BaseModel):
    """Result of a compatibility validation check.

    Attributes:
        is_compatible: Whether the agent graph is compatible with the runtime.
        errors: List of compatibility errors (blocking issues).
        warnings: List of compatibility warnings (non-blocking issues).
        version_check: Version compatibility details.
        tool_check: Tool availability and schema details.
        memory_check: Memory schema and key compatibility details.
        runtime_check: Runtime feature support details.
        breaking_changes: List of breaking changes detected.
    """

    is_compatible: bool = False
    errors: List[str] = []
    warnings: List[str] = []
    version_check: Optional[VersionCheckResult] = None
    tool_check: Optional[ToolCheckResult] = None
    memory_check: Optional[MemoryCheckResult] = None
    runtime_check: Optional[RuntimeCheckResult] = None
    breaking_changes: List[str] = []

    @field_validator("errors", "warnings", mode="before")
    @classmethod
    def convert_to_list(cls, v: Any) -> List[str]:
        """Convert errors and warnings to list format."""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [str(v)]

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)
        self.is_compatible = False

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)

    def get_summary(self) -> str:
        """Get a summary of the compatibility check."""
        if self.is_compatible:
            return f"Compatible ✓ ({len(self.warnings)} warnings)"
        else:
            return f"Incompatible ✗ ({len(self.errors)} errors, {len(self.warnings)} warnings)"


class VersionCheckResult(BaseModel):
    """Version compatibility check result.

    Attributes:
        old_version: Original graph version.
        new_version: Evolved graph version.
        is_compatible: Whether versions are compatible.
        is_backward_compatible: Whether new version supports old version.
        is_forward_compatible: Whether old version supports new version.
        migration_needed: Whether migration is required.
        migration_path: Recommended migration path if needed.
    """

    old_version: str = "1.0.0"
    new_version: str = "1.0.0"
    is_compatible: bool = True
    is_backward_compatible: bool = True
    is_forward_compatible: bool = True
    migration_needed: bool = False
    migration_path: str = ""

    @property
    def version_diff(self) -> Optional[tuple[int, int, int]]:
        """Get the version difference as (major, minor, patch)."""
        try:
            old = parse_version(self.old_version)
            new = parse_version(self.new_version)
            return (new.major - old.major, new.minor - old.minor, new.patch - old.patch)
        except (ValueError, AttributeError):
            return None


class ToolCheckResult(BaseModel):
    """Tool availability and schema compatibility check result.

    Attributes:
        required_tools: List of tools that must be available.
        available_tools: List of tools that are currently available.
        missing_tools: List of tools that are missing.
        deprecated_tools: List of tools that are deprecated.
        schema_compatible: Whether tool schemas are compatible.
        migration_available: Whether tools can be migrated.
    """

    required_tools: List[str] = []
    available_tools: List[str] = []
    missing_tools: List[str] = []
    deprecated_tools: List[str] = []
    schema_compatible: bool = True
    migration_available: bool = False


class MemoryCheckResult(BaseModel):
    """Memory schema and key compatibility check result.

    Attributes:
        old_memory_keys: Memory keys in the old state.
        new_memory_keys: Memory keys in the new graph.
        added_keys: Memory keys that were added.
        removed_keys: Memory keys that were removed.
        renamed_keys: Memory keys that were renamed.
        schema_compatible: Whether memory schemas are compatible.
        migration_needed: Whether memory migration is needed.
        migration_strategy: Recommended migration strategy.
    """

    old_memory_keys: List[str] = []
    new_memory_keys: List[str] = []
    added_keys: List[str] = []
    removed_keys: List[str] = []
    renamed_keys: List[str] = []
    schema_compatible: bool = True
    migration_needed: bool = False
    migration_strategy: str = ""


class RuntimeCheckResult(BaseModel):
    """Runtime feature support check result.

    Attributes:
        runtime_features: List of features required by the graph.
        supported_features: List of features supported by the runtime.
        unsupported_features: List of features not supported by the runtime.
        is_full_supported: Whether runtime fully supports all features.
    """

    runtime_features: List[str] = []
    supported_features: List[str] = []
    unsupported_features: List[str] = []
    is_full_supported: bool = True


class EvolutionValidationResult(BaseModel):
    """Complete validation result for graph evolution.

    Attributes:
        graph_version_check: Version compatibility details.
        tool_check: Tool availability and schema details.
        memory_check: Memory schema and key compatibility details.
        runtime_check: Runtime feature support details.
        breaking_changes: List of breaking changes detected.
        compatibility_result: Combined compatibility result.
    """

    graph_version_check: VersionCheckResult = VersionCheckResult()
    tool_check: ToolCheckResult = ToolCheckResult()
    memory_check: MemoryCheckResult = MemoryCheckResult()
    runtime_check: RuntimeCheckResult = RuntimeCheckResult()
    breaking_changes: List[str] = []
    compatibility_result: CompatibilityResult = CompatibilityResult()

    def is_compatible(self) -> bool:
        """Return True if no blocking errors are present."""
        return self.compatibility_result.is_compatible


class RuntimeCheckResult(BaseModel):
    """Runtime feature support check result.

    Attributes:
        runtime_features: List of features required by the graph.
        supported_features: List of features supported by the runtime.
        unsupported_features: List of features not supported by the runtime.
        is_full_supported: Whether runtime fully supports all features.
    """

    runtime_features: List[str] = []
    supported_features: List[str] = []
    unsupported_features: List[str] = []
    is_full_supported: bool = True


class CompatibilityValidator:
    """Validates that evolved agent graphs are compatible with the runtime.

    This class provides comprehensive checks to ensure that agent graphs can
    safely execute with existing tools, memory schemas, and runtime features.
    """

    def __init__(
        self,
        available_tools: Optional[List[str]] = None,
        memory_keys: Optional[List[str]] = None,
        runtime_features: Optional[Set[str]] = None,
    ):
        """Initialize the compatibility validator.

        Args:
            available_tools: List of tools that are currently available.
            memory_keys: List of memory keys that exist in the current state.
            runtime_features: Set of features supported by the runtime.
        """
        self.available_tools = available_tools or []
        self.memory_keys = memory_keys or []
        self.runtime_features = runtime_features or set()

    def validate_graph(
        self,
        graph: Any,
        old_graph: Optional[Any] = None,
    ) -> CompatibilityResult:
        """Validate a graph's compatibility with the runtime.

        Args:
            graph: The new GraphSpec to validate.
            old_graph: Optional old GraphSpec for evolution comparison.

        Returns:
            CompatibilityResult with validation details.
        """
        result = CompatibilityResult()

        # Perform version compatibility check
        result.version_check = self._check_version_compatibility(graph, old_graph)
        result.tool_check = self._check_tool_compatibility(graph)
        result.memory_check = self._check_memory_compatibility(graph)
        result.runtime_check = self._check_runtime_compatibility(graph)

        # Check for breaking changes
        if old_graph:
            result.breaking_changes = self._check_breaking_changes(old_graph, graph)
            if result.breaking_changes:
                result.add_error(
                    f"Detected {len(result.breaking_changes)} breaking change(s): "
                    f"{', '.join(result.breaking_changes)}"
                )

        # Determine overall compatibility
        result.is_compatible = (
            not result.errors
            and result.version_check.is_compatible
            and result.tool_check.schema_compatible
            and result.memory_check.schema_compatible
            and result.runtime_check.is_full_supported
        )

        return result

    def _check_version_compatibility(
        self, graph: Any, old_graph: Optional[Any]
    ) -> VersionCheckResult:
        """Check version compatibility between graphs.

        Args:
            graph: New graph to check.
            old_graph: Old graph for comparison (if evolving).

        Returns:
            VersionCheckResult with compatibility details.
        """
        result = VersionCheckResult()

        old_version = self._get_version(old_graph) if old_graph else "1.0.0"
        new_version = self._get_version(graph) or "1.0.0"

        result.old_version = old_version
        result.new_version = new_version

        try:
            old_parsed = parse_version(old_version)
            new_parsed = parse_version(new_version)

            # Check if versions are compatible
            result.is_compatible = self._are_versions_compatible(old_parsed, new_parsed)

            # Check backward compatibility
            result.is_backward_compatible = self._is_backward_compatible(old_parsed, new_parsed)

            # Check forward compatibility
            result.is_forward_compatible = self._is_forward_compatible(old_parsed, new_parsed)

            # Determine if migration is needed
            if not result.is_backward_compatible:
                result.migration_needed = True
                result.migration_path = self._get_migration_path(old_parsed, new_parsed)

        except (ValueError, AttributeError):
            result.add_error(f"Unable to parse version: {old_version} and {new_version}")

        return result

    def _check_tool_compatibility(self, graph: Any) -> ToolCheckResult:
        """Check tool availability and schema compatibility.

        Args:
            graph: Graph to check for tool compatibility.

        Returns:
            ToolCheckResult with tool compatibility details.
        """
        result = ToolCheckResult()

        # Extract required tools from graph
        required_tools = self._get_required_tools(graph)
        result.required_tools = required_tools
        result.available_tools = self.available_tools

        # Check for missing tools
        result.missing_tools = [tool for tool in required_tools if tool not in self.available_tools]

        # Check for deprecated tools
        result.deprecated_tools = self._get_deprecated_tools(required_tools)

        # Check schema compatibility
        result.schema_compatible = not result.missing_tools
        result.migration_available = len(result.missing_tools) > 0

        return result

    def _check_memory_compatibility(self, graph: Any) -> MemoryCheckResult:
        """Check memory schema and key compatibility.

        Args:
            graph: Graph to check for memory compatibility.

        Returns:
            MemoryCheckResult with memory compatibility details.
        """
        result = MemoryCheckResult()

        # Extract memory keys from graph
        new_memory_keys = self._get_memory_keys(graph)
        result.new_memory_keys = new_memory_keys

        # Check for key changes
        result.added_keys = [key for key in new_memory_keys if key not in self.memory_keys]
        result.removed_keys = [key for key in self.memory_keys if key not in new_memory_keys]
        result.renamed_keys = self._get_renamed_keys(self.memory_keys, new_memory_keys)

        # Check schema compatibility
        result.schema_compatible = not result.removed_keys
        result.migration_needed = bool(result.removed_keys)

        if result.removed_keys:
            result.migration_strategy = (
                "Generate missing keys with default values or adapt to new schema."
            )

        return result

    def _check_runtime_compatibility(self, graph: Any) -> RuntimeCheckResult:
        """Check runtime feature support.

        Args:
            graph: Graph to check for runtime compatibility.

        Returns:
            RuntimeCheckResult with runtime compatibility details.
        """
        result = RuntimeCheckResult()

        # Extract runtime features from graph
        result.runtime_features = self._get_runtime_features(graph)
        result.supported_features = list(self.runtime_features)
        result.unsupported_features = [
            feature for feature in result.runtime_features if feature not in self.runtime_features
        ]

        result.is_full_supported = not result.unsupported_features

        return result

    def _check_breaking_changes(self, old_graph: Any, new_graph: Any) -> List[str]:
        """Check for breaking changes between old and new graph.

        Args:
            old_graph: Old graph to compare against.
            new_graph: New graph to check.

        Returns:
            List of breaking change descriptions.
        """
        changes: List[str] = []

        # Check for removed nodes
        old_nodes = self._get_node_ids(old_graph)
        new_nodes = self._get_node_ids(new_graph)
        removed_nodes = old_nodes - new_nodes

        if removed_nodes:
            changes.append(
                f"Removed {len(removed_nodes)} node(s): {', '.join(sorted(removed_nodes))}"
            )

        # Check for node type changes
        old_node_types = self._get_node_types(old_graph)
        new_node_types = self._get_node_types(new_graph)

        for node_id in new_nodes:
            if node_id in old_nodes:
                old_type = old_node_types.get(node_id, "unknown")
                new_type = new_node_types.get(node_id, "unknown")
                if old_type != new_type and new_type in ["event_loop", "gcu"]:
                    changes.append(
                        f"Node '{node_id}' changed type from '{old_type}' to '{new_type}'"
                    )

        # Check for removed tools from nodes
        old_tools = self._get_tools_from_nodes(old_graph)
        new_tools = self._get_tools_from_nodes(new_graph)
        removed_tools = old_tools - new_tools

        if removed_tools:
            changes.append(
                f"Removed tool(s) from node configuration: {', '.join(sorted(removed_tools))}"
            )

        return changes

    def _are_versions_compatible(self, old_version: Any, new_version: Any) -> bool:
        """Check if versions are compatible.

        Args:
            old_version: Parsed old version.
            new_version: Parsed new version.

        Returns:
            True if versions are compatible.
        """
        # Major version must match
        if old_version.major != new_version.major:
            return False

        # Minor version must be compatible (new >= old, or old < 0)
        if new_version.minor < 0 or new_version.minor < old_version.minor:
            return False

        # Patch version must be compatible
        if new_version.patch < 0 or new_version.patch < old_version.patch:
            return False

        return True

    def _is_backward_compatible(self, old_version: Any, new_version: Any) -> bool:
        """Check if new version is backward compatible with old version.

        Args:
            old_version: Parsed old version.
            new_version: Parsed new version.

        Returns:
            True if backward compatible.
        """
        # New version should be >= old version
        if (new_version.major, new_version.minor, new_version.patch) >= (
            old_version.major,
            old_version.minor,
            old_version.patch,
        ):
            return True

        return False

    def _is_forward_compatible(self, old_version: Any, new_version: Any) -> bool:
        """Check if old version is forward compatible with new version.

        Args:
            old_version: Parsed old version.
            new_version: Parsed new version.

        Returns:
            True if forward compatible.
        """
        # New version should be <= old version for forward compatibility
        if (new_version.major, new_version.minor, new_version.patch) <= (
            old_version.major,
            old_version.minor,
            old_version.patch,
        ):
            return True

        return False

    def _get_migration_path(self, old_version: Any, new_version: Any) -> Optional[str]:
        """Get recommended migration path between versions.

        Args:
            old_version: Parsed old version.
            new_version: Parsed new version.

        Returns:
            Recommended migration path.
        """
        major_diff = new_version.major - old_version.major
        minor_diff = new_version.minor - old_version.minor
        patch_diff = new_version.patch - old_version.patch

        if major_diff > 0:
            return "Major version bump: Graph needs to be migrated or configuration updated."
        if minor_diff > 0:
            return "Minor version bump: Update memory keys and adapt to new schema."
        if patch_diff > 0:
            return "Patch version bump: Update for minor changes."

        return "Standard backward compatibility: Graph should work as-is."

    def _get_version(self, graph: Any) -> Optional[str]:
        """Extract version from graph.

        Args:
            graph: Graph to extract version from.

        Returns:
            Version string or None.
        """
        if hasattr(graph, "version"):
            return graph.version
        if hasattr(graph, "schema_version"):
            return graph.schema_version
        return None

    def _get_required_tools(self, graph: Any) -> List[str]:
        """Extract required tools from graph.

        Args:
            graph: Graph to extract tools from.

        Returns:
            List of required tool names.
        """
        tools = []

        if hasattr(graph, "nodes"):
            for node in graph.nodes:
                if hasattr(node, "tools"):
                    tools.extend(node.tools)

        return list(set(tools))

    def _get_memory_keys(self, graph: Any) -> List[str]:
        """Extract memory keys from graph.

        Args:
            graph: Graph to extract memory keys from.

        Returns:
            List of memory key names.
        """
        keys = []

        if hasattr(graph, "nodes"):
            for node in graph.nodes:
                if hasattr(node, "output_keys"):
                    keys.extend(node.output_keys)

        return list(set(keys))

    def _get_runtime_features(self, graph: Any) -> List[str]:
        """Extract runtime features required by graph.

        Args:
            graph: Graph to extract features from.

        Returns:
            List of required features.
        """
        features = []

        if hasattr(graph, "async_entry_points"):
            features.append("async_concurrent_execution")

        if hasattr(graph, "loop_config"):
            features.append("event_loop_node")

        if hasattr(graph, "terminal_nodes"):
            features.append("terminal_nodes")

        return features

    def _get_node_ids(self, graph: Any) -> Set[str]:
        """Extract node IDs from graph.

        Args:
            graph: Graph to extract node IDs from.

        Returns:
            Set of node IDs.
        """
        node_ids = set()

        if hasattr(graph, "nodes"):
            for node in graph.nodes:
                if hasattr(node, "id"):
                    node_ids.add(node.id)

        return node_ids

    def _get_node_types(self, graph: Any) -> Dict[str, str]:
        """Extract node types from graph.

        Args:
            graph: Graph to extract node types from.

        Returns:
            Dictionary mapping node IDs to types.
        """
        node_types = {}

        if hasattr(graph, "nodes"):
            for node in graph.nodes:
                if hasattr(node, "id") and hasattr(node, "node_type"):
                    node_types[node.id] = node.node_type

        return node_types

    def _get_tools_from_nodes(self, graph: Any) -> Set[str]:
        """Extract all tools used by nodes in graph.

        Args:
            graph: Graph to extract tools from.

        Returns:
            Set of tool names.
        """
        tools = set()

        if hasattr(graph, "nodes"):
            for node in graph.nodes:
                if hasattr(node, "tools"):
                    tools.update(node.tools)

        return tools

    def _get_deprecated_tools(self, tools: List[str]) -> List[str]:
        """Identify deprecated tools.

        Args:
            tools: List of tool names.

        Returns:
            List of deprecated tool names.
        """
        # Tools ending with _deprecated or _legacy
        deprecated = [
            tool for tool in tools if tool.endswith("_deprecated") or tool.endswith("_legacy")
        ]

        # Common deprecated tools
        common_deprecated = [
            "old_tool",
            "legacy_tool",
            "deprecated_feature",
        ]

        # Check if any common deprecated tools are used
        found_deprecated = [tool for tool in common_deprecated if tool in tools]

        return list(set(deprecated + found_deprecated))

    def _get_renamed_keys(self, old_keys: List[str], new_keys: List[str]) -> List[str]:
        """Identify renamed memory keys.

        Args:
            old_keys: List of old memory keys.
            new_keys: List of new memory keys.

        Returns:
            List of renamed keys in format "old_name -> new_name".
        """
        renamed = []

        old_set = set(old_keys)
        new_set = set(new_keys)

        for new_key in new_keys:
            if new_key in old_set:
                old_key = [k for k in old_keys if k.endswith(new_key) or new_key.endswith(k)]
                if old_key:
                    renamed.append(f"{old_key[0]} -> {new_key}")

        return renamed


def is_compatible(
    graph: Any,
    available_tools: Optional[List[str]] = None,
    memory_keys: Optional[List[str]] = None,
    runtime_features: Optional[Set[str]] = None,
    old_graph: Optional[Any] = None,
) -> CompatibilityResult:
    """Check if a graph is compatible with the runtime.

    This is a convenience function that creates a validator and checks compatibility.

    Args:
        graph: GraphSpec to check.
        available_tools: List of tools available in runtime.
        memory_keys: List of memory keys in current state.
        runtime_features: Set of features supported by runtime.
        old_graph: Optional old graph for evolution comparison.

    Returns:
        CompatibilityResult with validation details.
    """
    validator = CompatibilityValidator(
        available_tools=available_tools,
        memory_keys=memory_keys,
        runtime_features=runtime_features,
    )
    return validator.validate_graph(graph, old_graph)


def validate_agent_compatibility(
    graph: Any,
    agent_runtime: Any,
    old_graph: Optional[Any] = None,
) -> CompatibilityResult:
    """Validate agent compatibility using runtime instance.

    This function uses an agent runtime instance to extract current state
    and validates the graph against it.

    Args:
        graph: New GraphSpec to validate.
        agent_runtime: AgentRuntime instance.
        old_graph: Optional old graph for evolution comparison.

    Returns:
        CompatibilityResult with validation details.
    """
    available_tools = []
    memory_keys = []
    runtime_features = set()

    if hasattr(agent_runtime, "tools"):
        available_tools = agent_runtime.tools

    if hasattr(agent_runtime, "shared_memory"):
        memory_keys = agent_runtime.shared_memory._data.keys()

    if hasattr(agent_runtime, "_runtime_features"):
        runtime_features = agent_runtime._runtime_features

    return is_compatible(
        graph=graph,
        available_tools=available_tools,
        memory_keys=memory_keys,
        runtime_features=runtime_features,
        old_graph=old_graph,
    )


def validate_graph_evolution(old_graph: Any, new_graph: Any) -> EvolutionValidationResult:
    """Validate that an evolved graph is compatible with the old graph.

    This function specifically checks for graph evolution compatibility
    including breaking changes and migration requirements.

    Args:
        old_graph: Original graph.
        new_graph: Evolved graph.

    Returns:
        EvolutionValidationResult with evolution details.
    """
    validator = CompatibilityValidator()
    result = validator.validate_graph(new_graph, old_graph)

    evolution_result = EvolutionValidationResult()
    evolution_result.graph_version_check = result.version_check
    evolution_result.tool_check = result.tool_check
    evolution_result.memory_check = result.memory_check
    evolution_result.runtime_check = result.runtime_check
    evolution_result.breaking_changes = result.breaking_changes
    evolution_result.compatibility_result = result

    return evolution_result
