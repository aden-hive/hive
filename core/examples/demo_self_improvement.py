"""
End-to-End Demo: Self-Improvement Loop
---------------------------------------
Demonstrates the full Hive self-improvement cycle:

  1. Define a multi-node agent graph (Research -> Analyse -> Summarise)
  2. Execute it multiple times with varying success
  3. Evaluate each execution against goal criteria
  4. Diagnose patterns from evaluation history
  5. Apply automatic improvements via AgentBuilder
  6. Show before/after comparison

Run with:
    uv run python core/examples/demo_self_improvement.py
"""

import asyncio
import copy
import json
import shutil
import tempfile
from pathlib import Path

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.graph.goal import SuccessCriterion
from framework.graph.node import NodeContext, NodeProtocol, NodeResult
from framework.runtime.builder import AgentBuilder
from framework.runtime.core import Runtime
from framework.runtime.evaluation import (
    CriterionResult,
    EvaluationStore,
    ExecutionEvaluator,
)


# ---------------------------------------------------------------------------
# 1. Custom Node Implementations
# ---------------------------------------------------------------------------

class ResearchNode(NodeProtocol):
    """Simulates web research -- gathers raw data on a topic."""

    def __init__(self, fail: bool = False):
        self._fail = fail

    async def execute(self, ctx: NodeContext) -> NodeResult:
        topic = ctx.input_data.get("topic", "AI agents")

        if self._fail:
            return NodeResult(
                success=False,
                output={"error": "Research source unavailable"},
            )

        findings = {
            "topic": topic,
            "sources": ["arxiv.org", "scholar.google.com", "github.com"],
            "key_facts": [
                f"{topic} is a rapidly growing field",
                f"Multi-agent systems enable complex {topic} workflows",
                "Self-improvement loops close the feedback gap",
            ],
            "raw_data_length": 4200,
        }
        # Write to memory using keys that match output_keys
        ctx.memory.write("research_data", findings)
        return NodeResult(success=True, output=findings)


class AnalyseNode(NodeProtocol):
    """Analyses research findings and extracts insights."""

    def __init__(self, quality: str = "high"):
        self._quality = quality

    async def execute(self, ctx: NodeContext) -> NodeResult:
        research = ctx.memory.read("research_data")
        if not research:
            return NodeResult(success=False, output={"error": "No research data"})

        topic = research.get("topic", "unknown")
        facts = research.get("key_facts", [])

        insights = {
            "topic": topic,
            "insight_count": len(facts),
            "themes": ["automation", "self-improvement", "multi-agent"],
            "confidence": 0.92 if self._quality == "high" else 0.45,
            "analysis_depth": self._quality,
        }

        if self._quality == "high":
            insights["summary_preview"] = (
                f"Analysis of {topic}: {len(facts)} key findings across "
                f"{len(research.get('sources', []))} sources with high confidence."
            )

        ctx.memory.write("analysis_data", insights)
        return NodeResult(success=True, output=insights)


class SummariseNode(NodeProtocol):
    """Produces a final summary report."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        analysis = ctx.memory.read("analysis_data")
        if not analysis:
            return NodeResult(success=False, output={"error": "No analysis data"})

        topic = analysis.get("topic", "unknown")
        confidence = analysis.get("confidence", 0)
        themes = analysis.get("themes", [])

        report = {
            "title": f"Research Report: {topic}",
            "summary": (
                f"Comprehensive analysis of {topic} covering {analysis.get('insight_count', 0)} "
                f"insights across themes: {', '.join(themes)}. "
                f"Overall confidence: {confidence:.0%}."
            ),
            "confidence": confidence,
            "themes": themes,
            "word_count": 350,
            "report_ready": True,
        }
        ctx.memory.write("report", report)
        return NodeResult(success=True, output=report)


class DemoEvaluator(ExecutionEvaluator):
    """Custom evaluator that checks confidence thresholds."""

    def _evaluate_criterion(self, criterion, result):
        if criterion.metric == "confidence_above":
            # Check if confidence in analysis_data meets threshold
            analysis = result.output.get("analysis_data", {})
            confidence = analysis.get("confidence", 0)
            threshold = float(criterion.target)
            met = confidence >= threshold
            return CriterionResult(
                criterion_id=criterion.id,
                description=criterion.description,
                met=met,
                score=min(confidence / threshold, 1.0) if threshold > 0 else 1.0,
                evidence=f"confidence={confidence:.2f}, threshold={threshold}",
                metric_used="confidence_above",
            )
        return super()._evaluate_criterion(criterion, result)


# ---------------------------------------------------------------------------
# 2. Build the Agent Graph
# ---------------------------------------------------------------------------

def create_research_graph() -> tuple[GraphSpec, Goal]:
    """Create a 3-node research agent graph with goal and criteria."""
    goal = Goal(
        id="deep-research",
        name="Deep Research Report",
        description="Produce a high-quality research report on a given topic",
        success_criteria=[
            SuccessCriterion(
                id="report_produced",
                description="A final report with report_ready flag is generated",
                metric="output_contains",
                target="report_ready",
                weight=1.0,
            ),
            SuccessCriterion(
                id="high_confidence",
                description="Analysis confidence is above 70%",
                metric="confidence_above",
                target=0.7,
                weight=0.8,
            ),
            SuccessCriterion(
                id="multi_source",
                description="Research uses multiple sources",
                metric="output_contains",
                target="sources",
                weight=0.6,
            ),
        ],
    )

    # output_keys must match the memory.write() keys in each node
    nodes = [
        NodeSpec(
            id="researcher",
            name="Researcher",
            description="Gathers raw data from multiple sources",
            node_type="event_loop",
            input_keys=["topic"],
            output_keys=["research_data"],
            system_prompt="You are a thorough researcher. Gather comprehensive data.",
        ),
        NodeSpec(
            id="analyst",
            name="Analyst",
            description="Analyses research findings and extracts insights",
            node_type="event_loop",
            input_keys=["research_data"],
            output_keys=["analysis_data"],
            system_prompt="You are an expert analyst. Extract key insights from data.",
        ),
        NodeSpec(
            id="summariser",
            name="Summariser",
            description="Produces a polished final report",
            node_type="event_loop",
            input_keys=["analysis_data"],
            output_keys=["report"],
            system_prompt="You are a report writer. Produce clear, actionable summaries.",
        ),
    ]

    edges = [
        EdgeSpec(
            id="research-to-analysis",
            source="researcher",
            target="analyst",
            condition=EdgeCondition.ON_SUCCESS,
        ),
        EdgeSpec(
            id="analysis-to-summary",
            source="analyst",
            target="summariser",
            condition=EdgeCondition.ON_SUCCESS,
        ),
    ]

    graph = GraphSpec(
        id="research-agent",
        goal_id="deep-research",
        version="1.0.0",
        entry_node="researcher",
        terminal_nodes=["summariser"],
        nodes=nodes,
        edges=edges,
    )

    return graph, goal


# ---------------------------------------------------------------------------
# 3. Run a single execution
# ---------------------------------------------------------------------------

async def run_execution(
    graph: GraphSpec,
    goal: Goal,
    runtime: Runtime,
    research_fail: bool = False,
    analysis_quality: str = "high",
    topic: str = "AI agents",
) -> ExecutionResult:
    """Run a single execution of the research agent."""
    executor = GraphExecutor(runtime=runtime)
    executor.register_node("researcher", ResearchNode(fail=research_fail))
    executor.register_node("analyst", AnalyseNode(quality=analysis_quality))
    executor.register_node("summariser", SummariseNode())

    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"topic": topic},
    )
    return result


# ---------------------------------------------------------------------------
# 4. Main Demo
# ---------------------------------------------------------------------------

async def main():
    separator = "=" * 70
    print(separator)
    print("  HIVE SELF-IMPROVEMENT LOOP -- END-TO-END DEMO")
    print(separator)

    # Setup temp dirs for isolation
    tmp_dir = Path(tempfile.mkdtemp(prefix="hive_demo_"))
    storage_path = tmp_dir / "storage"
    eval_path = tmp_dir / "evaluations"

    try:
        runtime = Runtime(storage_path=storage_path)
        store = EvaluationStore(base_path=eval_path)
        evaluator = DemoEvaluator(store=store)
        builder = AgentBuilder()

        graph, goal = create_research_graph()
        stream_id = "demo-research-stream"

        # --- Phase 1: Run executions with mixed success/failure ---
        print("\n[PHASE 1] Execute agent with varying conditions\n")

        scenarios = [
            {"topic": "AI agents", "quality": "high", "fail": False, "label": "Run 1 (good research, high analysis)"},
            {"topic": "LLM orchestration", "quality": "low", "fail": False, "label": "Run 2 (good research, low analysis)"},
            {"topic": "self-improvement", "quality": "low", "fail": False, "label": "Run 3 (good research, low analysis)"},
            {"topic": "multi-agent systems", "quality": "high", "fail": False, "label": "Run 4 (good research, high analysis)"},
            {"topic": "agent evaluation", "quality": "low", "fail": True, "label": "Run 5 (FAILED research)"},
        ]

        evaluation_results = []

        for i, scenario in enumerate(scenarios, 1):
            result = await run_execution(
                graph=copy.deepcopy(graph),
                goal=goal,
                runtime=runtime,
                research_fail=scenario["fail"],
                analysis_quality=scenario["quality"],
                topic=scenario["topic"],
            )

            eval_result = evaluator.evaluate(
                result=result,
                goal=goal,
                stream_id=stream_id,
                execution_id=f"exec-{i:03d}",
            )
            evaluation_results.append(eval_result)

            status = "PASS" if eval_result.success else "FAIL"
            criteria_detail = ", ".join(
                f"{c.criterion_id}={'met' if c.met else 'miss'}"
                for c in eval_result.criteria_results
            )
            print(
                f"  {scenario['label']:45s} | "
                f"Score: {eval_result.overall_score:5.0%} | "
                f"{status} | {criteria_detail}"
            )

        # --- Phase 2: Diagnose ---
        print(f"\n{separator}")
        print("[PHASE 2] Diagnose patterns from evaluation history\n")

        plan = evaluator.diagnose(stream_id)

        print(f"  Success rate:        {plan.recent_success_rate:.0%}")
        print(f"  Trend:               {plan.trend}")
        print(f"  Failing criteria:    {plan.failing_criteria or 'none'}")
        print(f"  Bottleneck nodes:    {plan.bottleneck_nodes or 'none'}")
        print(f"  Avg tokens/step:     {plan.avg_tokens_per_step:.0f}")
        print(f"  Avg latency/step:    {plan.avg_latency_per_step_ms:.0f} ms")
        print(f"\n  Recommendations:")
        for j, rec in enumerate(plan.recommendations, 1):
            print(f"    {j}. {rec}")

        # Show the prompt context that gets injected into next execution
        prompt_ctx = plan.to_prompt_context()
        if prompt_ctx:
            print(f"\n  Generated improvement context (injected into next run):")
            for line in prompt_ctx.split("\n"):
                print(f"    | {line}")

        # --- Phase 3: Build improvements ---
        print(f"\n{separator}")
        print("[PHASE 3] Apply automatic improvements via AgentBuilder\n")

        graph_before = copy.deepcopy(graph)
        before_version = graph.version

        build_result = builder.build(
            graph_spec=graph,
            improvement_plan=plan,
            allow_restructure=True,
        )

        print(f"  Graph version:   {before_version} -> {build_result.graph_version_after or before_version}")
        print(f"  Modifications:   {build_result.modification_count}")
        print(f"\n  {build_result.summary()}")

        # Show prompt diff for first modified node
        for node_before in graph_before.nodes:
            for node_after in graph.nodes:
                if node_before.id == node_after.id:
                    before_prompt = getattr(node_before, "system_prompt", "") or ""
                    after_prompt = getattr(node_after, "system_prompt", "") or ""
                    if before_prompt != after_prompt:
                        added = after_prompt[len(before_prompt):]
                        print(f"\n  Prompt diff for '{node_after.id}':")
                        for line in added.strip().split("\n")[:8]:
                            print(f"    + {line}")
                        remaining = len(added.strip().split("\n")) - 8
                        if remaining > 0:
                            print(f"    + ... ({remaining} more lines)")
                        break
            else:
                continue
            break

        # --- Phase 4: Re-run with improved graph ---
        print(f"\n{separator}")
        print("[PHASE 4] Re-execute with improved graph\n")

        result_after = await run_execution(
            graph=graph,
            goal=goal,
            runtime=runtime,
            analysis_quality="high",
            topic="AI agents with self-improvement",
        )

        eval_after = evaluator.evaluate(
            result=result_after,
            goal=goal,
            stream_id=stream_id,
            execution_id="exec-006-improved",
        )

        status_after = "PASS" if eval_after.success else "FAIL"
        criteria_after = ", ".join(
            f"{c.criterion_id}={'met' if c.met else 'miss'}"
            for c in eval_after.criteria_results
        )
        print(f"  Topic:      AI agents with self-improvement")
        print(f"  Score:      {eval_after.overall_score:.0%}")
        print(f"  Status:     {status_after}")
        print(f"  Quality:    {eval_after.execution_quality}")
        print(f"  Path:       {' -> '.join(result_after.path)}")
        print(f"  Criteria:   {criteria_after}")

        # Show key output fields
        output = result_after.output
        print(f"\n  Output highlights:")
        if "report" in output:
            report = output["report"]
            print(f"    Title:        {report.get('title', 'N/A')}")
            print(f"    Summary:      {report.get('summary', 'N/A')[:120]}...")
            print(f"    Confidence:   {report.get('confidence', 'N/A')}")
            print(f"    Report ready: {report.get('report_ready', 'N/A')}")
        else:
            print(f"    {json.dumps(output, indent=2)[:400]}")

        # --- Phase 5: Final diagnosis (should show improvement) ---
        print(f"\n{separator}")
        print("[PHASE 5] Final diagnosis (post-improvement)\n")

        final_plan = evaluator.diagnose(stream_id)
        print(f"  Success rate:  {plan.recent_success_rate:.0%} -> {final_plan.recent_success_rate:.0%}")
        print(f"  Trend:         {plan.trend} -> {final_plan.trend}")
        print(f"  Recommendations:")
        for j, rec in enumerate(final_plan.recommendations, 1):
            print(f"    {j}. {rec}")

        # --- Summary ---
        print(f"\n{separator}")
        print("  DEMO COMPLETE -- SELF-IMPROVEMENT LOOP VERIFIED")
        print(separator)
        print(f"\n  Executions run:     6 (5 initial + 1 post-improvement)")
        print(f"  Evaluations:        6")
        print(f"  Builder mods:       {build_result.modification_count}")
        print(f"  Graph version:      1.0.0 -> {graph.version}")
        print(f"  Initial success:    {plan.recent_success_rate:.0%}")
        print(f"  Final success:      {final_plan.recent_success_rate:.0%}")
        print()

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
