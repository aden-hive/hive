"""
Eval System for Aden Hive.

End-to-end agent graph evaluation with scoring, reporting, and CI integration.

## Core Flow

1. Define an eval suite (YAML or Python)
2. Run: hive eval run --suite my_suite.yaml --agent exports/my-agent
3. Get a scored report: pass/fail, latency, cost, tool usage, LLM quality

## Key Components

- EvalCase: A single eval input + expected behaviour
- EvalResult: Scored result for one case
- EvalReport: Aggregate report for the full suite
- EvalRunner: Executes cases against a live agent
- EvalScorer: Scores outputs across multiple dimensions
"""

from framework.eval.case import EvalCase, EvalSuite
from framework.eval.report import EvalReport, EvalCaseResult
from framework.eval.runner import EvalRunner
from framework.eval.scorer import EvalScorer, ScorerConfig

__all__ = [
    "EvalCase",
    "EvalSuite",
    "EvalReport",
    "EvalCaseResult",
    "EvalRunner",
    "EvalScorer",
    "ScorerConfig",
]
