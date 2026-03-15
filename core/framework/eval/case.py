"""
EvalCase and EvalSuite — the input schema for the eval system.

Eval cases can be defined in YAML or Python.

YAML example:
    suite: summarisation_eval
    model: claude-haiku-4-5-20251001
    cases:
      - id: basic_summary
        input:
          text: "The quick brown fox jumps over the lazy dog."
        expect:
          contains: ["fox", "dog"]
          max_latency_ms: 5000
      - id: empty_input
        input:
          text: ""
        expect:
          error: true
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EvalExpectation(BaseModel):
    """What we expect from the agent for a given input."""

    # Output content checks
    contains: list[str] = Field(default_factory=list, description="Strings that must appear in output")
    not_contains: list[str] = Field(default_factory=list, description="Strings that must NOT appear")
    exact_match: str | None = Field(default=None, description="Exact expected output string")

    # Behaviour checks
    error: bool = Field(default=False, description="Expect the agent to raise an error")
    min_tools_called: int = Field(default=0, description="Minimum tool calls expected")
    max_tools_called: int | None = Field(default=None, description="Maximum tool calls allowed")
    required_tools: list[str] = Field(default_factory=list, description="Tool names that must be called")

    # Performance checks
    max_latency_ms: int | None = Field(default=None, description="Maximum allowed latency in ms")
    max_cost_usd: float | None = Field(default=None, description="Maximum allowed cost in USD")

    # LLM-as-judge
    llm_criteria: str | None = Field(
        default=None,
        description="Natural language criteria for LLM judge e.g. 'output must be polite and concise'",
    )

    model_config = {"extra": "allow"}


class EvalCase(BaseModel):
    """A single evaluation case."""

    __test__ = False

    id: str = Field(description="Unique identifier for this case")
    description: str = Field(default="", description="Human-readable description")
    input: dict[str, Any] = Field(description="Input passed to the agent")
    expect: EvalExpectation = Field(default_factory=EvalExpectation)
    tags: list[str] = Field(default_factory=list, description="Tags for filtering e.g. ['smoke', 'regression']")
    weight: float = Field(default=1.0, ge=0.0, description="Weight for scoring (higher = more important)")

    model_config = {"extra": "allow"}


class EvalSuite(BaseModel):
    """A collection of eval cases for a single agent."""

    __test__ = False

    suite: str = Field(description="Suite name")
    description: str = Field(default="")
    model: str = Field(default="claude-haiku-4-5-20251001", description="LLM model to use")
    agent_path: str | None = Field(default=None, description="Path to agent (can be overridden via CLI)")
    cases: list[EvalCase] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, description="Suite-level tags")

    model_config = {"extra": "allow"}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EvalSuite":
        """Load an EvalSuite from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Eval suite not found: {path}")
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def filter_by_tags(self, tags: list[str]) -> "EvalSuite":
        """Return a new suite with only cases matching the given tags."""
        filtered = [c for c in self.cases if any(t in c.tags for t in tags)]
        return self.model_copy(update={"cases": filtered})

    def __len__(self) -> int:
        return len(self.cases)
