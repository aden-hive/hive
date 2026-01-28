"""
Worker Node for Executing Plan Steps.

The Worker executes individual plan steps by dispatching to the
appropriate executor based on action type:
- LLM calls
- Tool usage
- Sub-graph execution
- Function calls
- Code execution (sandboxed)
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from framework.graph.code_sandbox import CodeSandbox
from framework.graph.plan import (
    ActionSpec,
    ActionType,
    PlanStep,
)
from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime

logger = logging.getLogger(__name__)


def parse_llm_json_response(text: str) -> tuple[Any | None, str]:
    """
    Parse JSON from LLM response, handling markdown code blocks.

    LLMs often return JSON wrapped in markdown code blocks like:
    ```json
    {"key": "value"}
    ```

    This function extracts and parses the JSON.

    Args:
        text: Raw LLM response text

    Returns:
        Tuple of (parsed_json_or_None, cleaned_text)
    """
    if not isinstance(text, str):
        return None, str(text)

    cleaned = text.strip()

    # Try to extract JSON from markdown code blocks
    # Pattern: ```json ... ``` or ``` ... ```
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    matches = re.findall(code_block_pattern, cleaned)

    if matches:
        # Try to parse each match
        for match in matches:
            try:
                parsed = json.loads(match.strip())
                return parsed, match.strip()
            except json.JSONDecodeError as e:
                logger.debug(
                    f"Failed to parse JSON from code block: {e}. "
                    f"Content preview: {match.strip()[:100]}..."
                )
                continue

    # No code blocks or parsing failed - try parsing the whole response
    try:
        parsed = json.loads(cleaned)
        return parsed, cleaned
    except json.JSONDecodeError as e:
        logger.debug(
            f"Failed to parse entire response as JSON: {e}. Content preview: {cleaned[:100]}..."
        )

    # Try to find JSON-like content (starts with { or [)
    json_start_pattern = r"(\{[\s\S]*\}|\[[\s\S]*\])"
    json_matches = re.findall(json_start_pattern, cleaned)

    for match in json_matches:
        try:
            parsed = json.loads(match)
            return parsed, match
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse JSON pattern: {e}. Content preview: {match[:100]}...")
            continue

    # Could not parse as JSON - log warning
    logger.warning(
        f"Could not parse LLM response as JSON after trying all strategies. "
        f"Response preview: {cleaned[:200]}..."
    )
    return None, cleaned


@dataclass
class StepExecutionResult:
    """Result of executing a plan step."""

    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None  # For judge rules: timeout, rate_limit, etc.

    # Metadata
    tokens_used: int = 0
    latency_ms: int = 0
    executor_type: str = ""


class WorkerNode:
    """
    Executes plan steps by dispatching to appropriate executors.

    Usage:
        worker = WorkerNode(
            runtime=runtime,
            llm=llm_provider,
            tools=tool_registry,
        )

        result = await worker.execute(step, context)
    """

    def __init__(
        self,
        runtime: Runtime,
        llm: LLMProvider | None = None,
        tools: dict[str, Tool] | None = None,
        tool_executor: Callable | None = None,
        functions: dict[str, Callable] | None = None,
        sub_graph_executor: Callable | None = None,
        sandbox: CodeSandbox | None = None,
    ):
        """
        Initialize the Worker.

        Args:
            runtime: Runtime for decision logging
            llm: LLM provider for LLM_CALL actions
            tools: Available tools for TOOL_USE actions
            tool_executor: Function to execute tools
            functions: Registered functions for FUNCTION actions
            sub_graph_executor: Function to execute sub-graphs
            sandbox: Code sandbox for CODE_EXECUTION actions
        """
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or {}
        self.tool_executor = tool_executor
        self.functions = functions or {}
        self.sub_graph_executor = sub_graph_executor
        self.sandbox = sandbox or CodeSandbox()

    async def execute(
        self,
        step: PlanStep,
        context: dict[str, Any],
    ) -> StepExecutionResult:
        """
        Execute a plan step.

        Args:
            step: The step to execute
            context: Current execution context

        Returns:
            StepExecutionResult with outputs and status
        """
        # Record decision
        decision_id = self.runtime.decide(
            intent=f"Execute plan step: {step.description}",
            options=[
                {
                    "id": step.action.action_type.value,
                    "description": f"Execute {step.action.action_type.value} action",
                    "action_type": step.action.action_type.value,
                }
            ],
            chosen=step.action.action_type.value,
            reasoning=f"Step requires {step.action.action_type.value}",
            context={"step_id": step.id, "inputs": step.inputs},
        )

        start_time = time.time()

        try:
            # Resolve inputs from context
            resolved_inputs = self._resolve_inputs(step.inputs, context)

            # Dispatch to appropriate executor
            result = await self._dispatch(step.action, resolved_inputs, context)

            latency_ms = int((time.time() - start_time) * 1000)
            result.latency_ms = latency_ms

            # Record outcome
            self.runtime.record_outcome(
                decision_id=decision_id,
                success=result.success,
                result=result.outputs if result.success else result.error,
                tokens_used=result.tokens_used,
                latency_ms=latency_ms,
            )

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)

            self.runtime.record_outcome(
                decision_id=decision_id,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )

            return StepExecutionResult(
                success=False,
                error=str(e),
                error_type="exception",
                latency_ms=latency_ms,
            )

    def _resolve_inputs(
        self,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve input references from context."""
        resolved = {}

        for key, value in inputs.items():
            if isinstance(value, str) and value.startswith("$"):
                # Reference to context variable
                ref_key = value[1:]  # Remove $
                resolved[key] = context.get(ref_key, value)
            else:
                resolved[key] = value

        return resolved

    async def _dispatch(
        self,
        action: ActionSpec,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> StepExecutionResult:
        """Dispatch to appropriate executor based on action type."""
        if action.action_type == ActionType.LLM_CALL:
            return await self._execute_llm_call(action, inputs, context)

        elif action.action_type == ActionType.TOOL_USE:
            return await self._execute_tool_use(action, inputs)

        elif action.action_type == ActionType.SUB_GRAPH:
            return await self._execute_sub_graph(action, inputs, context)

        elif action.action_type == ActionType.FUNCTION:
            return await self._execute_function(action, inputs)

        elif action.action_type == ActionType.CODE_EXECUTION:
            return self._execute_code(action, inputs, context)

        else:
            return StepExecutionResult(
                success=False,
                error=f"Unknown action type: {action.action_type}",
                error_type="invalid_action",
            )

    async def _execute_llm_call(
        self,
        action: ActionSpec,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> StepExecutionResult:
        """Execute an LLM call action."""
        if self.llm is None:
            return StepExecutionResult(
                success=False,
                error="No LLM provider configured",
                error_type="configuration",
                executor_type="llm_call",
            )

        try:
            # Build prompt with context data
            prompt = action.prompt or ""

            # First try format placeholders (for prompts like "Hello {name}")
            if inputs:
                try:
                    prompt = prompt.format(**inputs)
                except (KeyError, ValueError):
                    pass  # Keep original prompt if formatting fails

            # Always append context data so LLM can personalize
            # This ensures the LLM has access to lead info, company context, etc.
            if inputs:
                context_section = "\n\n--- Context Data ---\n"
                for key, value in inputs.items():
                    if isinstance(value, dict | list):
                        context_section += f"{key}: {json.dumps(value, indent=2)}\n"
                    else:
                        context_section += f"{key}: {value}\n"
                prompt = prompt + context_section

            messages = [{"role": "user", "content": prompt}]

            response = self.llm.complete(
                messages=messages,
                system=action.system_prompt,
            )

            # Try to parse JSON from LLM response
            # LLMs often return JSON wrapped in markdown code blocks
            parsed_json, _ = parse_llm_json_response(response.content)

            # If JSON was parsed successfully, use it as the result
            # Otherwise, use the raw text
            result_value = parsed_json if parsed_json is not None else response.content

            return StepExecutionResult(
                success=True,
                outputs={
                    "result": result_value,
                    "response": response.content,  # Always keep raw response
                    "parsed_json": parsed_json,  # Explicit parsed JSON (or None)
                },
                tokens_used=response.input_tokens + response.output_tokens,
                executor_type="llm_call",
            )

        except Exception as e:
            error_type = "rate_limit" if "rate" in str(e).lower() else "llm_error"
            return StepExecutionResult(
                success=False,
                error=str(e),
                error_type=error_type,
                executor_type="llm_call",
            )

    async def _execute_tool_use(
        self,
        action: ActionSpec,
        inputs: dict[str, Any],
    ) -> StepExecutionResult:
        """Execute a tool use action."""
        tool_name = action.tool_name
        if not tool_name:
            return StepExecutionResult(
                success=False,
                error="No tool name specified",
                error_type="invalid_action",
                executor_type="tool_use",
            )

        # Merge action args with inputs
        args = {**action.tool_args, **inputs}

        # Resolve any $variable references in the merged args
        # (tool_args may contain $refs that should be resolved from inputs)
        resolved_args = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$"):
                ref_key = value[1:]  # Remove $
                resolved_args[key] = args.get(ref_key, value)
            else:
                resolved_args[key] = value
        args = resolved_args

        # First, check if we have a registered function with this name
        # This allows simpler tool registration without full Tool/ToolExecutor setup
        if tool_name in self.functions:
            try:
                func = self.functions[tool_name]
                result = func(**args)

                # Handle async functions
                if hasattr(result, "__await__"):
                    result = await result

                # If result is already a dict with success/outputs, use it directly
                if isinstance(result, dict) and "success" in result:
                    return StepExecutionResult(
                        success=result.get("success", False),
                        outputs=result.get("outputs", {}),
                        error=result.get("error"),
                        error_type=result.get("error_type"),
                        executor_type="tool_use",
                    )

                # Otherwise wrap the result
                return StepExecutionResult(
                    success=True,
                    outputs={"result": result},
                    executor_type="tool_use",
                )

            except Exception as e:
                return StepExecutionResult(
                    success=False,
                    error=str(e),
                    error_type="tool_exception",
                    executor_type="tool_use",
                )

        # Fall back to formal Tool registry
        if tool_name not in self.tools:
            return StepExecutionResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                error_type="missing_tool",
                executor_type="tool_use",
            )

        if self.tool_executor is None:
            return StepExecutionResult(
                success=False,
                error="No tool executor configured",
                error_type="configuration",
                executor_type="tool_use",
            )

        try:
            # Execute tool via formal executor
            from framework.llm.provider import ToolUse

            tool_use = ToolUse(
                id=f"step_{tool_name}",
                name=tool_name,
                input=args,
            )

            result = self.tool_executor(tool_use)

            if result.is_error:
                return StepExecutionResult(
                    success=False,
                    outputs={},
                    error=result.content,
                    error_type="tool_error",
                    executor_type="tool_use",
                )

            # Parse JSON result and unpack fields into outputs
            # Tools return JSON like {"lead_email": "...", "company_name": "..."}
            # We want each field as a separate output key
            outputs = {"result": result.content}
            try:
                parsed = json.loads(result.content)
                if isinstance(parsed, dict):
                    # Unpack all fields from the JSON response
                    outputs.update(parsed)
            except (json.JSONDecodeError, TypeError):
                pass  # Keep result as-is if not valid JSON

            return StepExecutionResult(
                success=True,
                outputs=outputs,
                executor_type="tool_use",
            )

        except Exception as e:
            return StepExecutionResult(
                success=False,
                error=str(e),
                error_type="tool_exception",
                executor_type="tool_use",
            )

    async def _execute_sub_graph(
        self,
        action: ActionSpec,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> StepExecutionResult:
        """Execute a sub-graph action."""
        if self.sub_graph_executor is None:
            return StepExecutionResult(
                success=False,
                error="No sub-graph executor configured",
                error_type="configuration",
                executor_type="sub_graph",
            )

        graph_id = action.graph_id
        if not graph_id:
            return StepExecutionResult(
                success=False,
                error="No graph ID specified",
                error_type="invalid_action",
                executor_type="sub_graph",
            )

        try:
            result = await self.sub_graph_executor(graph_id, inputs, context)

            return StepExecutionResult(
                success=result.success,
                outputs=result.output if result.success else {},
                error=result.error if not result.success else None,
                tokens_used=result.total_tokens,
                executor_type="sub_graph",
            )

        except Exception as e:
            return StepExecutionResult(
                success=False,
                error=str(e),
                error_type="sub_graph_exception",
                executor_type="sub_graph",
            )

    async def _execute_function(
        self,
        action: ActionSpec,
        inputs: dict[str, Any],
    ) -> StepExecutionResult:
        """Execute a function action."""
        func_name = action.function_name
        if not func_name:
            return StepExecutionResult(
                success=False,
                error="No function name specified",
                error_type="invalid_action",
                executor_type="function",
            )

        if func_name not in self.functions:
            return StepExecutionResult(
                success=False,
                error=f"Function '{func_name}' not registered",
                error_type="missing_function",
                executor_type="function",
            )

        try:
            func = self.functions[func_name]

            # Merge action args with inputs
            args = {**action.function_args, **inputs}

            # Execute function
            result = func(**args)

            # Handle async functions
            if hasattr(result, "__await__"):
                result = await result

            return StepExecutionResult(
                success=True,
                outputs={"result": result},
                executor_type="function",
            )

        except Exception as e:
            return StepExecutionResult(
                success=False,
                error=str(e),
                error_type="function_exception",
                executor_type="function",
            )

    def _execute_code(
        self,
        action: ActionSpec,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> StepExecutionResult:
        """Execute a code action in sandbox."""
        code = action.code
        if not code:
            return StepExecutionResult(
                success=False,
                error="No code specified",
                error_type="invalid_action",
                executor_type="code_execution",
            )

        # Merge inputs with context for code
        code_inputs = {**context, **inputs}

        # Execute in sandbox
        sandbox_result = self.sandbox.execute(code, code_inputs)

        if sandbox_result.success:
            return StepExecutionResult(
                success=True,
                outputs={
                    "result": sandbox_result.result,
                    **sandbox_result.variables,
                },
                executor_type="code_execution",
                latency_ms=sandbox_result.execution_time_ms,
            )
        else:
            error_type = "security" if "Security" in (sandbox_result.error or "") else "code_error"
            return StepExecutionResult(
                success=False,
                error=sandbox_result.error,
                error_type=error_type,
                executor_type="code_execution",
                latency_ms=sandbox_result.execution_time_ms,
            )

    def register_function(self, name: str, func: Callable) -> None:
        """Register a function for FUNCTION actions."""
        self.functions[name] = func

    def register_tool(self, tool: Tool) -> None:
        """Register a tool for TOOL_USE actions."""
        self.tools[tool.name] = tool
