"""Memory compatibility utilities.

This module provides utilities for checking memory schema and key compatibility
during agent graph validation.
"""

from __future__ import annotations

from typing import Any, List, Optional


class MemoryCompatibilityChecker:
    """Checker for memory schema and key compatibility.

    This class provides utilities for validating memory keys used by agent graphs.
    """

    @staticmethod
    def check_memory_keys_compatibility(
        required_keys: List[str],
        existing_keys: List[str],
    ) -> dict[str, Any]:
        """Check memory key compatibility between old and new graphs.

        Args:
            required_keys: List of memory keys required by the new graph.
            existing_keys: List of memory keys in the current state.

        Returns:
            Dictionary with memory compatibility check results.
        """
        result = {
            "required_keys": required_keys,
            "existing_keys": existing_keys,
            "missing_keys": [],
            "extra_keys": [],
            "renamed_keys": [],
            "is_compatible": True,
            "migration_needed": False,
        }

        required_set = set(required_keys)
        existing_set = set(existing_keys)

        result["missing_keys"] = sorted(required_set - existing_set)
        result["extra_keys"] = sorted(existing_set - required_set)

        # Check for renamed keys
        result["renamed_keys"] = MemoryCompatibilityChecker._find_renamed_keys(
            existing_keys,
            required_keys,
        )

        # Check compatibility
        if result["missing_keys"]:
            result["is_compatible"] = False
            result["migration_needed"] = True

        return result

    @staticmethod
    def check_memory_schema_compatibility(
        old_schema: dict[str, Any],
        new_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Check if memory schemas are compatible.

        Args:
            old_schema: Old memory schema.
            new_schema: New memory schema.

        Returns:
            Dictionary with schema compatibility check results.
        """
        result = {
            "is_compatible": True,
            "added_fields": [],
            "removed_fields": [],
            "changed_fields": [],
            "warnings": [],
        }

        old_keys = set(old_schema.keys())
        new_keys = set(new_schema.keys())

        result["added_fields"] = sorted(new_keys - old_keys)
        result["removed_fields"] = sorted(old_keys - new_keys)

        # Check for changed fields
        for key in new_keys & old_keys:
            old_value = old_schema.get(key)
            new_value = new_schema.get(key)

            if old_value != new_value:
                result["changed_fields"].append(
                    {
                        "key": key,
                        "old_value": str(old_value),
                        "new_value": str(new_value),
                    }
                )

        # Check for critical changes that might break compatibility
        if result["removed_fields"]:
            result["is_compatible"] = False
            result["warnings"].append(
                f"Schema removes {len(result['removed_fields'])} field(s): "
                f"{', '.join(result['removed_fields'])}"
            )

        return result

    @staticmethod
    def detect_memory_key_patterns(keys: List[str]) -> dict[str, List[str]]:
        """Detect patterns in memory key names.

        Args:
            keys: List of memory key names.

        Returns:
            Dictionary mapping patterns to lists of keys.
        """
        patterns = {
            "user_data": [],
            "session_data": [],
            "agent_state": [],
            "temp_data": [],
            "config_data": [],
            "default_keys": [],
        }

        for key in keys:
            key_lower = key.lower()

            if "user" in key_lower and ("data" in key_lower or "info" in key_lower):
                patterns["user_data"].append(key)
            elif "session" in key_lower and ("data" in key_lower or "state" in key_lower):
                patterns["session_data"].append(key)
            elif "agent" in key_lower and ("state" in key_lower or "info" in key_lower):
                patterns["agent_state"].append(key)
            elif "temp" in key_lower or "temp_" in key_lower:
                patterns["temp_data"].append(key)
            elif "config" in key_lower and ("data" in key_lower or "settings" in key_lower):
                patterns["config_data"].append(key)
            else:
                patterns["default_keys"].append(key)

        return patterns

    @staticmethod
    def format_memory_key_report(
        compatibility_result: dict[str, Any],
        verbose: bool = False,
    ) -> str:
        """Format memory compatibility check result as a readable string.

        Args:
            compatibility_result: Memory compatibility check result.
            verbose: Whether to include detailed information.

        Returns:
            Formatted report string.
        """
        lines = ["Memory Key Compatibility Check"]

        if compatibility_result["is_compatible"]:
            lines.append("✓ Memory keys are compatible")
        else:
            lines.append("✗ Memory keys have compatibility issues")

            if compatibility_result["missing_keys"]:
                lines.append(f"  Missing keys: {', '.join(compatibility_result['missing_keys'])}")

            if compatibility_result["renamed_keys"]:
                lines.append(f"  Renamed keys: {', '.join(compatibility_result['renamed_keys'])}")

        if verbose and compatibility_result["added_keys"]:
            lines.append(f"\nAdded keys: {', '.join(compatibility_result['added_keys'])}")

        if verbose and compatibility_result["removed_keys"]:
            lines.append(f"Removed keys: {', '.join(compatibility_result['removed_keys'])}")

        return "\n".join(lines)


class MemoryMigrationHelper:
    """Helper for memory migration scenarios."""

    @staticmethod
    def get_migration_strategy(
        compatibility_result: dict[str, Any],
    ) -> str:
        """Get recommended migration strategy for memory keys.

        Args:
            compatibility_result: Memory compatibility check result.

        Returns:
            Migration strategy description.
        """
        if not compatibility_result["missing_keys"]:
            return "No migration needed. Memory keys are compatible."

        if compatibility_result["renamed_keys"]:
            strategy = "Generate new keys with default values and remap old data."
        else:
            strategy = "Generate new keys with default values or migrate existing data."

        return strategy

    @staticmethod
    def create_memory_migration_map(
        old_keys: List[str],
        new_keys: List[str],
    ) -> dict[str, str]:
        """Create a mapping from old key names to new key names.

        Args:
            old_keys: List of old memory keys.
            new_keys: List of new memory keys.

        Returns:
            Dictionary mapping old keys to new keys.
        """
        migration_map = {}

        old_set = set(old_keys)
        new_set = set(new_keys)

        for new_key in new_keys:
            if new_key in old_set:
                old_key = [
                    key for key in old_keys if key.endswith(new_key) or new_key.endswith(key)
                ]
                if old_key:
                    migration_map[old_key[0]] = new_key

        return migration_map

    @staticmethod
    def validate_memory_migration(
        migration_map: dict[str, str],
        old_keys: List[str],
        new_keys: List[str],
    ) -> bool:
        """Validate that a migration map is valid.

        Args:
            migration_map: Migration mapping from old keys to new keys.
            old_keys: List of old memory keys.
            new_keys: List of new memory keys.

        Returns:
            True if migration map is valid.
        """
        # Check that all old keys are either in migration map or missing
        old_set = set(old_keys)
        new_set = set(new_keys)

        mapped_old_keys = set(migration_map.keys())
        unmapped_old_keys = old_set - mapped_old_keys - new_set

        # Check that all new keys are either in migration map or new
        unmapped_new_keys = new_set - mapped_old_keys - old_set

        return not unmapped_old_keys and not unmapped_new_keys

    @staticmethod
    def generate_default_values(
        missing_keys: List[str],
        key_type: str = "string",
    ) -> dict[str, Any]:
        """Generate default values for missing memory keys.

        Args:
            missing_keys: List of missing key names.
            key_type: Type of keys to generate values for.

        Returns:
            Dictionary mapping key names to default values.
        """
        defaults = {}

        for key in missing_keys:
            key_lower = key.lower()

            if "config" in key_lower or "settings" in key_lower:
                defaults[key] = {}
            elif "data" in key_lower or "info" in key_lower:
                if key_type == "string":
                    defaults[key] = ""
                else:
                    defaults[key] = None
            elif "state" in key_lower:
                if key_type == "string":
                    defaults[key] = "initialized"
                else:
                    defaults[key] = None
            else:
                if key_type == "string":
                    defaults[key] = ""
                else:
                    defaults[key] = None

        return defaults

    @staticmethod
    def detect_memory_key_style(keys: List[str]) -> str:
        """Detect the style of memory key naming.

        Args:
            keys: List of memory key names.

        Returns:
            Style identifier.
        """
        if not keys:
            return "unknown"

        key_lower = keys[0].lower()

        if "_" in key_lower:
            return "snake_case"
        elif key_lower[0].isupper():
            return "PascalCase"
        else:
            return "camelCase"

    @staticmethod
    def format_key_style_suggestion(
        current_style: str,
        suggested_style: str = "snake_case",
    ) -> str:
        """Format a key style suggestion.

        Args:
            current_style: Current key style.
            suggested_style: Suggested key style.

        Returns:
            Formatted suggestion.
        """
        return (
            f"Memory keys use {current_style}. Consider migrating to {suggested_style} "
            f"for better consistency and readability."
        )
