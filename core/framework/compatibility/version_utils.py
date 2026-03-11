"""Version utilities for compatibility contract.

This module provides version comparison and parsing utilities for validating
compatibility between different agent graph versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Version:
    """Version representation with major, minor, and patch components.

    Attributes:
        major: Major version component.
        minor: Minor version component.
        patch: Patch version component.
    """

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Return version string in 'major.minor.patch' format."""
        return f"{self.major}.{self.minor}.{self.patch}"

    def __repr__(self) -> str:
        """Return repr of version."""
        return f"Version({self.major}, {self.minor}, {self.patch})"

    def __eq__(self, other: Any) -> bool:
        """Compare versions for equality."""
        if not isinstance(other, Version):
            return False
        return (self.major, self.minor, self.patch) == (
            other.major,
            other.minor,
            other.patch,
        )

    def __lt__(self, other: Any) -> bool:
        """Compare versions for less than."""
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (
            other.major,
            other.minor,
            other.patch,
        )

    def __le__(self, other: Any) -> bool:
        """Compare versions for less than or equal."""
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) <= (
            other.major,
            other.minor,
            other.patch,
        )

    def __gt__(self, other: Any) -> bool:
        """Compare versions for greater than."""
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) > (
            other.major,
            other.minor,
            other.patch,
        )

    def __ge__(self, other: Any) -> bool:
        """Compare versions for greater than or equal."""
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) >= (
            other.major,
            other.minor,
            other.patch,
        )

    def compare(self, other: Version) -> int:
        """Compare versions and return comparison result.

        Args:
            other: Version to compare against.

        Returns:
            -1 if self < other
            0 if self == other
            1 if self > other
        """
        if self < other:
            return -1
        elif self > other:
            return 1
        else:
            return 0


def parse_version(version_str: str | None) -> Version:
    """Parse a version string into a Version object.

    Args:
        version_str: Version string in 'major.minor.patch' format.

    Returns:
        Version object representing the parsed version.

    Raises:
        ValueError: If version string is invalid or not parsable.
    """
    if version_str is None:
        return Version(1, 0, 0)

    version_str = str(version_str).strip()

    # Handle special version strings
    if version_str.lower() == "latest" or version_str.lower() == "head":
        return Version(99, 99, 99)

    if version_str.lower() == "stable":
        return Version(1, 0, 0)

    # Parse version string
    parts = version_str.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"Invalid version string '{version_str}'. Expected format 'major.minor.patch'."
        )

    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])

        # Validate components
        if major < 0 or minor < 0 or patch < 0:
            raise ValueError("Version components must be non-negative")

        return Version(major, minor, patch)

    except ValueError as e:
        raise ValueError(f"Invalid version string '{version_str}': {e}")


def compare_versions(version1: str | None, version2: str | None) -> int:
    """Compare two version strings.

    Args:
        version1: First version string.
        version2: Second version string.

    Returns:
        -1 if version1 < version2
        0 if version1 == version2
        1 if version1 > version2
    """
    v1 = parse_version(version1)
    v2 = parse_version(version2)
    return v1.compare(v2)


def is_version_newer(version_str: str | None, reference: str | None) -> bool:
    """Check if a version is newer than a reference version.

    Args:
        version_str: Version string to check.
        reference: Reference version string.

    Returns:
        True if version_str is newer than reference.
    """
    v = parse_version(version_str)
    ref = parse_version(reference)
    return v > ref


def is_version_same(version_str: str | None, reference: str | None) -> bool:
    """Check if a version is the same as a reference version.

    Args:
        version_str: Version string to check.
        reference: Reference version string.

    Returns:
        True if versions are the same.
    """
    return compare_versions(version_str, reference) == 0


def is_version_older(version_str: str | None, reference: str | None) -> bool:
    """Check if a version is older than a reference version.

    Args:
        version_str: Version string to check.
        reference: Reference version string.

    Returns:
        True if version_str is older than reference.
    """
    v = parse_version(version_str)
    ref = parse_version(reference)
    return v < ref


def extract_version_from_string(text: str) -> str | None:
    """Extract version from text using regex patterns.

    Args:
        text: Text to extract version from.

    Returns:
        Extracted version string or None.
    """
    import re

    # Pattern to match major.minor.patch
    version_pattern = r"(\d+\.\d+\.\d+)"
    matches = re.findall(version_pattern, text)

    if matches:
        # Return the first match
        return matches[0]

    return None


def format_version_info(
    version: str | None,
    current: str | None,
    latest: str | None,
) -> str:
    """Format version information for display.

    Args:
        version: Current version.
        current: Version in current use.
        latest: Latest available version.

    Returns:
        Formatted version string.
    """
    version_info = f"Current: {version or 'unknown'}"

    if current:
        version_info += f" | Installed: {current}"

    if latest:
        if compare_versions(latest, version or current) > 0:
            version_info += f" | Update available: {latest}"
        else:
            version_info += f" | Latest: {latest}"

    return version_info
