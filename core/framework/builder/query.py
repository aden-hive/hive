"""
Builder Query Interface - How I (Builder) analyze agent runs.

This is designed around the questions I need to answer:
1. What happened? (summaries, narratives)
2. Why did it fail? (failure analysis, decision traces)
3. What patterns emerge? (across runs, across nodes)
4. What should we change? (suggestions)
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

from framework.schemas.decision import Decision
from framework.schemas.run import Run, RunStatus, RunSummary
from framework.storage.backend import FileStorage


class FailureAnalysis:
    """Structured analysis of why a run failed."""

    def __init__(
        self,
        run_id: str,
        failure_point: str,
        root_cause: str,
        decision_chain: list[str],
        problems: list[str],
        suggestions: list[str],
    ):
        self.run_id = run_id
        self.failure_point = failure_point
        self.root_cause = root_cause
        self.decision_chain = decision_chain
        self.problems = problems
        self.suggestions = suggestions

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "failure_point": self.failure_point,
            "root_cause": self.root_cause,
            "decision_chain": self.decision_chain,
            "problems": self.problems,
            "suggestions": self.suggestions,
        }

    def __str__(self) -> str:
        lines = [
            f"=== Failure Analysis for {self.run_id} ===",
            "",
            f"Failure Point: {self.failure_point}",
            f"Root Cause: {self.root_cause}",
            "",
            "Decision Chain Leading to Failure:",
        ]
        for i, dec in enumerate(self.decision_chain, 1):
            lines.append(f"  {i}. {dec}")

        if self.problems:
            lines.append("")
            lines.append("Reported Problems:")
            for prob in self.problems:
                lines.append(f"  - {prob}")

        if self.suggestions:
            lines.append("")
            lines.append("Suggestions:")
            for sug in self.suggestions:
                lines.append(f"  → {sug}")

        return "\n".join(lines)


class PatternAnalysis:
    """Patterns detected across multiple runs."""

    def __init__(
        self,
        goal_id: str,
        run_count: int,
        success_rate: float,
        common_failures: list[tuple[str, int]],
        problematic_nodes: list[tuple[str, float]],
        decision_patterns: dict[str, Any],
    ):
        self.goal_id = goal_id
        self.run_count = run_count
        self.success_rate = success_rate
        self.common_failures = common_failures
        self.problematic_nodes = problematic_nodes
        self.decision_patterns = decision_patterns

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "run_count": self.run_count,
            "success_rate": self.success_rate,
            "common_failures": self.common_failures,
            "problematic_nodes": self.problematic_nodes,
            "decision_patterns": self.decision_patterns,
        }

    def __str__(self) -> str:
        lines = [
            f"=== Pattern Analysis for Goal {self.goal_id} ===",
            "",
            f"Runs Analyzed: {self.run_count}",
            f"Success Rate: {self.success_rate:.1%}",
        ]

        if self.common_failures:
            lines.append("")
            lines.append("Common Failures:")
            for failure, count in self.common_failures:
                lines.append(f"  - {failure} ({count} occurrences)")

        if self.problematic_nodes:
            lines.append("")
            lines.append("Problematic Nodes (failure rate):")
            for node, rate in self.problematic_nodes:
                lines.append(f"  - {node}: {rate:.1%} failure rate")

        return "\n".join(lines)


class BuilderQuery:
    """
    The interface I (Builder) use to understand what agents are doing.

    This is optimized for the questions I need to answer when analyzing
    agent behavior and deciding what to improve.
    """

    def __init__(self, storage_path: str | Path):
        self.storage = FileStorage(storage_path)

    # === WHAT HAPPENED? ===

    def get_run_summary(self, run_id: str) -> RunSummary | None:
        """Get a quick summary of a run."""
        return self.storage.load_summary(run_id)

    def get_full_run(self, run_id: str) -> Run | None:
        """Get the complete run with all decisions."""
        return self.storage.load_run(run_id)

    def list_runs_for_goal(self, goal_id: str) -> list[RunSummary]:
        """Get summaries of all runs for a goal."""
        run_ids = self.storage.get_runs_by_goal(goal_id)
        summaries = []
        for run_id in run_ids:
            summary = self.storage.load_summary(run_id)
            if summary:
                summaries.append(summary)
        return summaries

    def get_recent_failures(self, limit: int = 10) -> list[RunSummary]:
        """Get recent failed runs."""
        run_ids = self.storage.get_runs_by_status(RunStatus.FAILED)
        summaries = []
        for run_id in run_ids[:limit]:
            summary = self.storage.load_summary(run_id)
            if summary:
                summaries.append(summary)
        return summaries

    # === WHY DID IT FAIL? ===

    def analyze_failure(self, run_id: str) -> FailureAnalysis | None:
        """
        Deep analysis of why a run failed.

        This is my primary tool for understanding what went wrong.
        """
        run = self.storage.load_run(run_id)
        if run is None or run.status != RunStatus.FAILED:
            return None

        # Find the first failed decision
        failed_decisions = [d for d in run.decisions if not d.was_successful]
        if not failed_decisions:
            failure_point = "Unknown - no decision marked as failed"
            root_cause = "Run failed but all decisions succeeded (external cause?)"
        else:
            first_failure = failed_decisions[0]
            failure_point = first_failure.summary_for_builder()
            root_cause = first_failure.outcome.error if first_failure.outcome else "Unknown"

        # Build the decision chain leading to failure
        decision_chain = []
        for d in run.decisions:
            decision_chain.append(d.summary_for_builder())
            if not d.was_successful:
                break

        # Extract problems
        problems = [f"[{p.severity}] {p.description}" for p in run.problems]

        # Generate suggestions based on the failure
        suggestions = self._generate_suggestions(run, failed_decisions)

        return FailureAnalysis(
            run_id=run_id,
            failure_point=failure_point,
            root_cause=root_cause,
            decision_chain=decision_chain,
            problems=problems,
            suggestions=suggestions,
        )

    def get_decision_trace(self, run_id: str) -> list[str]:
        """Get a readable trace of all decisions in a run."""
        run = self.storage.load_run(run_id)
        if run is None:
            return []
        return [d.summary_for_builder() for d in run.decisions]

    # === WHAT PATTERNS EMERGE? ===

    def find_patterns(self, goal_id: str) -> PatternAnalysis | None:
        """
        Find patterns across runs for a goal.

        This helps me understand systemic issues vs one-off failures.
        """
        run_ids = self.storage.get_runs_by_goal(goal_id)
        if not run_ids:
            return None

        runs = []
        for run_id in run_ids:
            run = self.storage.load_run(run_id)
            if run:
                runs.append(run)

        if not runs:
            return None

        # Calculate success rate
        completed = [r for r in runs if r.status == RunStatus.COMPLETED]
        success_rate = len(completed) / len(runs) if runs else 0.0

        # Find common failures
        failure_counts: dict[str, int] = defaultdict(int)
        for run in runs:
            for decision in run.decisions:
                if not decision.was_successful and decision.outcome:
                    error = decision.outcome.error or "Unknown error"
                    failure_counts[error] += 1

        common_failures = sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Find problematic nodes
        node_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "failed": 0})
        for run in runs:
            for decision in run.decisions:
                node_stats[decision.node_id]["total"] += 1
                if not decision.was_successful:
                    node_stats[decision.node_id]["failed"] += 1

        problematic_nodes = []
        for node_id, stats in node_stats.items():
            if stats["total"] > 0:
                failure_rate = stats["failed"] / stats["total"]
                if failure_rate > 0.1:  # More than 10% failure rate
                    problematic_nodes.append((node_id, failure_rate))

        problematic_nodes.sort(key=lambda x: x[1], reverse=True)

        # Decision patterns
        decision_patterns = self._analyze_decision_patterns(runs)

        return PatternAnalysis(
            goal_id=goal_id,
            run_count=len(runs),
            success_rate=success_rate,
            common_failures=common_failures,
            problematic_nodes=problematic_nodes,
            decision_patterns=decision_patterns,
        )

    def compare_runs(self, run_id_1: str, run_id_2: str) -> dict[str, Any]:
        """Compare two runs to understand what differed."""
        run1 = self.storage.load_run(run_id_1)
        run2 = self.storage.load_run(run_id_2)

        if run1 is None or run2 is None:
            return {"error": "One or both runs not found"}

        return {
            "run_1": {
                "id": run1.id,
                "status": run1.status.value,
                "decisions": len(run1.decisions),
                "success_rate": run1.metrics.success_rate,
            },
            "run_2": {
                "id": run2.id,
                "status": run2.status.value,
                "decisions": len(run2.decisions),
                "success_rate": run2.metrics.success_rate,
            },
            "differences": self._find_differences(run1, run2),
        }

    # === WHAT SHOULD WE CHANGE? ===

    def suggest_improvements(self, goal_id: str) -> list[dict[str, Any]]:
        """
        Generate improvement suggestions based on run analysis.

        This is what I use to propose changes to the human engineer.
        """
        patterns = self.find_patterns(goal_id)
        if patterns is None:
            return []

        suggestions = []

        # Suggestion: Fix problematic nodes
        for node_id, failure_rate in patterns.problematic_nodes:
            suggestions.append(
                {
                    "type": "node_improvement",
                    "target": node_id,
                    "reason": f"Node has {failure_rate:.1%} failure rate",
                    "recommendation": (
                        f"Review and improve node '{node_id}' - "
                        "high failure rate suggests prompt or tool issues"
                    ),
                    "priority": "high" if failure_rate > 0.3 else "medium",
                }
            )

        # Suggestion: Address common failures
        for failure, count in patterns.common_failures:
            if count >= 2:
                suggestions.append(
                    {
                        "type": "error_handling",
                        "target": failure,
                        "reason": f"Error occurred {count} times",
                        "recommendation": f"Add handling for: {failure}",
                        "priority": "high" if count >= 5 else "medium",
                    }
                )

        # Suggestion: Overall success rate
        if patterns.success_rate < 0.8:
            suggestions.append(
                {
                    "type": "architecture",
                    "target": goal_id,
                    "reason": f"Goal success rate is only {patterns.success_rate:.1%}",
                    "recommendation": (
                        "Consider restructuring the agent graph or improving goal definition"
                    ),
                    "priority": "high",
                }
            )

        return suggestions

    def get_node_performance(self, node_id: str) -> dict[str, Any]:
        """Get performance metrics for a specific node across all runs."""
        run_ids = self.storage.get_runs_by_node(node_id)

        total_decisions = 0
        successful_decisions = 0
        total_latency = 0
        total_tokens = 0
        decision_types: dict[str, int] = defaultdict(int)

        for run_id in run_ids:
            run = self.storage.load_run(run_id)
            if run:
                for decision in run.decisions:
                    if decision.node_id == node_id:
                        total_decisions += 1
                        if decision.was_successful:
                            successful_decisions += 1
                        if decision.outcome:
                            total_latency += decision.outcome.latency_ms
                            total_tokens += decision.outcome.tokens_used
                        decision_types[decision.decision_type.value] += 1

        return {
            "node_id": node_id,
            "total_decisions": total_decisions,
            "success_rate": successful_decisions / total_decisions if total_decisions > 0 else 0,
            "avg_latency_ms": total_latency / total_decisions if total_decisions > 0 else 0,
            "total_tokens": total_tokens,
            "decision_type_distribution": dict(decision_types),
        }

    # === PRIVATE HELPERS ===

    def _generate_suggestions(
        self,
        run: Run,
        failed_decisions: list[Decision],
    ) -> list[str]:
        """Generate suggestions based on failure analysis."""
        suggestions = []

        for decision in failed_decisions:
            # Check if there were alternatives
            if len(decision.options) > 1:
                chosen = decision.chosen_option
                alternatives = [o for o in decision.options if o.id != decision.chosen_option_id]
                if alternatives:
                    alt_desc = alternatives[0].description
                    chosen_desc = chosen.description if chosen else "unknown"
                    suggestions.append(
                        f"Consider alternative: '{alt_desc}' instead of '{chosen_desc}'"
                    )

            # Check for missing context
            if not decision.input_context:
                suggestions.append(
                    f"Decision '{decision.intent}' had no input context - "
                    "ensure relevant data is passed"
                )

            # Check for constraint issues
            if decision.active_constraints:
                constraints = ", ".join(decision.active_constraints)
                suggestions.append(f"Review constraints: {constraints} - may be too restrictive")

        # Check for reported problems with suggestions
        for problem in run.problems:
            if problem.suggested_fix:
                suggestions.append(problem.suggested_fix)

        return suggestions

    def _analyze_decision_patterns(self, runs: list[Run]) -> dict[str, Any]:
        """Analyze decision patterns across runs."""
        type_counts: dict[str, int] = defaultdict(int)
        option_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for run in runs:
            for decision in run.decisions:
                type_counts[decision.decision_type.value] += 1

                # Track which options are chosen for similar intents
                intent_key = decision.intent[:50]  # Truncate for grouping
                if decision.chosen_option:
                    option_counts[intent_key][decision.chosen_option.description] += 1

        # Find most common choices per intent
        common_choices = {}
        for intent, choices in option_counts.items():
            if choices:
                most_common = max(choices.items(), key=lambda x: x[1])
                common_choices[intent] = {
                    "choice": most_common[0],
                    "count": most_common[1],
                    "alternatives": len(choices) - 1,
                }

        return {
            "decision_type_distribution": dict(type_counts),
            "common_choices": common_choices,
        }

    def _find_differences(self, run1: Run, run2: Run) -> list[str]:
        """Find key differences between two runs."""
        differences = []

        # Status difference
        if run1.status != run2.status:
            differences.append(f"Status: {run1.status.value} vs {run2.status.value}")

        # Decision count difference
        if len(run1.decisions) != len(run2.decisions):
            differences.append(f"Decision count: {len(run1.decisions)} vs {len(run2.decisions)}")

        # Find first divergence point
        for i, (d1, d2) in enumerate(zip(run1.decisions, run2.decisions, strict=False)):
            if d1.chosen_option_id != d2.chosen_option_id:
                differences.append(
                    f"Diverged at decision {i}: "
                    f"chose '{d1.chosen_option_id}' vs '{d2.chosen_option_id}'"
                )
                break

        # Node differences
        nodes1 = set(run1.metrics.nodes_executed)
        nodes2 = set(run2.metrics.nodes_executed)
        if nodes1 != nodes2:
            only_1 = nodes1 - nodes2
            only_2 = nodes2 - nodes1
            if only_1:
                differences.append(f"Nodes only in run 1: {only_1}")
            if only_2:
                differences.append(f"Nodes only in run 2: {only_2}")

        return differences
