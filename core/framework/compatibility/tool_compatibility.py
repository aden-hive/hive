"""Tool compatibility utilities.

This module provides utilities for checking tool availability and schema compatibility
during agent graph validation.
"""

from __future__ import annotations

from typing import Any, List, Optional


class ToolCompatibilityChecker:
    """Checker for tool availability and schema compatibility.

    This class provides utilities for validating tools used by agent graphs.
    """

    @staticmethod
    def check_tool_availability(
        required_tools: List[str],
        available_tools: List[str],
    ) -> dict[str, Any]:
        """Check if required tools are available.

        Args:
            required_tools: List of tools that must be available.
            available_tools: List of tools that are currently available.

        Returns:
            Dictionary with tool availability check results.
        """
        result = {
            "required_tools": required_tools,
            "available_tools": available_tools,
            "missing_tools": [],
            "extra_tools": [],
            "is_complete": True,
            "tools_by_category": {},
        }

        required_set = set(required_tools)
        available_set = set(available_tools)

        result["missing_tools"] = sorted(required_set - available_set)
        result["extra_tools"] = sorted(available_set - required_set)

        if result["missing_tools"]:
            result["is_complete"] = False

        # Group tools by category
        for tool in required_tools:
            category = ToolCompatibilityChecker._get_tool_category(tool)
            if category not in result["tools_by_category"]:
                result["tools_by_category"][category] = []
            result["tools_by_category"][category].append(tool)

        return result

    @staticmethod
    def check_tool_schema_compatibility(
        required_tools: List[str],
        available_tools: List[str],
    ) -> bool:
        """Check if required tool schemas are compatible.

        Args:
            required_tools: List of required tool names.
            available_tools: List of available tool names.

        Returns:
            True if all required tools are available.
        """
        required_set = set(required_tools)
        available_set = set(available_tools)
        return required_set.issubset(available_set)

    @staticmethod
    def get_tool_schemas(tools: List[str]) -> dict[str, Any]:
        """Get schema information for tools.

        Args:
            tools: List of tool names.

        Returns:
            Dictionary mapping tool names to their schemas.
        """
        schemas = {}

        for tool in tools:
            schemas[tool] = ToolCompatibilityChecker._get_tool_schema(tool)

        return schemas

    @staticmethod
    def detect_deprecated_tools(tools: List[str]) -> List[str]:
        """Identify deprecated tools in a list.

        Args:
            tools: List of tool names.

        Returns:
            List of deprecated tool names.
        """
        deprecated_patterns = [
            "_deprecated",
            "_legacy",
            "_old",
            "_archived",
        ]

        deprecated_tools = []
        for tool in tools:
            for pattern in deprecated_patterns:
                if pattern in tool.lower():
                    if tool not in deprecated_tools:
                        deprecated_tools.append(tool)
                    break

        return deprecated_tools

    @staticmethod
    def check_tool_categories(
        tools: List[str],
    ) -> dict[str, int]:
        """Group tools by category.

        Args:
            tools: List of tool names.

        Returns:
            Dictionary mapping categories to tool counts.
        """
        categories = {}

        for tool in tools:
            category = ToolCompatibilityChecker._get_tool_category(tool)
            categories[category] = categories.get(category, 0) + 1

        return categories

    @staticmethod
    def _get_tool_category(tool: str) -> str:
        """Get the category of a tool.

        Args:
            tool: Tool name.

        Returns:
            Tool category name.
        """
        tool_lower = tool.lower()

        if "memory" in tool_lower or "store" in tool_lower:
            return "storage"
        elif "network" in tool_lower or "http" in tool_lower or "api" in tool_lower:
            return "network"
        elif "search" in tool_lower or "find" in tool_lower:
            return "search"
        elif "compute" in tool_lower or "calculate" in tool_lower:
            return "compute"
        elif "mcp" in tool_lower:
            return "mcp"
        elif "custom" in tool_lower:
            return "custom"
        else:
            return "general"

    @staticmethod
    def _get_tool_schema(tool: str) -> dict[str, Any]:
        """Get schema information for a specific tool.

        Args:
            tool: Tool name.

        Returns:
            Tool schema dictionary.
        """
        # This is a placeholder implementation
        # In a real implementation, this would query the tool registry
        # to get actual schema information

        return {
            "name": tool,
            "description": f"Tool: {tool}",
            "parameters": {},
            "required": [],
            "deprecated": False,
        }

    @staticmethod
    def format_tool_availability_report(
        check_result: dict[str, Any],
        verbose: bool = False,
    ) -> str:
        """Format tool availability check result as a readable string.

        Args:
            check_result: Tool availability check result.
            verbose: Whether to include detailed information.

        Returns:
            Formatted report string.
        """
        lines = ["Tool Availability Check"]

        if check_result["is_complete"]:
            lines.append("✓ All required tools are available")
        else:
            lines.append("✗ Some required tools are missing")
            if check_result["missing_tools"]:
                lines.append(f"  Missing tools: {', '.join(check_result['missing_tools'])}")

        if verbose and check_result["tools_by_category"]:
            lines.append("\nTools by category:")
            for category, tools in check_result["tools_by_category"].items():
                lines.append(f"  {category}: {len(tools)} tool(s)")

        return "\n".join(lines)


class ToolMigrationHelper:
    """Helper for tool migration scenarios."""

    @staticmethod
    def get_migration_suggestions(
        missing_tools: List[str],
        available_tools: List[str],
    ) -> List[str]:
        """Get migration suggestions for missing tools.

        Args:
            missing_tools: List of missing tool names.
            available_tools: List of available tool names.

        Returns:
            List of migration suggestions.
        """
        suggestions = []

        for missing_tool in missing_tools:
            # Check for alternative tools
            alternatives = ToolMigrationHelper._find_alternatives(
                missing_tool,
                available_tools,
            )

            if alternatives:
                suggestions.append(
                    f"Tool '{missing_tool}' is missing. Alternative tools available: "
                    f"{', '.join(alternatives)}"
                )
            else:
                suggestions.append(
                    f"Tool '{missing_tool}' is missing. No alternatives available. "
                    "Consider implementing this tool or finding an alternative."
                )

        return suggestions

    @staticmethod
    def _find_alternatives(
        tool_name: str,
        available_tools: List[str],
    ) -> List[str]:
        """Find alternative tools for a missing tool.

        Args:
            tool_name: Name of the missing tool.
            available_tools: List of available tools.

        Returns:
            List of alternative tool names.
        """
        alternatives = []

        # Try removing suffixes to find alternatives
        suffixes = ["_v2", "_v3", "_new", "_latest", "_modern", "_updated"]

        for alt_tool in available_tools:
            # Check if tool names are similar
            if (
                alt_tool.replace("_v2", "").replace("_v3", "")
                == tool_name.replace("_v2", "").replace("_v3", "")
                and alt_tool != tool_name
            ):
                alternatives.append(alt_tool)

        return alternatives
