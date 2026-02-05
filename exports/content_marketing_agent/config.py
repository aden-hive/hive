"""Configuration for Content Marketing Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ContentMarketingConfig:
    """Configuration settings for the Content Marketing Agent."""

    # LLM Settings
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.7
    max_tokens: int = 4096

    # Quality thresholds
    quality_threshold: float = 0.7  # Minimum quality score for human review
    max_revision_attempts: int = 3  # Max rewrites before escalation

    # Brand voice settings
    brand_name: str = "Acme Corp"
    brand_voice: str = "professional, innovative, approachable"
    target_audience: str = "tech-savvy business professionals"

    # WordPress settings (optional)
    wordpress_url: str = field(default_factory=lambda: os.environ.get("WORDPRESS_URL", ""))
    wordpress_token: str = field(default_factory=lambda: os.environ.get("WORDPRESS_TOKEN", ""))

    # News sources
    rss_feeds: list[str] = field(default_factory=lambda: [
        "https://news.ycombinator.com/rss",
    ])


def load_config() -> ContentMarketingConfig:
    """Load configuration from environment variables."""
    return ContentMarketingConfig(
        model=os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514"),
        brand_name=os.environ.get("BRAND_NAME", "Acme Corp"),
        brand_voice=os.environ.get("BRAND_VOICE", "professional, innovative, approachable"),
        target_audience=os.environ.get("TARGET_AUDIENCE", "tech-savvy business professionals"),
    )
