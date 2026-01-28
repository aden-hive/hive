"""
Flexible Graph Executor with Worker-Judge Loop.

Executes plans created by external planner (Claude Code, etc.)
using a Worker-Judge loop:

1. External planner creates Plan
2. FlexibleGraphExecutor receives Plan
3. Worker executes each step
4. Judge evaluates each result
5. If Judge says "replan" → return to external planner with feedback
6. If Judge says "escalate" → request human intervention
7. If all steps complete → return success

This keeps planning external while execution/evaluation is internal.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.graph.code_sandbox import CodeSandbox
from framework.graph.goal import Goal
from framework.graph.judge import HybridJudge, create_default_judge
from framework.graph.plan import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResult,
    ExecutionStatus,
    Judgment,
    JudgmentAction,
    Plan,
    PlanExecutionResult,
    PlanStep,
    StepStatus,
)
from framework.graph.worker_node import StepExecutionResult, WorkerNode
from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime

# Type alias for approval callback
ApprovalCallback = Callable[[ApprovalRequest], ApprovalResult]


@dataclass
class ExecutorConfig:
    """Configuration for FlexibleGraphExecutor."""

    max_retries_per_step: int = 3
    max_total_steps: int = 100
    timeout_seconds: int = 300
    enable_parallel_execution: bool = False  # Future: parallel step execution


class FlexibleGraphExecutor:
    """
    Executes plans with Worker-Judge loop.

    Plans come from external source (Claude Code, etc.).
    Returns feedback for replanning if needed.

    Usage:
        executor = FlexibleGraphExecutor(
            runtime=runtime,
            llm=llm_provider,
            tools=tools,
        )

        result = await executor.execute_plan(plan, goal, context)

        if result.status == ExecutionStatus.NEEDS_REPLAN:
            # External planner should create new plan using result.feedback
            new_plan = external_planner.replan(result.feedback_context)
            result = await executor.execute_plan(new_plan, goal, result.feedback_context)
    """

    def __init__(
        self,
        runtime: Runtime,
        llm: LLMProvider | None = None,
        tools: dict[str, Tool] | None = None,
        tool_executor: Callable | None = None,
        functions: dict[str, Callable] | None = None,
        judge: HybridJudge | None = None,
        config: ExecutorConfig | None = None,
        approval_callback: ApprovalCallback | None = None,
    ):
        """
        Initialize the FlexibleGraphExecutor.

        Args:
            runtime: Runtime for decision logging
            llm: LLM provider for Worker and Judge
            tools: Available tools
            tool_executor: Function to execute tools
            functions: Registered functions
            judge: Custom judge (defaults to HybridJudge with default rules)
            config: Executor configuration
            approval_callback: Callback for human-in-the-loop approval.
                If None, steps requiring approval will pause execution.
        """
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or {}
        self.tool_executor = tool_executor
        self.functions = functions or {}
        self.config = config or ExecutorConfig()
        self.approval_callback = approval_callback

        # Create judge
        self.judge = judge or create_default_judge(llm)

        # Create worker
        self.worker = WorkerNode(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            functions=functions,
            sandbox=CodeSandbox(),
        )

    async def execute_plan(
        self,
        plan: Plan,
        goal: Goal,
        context: dict[str, Any] | None = None,
    ) -> PlanExecutionResult:
        """
        Execute a plan created by external planner.

        Args:
            plan: The plan to execute
            goal: The goal context
            context: Initial context (e.g., from previous execution)

        Returns:
            PlanExecutionResult with status and feedback
        """
        context = context or {}
        context.update(plan.context)  # Merge plan's accumulated context

        # Start run
        _run_id = self.runtime.start_run(
            goal_id=goal.id,
            goal_description=goal.description,
            input_data={"plan_id": plan.id, "revision": plan.revision},
        )

        steps_executed = 0
        total_tokens = 0
        total_latency = 0

        try:
            while steps_executed < self.config.max_total_steps:
                # Get next ready steps
                ready_steps = plan.get_ready_steps()

                if not ready_steps:
                    # Check if we're done or stuck
                    if plan.is_complete():
                        break
                    else:
                        # No ready steps but not complete - something's wrong
                        return self._create_result(
                            status=ExecutionStatus.NEEDS_REPLAN,
                            plan=plan,
                            context=context,
                            feedback=(
                                "No executable steps available but plan not complete. "
                                "Check dependencies."
                            ),
                            steps_executed=steps_executed,
                            total_tokens=total_tokens,
                            total_latency=total_latency,
                        )

                # Execute next step (for now, sequential; could be parallel)
                step = ready_steps[0]
                # Debug: show ready steps
                # ready_ids = [s.id for s in ready_steps]
                # print(f"  [DEBUG] Ready steps: {ready_ids}, executing: {step.id}")

                # APPROVAL CHECK - before execution
                if step.requires_approval:
                    approval_result = await self._request_approval(step, context)

                    if approval_result is None:
                        # No callback, pause execution
                        step.status = StepStatus.AWAITING_APPROVAL
                        return self._create_result(
                            status=ExecutionStatus.AWAITING_APPROVAL,
                            plan=plan,
                            context=context,
                            feedback=f"Step '{step.id}' requires approval: {step.description}",
                            steps_executed=steps_executed,
                            total_tokens=total_tokens,
                            total_latency=total_latency,
                        )

                    if approval_result.decision == ApprovalDecision.REJECT:
                        step.status = StepStatus.REJECTED
                        step.error = approval_result.reason or "Rejected by human"
                        # Skip this step and continue with dependents marked as skipped
                        self._skip_dependent_steps(plan, step.id)
                        continue

                    if approval_result.decision == ApprovalDecision.ABORT:
                        return self._create_result(
                            status=ExecutionStatus.ABORTED,
                            plan=plan,
                            context=context,
                            feedback=approval_result.reason or "Aborted by human",
                            steps_executed=steps_executed,
                            total_tokens=total_tokens,
                            total_latency=total_latency,
                        )

                    if approval_result.decision == ApprovalDecision.MODIFY:
                        # Apply modifications to step
                        if approval_result.modifications:
                            self._apply_modifications(step, approval_result.modifications)

                    # APPROVE - continue to execution

                step.status = StepStatus.IN_PROGRESS
                step.started_at = datetime.now()
                step.attempts += 1

                # WORK
                work_result = await self.worker.execute(step, context)
                steps_executed += 1
                total_tokens += work_result.tokens_used
                total_latency += work_result.latency_ms

                # JUDGE
                judgment = await self.judge.evaluate(
                    step=step,
                    result=work_result.__dict__,
                    goal=goal,
                    context=context,
                )

                # Handle judgment
                result = await self._handle_judgment(
                    step=step,
                    work_result=work_result,
                    judgment=judgment,
                    plan=plan,
                    goal=goal,
                    context=context,
                    steps_executed=steps_executed,
                    total_tokens=total_tokens,
                    total_latency=total_latency,
                )

                if result is not None:
                    # Judgment resulted in early return (replan/escalate)
                    self.runtime.end_run(
                        success=False,
                        narrative=f"Execution stopped: {result.status.value}",
                    )
                    return result

            # All steps completed successfully
            self.runtime.end_run(
                success=True,
                output_data=context,
                narrative=f"Plan completed: {steps_executed} steps executed",
            )

            return self._create_result(
                status=ExecutionStatus.COMPLETED,
                plan=plan,
                context=context,
                steps_executed=steps_executed,
                total_tokens=total_tokens,
                total_latency=total_latency,
            )

        except Exception as e:
            self.runtime.report_problem(
                severity="critical",
                description=str(e),
            )
            self.runtime.end_run(
                success=False,
                narrative=f"Execution failed: {e}",
            )

            return PlanExecutionResult(
                status=ExecutionStatus.FAILED,
                error=str(e),
                feedback=f"Execution error: {e}",
                feedback_context=plan.to_feedback_context(),
                completed_steps=[s.id for s in plan.get_completed_steps()],
                steps_executed=steps_executed,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
            )

    async def _handle_judgment(
        self,
        step: PlanStep,
        work_result: StepExecutionResult,
        judgment: Judgment,
        plan: Plan,
        goal: Goal,
        context: dict[str, Any],
        steps_executed: int,
        total_tokens: int,
        total_latency: int,
    ) -> PlanExecutionResult | None:
        """
        Handle judgment and return result if execution should stop.

        Returns None to continue execution, or PlanExecutionResult to stop.
        """
        if judgment.action == JudgmentAction.ACCEPT:
            # Step succeeded - update state and continue
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.now()
            step.result = work_result.outputs

            # Map outputs to expected output keys
            # If output has generic "result" key but step expects specific keys, map it
            outputs_to_store = work_result.outputs.copy()
            if step.expected_outputs and "result" in outputs_to_store:
                result_value = outputs_to_store["result"]
                # For each expected output key that's not in outputs, map from "result"
                for expected_key in step.expected_outputs:
                    if expected_key not in outputs_to_store:
                        outputs_to_store[expected_key] = result_value

            # Update context with mapped outputs
            context.update(outputs_to_store)

            # Store in plan context for replanning feedback
            plan.context[step.id] = outputs_to_store

            return None  # Continue execution

        elif judgment.action == JudgmentAction.RETRY:
            # Retry step if under limit
            if step.attempts < step.max_retries:
                step.status = StepStatus.PENDING
                step.error = judgment.feedback

                # Record retry decision
                self.runtime.decide(
                    intent=f"Retry step {step.id}",
                    options=[{"id": "retry", "description": "Retry with feedback"}],
                    chosen="retry",
                    reasoning=judgment.reasoning,
                    context={"attempt": step.attempts, "feedback": judgment.feedback},
                )

                return None  # Continue (step will be retried)
            else:
                # Max retries exceeded - escalate to replan
                step.status = StepStatus.FAILED
                step.error = f"Max retries ({step.max_retries}) exceeded: {judgment.feedback}"

                return self._create_result(
                    status=ExecutionStatus.NEEDS_REPLAN,
                    plan=plan,
                    context=context,
                    feedback=(
                        f"Step '{step.id}' failed after {step.attempts} attempts: "
                        f"{judgment.feedback}"
                    ),
                    steps_executed=steps_executed,
                    total_tokens=total_tokens,
                    total_latency=total_latency,
                )

        elif judgment.action == JudgmentAction.REPLAN:
            # Return to external planner
            step.status = StepStatus.FAILED
            step.error = judgment.feedback

            return self._create_result(
                status=ExecutionStatus.NEEDS_REPLAN,
                plan=plan,
                context=context,
                feedback=judgment.feedback or f"Step '{step.id}' requires replanning",
                steps_executed=steps_executed,
                total_tokens=total_tokens,
                total_latency=total_latency,
            )

        elif judgment.action == JudgmentAction.ESCALATE:
            # Request human intervention
            return self._create_result(
                status=ExecutionStatus.NEEDS_ESCALATION,
                plan=plan,
                context=context,
                feedback=judgment.feedback or f"Step '{step.id}' requires human intervention",
                steps_executed=steps_executed,
                total_tokens=total_tokens,
                total_latency=total_latency,
            )

        return None  # Unknown action - continue

    def _create_result(
        self,
        status: ExecutionStatus,
        plan: Plan,
        context: dict[str, Any],
        feedback: str | None = None,
        steps_executed: int = 0,
        total_tokens: int = 0,
        total_latency: int = 0,
    ) -> PlanExecutionResult:
        """Create a PlanExecutionResult."""
        return PlanExecutionResult(
            status=status,
            results=context,
            feedback=feedback,
            feedback_context=plan.to_feedback_context(),
            completed_steps=[s.id for s in plan.get_completed_steps()],
            steps_executed=steps_executed,
            total_tokens=total_tokens,
            total_latency_ms=total_latency,
        )

    def register_function(self, name: str, func: Callable) -> None:
        """Register a function for FUNCTION actions."""
        self.functions[name] = func
        self.worker.register_function(name, func)

    def register_tool(self, tool: Tool) -> None:
        """Register a tool for TOOL_USE actions."""
        self.tools[tool.name] = tool
        self.worker.register_tool(tool)

    def add_evaluation_rule(self, rule) -> None:
        """Add an evaluation rule to the judge."""
        self.judge.add_rule(rule)

    async def _request_approval(
        self,
        step: PlanStep,
        context: dict[str, Any],
    ) -> ApprovalResult | None:
        """
        Request human approval for a step.

        Returns None if no callback is set (execution should pause).
        """
        if self.approval_callback is None:
            return None

        # Build preview of what will happen
        preview_parts = []
        if step.action.tool_name:
            preview_parts.append(f"Tool: {step.action.tool_name}")
            if step.action.tool_args:
                import json

                args_preview = json.dumps(step.action.tool_args, indent=2, default=str)
                if len(args_preview) > 500:
                    args_preview = args_preview[:500] + "..."
                preview_parts.append(f"Args: {args_preview}")
        elif step.action.prompt:
            prompt_preview = (
                step.action.prompt[:300] + "..."
                if len(step.action.prompt) > 300
                else step.action.prompt
            )
            preview_parts.append(f"Prompt: {prompt_preview}")

        # Include step inputs resolved from context (what will be sent/used)
        relevant_context = {}
        for input_key, input_value in step.inputs.items():
            # Resolve variable references like "$email_sequence"
            if isinstance(input_value, str) and input_value.startswith("$"):
                context_key = input_value[1:]  # Remove $ prefix
                if context_key in context:
                    relevant_context[input_key] = context[context_key]
            else:
                relevant_context[input_key] = input_value

        request = ApprovalRequest(
            step_id=step.id,
            step_description=step.description,
            action_type=step.action.action_type.value,
            action_details={
                "tool_name": step.action.tool_name,
                "tool_args": step.action.tool_args,
                "prompt": step.action.prompt,
            },
            context=relevant_context,
            approval_message=step.approval_message,
            preview="\n".join(preview_parts) if preview_parts else None,
        )

        return self.approval_callback(request)

    def _skip_dependent_steps(self, plan: Plan, rejected_step_id: str) -> None:
        """Mark steps that depend on a rejected step as skipped."""
        for step in plan.steps:
            if rejected_step_id in step.dependencies:
                if step.status == StepStatus.PENDING:
                    step.status = StepStatus.SKIPPED
                    step.error = f"Skipped because dependency '{rejected_step_id}' was rejected"
                    # Recursively skip dependents
                    self._skip_dependent_steps(plan, step.id)

    def _apply_modifications(self, step: PlanStep, modifications: dict[str, Any]) -> None:
        """Apply human modifications to a step before execution."""
        # Allow modifying tool args
        if "tool_args" in modifications and step.action.tool_args:
            step.action.tool_args.update(modifications["tool_args"])

        # Allow modifying prompt
        if "prompt" in modifications:
            step.action.prompt = modifications["prompt"]

        # Allow modifying inputs
        if "inputs" in modifications:
            step.inputs.update(modifications["inputs"])

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """Set the approval callback for HITL steps."""
        self.approval_callback = callback


# Convenience function for simple execution
async def execute_plan(
    plan: Plan,
    goal: Goal,
    runtime: Runtime,
    llm: LLMProvider | None = None,
    tools: dict[str, Tool] | None = None,
    tool_executor: Callable | None = None,
    context: dict[str, Any] | None = None,
) -> PlanExecutionResult:
    """
    Execute a plan with default configuration.

    Convenience function for simple use cases.
    """
    executor = FlexibleGraphExecutor(
        runtime=runtime,
        llm=llm,
        tools=tools,
        tool_executor=tool_executor,
    )
    return await executor.execute_plan(plan, goal, context)
