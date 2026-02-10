"""Configuration for the observability subsystem.

Usage::

    config = ObservabilityConfig(
        enabled=True,
        hooks=[ConsoleExporter(), PrometheusExporter(port=9090)],
        sample_rate=1.0,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.observability.hooks import ObservabilityHooks


@dataclass
class ObservabilityConfig:
    """Configuration for observability.

    Attributes:
        enabled: Master switch. When False, no hooks are called.
        hooks: List of hook implementations to receive events.
               Multiple hooks are wrapped in a CompositeHooks automatically.
        sample_rate: Fraction of runs to instrument (0.0–1.0).
                     1.0 = every run, 0.1 = 10% of runs.
                     Useful for high-throughput production to reduce overhead.
    """

    enabled: bool = True
    hooks: list[ObservabilityHooks] = field(default_factory=list)
    sample_rate: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.sample_rate <= 1.0:
            msg = f"sample_rate must be between 0.0 and 1.0, got {self.sample_rate}"
            raise ValueError(msg)

    def should_sample(self) -> bool:
        """Determine whether a given run should be instrumented."""
        if not self.enabled:
            return False
        if self.sample_rate >= 1.0:
            return True
        import random

        return random.random() < self.sample_rate
