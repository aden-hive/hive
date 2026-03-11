"""Tests for agent execution compatibility contract.

This test suite validates the compatibility contract for evolved agent graphs,
ensuring that version compatibility, tool availability, and memory schema
compatibility are properly checked.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from framework.compatibility import (
    CompatibilityResult,
    CompatibilityValidator,
    EvolutionValidationResult,
    is_compatible,
    validate_agent_compatibility,
    validate_graph_evolution,
)
from framework.compatibility.version_utils import (
    Version,
    compare_versions,
    extract_version_from_string,
    format_version_info,
    is_version_older,
    is_version_same,
    is_version_newer,
    parse_version,
)
from framework.compatibility.compatibility import (
    VersionCheckResult,
    ToolCheckResult,
    MemoryCheckResult,
    RuntimeCheckResult,
)


class TestVersionParsing:
    """Test version parsing utilities."""

    def test_parse_valid_version(self):
        """Test parsing a valid version string."""
        version = parse_version("1.2.3")
        assert isinstance(version, Version)
        assert version.major == 1
        assert version.minor == 2
        assert version.patch == 3
        assert str(version) == "1.2.3"

    def test_parse_version_with_extra_whitespace(self):
        """Test parsing version with extra whitespace."""
        version = parse_version("  2.0.0  ")
        assert version.major == 2
        assert version.minor == 0
        assert version.patch == 0

    def test_parse_version_latest(self):
        """Test parsing special 'latest' version."""
        version = parse_version("latest")
        assert version.major == 99
        assert version.minor == 99
        assert version.patch == 99

    def test_parse_version_stable(self):
        """Test parsing special 'stable' version."""
        version = parse_version("stable")
        assert version.major == 1
        assert version.minor == 0
        assert version.patch == 0

    def test_parse_version_none(self):
        """Test parsing None version."""
        version = parse_version(None)
        assert version.major == 1
        assert version.minor == 0
        assert version.patch == 0

    def test_parse_invalid_version(self):
        """Test parsing invalid version string."""
        with pytest.raises(ValueError):
            parse_version("invalid")

    def test_parse_version_without_patch(self):
        """Test parsing version without patch component."""
        with pytest.raises(ValueError):
            parse_version("1.2")

    def test_parse_version_negative_components(self):
        """Test parsing version with negative components."""
        with pytest.raises(ValueError):
            parse_version("1.2.-1")

    def test_compare_versions_equal(self):
        """Test comparing equal versions."""
        assert compare_versions("1.2.3", "1.2.3") == 0

    def test_compare_versions_newer(self):
        """Test comparing newer version."""
        assert compare_versions("2.0.0", "1.2.3") == 1
        assert compare_versions("1.3.0", "1.2.3") == 1
        assert compare_versions("1.2.4", "1.2.3") == 1

    def test_compare_versions_older(self):
        """Test comparing older version."""
        assert compare_versions("1.2.3", "2.0.0") == -1
        assert compare_versions("1.2.3", "1.3.0") == -1
        assert compare_versions("1.2.3", "1.2.4") == -1

    def test_is_version_same(self):
        """Test version equality check."""
        assert is_version_same("1.2.3", "1.2.3")
        assert not is_version_same("1.2.3", "1.2.4")

    def test_is_version_newer(self):
        """Test version newer check."""
        assert is_version_newer("1.2.4", "1.2.3")
        assert not is_version_newer("1.2.3", "1.2.4")

    def test_is_version_older(self):
        """Test version older check."""
        assert is_version_older("1.2.3", "1.2.4")
        assert not is_version_older("1.2.4", "1.2.3")

    def test_extract_version_from_string(self):
        """Test extracting version from text."""
        version = extract_version_from_string("Graph version 1.2.3 released")
        assert version == "1.2.3"

        version = extract_version_from_string("Use version 2.0.0 or later")
        assert version == "2.0.0"

    def test_format_version_info(self):
        """Test formatting version information."""
        info = format_version_info("1.2.3", "1.2.0", "1.3.0")
        assert "1.2.3" in info
        assert "1.2.0" in info
        assert "1.3.0" in info

        info = format_version_info("1.2.3", None, None)
        assert "1.2.3" in info


class TestCompatibilityResult:
    """Test compatibility result model."""

    def test_compatibility_result_initialization(self):
        """Test creating a compatibility result."""
        result = CompatibilityResult()
        assert result.is_compatible is False
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self):
        """Test adding an error."""
        result = CompatibilityResult()
        result.add_error("Test error")
        assert len(result.errors) == 1
        assert result.errors[0] == "Test error"
        assert result.is_compatible is False

    def test_add_warning(self):
        """Test adding a warning."""
        result = CompatibilityResult()
        result.add_warning("Test warning")
        assert len(result.warnings) == 1
        assert result.warnings[0] == "Test warning"
        assert result.is_compatible is False

    def test_get_summary_compatible(self):
        """Test getting summary for compatible result."""
        result = CompatibilityResult()
        result.is_compatible = True
        result.warnings = ["Warning 1", "Warning 2"]
        summary = result.get_summary()
        assert "Compatible" in summary
        assert "2 warnings" in summary

    def test_get_summary_incompatible(self):
        """Test getting summary for incompatible result."""
        result = CompatibilityResult()
        result.is_compatible = False
        result.errors = ["Error 1"]
        result.warnings = ["Warning 1"]
        summary = result.get_summary()
        assert "Incompatible" in summary
        assert "1 errors" in summary
        assert "1 warnings" in summary


class TestCompatibilityValidator:
    """Test compatibility validator."""

    def test_validator_initialization(self):
        """Test creating a compatibility validator."""
        validator = CompatibilityValidator(
            available_tools=["tool1", "tool2"],
            memory_keys=["key1", "key2"],
            runtime_features={"feature1"},
        )
        assert validator.available_tools == ["tool1", "tool2"]
        assert validator.memory_keys == ["key1", "key2"]

    def test_validate_compatible_graph(self):
        """Test validating a compatible graph."""

        class MockGraph:
            version = "1.0.0"
            nodes = []

        validator = CompatibilityValidator(
            available_tools=["tool1", "tool2"],
            memory_keys=["key1", "key2"],
            runtime_features=set(),
        )

        result = validator.validate_graph(MockGraph())
        assert result.is_compatible is True
        assert result.memory_check.schema_compatible is True
        assert result.tool_check.schema_compatible is True

    def test_validate_missing_tools(self):
        """Test validating graph with missing tools."""

        class MockNode:
            def __init__(self, tools):
                self.tools = tools

        class MockGraph:
            version = "1.0.0"
            nodes = [MockNode(tools=["missing_tool"])]

        validator = CompatibilityValidator(
            available_tools=["tool1", "tool2"],
            memory_keys=["key1", "key2"],
        )

        result = validator.validate_graph(MockGraph())
        assert result.is_compatible is False
        assert "missing_tool" in result.tool_check.missing_tools

    def test_validate_missing_memory_keys(self):
        """Test validating graph with missing memory keys."""

        class MockNode:
            def __init__(self, output_keys):
                self.output_keys = output_keys

        class MockGraph:
            version = "1.0.0"
            nodes = [MockNode(output_keys=["new_key"])]

        validator = CompatibilityValidator(
            available_tools=["tool1"],
            memory_keys=["key1", "key2"],
        )

        result = validator.validate_graph(MockGraph())
        assert result.is_compatible is False
        assert result.memory_check.migration_needed is True
        assert "new_key" in result.memory_check.added_keys

    def test_validate_version_compatibility(self):
        """Test version compatibility check."""

        class OldGraph:
            version = "1.0.0"
            nodes = []

        class NewGraph:
            version = "1.1.0"
            nodes = []

        validator = CompatibilityValidator()
        result = validator.validate_graph(NewGraph(), OldGraph())
        assert result.version_check.is_compatible is True
        assert result.version_check.is_backward_compatible is True

    def test_validate_breaking_changes(self):
        """Test detecting breaking changes."""

        class MockNode:
            def __init__(self, id=None, node_type=None, tools=None, output_keys=None):
                self.id = id or "node1"
                self.node_type = node_type or "gcu"
                self.tools = tools or []
                self.output_keys = output_keys or []

        class OldGraph:
            version = "1.0.0"
            nodes = [
                MockNode(id="node1", node_type="gcu"),
                MockNode(id="node2", node_type="gcu"),
            ]

        class NewGraph:
            version = "1.1.0"
            nodes = [
                MockNode(id="node1", node_type="event_loop"),
                MockNode(id="node3", node_type="gcu"),
            ]

        validator = CompatibilityValidator()
        result = validator.validate_graph(NewGraph(), OldGraph())

        assert len(result.breaking_changes) > 0
        assert any("removed" in change.lower() for change in result.breaking_changes)


class TestEvolutionValidationResult:
    """Test evolution validation result."""

    def test_evolution_result_initialization(self):
        """Test creating an evolution validation result."""
        result = EvolutionValidationResult()
        assert result.is_compatible() is True

    def test_evolution_result_with_incompatibilities(self):
        """Test evolution result with incompatibilities."""
        result = EvolutionValidationResult()
        result.compatibility_result.add_error("Test error")
        assert result.is_compatible() is False


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_compatible_simple(self):
        """Test simple compatibility check."""

        class MockGraph:
            version = "1.0.0"
            nodes = []

        result = is_compatible(
            MockGraph(),
            available_tools=["tool1"],
            memory_keys=["key1"],
        )
        assert result.is_compatible is True

    def test_validate_graph_evolution(self):
        """Test graph evolution validation."""

        class OldGraph:
            version = "1.0.0"
            nodes = []

        class NewGraph:
            version = "1.1.0"
            nodes = []

        result = validate_graph_evolution(OldGraph(), NewGraph())
        assert result.is_compatible() is True


class TestVersionCheckResult:
    """Test version check result model."""

    def test_version_check_result_initialization(self):
        """Test initializing version check result."""
        result = VersionCheckResult()
        assert result.old_version == "1.0.0"
        assert result.new_version == "1.0.0"
        assert result.is_compatible is True

    def test_version_check_result_with_versions(self):
        """Test version check with specific versions."""
        result = VersionCheckResult(
            old_version="1.0.0",
            new_version="1.1.0",
        )
        assert result.old_version == "1.0.0"
        assert result.new_version == "1.1.0"
        assert result.is_compatible is True

    def test_version_check_result_migration_needed(self):
        """Test version check with migration needed."""
        result = VersionCheckResult(
            old_version="1.0.0",
            new_version="2.0.0",
        )
        # Migration is needed when new version is different from old version
        assert result.migration_needed is True
        assert result.migration_path is not None

    def test_version_check_result_version_diff(self):
        """Test version difference calculation."""
        result = VersionCheckResult(
            old_version="1.0.0",
            new_version="1.2.3",
        )
        diff = result.version_diff
        assert diff == (0, 2, 3)


class TestToolCheckResult:
    """Test tool check result model."""

    def test_tool_check_result_initialization(self):
        """Test initializing tool check result."""
        result = ToolCheckResult()
        assert result.required_tools == []
        assert result.available_tools == []
        assert result.missing_tools == []
        assert result.schema_compatible is True

    def test_tool_check_result_with_tools(self):
        """Test tool check with tools."""
        result = ToolCheckResult(
            required_tools=["tool1", "tool2"],
            available_tools=["tool1"],
        )
        assert len(result.required_tools) == 2
        assert len(result.available_tools) == 1
        assert "tool1" in result.available_tools
        # When tools are missing, schema_compatible should be False
        assert result.schema_compatible is False
        assert len(result.missing_tools) == 1


class TestMemoryCheckResult:
    """Test memory check result model."""

    def test_memory_check_result_initialization(self):
        """Test initializing memory check result."""
        result = MemoryCheckResult()
        assert result.old_memory_keys == []
        assert result.new_memory_keys == []
        assert result.added_keys == []
        assert result.removed_keys == []
        assert result.schema_compatible is True

    def test_memory_check_result_with_keys(self):
        """Test memory check with keys."""
        result = MemoryCheckResult(
            old_memory_keys=["key1", "key2"],
            new_memory_keys=["key1", "key3"],
        )
        assert len(result.old_memory_keys) == 2
        assert len(result.new_memory_keys) == 2
        # When keys are added, schema_compatible should still be True
        assert result.schema_compatible is True
        assert len(result.added_keys) == 1
        assert len(result.removed_keys) == 1

    def test_memory_check_result_with_removals(self):
        """Test memory check with removed keys."""
        result = MemoryCheckResult(
            old_memory_keys=["key1", "key2"],
            new_memory_keys=["key1"],
        )
        # When keys are removed, schema_compatible should be False
        assert result.schema_compatible is False
        assert result.migration_needed is True
        assert len(result.removed_keys) == 1


class TestRuntimeCheckResult:
    """Test runtime check result model."""

    def test_runtime_check_result_initialization(self):
        """Test initializing runtime check result."""
        result = RuntimeCheckResult()
        assert result.runtime_features == []
        assert result.supported_features == []
        assert result.unsupported_features == []
        assert result.is_full_supported is True

    def test_runtime_check_result_with_features(self):
        """Test runtime check with features."""
        result = RuntimeCheckResult(
            runtime_features=["feature1", "feature2"],
            supported_features=["feature1"],
        )
        assert len(result.runtime_features) == 2
        assert len(result.supported_features) == 1
        assert len(result.unsupported_features) == 1
        assert "feature1" in result.supported_features
        assert "feature2" in result.unsupported_features
        assert result.is_full_supported is False
