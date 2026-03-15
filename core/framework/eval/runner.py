"""
EvalRunner — runs an EvalSuite against a live agent and produces an EvalReport.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from framework.eval.case import EvalCase, EvalSuite
from framework.eval.report import EvalReport, EvalCaseResult
from framework.eval.scorer import EvalScorer, ScorerConfig


class EvalRunner:
    """
    Runs an EvalSuite against a live AgentRunner and produces an EvalReport.

    Usage:
        suite = EvalSuite.from_yaml("my_suite.yaml")
        runner = EvalRunner(agent_path="exports/my-agent")
        report = asyncio.run(runner.run(suite))
        report.print_summary()
    """

    def __init__(
        self,
        agent_path: str | Path,
        scorer_config: ScorerConfig | None = None,
        concurrency: int = 1,
        verbose: bool = False,
    ):
        self.agent_path = Path(agent_path)
        self.scorer = EvalScorer(scorer_config)
        self.concurrency = concurrency
        self.verbose = verbose

    async def run(self, suite: EvalSuite) -> EvalReport:
        """Run all cases in the suite and return a report."""
        started_at = datetime.now()
        start_ms = time.monotonic_ns() // 1_000_000

        report = EvalReport(
            suite_name=suite.suite,
            agent_path=str(self.agent_path),
            model=suite.model,
            total=len(suite.cases),
            started_at=started_at,
        )

        if self.verbose:
            print(f"\nRunning eval suite: {suite.suite} ({len(suite.cases)} cases)")

        # Run cases with controlled concurrency
        semaphore = asyncio.Semaphore(self.concurrency)
        tasks = [self._run_case(case, suite.model, semaphore) for case in suite.cases]
        results: list[EvalCaseResult] = await asyncio.gather(*tasks)

        # Aggregate
        report.case_results = results
        report.passed = sum(1 for r in results if r.passed)
        report.failed = sum(1 for r in results if not r.passed)
        report.overall_score = (
            sum(r.score * c.weight for r, c in zip(results, suite.cases))
            / max(sum(c.weight for c in suite.cases), 1e-9)
        )
        report.avg_latency_ms = (
            sum(r.latency_ms for r in results) / len(results) if results else 0.0
        )
        report.total_cost_usd = sum(r.estimated_cost_usd for r in results)
        report.finished_at = datetime.now()
        report.duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms

        if self.verbose:
            report.print_summary()

        return report

    async def _run_case(
        self, case: EvalCase, model: str, semaphore: asyncio.Semaphore
    ) -> EvalCaseResult:
        """Run a single eval case."""
        async with semaphore:
            if self.verbose:
                print(f"  Running: {case.id} ...", end=" ", flush=True)

            t0 = time.monotonic_ns()
            agent_output = None
            agent_error = None
            tools_called: list[str] = []
            nodes_visited: list[str] = []
            estimated_cost_usd = 0.0

            try:
                from framework.runner.runner import AgentRunner

                async with AgentRunner.load(self.agent_path) as runner:
                    # Override model if specified
                    if hasattr(runner, "_llm") and runner._llm is not None:
                        pass  # model already set during load

                    result = await runner.run(case.input)

                    agent_output = result.output
                    nodes_visited = result.path or []

                    # Extract tool calls from runtime logs if available
                    if hasattr(result, "tool_calls"):
                        tools_called = [tc.get("name", "") for tc in (result.tool_calls or [])]

                    # Estimate cost from token usage if available
                    if hasattr(result, "usage") and result.usage:
                        input_tokens = result.usage.get("input_tokens", 0)
                        output_tokens = result.usage.get("output_tokens", 0)
                        # Claude haiku pricing approximation
                        estimated_cost_usd = (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000

            except Exception as e:
                agent_error = str(e)

            latency_ms = (time.monotonic_ns() - t0) // 1_000_000

            result = self.scorer.score(
                case=case,
                agent_output=agent_output,
                agent_error=agent_error,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost_usd,
                tools_called=tools_called,
                nodes_visited=nodes_visited,
            )

            if self.verbose:
                status = "✓" if result.passed else "✗"
                print(f"{status} ({latency_ms}ms, score={result.score:.2f})")

            return result
