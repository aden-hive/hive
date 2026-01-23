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

Checkpoint System:
- Auto-saves state after each successful step
- Supports resuming from last checkpoint on failure
- Minimal overhead with filesystem storage
"""

from typing import Any, Callable
from dataclasses import dataclass
from datetime import datetime

from framework.runtime.core import Runtime
from framework.runtime.checkpoint import CheckpointManager
from framework.graph.goal import Goal
from framework.graph.plan import (
    Plan,
    PlanStep,
    PlanExecutionResult,
    ExecutionStatus,
    StepStatus,
    Judgment,
    JudgmentAction,
    ApprovalRequest,
    ApprovalResult,
    ApprovalDecision,
)
from framework.graph.judge import HybridJudge, create_default_judge
from framework.graph.worker_node import WorkerNode, StepExecutionResult
from framework.graph.code_sandbox import CodeSandbox
from framework.llm.provider import LLMProvider, Tool

# Type alias for approval callback
ApprovalCallback = Callable[[ApprovalRequest], ApprovalResult]


@dataclass
class ExecutorConfig:
    """Configuration for FlexibleGraphExecutor."""
    max_retries_per_step: int = 3
    max_total_steps: int = 100
    timeout_seconds: int = 300
    enable_parallel_execution: bool = False  # Future: parallel step execution
    # Checkpoint options
    checkpoint_enabled: bool = True
    checkpoint_path: str | None = None
    auto_cleanup_checkpoints: bool = True


class FlexibleGraphExecutor:
    """
    Executes plans with Worker-Judge loop.

    Plans come from external source (Claude Code, etc.).
    Returns feedback for replanning if needed.
    
    Supports checkpoint-based recovery:
    - Auto-saves state after each successful step
    - Resume from last checkpoint using run_id and resume_from_checkpoint=True

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
            
    With checkpoint recovery:
        # Resume a failed execution
        result = await executor.execute_plan(
            plan, goal, context,
            run_id="run_20250123_abc123",
            resume_from_checkpoint=True,
        )
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
            config: Executor configuration (includes checkpoint options)
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
        
        # Initialize checkpoint manager
        self.checkpoint_manager = CheckpointManager(
            storage_path=self.config.checkpoint_path,
            enabled=self.config.checkpoint_enabled,
            auto_cleanup=self.config.auto_cleanup_checkpoints,
        )

    async def execute_plan(
        self,
        plan: Plan,
        goal: Goal,
        context: dict[str, Any] | None = None,
        # Checkpoint recovery options
        run_id: str | None = None,
        resume_from_checkpoint: bool = False,
    ) -> PlanExecutionResult:
        """
        Execute a plan created by external planner.

        Args:
            plan: The plan to execute
            goal: The goal context
            context: Initial context (e.g., from previous execution)
            run_id: Optional run ID for checkpoint recovery
            resume_from_checkpoint: Whether to resume from last checkpoint

        Returns:
            PlanExecutionResult with status and feedback
        """
        context = context or {}
        context.update(plan.context)  # Merge plan's accumulated context

        steps_executed = 0
        total_tokens = 0
        total_latency = 0
        completed_step_ids: set[str] = set()

        # Check for checkpoint recovery
        if resume_from_checkpoint and run_id and self.checkpoint_manager.can_resume(run_id):
            checkpoint = self.checkpoint_manager.load_latest(run_id)
            if checkpoint:
                # Restore state from checkpoint
                context.update(checkpoint.memory_state.get("context", {}))
                completed_step_ids = set(checkpoint.memory_state.get("completed_step_ids", []))
                total_tokens = checkpoint.total_tokens
                total_latency = checkpoint.total_latency_ms
                steps_executed = checkpoint.step_number
                
                # Mark completed steps in plan
                for step in plan.steps:
                    if step.id in completed_step_ids:
                        step.status = StepStatus.COMPLETED

        # Start run
        _run_id = run_id or self.runtime.start_run(
            goal_id=goal.id,
            goal_description=goal.description,
            input_data={"plan_id": plan.id, "revision": plan.revision},
        )

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
                            feedback="No executable steps available but plan not complete. Check dependencies.",
                            steps_executed=steps_executed,
                            total_tokens=total_tokens,
                            total_latency=total_latency,
                        )

                # Execute next step (for now, sequential; could be parallel)
                step = ready_steps[0]

                # APPROVAL CHECK - before execution
                if step.requires_approval:
                    approval_result = await self._request_approval(step, context)

                    if approval_result is None:
                        # No callback, pause execution
                        step.status = StepStatus.AWAITING_APPROVAL
                        
                        # Save checkpoint before pausing
                        self._save_checkpoint(
                            run_id=_run_id,
                            plan=plan,
                            goal=goal,
                            step=step,
                            context=context,
                            completed_step_ids=completed_step_ids,
                            steps_executed=steps_executed,
                            total_tokens=total_tokens,
                            total_latency=total_latency,
                        )
                        self.checkpoint_manager.on_pause(_run_id)
                        
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
                        if approval_result.modifications:
                            self._apply_modifications(step, approval_result.modifications)

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
                    completed_step_ids=completed_step_ids,
                    steps_executed=steps_executed,
                    total_tokens=total_tokens,
                    total_latency=total_latency,
                    run_id=_run_id,
                )

                if result is not None:
                    # Judgment resulted in early return (replan/escalate)
                    self.runtime.end_run(
                        success=False,
                        narrative=f"Execution stopped: {result.status.value}",
                    )
                    # Mark as failed but keep checkpoints
                    self.checkpoint_manager.on_execution_complete(_run_id, success=False, error=result.feedback)
                    return result

            # All steps completed successfully
            self.runtime.end_run(
                success=True,
                output_data=context,
                narrative=f"Plan completed: {steps_executed} steps executed",
            )
            
            # Cleanup checkpoints on success
            self.checkpoint_manager.on_execution_complete(_run_id, success=True)

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
            
            # Mark as failed, keep checkpoints for recovery
            self.checkpoint_manager.on_execution_complete(_run_id, success=False, error=str(e))

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

    def _save_checkpoint(
        self,
        run_id: str,
        plan: Plan,
        goal: Goal,
        step: PlanStep,
        context: dict[str, Any],
        completed_step_ids: set[str],
        steps_executed: int,
        total_tokens: int,
        total_latency: int,
    ) -> None:
        """Save a checkpoint after successful step execution."""
        self.checkpoint_manager.save(
            run_id=run_id,
            graph_id=plan.id,
            step_number=steps_executed,
            completed_node_id=step.id,
            next_node_id=None,  # Will be determined by plan.get_ready_steps()
            path=list(completed_step_ids),
            memory_state={
                "context": context,
                "completed_step_ids": list(completed_step_ids),
                "plan_revision": plan.revision,
            },
            total_tokens=total_tokens,
            total_latency_ms=total_latency,
            input_data={"plan_id": plan.id},
            goal_id=goal.id,
        )

    async def _handle_judgment(
        self,
        step: PlanStep,
        work_result: StepExecutionResult,
        judgment: Judgment,
        plan: Plan,
        goal: Goal,
        context: dict[str, Any],
        completed_step_ids: set[str],
        steps_executed: int,
        total_tokens: int,
        total_latency: int,
        run_id: str,
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
            completed_step_ids.add(step.id)

            # Map outputs to expected output keys
            outputs_to_store = work_result.outputs.copy()
            if step.expected_outputs and "result" in outputs_to_store:
                result_value = outputs_to_store["result"]
                for expected_key in step.expected_outputs:
                    if expected_key not in outputs_to_store:
                        outputs_to_store[expected_key] = result_value

            # Update context with mapped outputs
            context.update(outputs_to_store)

            # Store in plan context for replanning feedback
            plan.context[step.id] = outputs_to_store
            
            # SAVE CHECKPOINT after successful step
            self._save_checkpoint(
                run_id=run_id,
                plan=plan,
                goal=goal,
                step=step,
                context=context,
                completed_step_ids=completed_step_ids,
                steps_executed=steps_executed,
                total_tokens=total_tokens,
                total_latency=total_latency,
            )

            return None  # Continue execution

        elif judgment.action == JudgmentAction.RETRY:
            # Retry step if under limit
            if step.attempts < step.max_retries:
                step.status = StepStatus.PENDING
                step.error = judgment.feedback

                self.runtime.decide(
                    intent=f"Retry step {step.id}",
                    options=[{"id": "retry", "description": "Retry with feedback"}],
                    chosen="retry",
                    reasoning=judgment.reasoning,
                    context={"attempt": step.attempts, "feedback": judgment.feedback},
                )

                return None  # Continue (step will be retried)
            else:
                step.status = StepStatus.FAILED
                step.error = f"Max retries ({step.max_retries}) exceeded: {judgment.feedback}"

                return self._create_result(
                    status=ExecutionStatus.NEEDS_REPLAN,
                    plan=plan,
                    context=context,
                    feedback=f"Step '{step.id}' failed after {step.attempts} attempts: {judgment.feedback}",
                    steps_executed=steps_executed,
                    total_tokens=total_tokens,
                    total_latency=total_latency,
                )

        elif judgment.action == JudgmentAction.REPLAN:
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
            prompt_preview = step.action.prompt[:300] + "..." if len(step.action.prompt) > 300 else step.action.prompt
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
