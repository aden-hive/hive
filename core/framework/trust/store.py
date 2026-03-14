"""Trust store for managing trusted repositories.

This module provides functionality to manage trusted repositories for skill loading.
Project-level skills from untrusted repositories require explicit user consent before loading.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("framework.trust")


@dataclass
class TrustedRepo:
    """Represents a trusted repository."""

    remote_url: str
    trusted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    permanent: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "trusted_at": self.trusted_at.isoformat(),
            "permanent": self.permanent,
        }

    @classmethod
    def from_dict(cls, remote_url: str, data: dict[str, Any]) -> TrustedRepo:
        """Create from dictionary."""
        return cls(
            remote_url=remote_url,
            trusted_at=datetime.fromisoformat(data["trusted_at"]),
            permanent=data.get("permanent", False),
        )


class TrustStore:
    """Manages trusted repository storage.

    Stores trusted repo information in ~/.hive/trusted_repos.json
    """

    DEFAULT_FILE = "~/.hive/trusted_repos.json"

    def __init__(self, storage_path: str | Path | None = None):
        """Initialize trust store.

        Args:
            storage_path: Path to trusted repos JSON file. Defaults to ~/.hive/trusted_repos.json
        """
        self._storage_path = Path(storage_path or self.DEFAULT_FILE).expanduser()
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """Ensure the storage file exists."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._storage_path.exists():
            self._save({"version": "1.0", "trusted_repos": {}})

    def _load(self) -> dict[str, Any]:
        """Load trusted repos from storage."""
        try:
            with open(self._storage_path, encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load trust store: %s", e)
            return {"version": "1.0", "trusted_repos": {}}

    def _save(self, data: dict[str, Any]) -> None:
        """Save trusted repos to storage."""
        with open(self._storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def is_trusted(self, remote_url: str) -> bool:
        """Check if a repository is trusted.

        Args:
            remote_url: The git remote URL to check

        Returns:
            True if the repository is trusted
        """
        normalized = self._normalize_url(remote_url)
        data = self._load()
        trusted_repos = data.get("trusted_repos", {})
        return normalized in trusted_repos or self._any_url_matches(normalized, trusted_repos)

    def _normalize_url(self, url: str) -> str:
        """Normalize git URL for comparison.

        Handles:
        - HTTPS vs SSH URLs
        - .git suffix
        - Trailing slashes
        """
        if not url:
            return ""

        normalized = url.lower().strip()
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        if normalized.endswith("/"):
            normalized = normalized[:-1]

        if normalized.startswith("git@"):
            normalized = normalized.replace("git@", "https://")

        if normalized.startswith("ssh://git@"):
            normalized = normalized.replace("ssh://git@", "https://")

        return normalized

    def _any_url_matches(self, normalized: str, trusted: dict[str, Any]) -> bool:
        """Check if any trusted URL matches the given URL."""
        for trusted_url in trusted.keys():
            trusted_normalized = self._normalize_url(trusted_url)
            if normalized == trusted_normalized:
                return True
            if trusted_normalized in normalized or normalized in trusted_normalized:
                return True
        return False

    def trust(self, remote_url: str, permanent: bool = False) -> None:
        """Add a repository to the trusted list.

        Args:
            remote_url: The git remote URL to trust
            permanent: If True, trust forever. If False, trust for current session only.
        """
        normalized = self._normalize_url(remote_url)
        data = self._load()

        trusted_repo = TrustedRepo(
            remote_url=normalized,
            trusted_at=datetime.now(UTC),
            permanent=permanent,
        )

        data["trusted_repos"][normalized] = trusted_repo.to_dict()
        self._save(data)

        logger.info(
            "Trusted repository '%s' (permanent=%s)",
            normalized,
            permanent,
        )

    def untrust(self, remote_url: str) -> bool:
        """Remove a repository from the trusted list.

        Args:
            remote_url: The git remote URL to untrust

        Returns:
            True if the repository was removed, False if it wasn't trusted
        """
        normalized = self._normalize_url(remote_url)
        data = self._load()
        trusted_repos = data.get("trusted_repos", {})

        if normalized in trusted_repos:
            del trusted_repos[normalized]
            self._save(data)
            logger.info("Removed '%s' from trusted repositories", normalized)
            return True

        for url in list(trusted_repos.keys()):
            if self._normalize_url(url) == normalized:
                del trusted_repos[url]
                self._save(data)
                logger.info("Removed '%s' from trusted repositories", normalized)
                return True

        return False

    def list_trusted(self) -> list[TrustedRepo]:
        """List all trusted repositories.

        Returns:
            List of TrustedRepo objects
        """
        data = self._load()
        trusted_repos = data.get("trusted_repos", {})
        return [
            TrustedRepo.from_dict(url, info)
            for url, info in trusted_repos.items()
        ]

    def clear_session_trusted(self) -> int:
        """Clear all non-permanent trusted repos (session-only).

        Returns:
            Number of repos cleared
        """
        data = self._load()
        trusted_repos = data.get("trusted_repos", {})
        to_remove = [
            url for url, info in trusted_repos.items()
            if not info.get("permanent", False)
        ]
        for url in to_remove:
            del trusted_repos[url]

        self._save(data)
        logger.info("Cleared %d session-trusted repositories", len(to_remove))
        return len(to_remove)


def get_trust_store() -> TrustStore:
    """Get the default trust store instance."""
    return TrustStore()


def get_project_remote_url(project_path: Path | str | None = None) -> str | None:
    """Get the git remote URL for a project.

    Args:
        project_path: Path to the project. Defaults to current directory.

    Returns:
        The remote URL, or None if not a git repo or no remote
    """
    if project_path is None:
        project_path = Path.cwd()
    else:
        project_path = Path(project_path)

    git_dir = project_path / ".git"
    if not git_dir.exists():
        logger.debug("Not a git repository: %s", project_path)
        return None

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            logger.debug("Found remote URL for %s: %s", project_path, url)
            return url
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.warning("Failed to get git remote URL: %s", e)

    return None


def get_all_remote_urls(project_path: Path | str | None = None) -> list[str]:
    """Get all git remote URLs for a project.

    Args:
        project_path: Path to the project. Defaults to current directory.

    Returns:
        List of remote URLs
    """
    if project_path is None:
        project_path = Path.cwd()
    else:
        project_path = Path(project_path)

    git_dir = project_path / ".git"
    if not git_dir.exists():
        return []

    try:
        result = subprocess.run(
            ["git", "remote"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        remotes = result.stdout.strip().split("\n")
        urls = []
        for remote in remotes:
            if not remote.strip():
                continue
            url_result = subprocess.run(
                ["git", "remote", "get-url", remote.strip()],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if url_result.returncode == 0:
                urls.append(url_result.stdout.strip())

        return urls
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
