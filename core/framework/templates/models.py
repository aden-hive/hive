"""Template metadata models for the Hive template library."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TemplateCategory(Enum):
    """Categories for organizing templates."""

    SALES = "sales"
    SUPPORT = "support"
    OPS = "ops"
    RESEARCH = "research"
    GROWTH = "growth"
    PRODUCTIVITY = "productivity"
    DEVELOPMENT = "development"
    HR = "hr"
    FINANCE = "finance"
    MARKETING = "marketing"
    GENERAL = "general"

    @classmethod
    def from_string(cls, value: str | None) -> TemplateCategory:
        """Convert a string to a TemplateCategory, defaulting to GENERAL."""
        if value is None:
            return cls.GENERAL
        try:
            return cls(value.lower())
        except ValueError:
            return cls.GENERAL

    def display_name(self) -> str:
        """Return a human-readable category name."""
        special_cases = {"hr": "HR", "ops": "Ops"}
        return special_cases.get(self.value, self.value.title())


@dataclass
class TemplateMetadata:
    """Metadata for a template agent."""

    id: str
    name: str
    description: str
    category: TemplateCategory
    tags: list[str] = field(default_factory=list)
    author: str = "Hive Team"
    version: str = "1.0.0"
    node_count: int = 0
    tool_count: int = 0
    required_tools: list[str] = field(default_factory=list)
    popularity: int = 0
    path: Path | None = None

    def to_dict(self) -> dict:
        """Convert metadata to a dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "tags": self.tags,
            "author": self.author,
            "version": self.version,
            "node_count": self.node_count,
            "tool_count": self.tool_count,
            "required_tools": self.required_tools,
            "popularity": self.popularity,
        }

    @classmethod
    def from_dict(cls, data: dict, path: Path | None = None) -> TemplateMetadata:
        """Create TemplateMetadata from a dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=TemplateCategory.from_string(data.get("category", "general")),
            tags=data.get("tags", []),
            author=data.get("author", "Hive Team"),
            version=data.get("version", "1.0.0"),
            node_count=data.get("node_count", 0),
            tool_count=data.get("tool_count", 0),
            required_tools=data.get("required_tools", []),
            popularity=data.get("popularity", 0),
            path=path,
        )
