"""Worker profile data model and per-colony persistence.

A colony today has a single worker template at ``{colony_dir}/worker.json``
spawned as N parallel clones with identical tools, prompt, and credentials.
Worker profiles let the queen declare multiple templates per colony, each
with its own credential aliases (e.g. one profile pinned to Slack workspace
"work" and another to "personal").

Layout::

    {COLONIES_DIR}/{colony_name}/
        worker.json                       # legacy / "default" profile
        profiles/
            slack-work/worker.json
            slack-personal/worker.json
        metadata.json                     # has worker_profiles: [{...}, ...]

The default profile keeps living at ``{colony_dir}/worker.json`` so existing
colonies and code that hardcodes that path stay correct. Named profiles live
under ``profiles/<name>/`` and are read through :func:`worker_spec_path`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from framework.config import COLONIES_DIR
from framework.host.colony_metadata import (
    colony_metadata_path,
    load_colony_metadata,
    update_colony_metadata,
)

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_NAME = "default"
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass
class WorkerProfile:
    """Template for a worker spawned within a colony.

    ``integrations`` maps provider id (``slack``, ``google``, ``github``…) to
    the alias of the connected account this profile should use. The runtime
    sets these aliases as defaults on MCP tool calls; an explicit
    ``account="..."`` argument on a call still wins.
    """

    name: str
    task: str = ""
    skill_name: str = ""
    integrations: dict[str, str] = field(default_factory=dict)
    concurrency_hint: int | None = None
    prompt_override: str | None = None
    tool_filter: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop None / empty fields so on-disk metadata stays tidy.
        if d.get("prompt_override") is None:
            d.pop("prompt_override", None)
        if d.get("tool_filter") is None:
            d.pop("tool_filter", None)
        if d.get("concurrency_hint") is None:
            d.pop("concurrency_hint", None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerProfile:
        return cls(
            name=str(data.get("name", "")).strip(),
            task=str(data.get("task", "")),
            skill_name=str(data.get("skill_name", "")),
            integrations={str(k): str(v) for k, v in (data.get("integrations") or {}).items() if str(k) and str(v)},
            concurrency_hint=(
                int(data["concurrency_hint"])
                if isinstance(data.get("concurrency_hint"), int) and data["concurrency_hint"] > 0
                else None
            ),
            prompt_override=(data.get("prompt_override") or None),
            tool_filter=list(data["tool_filter"]) if isinstance(data.get("tool_filter"), list) else None,
        )


def validate_profile_name(name: str) -> str | None:
    """Return an error message if ``name`` is invalid, else ``None``."""
    if not isinstance(name, str) or not _PROFILE_NAME_RE.match(name):
        return (
            "profile name must be lowercase alphanumeric (with - or _), "
            "start with a letter/digit, and be ≤64 characters"
        )
    return None


def worker_spec_path(colony_name: str, profile_name: str | None = None) -> Path:
    """Return the on-disk path to a profile's ``worker.json``.

    The default / unnamed profile lives at ``{colony_dir}/worker.json``
    (legacy location). Named profiles live at
    ``{colony_dir}/profiles/{profile_name}/worker.json``.
    """
    colony_dir = COLONIES_DIR / colony_name
    if not profile_name or profile_name == DEFAULT_PROFILE_NAME:
        return colony_dir / "worker.json"
    return colony_dir / "profiles" / profile_name / "worker.json"


def list_worker_profiles(colony_name: str) -> list[WorkerProfile]:
    """Return the colony's declared worker profiles.

    Legacy colonies (no ``worker_profiles`` field in metadata.json) get a
    synthetic single-entry list with the default profile, so dispatch logic
    elsewhere can treat the profile registry as always non-empty.
    """
    metadata = load_colony_metadata(colony_name)
    raw = metadata.get("worker_profiles")
    if not isinstance(raw, list) or not raw:
        return [WorkerProfile(name=DEFAULT_PROFILE_NAME)]
    profiles: list[WorkerProfile] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        profile = WorkerProfile.from_dict(entry)
        if not profile.name or profile.name in seen:
            continue
        if validate_profile_name(profile.name) is not None:
            logger.warning(
                "worker_profiles: skipping invalid profile name %r in colony %s",
                profile.name,
                colony_name,
            )
            continue
        seen.add(profile.name)
        profiles.append(profile)
    if not profiles:
        return [WorkerProfile(name=DEFAULT_PROFILE_NAME)]
    return profiles


def get_worker_profile(colony_name: str, profile_name: str) -> WorkerProfile | None:
    """Return one profile by name, or ``None`` if not declared."""
    for profile in list_worker_profiles(colony_name):
        if profile.name == profile_name:
            return profile
    return None


def save_worker_profiles(colony_name: str, profiles: list[WorkerProfile]) -> list[WorkerProfile]:
    """Persist ``profiles`` to the colony's metadata.json.

    Validates names, deduplicates, and refuses to write an empty list (use
    the default profile representation instead). Returns the canonicalized
    list as written.
    """
    if not colony_metadata_path(colony_name).parent.exists():
        raise FileNotFoundError(f"Colony '{colony_name}' not found")

    canonical: list[WorkerProfile] = []
    seen: set[str] = set()
    for profile in profiles:
        err = validate_profile_name(profile.name)
        if err is not None:
            raise ValueError(err)
        if profile.name in seen:
            raise ValueError(f"duplicate worker profile name: {profile.name!r}")
        seen.add(profile.name)
        canonical.append(profile)
    if not canonical:
        canonical = [WorkerProfile(name=DEFAULT_PROFILE_NAME)]
    update_colony_metadata(colony_name, {"worker_profiles": [p.to_dict() for p in canonical]})
    return canonical


def upsert_worker_profile(colony_name: str, profile: WorkerProfile) -> list[WorkerProfile]:
    """Insert or replace a single profile, preserving siblings."""
    err = validate_profile_name(profile.name)
    if err is not None:
        raise ValueError(err)
    existing = list_worker_profiles(colony_name)
    out = [p for p in existing if p.name != profile.name]
    out.append(profile)
    return save_worker_profiles(colony_name, out)


def delete_worker_profile(colony_name: str, profile_name: str) -> bool:
    """Remove a profile by name. Returns True if a profile was removed.

    Refuses to remove the default profile so dispatch always has a fallback.
    """
    if profile_name == DEFAULT_PROFILE_NAME:
        raise ValueError("cannot delete the default worker profile")
    existing = list_worker_profiles(colony_name)
    out = [p for p in existing if p.name != profile_name]
    if len(out) == len(existing):
        return False
    save_worker_profiles(colony_name, out)
    return True
