"""FinOps configuration for cost guardrails and observability."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BudgetAction(StrEnum):
    """Actions to take when budget thresholds are exceeded."""

    WARN = "warn"
    DEGRADE = "degrade"
    THROTTLE = "throttle"
    KILL = "kill"


@dataclass
class BudgetThreshold:
    """A budget threshold with an associated action."""

    threshold: float
    action: BudgetAction
    message: str = ""


@dataclass
class BudgetPolicy:
    """Budget policy for a specific scope (agent, node, tool, model)."""

    name: str
    scope: str
    scope_id: str
    max_tokens_per_run: int | None = None
    max_cost_usd_per_run: float | None = None
    max_tokens_per_minute: int | None = None
    burn_rate_threshold: float | None = None
    thresholds: list[BudgetThreshold] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "max_tokens_per_run": self.max_tokens_per_run,
            "max_cost_usd_per_run": self.max_cost_usd_per_run,
            "max_tokens_per_minute": self.max_tokens_per_minute,
            "burn_rate_threshold": self.burn_rate_threshold,
            "thresholds": [
                {"threshold": t.threshold, "action": t.action.value, "message": t.message}
                for t in self.thresholds
            ],
            "enabled": self.enabled,
        }


@dataclass
class FinOpsConfig:
    """Configuration for FinOps integration."""

    enabled: bool = True
    prometheus_enabled: bool = True
    prometheus_port: int = 9090
    prometheus_host: str = "0.0.0.0"
    otel_enabled: bool = False
    otel_endpoint: str | None = None
    otel_service_name: str = "hive-agent"
    budget_policies: list[BudgetPolicy] = field(default_factory=list)
    runaway_detection_enabled: bool = True
    runaway_failure_threshold: int = 3
    runaway_burn_rate_multiplier: float = 2.0
    cost_estimation_enabled: bool = True

    @classmethod
    def from_env(cls) -> FinOpsConfig:
        """Load configuration from environment variables."""
        return cls(
            enabled=os.getenv("HIVE_FINOPS_ENABLED", "true").lower() == "true",
            prometheus_enabled=os.getenv("HIVE_PROMETHEUS_ENABLED", "true").lower() == "true",
            prometheus_port=int(os.getenv("HIVE_PROMETHEUS_PORT", "9090")),
            prometheus_host=os.getenv("HIVE_PROMETHEUS_HOST", "0.0.0.0"),
            otel_enabled=os.getenv("HIVE_OTEL_ENABLED", "false").lower() == "true",
            otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            otel_service_name=os.getenv("OTEL_SERVICE_NAME", "hive-agent"),
            runaway_detection_enabled=os.getenv("HIVE_RUNAWAY_DETECTION_ENABLED", "true").lower()
            == "true",
            runaway_failure_threshold=int(os.getenv("HIVE_RUNAWAY_FAILURE_THRESHOLD", "3")),
            runaway_burn_rate_multiplier=float(
                os.getenv("HIVE_RUNAWAY_BURN_RATE_MULTIPLIER", "2.0")
            ),
            cost_estimation_enabled=os.getenv("HIVE_COST_ESTIMATION_ENABLED", "true").lower()
            == "true",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "prometheus_enabled": self.prometheus_enabled,
            "prometheus_port": self.prometheus_port,
            "prometheus_host": self.prometheus_host,
            "otel_enabled": self.otel_enabled,
            "otel_endpoint": self.otel_endpoint,
            "otel_service_name": self.otel_service_name,
            "budget_policies": [p.to_dict() for p in self.budget_policies],
            "runaway_detection_enabled": self.runaway_detection_enabled,
            "runaway_failure_threshold": self.runaway_failure_threshold,
            "runaway_burn_rate_multiplier": self.runaway_burn_rate_multiplier,
            "cost_estimation_enabled": self.cost_estimation_enabled,
        }
