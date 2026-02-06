"""Starter Coding Agent (Dev/Test Only)
-------------------------------------
This lightweight example demonstrates running an LLM-backed node locally
without requiring Claude. It will use OpenRouter if `OPENROUTER_API_KEY`
is present, otherwise it falls back to `LiteLLMProvider` (if installed) or
the `MockLLMProvider` for offline development.

Run with:
    PYTHONPATH=core python core/examples/starter_coding_agent.py

This script is intended for development and testing only — it's NOT a
production-ready agent. It helps validate LLM node execution, basic
tool usage plumbing, and graph generation locally.
"""

import asyncio
import os
from pathlib import Path

from framework.builder.query import BuilderQuery
from framework.graph import Goal
from framework.graph.flexible_executor import ExecutorConfig, FlexibleGraphExecutor
from framework.graph.judge import create_default_judge
from framework.graph.plan import (
    ActionSpec,
    ActionType,
    EvaluationRule,
    ExecutionStatus,
    JudgmentAction,
    Plan,
    PlanStep,
)
from framework.runtime.core import Runtime

# LLM providers
from framework.llm import mock as _mock

try:
    from framework.llm.openrouter import OpenRouterProvider
except Exception:
    OpenRouterProvider = None  # type: ignore[assignment]

try:
    from framework.llm.litellm import LiteLLMProvider
except Exception:
    LiteLLMProvider = None  # type: ignore[assignment]


async def main():
    print("🚧 Starter coding agent (dev/test-only) — starting...")

    # Choose provider: OpenRouter > LiteLLM > Mock
    # Set STARTER_USE_MOCK=1 to force mock provider (offline testing)
    provider = None
    use_mock = os.environ.get("STARTER_USE_MOCK") == "1"
    
    if use_mock:
        print("Using MockLLMProvider (STARTER_USE_MOCK=1)")
        provider = _mock.MockLLMProvider()
    else:
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openrouter_key and OpenRouterProvider is not None:
            print("Using OpenRouter provider (OPENROUTER_API_KEY detected)")
            # OpenRouter requires provider prefix: "openai/gpt-4o-mini", "anthropic/claude-3-haiku", etc.
            default_model = os.environ.get("OPENROUTER_MODEL", "")
            provider = OpenRouterProvider(api_key=openrouter_key, model=default_model)
        elif LiteLLMProvider is not None:
            print("Using LiteLLM provider (litellm available). Configure model via OPENROUTER_MODEL env var.")
            provider = LiteLLMProvider(model=os.environ.get("OPENROUTER_MODEL", ""))
        else:
            print("No LLM available — falling back to MockLLMProvider for offline testing")
            provider = _mock.MockLLMProvider()

    # Define a simple goal that asks the LLM to produce a JSON 'solution'
    goal = Goal(
        id="starter-coding",
        name="Starter Coding Agent",
        description="Produce a short development-friendly solution string",
        success_criteria=[
            {
                "id": "solution_present",
                "description": "Solution key present in output",
                "metric": "custom",
                "target": "any",
            }
        ],
    )

    # Initialize runtime and executor (FlexibleGraphExecutor uses Worker-Judge loop)
    runtime = Runtime(storage_path=Path("./agent_logs"))
    judge = create_default_judge(llm=provider)

    # Custom rules: require valid JSON with "solution"
    judge.add_rule(
        EvaluationRule(
            id="solution_json_present",
            description="LLM returned JSON with solution",
            condition=(
                "isinstance(result, dict) and result.get('success') == True and "
                "isinstance(result.get('outputs', {}).get('parsed_json'), dict) and "
                "'solution' in result.get('outputs', {}).get('parsed_json')"
            ),
            action=JudgmentAction.ACCEPT,
            priority=200,
        )
    )
    judge.add_rule(
        EvaluationRule(
            id="solution_missing_replan",
            description="LLM response missing required solution key",
            condition=(
                "isinstance(result, dict) and result.get('success') == True and "
                "(not isinstance(result.get('outputs', {}).get('parsed_json'), dict) or "
                "'solution' not in result.get('outputs', {}).get('parsed_json'))"
            ),
            action=JudgmentAction.REPLAN,
            feedback_template="Response must be valid JSON with a top-level 'solution' key.",
            priority=190,
        )
    )

    executor = FlexibleGraphExecutor(
        runtime=runtime,
        llm=provider,
        judge=judge,
        config=ExecutorConfig(max_retries_per_step=2, max_total_steps=10),
    )

    def build_plan(revision: int, feedback: str | None = None) -> Plan:
        """Build a one-step plan. If feedback is provided, tighten the prompt."""
        base_prompt = (
            "Given the task, respond with a JSON object containing a single key "
            "'solution' with a short, actionable answer. Only output valid JSON."
        )
        if feedback:
            base_prompt += f"\n\nPrevious attempt failed: {feedback}\nFix the response."

        step = PlanStep(
            id="generate_solution",
            description="Generate a short solution in JSON",
            action=ActionSpec(
                action_type=ActionType.LLM_CALL,
                prompt=base_prompt,
                system_prompt="You are a concise coding assistant.",
            ),
            inputs={"task": "$task"},
            expected_outputs=[],
            max_retries=2,
        )

        return Plan(
            id=f"starter-plan-r{revision}",
            goal_id=goal.id,
            description="Single-step coding plan",
            steps=[step],
            revision=revision,
            created_by="starter",
        )

    # Execute with a small test task
    print("▶ Executing starter agent with sample task...")
    task = "Write a one-line Python function that returns the sum of two numbers."
    context = {"task": task}

    max_replans = 2
    feedback = None
    final_status = None

    for attempt in range(max_replans + 1):
        plan = build_plan(revision=attempt + 1, feedback=feedback)
        result = await executor.execute_plan(plan=plan, goal=goal, context=context)
        final_status = result.status

        if result.status == ExecutionStatus.COMPLETED:
            parsed = result.results.get("parsed_json")
            solution = parsed.get("solution") if isinstance(parsed, dict) else None
            print("\n✅ Starter agent completed successfully")
            if solution:
                print(f"Solution: {solution}")
            else:
                print(f"Raw output: {result.results}")
            break

        if result.status == ExecutionStatus.NEEDS_REPLAN:
            feedback = result.feedback or "Unknown failure"
            print(f"\n🔁 Replanning due to: {feedback}")
            continue

        if result.status == ExecutionStatus.NEEDS_ESCALATION:
            print("\n🛑 Escalation required (human intervention).")
            print(f"Reason: {result.feedback}")
            break

        if result.status == ExecutionStatus.AWAITING_APPROVAL:
            print("\n⏸️ Execution paused for approval.")
            print(f"Reason: {result.feedback}")
            break

        print("\n❌ Execution failed.")
        print(f"Status: {result.status.value}")
        print(f"Feedback: {result.feedback}")
        break

    # If not completed, show failure analysis from last failed run
    if final_status is not None and final_status != ExecutionStatus.COMPLETED:
        print("\n📎 Failure Analysis (most recent failed run)")
        query = BuilderQuery(Path("./agent_logs"))
        failures = query.get_recent_failures(limit=1)
        if failures:
            analysis = query.analyze_failure(failures[0].run_id)
            if analysis:
                print(str(analysis))
        else:
            print("No failed runs found in agent_logs.")


if __name__ == "__main__":
    asyncio.run(main())
