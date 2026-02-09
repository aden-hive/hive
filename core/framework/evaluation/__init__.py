"""Agent evaluation and adaptiveness framework."""

from framework.evaluation.evaluator import AgentEvaluator
from framework.evaluation.failure_classifier import (
    FailureCategory,
    FailureClassifier,
    FailureRecord,
)
from framework.evaluation.metrics import EvaluationMetrics, MetricsCollector
from framework.evaluation.report import EvaluationReport, EvolutionRecommendation

__all__ = [
    "AgentEvaluator",
    "EvaluationMetrics",
    "EvaluationReport",
    "EvolutionRecommendation",
    "FailureCategory",
    "FailureClassifier",
    "FailureRecord",
    "MetricsCollector",
]
