"""Runtime configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _twitter_post_mode() -> str:
    """Load TWITTER_POST_MODE from env; must be 'draft' or 'live'."""
    raw = os.environ.get("TWITTER_POST_MODE", "draft").strip().lower()
    return raw if raw in ("draft", "live") else "draft"


def _load_preferred_model() -> str:
    """Load preferred model from ~/.hive/configuration.json."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            llm = config.get("llm", {})
            if llm.get("provider") and llm.get("model"):
                return f"{llm['provider']}/{llm['model']}"
        except Exception:
            pass
    return "anthropic/claude-sonnet-4-20250514"


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=_load_preferred_model)
    temperature: float = 0.7
    max_tokens: int = 8000
    api_key: str | None = None
    api_base: str | None = None
    # Twitter posting: draft (default) or live
    twitter_post_mode: str = field(default_factory=_twitter_post_mode)
    twitter_bearer_token: str | None = field(
        default_factory=lambda: os.environ.get("TWITTER_BEARER_TOKEN") or None
    )
    twitter_api_key: str | None = field(
        default_factory=lambda: os.environ.get("TWITTER_API_KEY") or None
    )
    twitter_api_secret: str | None = field(
        default_factory=lambda: os.environ.get("TWITTER_API_SECRET") or None
    )
    twitter_access_token: str | None = field(
        default_factory=lambda: os.environ.get("TWITTER_ACCESS_TOKEN") or None
    )
    twitter_access_secret: str | None = field(
        default_factory=lambda: os.environ.get("TWITTER_ACCESS_SECRET") or None
    )


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "RSS-to-Twitter Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated content repurposing from RSS feeds to Twitter threads. "
        "Fetches articles from configured RSS feeds, extracts key points, "
        "and generates engaging Twitter threads for user review."
    )


metadata = AgentMetadata()
