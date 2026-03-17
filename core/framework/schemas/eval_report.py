"""Multi-dimensional evaluation report for node execution quality."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvalReport(BaseModel):
    """Structured quality report produced by a NodeEvaluator after each node runs.

    Each dimension is scored 0.0–1.0.  ``weak_dimensions`` lists any
    dimension below a caller-defined threshold so downstream policies
    (e.g. DegradationPolicy from #6214) can react without re-parsing scores.
    """

    node_id: str
    faithfulness: float = Field(default=1.0, ge=0.0, le=1.0)
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    cost_efficiency: float = Field(default=1.0, ge=0.0, le=1.0)
    weak_dimensions: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    evaluator_model: str | None = None

    model_config = {"extra": "allow"}
