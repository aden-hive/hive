"""Neutrosophic scoring layer for swarm decision quality.

Adds an optional T/I/F (truth / indeterminacy / falsity) signal alongside
existing worker reports. See RFC aden-hive/hive#7179 for motivation.
"""

from .judge import NeutrosophicJudge, score_judge_context
from .scoring import (
    NeutrosophicDecision,
    NeutrosophicScore,
    aggregate_scores,
    aggregate_worker_reports,
    score_worker_report,
)

__all__ = [
    "NeutrosophicDecision",
    "NeutrosophicJudge",
    "NeutrosophicScore",
    "aggregate_scores",
    "aggregate_worker_reports",
    "score_judge_context",
    "score_worker_report",
]
