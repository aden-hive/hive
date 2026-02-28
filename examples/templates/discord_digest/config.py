"""Runtime configuration for Discord Community Digest."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from framework.config import RuntimeConfig

default_config = RuntimeConfig()

DEFAULT_STORAGE = Path.home() / ".hive" / "discord_digest"
CONFIG_FILENAME = "config.json"


@dataclass
class AgentMetadata:
    name: str = "Discord Community Digest"
    version: str = "1.0.0"
    description: str = (
        "Monitor Discord servers, categorize messages by priority, "
        "and deliver an actionable summary as a Discord DM."
    )
    intro_message: str = (
        "Hi! I'm your Discord digest assistant. I'll scan your Discord servers "
        "and put together a summary of what needs your attention. "
        "Let me ask a few questions to get set up."
    )


metadata = AgentMetadata()


@dataclass
class UserConfig:
    """User preferences for digest generation."""

    servers: list[str] = field(default_factory=lambda: ["all"])
    channels: list[str] = field(default_factory=lambda: ["all"])
    lookback_days: int = 3
    keywords: list[str] = field(
        default_factory=lambda: ["agent", "integration", "PR", "bug", "release"]
    )
    user_id: str = ""


def save_user_config(config: UserConfig, storage_path: Path | None = None) -> Path:
    """Save user config to disk. Returns the path written."""
    path = (storage_path or DEFAULT_STORAGE) / CONFIG_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "servers": config.servers,
                "channels": config.channels,
                "lookback_days": config.lookback_days,
                "keywords": config.keywords,
                "user_id": config.user_id,
            },
            f,
            indent=2,
        )
    return path


def load_user_config(storage_path: Path | None = None) -> UserConfig | None:
    """Load saved user config from disk. Returns None if not found."""
    path = (storage_path or DEFAULT_STORAGE) / CONFIG_FILENAME
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return UserConfig(**data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None
