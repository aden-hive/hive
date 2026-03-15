"""
EvalScorer — scores agent output against EvalExpectation across multiple dimensions.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from framework.eval.case import EvalCase, EvalExpectation
from framework.eval.report import EvalCaseResult, ScoreDimension


class ScorerConfig(BaseModel):
    """Configuration for the scorer."""

    use_llm_judge: bool = Field(default=True, description="Use LLM judge for llm_criteria checks")
    llm_judge_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    content_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    performance_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    tool_weight: float = Field(default=0.1, ge=0.0, le=1.0)


class EvalScorer:
    """
    Scores agent output against an EvalCase expectation.

    Scoring dimensions:
    - content: contains/not_contains/exact_match checks
    - performance: latency and cost checks
    - tools: tool call checks
    - llm_judge: semantic quality via LLMJudge
    """

    def __init__(self, config: ScorerConfig | None = None):
        self.config = config or ScorerConfig()
        self._judge = None

    def _get_judge(self):
        if self._judge is None:
            from framework.testing.llm_judge import LLMJudge
            self._judge = LLMJudge()
        return self._judge

    def score(
        self,
        case: EvalCase,
        agent_output: Any,
        agent_error: str | None,
        latency_ms: int,
        estimated_cost_usd: float,
        tools_called: list[str],
        nodes_visited: list[str],
    ) -> EvalCaseResult:
        """Score a single eval case result."""

        expect = case.expect
        dimensions: list[ScoreDimension] = []

        # 1. Error expectation check
        if expect.error:
            error_passed = agent_error is not None
            dimensions.append(ScoreDimension(
                name="error_expected",
                passed=error_passed,
                score=1.0 if error_passed else 0.0,
                detail="Expected error" + ("" if error_passed else " but agent succeeded"),
            ))
            # If we expected an error and got one, short-circuit with full pass
            if error_passed:
                return EvalCaseResult(
                    case_id=case.id,
                    passed=True,
                    score=1.0,
                    agent_error=agent_error,
                    dimensions=dimensions,
                    latency_ms=latency_ms,
                    estimated_cost_usd=estimated_cost_usd,
                    tools_called=tools_called,
                    nodes_visited=nodes_visited,
                )
        elif agent_error is not None:
            # Unexpected error — instant fail
            dimensions.append(ScoreDimension(
                name="no_error",
                passed=False,
                score=0.0,
                detail=f"Unexpected error: {agent_error[:200]}",
            ))
            return EvalCaseResult(
                case_id=case.id,
                passed=False,
                score=0.0,
                agent_error=agent_error,
                dimensions=dimensions,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost_usd,
                tools_called=tools_called,
                nodes_visited=nodes_visited,
            )

        # Flatten output to string for content checks
        output_str = self._to_str(agent_output)

        # 2. Content dimension
        content_dims = self._score_content(expect, output_str)
        dimensions.extend(content_dims)

        # 3. Performance dimension
        perf_dims = self._score_performance(expect, latency_ms, estimated_cost_usd)
        dimensions.extend(perf_dims)

        # 4. Tool dimension
        tool_dims = self._score_tools(expect, tools_called)
        dimensions.extend(tool_dims)

        # 5. LLM judge dimension
        llm_passed = None
        llm_explanation = None
        if expect.llm_criteria and self.config.use_llm_judge:
            judge_result = self._get_judge().evaluate(
                constraint=expect.llm_criteria,
                source_document=str(case.input),
                summary=output_str,
                criteria=expect.llm_criteria,
            )
            llm_passed = judge_result.get("passes", False)
            llm_explanation = judge_result.get("explanation", "")
            dimensions.append(ScoreDimension(
                name="llm_judge",
                passed=llm_passed,
                score=1.0 if llm_passed else 0.0,
                detail=llm_explanation,
            ))

        # Compute composite score
        composite = self._composite_score(dimensions)
        all_passed = all(d.passed for d in dimensions)

        return EvalCaseResult(
            case_id=case.id,
            passed=all_passed,
            score=composite,
            agent_output=agent_output,
            dimensions=dimensions,
            latency_ms=latency_ms,
            estimated_cost_usd=estimated_cost_usd,
            tools_called=tools_called,
            nodes_visited=nodes_visited,
            llm_judge_passed=llm_passed,
            llm_judge_explanation=llm_explanation,
        )

    def _to_str(self, output: Any) -> str:
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            import json
            return json.dumps(output)
        return str(output)

    def _score_content(self, expect: EvalExpectation, output_str: str) -> list[ScoreDimension]:
        dims = []

        if expect.contains:
            missing = [s for s in expect.contains if s.lower() not in output_str.lower()]
            passed = len(missing) == 0
            dims.append(ScoreDimension(
                name="contains",
                passed=passed,
                score=1.0 - len(missing) / len(expect.contains),
                detail=f"Missing: {missing}" if missing else "All required strings found",
            ))

        if expect.not_contains:
            found = [s for s in expect.not_contains if s.lower() in output_str.lower()]
            passed = len(found) == 0
            dims.append(ScoreDimension(
                name="not_contains",
                passed=passed,
                score=1.0 - len(found) / len(expect.not_contains),
                detail=f"Found forbidden: {found}" if found else "No forbidden strings found",
            ))

        if expect.exact_match is not None:
            passed = output_str.strip() == expect.exact_match.strip()
            dims.append(ScoreDimension(
                name="exact_match",
                passed=passed,
                score=1.0 if passed else 0.0,
                detail="Exact match" if passed else "Output did not match expected exactly",
            ))

        return dims

    def _score_performance(
        self, expect: EvalExpectation, latency_ms: int, cost_usd: float
    ) -> list[ScoreDimension]:
        dims = []

        if expect.max_latency_ms is not None:
            passed = latency_ms <= expect.max_latency_ms
            score = min(1.0, expect.max_latency_ms / max(latency_ms, 1))
            dims.append(ScoreDimension(
                name="latency",
                passed=passed,
                score=score,
                detail=f"{latency_ms}ms vs limit {expect.max_latency_ms}ms",
            ))

        if expect.max_cost_usd is not None:
            passed = cost_usd <= expect.max_cost_usd
            score = min(1.0, expect.max_cost_usd / max(cost_usd, 1e-9))
            dims.append(ScoreDimension(
                name="cost",
                passed=passed,
                score=score,
                detail=f"${cost_usd:.6f} vs limit ${expect.max_cost_usd:.6f}",
            ))

        return dims

    def _score_tools(self, expect: EvalExpectation, tools_called: list[str]) -> list[ScoreDimension]:
        dims = []

        if expect.required_tools:
            missing = [t for t in expect.required_tools if t not in tools_called]
            passed = len(missing) == 0
            dims.append(ScoreDimension(
                name="required_tools",
                passed=passed,
                score=1.0 - len(missing) / len(expect.required_tools),
                detail=f"Missing tools: {missing}" if missing else "All required tools called",
            ))

        if expect.max_tools_called is not None:
            passed = len(tools_called) <= expect.max_tools_called
            dims.append(ScoreDimension(
                name="tool_count",
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"{len(tools_called)} tools called vs max {expect.max_tools_called}",
            ))

        if expect.min_tools_called > 0:
            passed = len(tools_called) >= expect.min_tools_called
            dims.append(ScoreDimension(
                name="min_tools",
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"{len(tools_called)} tools called vs min {expect.min_tools_called}",
            ))

        return dims

    def _composite_score(self, dimensions: list[ScoreDimension]) -> float:
        if not dimensions:
            return 1.0
        return sum(d.score for d in dimensions) / len(dimensions)
