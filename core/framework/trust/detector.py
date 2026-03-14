"""Repository trust detector.

This module provides functionality to determine if a project repository
should be trusted based on git configuration and user settings.
"""

from __future__ import annotations

import configparser
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import TrustStore, get_all_remote_urls, get_project_remote_url

logger = logging.getLogger("framework.trust.detector")

DEFAULT_TRUSTED_ORGS = ["github.com"]


def get_git_config_value(key: str, project_path: Path | None = None) -> str | None:
    """Get a git config value.

    Args:
        key: The config key (e.g., 'user.email')
        project_path: Path to check project git config first. Defaults to None.

    Returns:
        The config value, or None if not found
    """
    try:
        if project_path and (project_path / ".git").exists():
            result = subprocess.run(
                ["git", "config", "--local", key],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        result = subprocess.run(
            ["git", "config", "--global", key],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def get_gitconfig_path() -> Path | None:
    """Get the global git config file path."""
    try:
        result = subprocess.run(
            ["git", "config", "--global", "--list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "gitdir:" in line.lower():
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        gitdir = Path(parts[1].strip())
                        return gitdir.parent / ".gitconfig"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return Path.home() / ".gitconfig"


def get_configured_trusted_orgs() -> list[str]:
    """Get trusted orgs from git config and Hive configuration.

    Reads from:
    1. ~/.hive/configuration.json -> trusted_orgs
    2. ~/.gitconfig -> trustedorgs (comma-separated)

    Returns:
        List of org/domain strings to auto-trust
    """
    orgs = set()

    try:
        from framework.config import get_trusted_orgs

        config_orgs = get_trusted_orgs()
        orgs.update(config_orgs)
    except ImportError:
        try:
            from framework.config import get_hive_config

            config = get_hive_config()
            config_orgs = config.get("trusted_orgs", [])
            orgs.update(config_orgs)
        except Exception:
            pass

    gitconfig_path = get_gitconfig_path()
    if gitconfig_path and gitconfig_path.exists():
        try:
            parser = configparser.ConfigParser()
            parser.read(gitconfig_path)

            if parser.has_option("trustedorgs", "orgs"):
                orgs_str = parser.get("trustedorgs", "orgs")
                orgs.update(o.strip() for o in orgs_str.split(",") if o.strip())

            if parser.has_option("trustedorgs", "domains"):
                domains_str = parser.get("trustedorgs", "domains")
                orgs.update(d.strip() for d in domains_str.split(",") if d.strip())
        except Exception as e:
            logger.debug("Failed to parse gitconfig: %s", e)

    return list(orgs) if orgs else DEFAULT_TRUSTED_ORGS


def extract_org_from_url(url: str) -> str | None:
    """Extract organization/domain from a git URL.

    Handles:
    - https://github.com/org/repo
    - git@github.com:org/repo
    - ssh://git@gitlab.company.com/org/repo

    Args:
        url: The git remote URL

    Returns:
        The org/company part of the URL, or None
    """
    if not url:
        return None

    url = url.lower().strip()
    if url.endswith(".git"):
        url = url[:-4]

    if "://" in url:
        parts = url.split("/")
        if len(parts) >= 3:
            host = parts[2] if parts[0] else parts[1]
            if "@" in host:
                host = host.split("@")[-1]
            idx = url.index(host) + len(host)
            if len(parts) > idx:
                after_host = url[idx + 1:]
                if "/" in after_host:
                    return after_host.split("/")[0]
            return host
    elif ":" in url and "@" not in url.split(":")[0]:
        parts = url.split(":")
        if len(parts) >= 2:
            return parts[0]
    elif "@" in url:
        parts = url.split(":")
        if len(parts) == 2:
            host_and_org = parts[1]
            if "/" in host_and_org:
                return host_and_org.split("/")[0]

    return None


@dataclass
class TrustStatus:
    """Represents the trust status of a project."""

    is_trusted: bool
    remote_url: str | None
    all_remote_urls: list[str]
    reason: str
    matched_org: str | None = None


def check_project_trust(
    project_path: Path | str | None,
    trust_store: TrustStore | None = None,
) -> TrustStatus:
    """Check if a project should be trusted.

    Args:
        project_path: Path to the project
        trust_store: TrustStore instance. If None, uses default.

    Returns:
        TrustStatus with trust decision details
    """
    if trust_store is None:
        trust_store = TrustStore()

    project_path = Path(project_path) if project_path else Path.cwd()

    remote_url = get_project_remote_url(project_path)
    all_remote_urls = get_all_remote_urls(project_path)

    if not remote_url and not all_remote_urls:
        return TrustStatus(
            is_trusted=True,
            remote_url=None,
            all_remote_urls=[],
            reason="Local project (no git remote)",
        )

    current_url = remote_url or all_remote_urls[0] if all_remote_urls else None

    if trust_store.is_trusted(current_url or ""):
        return TrustStatus(
            is_trusted=True,
            remote_url=current_url,
            all_remote_urls=all_remote_urls,
            reason="Repository is explicitly trusted",
        )

    trusted_orgs = get_configured_trusted_orgs()

    for url in all_remote_urls:
        org = extract_org_from_url(url)
        if org:
            for trusted_org in trusted_orgs:
                if trusted_org.lower() in url.lower():
                    return TrustStatus(
                        is_trusted=True,
                        remote_url=current_url,
                        all_remote_urls=all_remote_urls,
                        reason=f"Matches trusted org/domain: {trusted_org}",
                        matched_org=trusted_org,
                    )

    return TrustStatus(
        is_trusted=False,
        remote_url=current_url,
        all_remote_urls=all_remote_urls,
        reason="Repository is not in trusted list and does not match any trusted orgs",
    )


def is_project_trusted(
    project_path: Path | str | None = None,
    trust_store: TrustStore | None = None,
) -> bool:
    """Check if a project is trusted.

    Args:
        project_path: Path to the project. Defaults to current directory.
        trust_store: TrustStore instance.

    Returns:
        True if the project should be trusted
    """
    status = check_project_trust(project_path, trust_store)
    return status.is_trusted
