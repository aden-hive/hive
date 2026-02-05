"""
Node Protocol - The building block of agent graphs.

A Node is a unit of work that:
1. Receives context (goal, shared memory, input)
2. Makes decisions (using LLM, tools, or logic)
3. Produces results (output, state changes)
4. Records everything to the Runtime

Nodes are composable and reusable. The same node can appear
in different graphs for different goals.

Protocol:
    Every node must implement the NodeProtocol interface.
    The framework provides NodeContext with everything the node needs.
"""

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from pydantic import BaseModel, Field

from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime

logger = logging.getLogger(__name__)


def _fix_unescaped_newlines_in_json(json_str: str) -> str:
    """Fix unescaped newlines inside JSON string values.

    LLMs sometimes output actual newlines inside JSON strings instead of \\n.
    This function fixes that by properly escaping newlines within string values.
    """
    result = []
    in_string = False
    escape_next = False
    i = 0

    while i < len(json_str):
        char = json_str[i]

        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue

        if char == "\\" and in_string:
            escape_next = True
            result.append(char)
            i += 1
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            result.append(char)
            i += 1
            continue

        # Fix unescaped newlines inside strings
        if in_string and char == "\n":
            result.append("\\n")
            i += 1
            continue

        # Fix unescaped carriage returns inside strings
        if in_string and char == "\r":
            result.append("\\r")
            i += 1
            continue

        # Fix unescaped tabs inside strings
        if in_string and char == "\t":
            result.append("\\t")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


def find_json_object(text: str) -> str | None:
    """Find the first valid JSON object in text using balanced brace matching.

    This handles nested objects correctly, unlike simple regex like r'\\{[^{}]*\\}'.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


class NodeSpec(BaseModel):
    """
    Specification for a node in the graph.

    This is the declarative definition of a node - what it does,
    what it needs, and what it produces. The actual implementation
    is separate (NodeProtocol).

    Example:
        NodeSpec(
            id="calculator",
            name="Calculator Node",
            description="Performs mathematical calculations",
            node_type="llm_tool_use",
            input_keys=["expression"],
            output_keys=["result"],
            tools=["calculate", "math_function"],
            system_prompt="You are a calculator..."
        )
    """

    id: str
    name: str
    description: str

    # Node behavior type
    node_type: str = Field(
        default="llm_tool_use",
        description=(
            "Type: 'event_loop', 'function', 'router', 'human_input'. "
            "Deprecated: 'llm_tool_use', 'llm_generate' (use 'event_loop' instead)."
        ),
    )

    # Data flow
    input_keys: list[str] = Field(
        default_factory=list, description="Keys this node reads from shared memory or input"
    )
    output_keys: list[str] = Field(
        default_factory=list, description="Keys this node writes to shared memory or output"
    )
    nullable_output_keys: list[str] = Field(
        default_factory=list,
        description="Output keys that can be None without triggering validation errors",
    )

    # Optional schemas for validation and cleansing
    input_schema: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Optional schema for input validation. "
            "Format: {key: {type: 'string', required: True, description: '...'}}"
        ),
    )
    output_schema: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Optional schema for output validation. "
            "Format: {key: {type: 'dict', required: True, description: '...'}}"
        ),
    )

    # For LLM nodes
    system_prompt: str | None = Field(default=None, description="System prompt for LLM nodes")
    tools: list[str] = Field(default_factory=list, description="Tool names this node can use")
    model: str | None = Field(
        default=None, description="Specific model to use (defaults to graph default)"
    )

    # For function nodes
    function: str | None = Field(
        default=None, description="Function name or path for function nodes"
    )

    # For router nodes
    routes: dict[str, str] = Field(
        default_factory=dict, description="Condition -> target_node_id mapping for routers"
    )

    # Retry behavior
    max_retries: int = Field(default=3)
    retry_on: list[str] = Field(default_factory=list, description="Error types to retry on")

    # Visit limits (for feedback/callback edges)
    max_node_visits: int = Field(
        default=1,
        description=(
            "Max times this node executes in one graph run. "
            "Set >1 for feedback loops. 0 = unlimited (max_steps guards)."
        ),
    )

    # Pydantic model for output validation
    output_model: type[BaseModel] | None = Field(
        default=None,
        description=(
            "Optional Pydantic model class for validating and parsing LLM output. "
            "When set, the LLM response will be validated against this model."
        ),
    )
    max_validation_retries: int = Field(
        default=2,
        description="Maximum retries when Pydantic validation fails (with feedback to LLM)",
    )

    # Client-facing behavior
    client_facing: bool = Field(
        default=False,
        description="If True, this node streams output to the end user and can request input.",
    )

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}


class MemoryWriteError(Exception):
    """Raised when an invalid value is written to memory."""

    pass


@dataclass
class SharedMemory:
    """
    Shared state between nodes in a graph execution.

    Nodes read and write to shared memory using typed keys.
    The memory is scoped to a single run.

    For parallel execution, use write_async() which provides per-key locking
    to prevent race conditions when multiple nodes write concurrently.
    """

    _data: dict[str, Any] = field(default_factory=dict)
    _allowed_read: set[str] = field(default_factory=set)
    _allowed_write: set[str] = field(default_factory=set)
    # Locks for thread-safe parallel execution
    _lock: asyncio.Lock | None = field(default=None, repr=False)
    _key_locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Initialize the main lock if not provided."""
        if self._lock is None:
            self._lock = asyncio.Lock()

    def read(self, key: str) -> Any:
        """Read a value from shared memory."""
        if self._allowed_read and key not in self._allowed_read:
            raise PermissionError(f"Node not allowed to read key: {key}")
        return self._data.get(key)

    def write(self, key: str, value: Any, validate: bool = True) -> None:
        """
        Write a value to shared memory.

        Args:
            key: The memory key to write to
            value: The value to write
            validate: If True, check for suspicious content (default True)

        Raises:
            PermissionError: If node doesn't have write permission
            MemoryWriteError: If value appears to be hallucinated content
        """
        if self._allowed_write and key not in self._allowed_write:
            raise PermissionError(f"Node not allowed to write key: {key}")

        if validate and isinstance(value, str):
            # Check for obviously hallucinated content
            if len(value) > 5000:
                # Long strings that look like code are suspicious
                if self._contains_code_indicators(value):
                    logger.warning(
                        f"⚠ Suspicious write to key '{key}': appears to be code "
                        f"({len(value)} chars). Consider using validate=False if intended."
                    )
                    raise MemoryWriteError(
                        f"Rejected suspicious content for key '{key}': "
                        f"appears to be hallucinated code ({len(value)} chars). "
                        "If this is intentional, use validate=False."
                    )

        self._data[key] = value

    async def write_async(self, key: str, value: Any, validate: bool = True) -> None:
        """
        Thread-safe async write with per-key locking.

        Use this method when multiple nodes may write concurrently during
        parallel execution. Each key has its own lock to minimize contention.

        Args:
            key: The memory key to write to
            value: The value to write
            validate: If True, check for suspicious content (default True)

        Raises:
            PermissionError: If node doesn't have write permission
            MemoryWriteError: If value appears to be hallucinated content
        """
        # Check permissions first (no lock needed)
        if self._allowed_write and key not in self._allowed_write:
            raise PermissionError(f"Node not allowed to write key: {key}")

        # Ensure key has a lock (double-checked locking pattern)
        if key not in self._key_locks:
            async with self._lock:
                if key not in self._key_locks:
                    self._key_locks[key] = asyncio.Lock()

        # Acquire per-key lock and write
        async with self._key_locks[key]:
            if validate and isinstance(value, str):
                if len(value) > 5000:
                    if self._contains_code_indicators(value):
                        logger.warning(
                            f"⚠ Suspicious write to key '{key}': appears to be code "
                            f"({len(value)} chars). Consider using validate=False if intended."
                        )
                        raise MemoryWriteError(
                            f"Rejected suspicious content for key '{key}': "
                            f"appears to be hallucinated code ({len(value)} chars). "
                            "If this is intentional, use validate=False."
                        )
            self._data[key] = value

    def _contains_code_indicators(self, value: str) -> bool:
        """
        Check for code patterns in a string using sampling for efficiency.

        For strings under 10KB, checks the entire content.
        For longer strings, samples at strategic positions to balance
        performance with detection accuracy.

        Args:
            value: The string to check for code indicators

        Returns:
            True if code indicators are found, False otherwise
        """
        code_indicators = [
            # Python
            "```python",
            "def ",
            "class ",
            "import ",
            "async def ",
            "from ",
            # JavaScript/TypeScript
            "function ",
            "const ",
            "let ",
            "=> {",
            "require(",
            "export ",
            # SQL
            "SELECT ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "DROP ",
            # HTML/Script injection
            "<script",
            "<?php",
            "<%",
        ]

        # For strings under 10KB, check the entire content
        if len(value) < 10000:
            return any(indicator in value for indicator in code_indicators)

        # For longer strings, sample at strategic positions
        sample_positions = [
            0,  # Start
            len(value) // 4,  # 25%
            len(value) // 2,  # 50%
            3 * len(value) // 4,  # 75%
            max(0, len(value) - 2000),  # Near end
        ]

        for pos in sample_positions:
            chunk = value[pos : pos + 2000]
            if any(indicator in chunk for indicator in code_indicators):
                return True

        return False

    def read_all(self) -> dict[str, Any]:
        """Read all accessible data."""
        if self._allowed_read:
            return {k: v for k, v in self._data.items() if k in self._allowed_read}
        return dict(self._data)

    def with_permissions(
        self,
        read_keys: list[str],
        write_keys: list[str],
    ) -> "SharedMemory":
        """Create a view with restricted permissions for a specific node.

        The scoped view shares the same underlying data and locks,
        enabling thread-safe parallel execution across scoped views.
        """
        return SharedMemory(
            _data=self._data,
            _allowed_read=set(read_keys) if read_keys else set(),
            _allowed_write=set(write_keys) if write_keys else set(),
            _lock=self._lock,  # Share lock for thread safety
            _key_locks=self._key_locks,  # Share key locks
        )


@dataclass
class NodeContext:
    """
    Everything a node needs to execute.

    This is passed to every node and provides:
    - Access to the runtime (for decision logging)
    - Access to shared memory (for state)
    - Access to LLM (for generation)
    - Access to tools (for actions)
    - The goal context (for guidance)
    """

    # Core runtime
    runtime: Runtime

    # Node identity
    node_id: str
    node_spec: NodeSpec

    # State
    memory: SharedMemory
    input_data: dict[str, Any] = field(default_factory=dict)

    # LLM access (if applicable)
    llm: LLMProvider | None = None
    available_tools: list[Tool] = field(default_factory=list)

    # Goal context
    goal_context: str = ""
    goal: Any = None  # Goal object for LLM-powered routers

    # LLM configuration
    max_tokens: int = 4096  # Maximum tokens for LLM responses

    # Execution metadata
    attempt: int = 1
    max_attempts: int = 3


@dataclass
class NodeResult:
    """
    The output of a node execution.

    Contains:
    - Success/failure status
    - Output data
    - State changes made
    - Route decision (for routers)
    """

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    # For routing decisions
    next_node: str | None = None
    route_reason: str | None = None

    # Metadata
    tokens_used: int = 0
    latency_ms: int = 0

    # Pydantic validation errors (if any)
    validation_errors: list[str] = field(default_factory=list)

    def to_summary(self, node_spec: Any = None) -> str:
        """
        Generate a human-readable summary of this node's execution and output.

        This is like toString() - it describes what the node produced in its current state.
        Uses Haiku to intelligently summarize complex outputs.
        """
        if not self.success:
            return f"❌ Failed: {self.error}"

        if not self.output:
            return "✓ Completed (no output)"

        # Use Haiku to generate intelligent summary
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            # Fallback: simple key-value listing
            parts = [f"✓ Completed with {len(self.output)} outputs:"]
            for key, value in list(self.output.items())[:5]:  # Limit to 5 keys
                value_str = str(value)[:100]
                if len(str(value)) > 100:
                    value_str += "..."
                parts.append(f"  • {key}: {value_str}")
            return "\n".join(parts)

        # Use Haiku to generate intelligent summary
        try:
            import json

            import anthropic

            node_context = ""
            if node_spec:
                node_context = f"\nNode: {node_spec.name}\nPurpose: {node_spec.description}"

            output_json = json.dumps(self.output, indent=2, default=str)[:2000]
            prompt = (
                f"Generate a 1-2 sentence human-readable summary of "
                f"what this node produced.{node_context}\n\n"
                f"Node output:\n{output_json}\n\n"
                "Provide a concise, clear summary that a human can quickly "
                "understand. Focus on the key information produced."
            )

            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )

            summary = message.content[0].text.strip()
            return f"✓ {summary}"

        except Exception:
            # Fallback on error
            parts = [f"✓ Completed with {len(self.output)} outputs:"]
            for key, value in list(self.output.items())[:3]:
                value_str = str(value)[:80]
                if len(str(value)) > 80:
                    value_str += "..."
                parts.append(f"  • {key}: {value_str}")
            return "\n".join(parts)


class NodeProtocol(ABC):
    """
    The interface all nodes must implement.

    To create a node:
    1. Subclass NodeProtocol
    2. Implement execute()
    3. Register with the executor

    Example:
        class CalculatorNode(NodeProtocol):
            async def execute(self, ctx: NodeContext) -> NodeResult:
                expression = ctx.input_data.get("expression")

                # Record decision
                decision_id = ctx.runtime.decide(
                    intent="Calculate expression",
                    options=[...],
                    chosen="evaluate",
                    reasoning="Direct evaluation"
                )

                # Do the work
                result = eval(expression)

                # Record outcome
                ctx.runtime.record_outcome(decision_id, success=True, result=result)

                return NodeResult(success=True, output={"result": result})
    """

    @abstractmethod
    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Execute this node's logic.

        Args:
            ctx: NodeContext with everything needed

        Returns:
            NodeResult with output and status
        """
        pass

    def validate_input(self, ctx: NodeContext) -> list[str]:
        """
        Validate that required inputs are present.

        Override to add custom validation.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        for key in ctx.node_spec.input_keys:
            if key not in ctx.input_data and ctx.memory.read(key) is None:
                errors.append(f"Missing required input: {key}")
        return errors


class LLMNode(NodeProtocol):
    """
    A node that uses an LLM with tools.

    This is the most common node type. It:
    1. Builds a prompt from context
    2. Calls the LLM with available tools
    3. Executes tool calls
    4. Returns the final result

    The LLM decides how to achieve the goal within constraints.
    """

    # Stop reasons indicating truncation (varies by provider)
    TRUNCATION_STOP_REASONS = {"length", "max_tokens", "token_limit"}

    # Compaction instruction added when response is truncated
    COMPACTION_INSTRUCTION = """
IMPORTANT: Your previous response was truncated because it exceeded the token limit.
Please provide a MORE CONCISE response that fits within the limit.
Focus on the essential information and omit verbose details.
Keep the same JSON structure but with shorter content values.
"""

    def __init__(
        self,
        tool_executor: Callable | None = None,
        require_tools: bool = False,
        cleanup_llm_model: str | None = None,
        max_compaction_retries: int = 2,
    ):
        self.tool_executor = tool_executor
        self.require_tools = require_tools
        self.cleanup_llm_model = cleanup_llm_model
        self.max_compaction_retries = max_compaction_retries

    def _is_truncated(self, response) -> bool:
        """Check if LLM response was truncated due to token limit."""
        stop_reason = getattr(response, "stop_reason", "").lower()
        return stop_reason in self.TRUNCATION_STOP_REASONS

    def _strip_code_blocks(self, content: str) -> str:
        """Strip markdown code block wrappers from content.

        LLMs often wrap JSON output in ```json...``` blocks.
        This method removes those wrappers to get clean content.
        """
        import re

        content = content.strip()
        # Match ```json or ``` at start and ``` at end (greedy to handle nested)
        match = re.match(r"^```(?:json|JSON)?\s*\n?(.*)\n?```\s*$", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content

    def _estimate_tokens(
        self, model: str, system: str, messages: list[dict], tools: list | None
    ) -> int:
        """Estimate total input tokens for an LLM call."""
        import json

        try:
            import litellm as _litellm
        except ImportError:
            # Rough estimate: 1 token ≈ 4 chars
            total_chars = len(system)
            for m in messages:
                total_chars += len(str(m.get("content", "")))
            if tools:
                total_chars += len(
                    json.dumps(
                        [
                            {
                                "name": t.name,
                                "description": t.description,
                                "parameters": t.parameters,
                            }
                            for t in tools
                        ],
                        default=str,
                    )
                )
            return total_chars // 4

        total = 0
        if system:
            total += _litellm.token_counter(model=model, text=system)
        for m in messages:
            content = str(m.get("content", ""))
            if content:
                total += _litellm.token_counter(model=model, text=content)
        if tools:
            tools_text = json.dumps(
                [
                    {"name": t.name, "description": t.description, "parameters": t.parameters}
                    for t in tools
                ],
                default=str,
            )
            total += _litellm.token_counter(model=model, text=tools_text)
        return total

    def _get_context_limit(self, model: str) -> int:
        """Get usable input token budget (80% of model's max_input_tokens)."""
        try:
            import litellm as _litellm

            info = _litellm.get_model_info(model)
            max_input = info.get("max_input_tokens") or info.get("max_tokens") or 8192
            return int(max_input * 0.8)
        except Exception:
            return 8192

    def _compact_inputs(
        self, ctx: NodeContext, system: str, messages: list[dict], tools: list | None
    ) -> list[dict]:
        """Compact message inputs if they exceed the model's context window.

        Uses a sliding window strategy: iteratively halves the longest input
        value until the total token count fits within the budget.
        """
        model = ctx.llm.model if hasattr(ctx.llm, "model") else "gpt-3.5-turbo"
        budget = self._get_context_limit(model)
        estimated = self._estimate_tokens(model, system, messages, tools)

        if estimated <= budget:
            return messages

        logger.warning(
            f"[compaction] Input tokens (~{estimated}) exceed budget ({budget}) "
            f"for model {model}. Compacting inputs..."
        )

        # Parse user message into key:value pairs for selective truncation
        if not messages or not messages[0].get("content"):
            return messages

        content = messages[0]["content"]
        lines = content.split("\n")
        pairs: list[tuple[str, str]] = []
        for line in lines:
            if ": " in line:
                key, _, value = line.partition(": ")
                pairs.append((key, value))
            else:
                pairs.append(("", line))

        # Iteratively halve the longest value until we fit
        max_iterations = 20
        for i in range(max_iterations):
            # Find longest value
            longest_idx = -1
            longest_len = 0
            for idx, (key, value) in enumerate(pairs):
                if key and len(value) > longest_len:
                    longest_len = len(value)
                    longest_idx = idx

            if longest_idx == -1 or longest_len <= 100:
                break

            key, value = pairs[longest_idx]
            new_len = max(longest_len // 2, 100)
            pairs[longest_idx] = (key, value[:new_len] + "...")
            logger.warning(f"[compaction] Truncated '{key}' from {longest_len} to {new_len} chars")

            # Re-estimate
            new_content = "\n".join(f"{k}: {v}" if k else v for k, v in pairs)
            test_messages = [{"role": "user", "content": new_content}]
            estimated = self._estimate_tokens(model, system, test_messages, tools)
            if estimated <= budget:
                logger.warning(
                    f"[compaction] Fits within budget after {i + 1} rounds (~{estimated} tokens)"
                )
                return test_messages

        # Final reassembly even if still over budget
        final_content = "\n".join(f"{k}: {v}" if k else v for k, v in pairs)
        final_messages = [{"role": "user", "content": final_content}]
        final_est = self._estimate_tokens(model, system, final_messages, tools)
        logger.warning(
            f"[compaction] Still ~{final_est} tokens after max compaction "
            f"(budget={budget}). Proceeding anyway."
        )
        return final_messages

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute the LLM node."""
        import time

        if ctx.llm is None:
            return NodeResult(success=False, error="LLM not available")

        # Fail fast if tools are required but not available
        if self.require_tools and not ctx.available_tools:
            return NodeResult(
                success=False,
                error=f"Node '{ctx.node_spec.name}' requires tools but none are available. "
                f"Declared tools: {ctx.node_spec.tools}. "
                "Register tools via ToolRegistry before running the agent.",
            )

        ctx.runtime.set_node(ctx.node_id)

        # Record the decision to use LLM
        decision_id = ctx.runtime.decide(
            intent=f"Execute {ctx.node_spec.name}",
            options=[
                {
                    "id": "llm_execute",
                    "description": f"Use LLM to {ctx.node_spec.description}",
                    "action_type": "llm_call",
                }
            ],
            chosen="llm_execute",
            reasoning=f"Node type is {ctx.node_spec.node_type}",
            context={"input": ctx.input_data},
        )

        start = time.time()

        try:
            # Build messages
            messages = self._build_messages(ctx)

            # Build system prompt
            system = self._build_system_prompt(ctx)

            # Compact inputs if they exceed the model's context window
            messages = self._compact_inputs(ctx, system, messages, ctx.available_tools)

            # Log the LLM call details
            logger.info("      🤖 LLM Call:")
            logger.info(
                f"         System: {system[:150]}..."
                if len(system) > 150
                else f"         System: {system}"
            )
            logger.info(
                f"         User message: {messages[-1]['content'][:150]}..."
                if len(messages[-1]["content"]) > 150
                else f"         User message: {messages[-1]['content']}"
            )
            if ctx.available_tools:
                logger.info(f"         Tools available: {[t.name for t in ctx.available_tools]}")

            # Call LLM
            if ctx.available_tools and self.tool_executor:
                from framework.llm.provider import ToolResult, ToolUse

                def executor(tool_use: ToolUse) -> ToolResult:
                    args = ", ".join(f"{k}={v}" for k, v in tool_use.input.items())
                    logger.info(f"         🔧 Tool call: {tool_use.name}({args})")
                    result = self.tool_executor(tool_use)
                    # Truncate long results
                    result_str = str(result.content)[:150]
                    if len(str(result.content)) > 150:
                        result_str += "..."
                    logger.info(f"         ✓ Tool result: {result_str}")
                    return result

                response = ctx.llm.complete_with_tools(
                    messages=messages,
                    system=system,
                    tools=ctx.available_tools,
                    tool_executor=executor,
                    max_tokens=ctx.max_tokens,
                )
            else:
                # Use JSON mode for llm_generate nodes with output_keys
                # Skip strict schema validation - just validate keys after parsing
                use_json_mode = (
                    ctx.node_spec.node_type == "llm_generate"
                    and ctx.node_spec.output_keys
                    and len(ctx.node_spec.output_keys) >= 1
                )
                if use_json_mode:
                    logger.info(
                        f"         📋 Expecting JSON output with keys: {ctx.node_spec.output_keys}"
                    )

                response = ctx.llm.complete(
                    messages=messages,
                    system=system,
                    json_mode=use_json_mode,
                    max_tokens=ctx.max_tokens,
                )

            # Check for truncation and retry with compaction if needed
            expects_json = (
                ctx.node_spec.node_type in ("llm_generate", "llm_tool_use")
                and ctx.node_spec.output_keys
                and len(ctx.node_spec.output_keys) >= 1
            )

            compaction_attempt = 0
            while (
                self._is_truncated(response)
                and expects_json
                and compaction_attempt < self.max_compaction_retries
            ):
                compaction_attempt += 1
                logger.warning(
                    f"      ⚠ Response truncated (stop_reason: {response.stop_reason}), "
                    f"retrying with compaction ({compaction_attempt}/{self.max_compaction_retries})"
                )

                # Add compaction instruction to messages
                compaction_messages = messages + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": self.COMPACTION_INSTRUCTION},
                ]

                # Retry the call with compaction instruction
                if ctx.available_tools and self.tool_executor:
                    response = ctx.llm.complete_with_tools(
                        messages=compaction_messages,
                        system=system,
                        tools=ctx.available_tools,
                        tool_executor=executor,
                        max_tokens=ctx.max_tokens,
                    )
                else:
                    response = ctx.llm.complete(
                        messages=compaction_messages,
                        system=system,
                        json_mode=use_json_mode,
                        max_tokens=ctx.max_tokens,
                    )

            if self._is_truncated(response) and expects_json:
                logger.warning(
                    f"      ⚠ Response still truncated after "
                    f"{compaction_attempt} compaction attempts"
                )

            # Phase 2: Validation retry loop for Pydantic models
            max_validation_retries = (
                ctx.node_spec.max_validation_retries if ctx.node_spec.output_model else 0
            )
            validation_attempt = 0
            total_input_tokens = 0
            total_output_tokens = 0
            current_messages = messages.copy()

            while True:
                total_input_tokens += response.input_tokens
                total_output_tokens += response.output_tokens

                # Log the response
                response_preview = (
                    response.content[:200] if len(response.content) > 200 else response.content
                )
                if len(response.content) > 200:
                    response_preview += "..."
                logger.info(f"      ← Response: {response_preview}")

                # If no output_model, break immediately (no validation needed)
                if ctx.node_spec.output_model is None:
                    break

                # Try to parse and validate the response
                try:
                    import json

                    parsed = self._extract_json(response.content, ctx.node_spec.output_keys)

                    if isinstance(parsed, dict):
                        from framework.graph.validator import OutputValidator

                        validator = OutputValidator()
                        validation_result, validated_model = validator.validate_with_pydantic(
                            parsed, ctx.node_spec.output_model
                        )

                        if validation_result.success:
                            # Validation passed, break out of retry loop
                            model_name = ctx.node_spec.output_model.__name__
                            logger.info(f"      ✓ Pydantic validation passed for {model_name}")
                            break
                        else:
                            # Validation failed
                            validation_attempt += 1

                            if validation_attempt <= max_validation_retries:
                                # Add validation feedback to messages and retry
                                feedback = validator.format_validation_feedback(
                                    validation_result, ctx.node_spec.output_model
                                )
                                logger.warning(
                                    f"      ⚠ Pydantic validation failed "
                                    f"(attempt {validation_attempt}/{max_validation_retries}): "
                                    f"{validation_result.error}"
                                )
                                logger.info("      🔄 Retrying with validation feedback...")

                                # Add the assistant's failed response and feedback
                                current_messages.append(
                                    {"role": "assistant", "content": response.content}
                                )
                                current_messages.append({"role": "user", "content": feedback})

                                # Re-call LLM with feedback
                                if ctx.available_tools and self.tool_executor:
                                    response = ctx.llm.complete_with_tools(
                                        messages=current_messages,
                                        system=system,
                                        tools=ctx.available_tools,
                                        tool_executor=executor,
                                        max_tokens=ctx.max_tokens,
                                    )
                                else:
                                    response = ctx.llm.complete(
                                        messages=current_messages,
                                        system=system,
                                        json_mode=use_json_mode,
                                        max_tokens=ctx.max_tokens,
                                    )
                                continue  # Retry validation
                            else:
                                # Max retries exceeded
                                latency_ms = int((time.time() - start) * 1000)
                                err = validation_result.error
                                logger.error(
                                    f"      ✗ Pydantic validation failed after "
                                    f"{max_validation_retries} retries: {err}"
                                )
                                ctx.runtime.record_outcome(
                                    decision_id=decision_id,
                                    success=False,
                                    error=f"Validation failed: {validation_result.error}",
                                    tokens_used=total_input_tokens + total_output_tokens,
                                    latency_ms=latency_ms,
                                )
                                error_msg = (
                                    f"Pydantic validation failed after "
                                    f"{max_validation_retries} retries: {err}"
                                )
                                return NodeResult(
                                    success=False,
                                    error=error_msg,
                                    output=parsed,
                                    tokens_used=total_input_tokens + total_output_tokens,
                                    latency_ms=latency_ms,
                                    validation_errors=validation_result.errors,
                                )
                    else:
                        # Not a dict, can't validate - break and let downstream handle
                        break
                except Exception:
                    # JSON extraction failed - break and let downstream handle
                    break

            latency_ms = int((time.time() - start) * 1000)

            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=True,
                result=response.content,
                tokens_used=response.input_tokens + response.output_tokens,
                latency_ms=latency_ms,
            )

            # Write to output keys
            output = self._parse_output(response.content, ctx.node_spec)

            # For llm_generate and llm_tool_use nodes, try to parse JSON and extract fields
            if (
                ctx.node_spec.node_type in ("llm_generate", "llm_tool_use")
                and len(ctx.node_spec.output_keys) >= 1
            ):
                try:
                    import json

                    # Try to extract JSON from response
                    parsed = self._extract_json(
                        response.content, ctx.node_spec.output_keys, self.cleanup_llm_model
                    )

                    # If parsed successfully, write each field to its corresponding output key
                    # Use validate=False since LLM output legitimately contains text that
                    # may trigger false positives (e.g., "from OpenAI" matches "from ")
                    if isinstance(parsed, dict):
                        # If we have output_model, the validation already happened in the retry loop
                        if ctx.node_spec.output_model is not None:
                            from framework.graph.validator import OutputValidator

                            validator = OutputValidator()
                            validation_result, validated_model = validator.validate_with_pydantic(
                                parsed, ctx.node_spec.output_model
                            )
                            # Use validated model's dict representation
                            if validated_model:
                                parsed = validated_model.model_dump()

                        for key in ctx.node_spec.output_keys:
                            if key in parsed:
                                value = parsed[key]
                                # Strip code block wrappers from string values
                                if isinstance(value, str):
                                    value = self._strip_code_blocks(value)
                                ctx.memory.write(key, value, validate=False)
                                output[key] = value
                            elif key in ctx.input_data:
                                # Key not in JSON but exists in input - pass through
                                ctx.memory.write(key, ctx.input_data[key], validate=False)
                                output[key] = ctx.input_data[key]
                            else:
                                # Key not in JSON or input, write whole response (stripped)
                                stripped_content = self._strip_code_blocks(response.content)
                                ctx.memory.write(key, stripped_content, validate=False)
                                output[key] = stripped_content
                    else:
                        # Not a dict, fall back to writing entire response to all keys (stripped)
                        stripped_content = self._strip_code_blocks(response.content)
                        for key in ctx.node_spec.output_keys:
                            ctx.memory.write(key, stripped_content, validate=False)
                            output[key] = stripped_content

                except (json.JSONDecodeError, Exception) as e:
                    # JSON extraction failed - fail explicitly instead of polluting memory
                    logger.error(f"      ✗ Failed to extract structured output: {e}")
                    logger.error(
                        f"      Raw response (first 500 chars): {response.content[:500]}..."
                    )

                    # Return failure instead of writing garbage to all keys
                    return NodeResult(
                        success=False,
                        error=(
                            f"Output extraction failed: {e}. LLM returned non-JSON response. "
                            f"Expected keys: {ctx.node_spec.output_keys}"
                        ),
                        output={},
                        tokens_used=response.input_tokens + response.output_tokens,
                        latency_ms=latency_ms,
                    )
                    # JSON extraction failed completely - still strip code blocks
                    # logger.warning(f"      ⚠ Failed to extract JSON output: {e}")
                    # stripped_content = self._strip_code_blocks(response.content)
                    # for key in ctx.node_spec.output_keys:
                    #     ctx.memory.write(key, stripped_content)
                    #     output[key] = stripped_content
            else:
                # For non-llm_generate or single output nodes, write entire response (stripped)
                stripped_content = self._strip_code_blocks(response.content)
                for key in ctx.node_spec.output_keys:
                    ctx.memory.write(key, stripped_content, validate=False)
                    output[key] = stripped_content

            return NodeResult(
                success=True,
                output=output,
                tokens_used=response.input_tokens + response.output_tokens,
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )
            return NodeResult(success=False, error=str(e), latency_ms=latency_ms)

    def _parse_output(self, content: str, node_spec: NodeSpec) -> dict[str, Any]:
        """
        Parse LLM output based on node type.

        For llm_generate nodes with multiple output keys, attempts to parse JSON.
        Otherwise returns raw content.
        """
        # Default output
        return {"result": content}

    def _extract_json(
        self, raw_response: str, output_keys: list[str], cleanup_llm_model: str | None = None
    ) -> dict[str, Any]:
        """Extract clean JSON from potentially verbose LLM response.

        Tries multiple extraction strategies in order:
        1. Direct JSON parse
        2. Markdown code block extraction
        3. Balanced brace matching
        4. Configured LLM fallback (last resort)

        Args:
            raw_response: The raw LLM response text
            output_keys: Expected output keys for the JSON
            cleanup_llm_model: Optional model to use for LLM cleanup fallback
        """
        import json
        import re

        content = raw_response.strip()

        # Try direct JSON parse first (fast path)
        try:
            content = raw_response.strip()

            # Remove markdown code blocks if present - more robust extraction
            if content.startswith("```"):
                # Try multiple patterns for markdown code blocks
                # Pattern 1: ```json\n...\n``` or ```\n...\n```
                match = re.search(r"^```(?:json)?\s*\n([\s\S]*?)\n```\s*$", content)
                if match:
                    content = match.group(1).strip()
                else:
                    # Pattern 2: Just strip the first and last lines if they're ```
                    lines = content.split("\n")
                    if lines[0].startswith("```") and lines[-1].strip() == "```":
                        content = "\n".join(lines[1:-1]).strip()

            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e:
            logger.info(f"      Direct JSON parse failed: {e}")
            logger.info(f"      Content first 200 chars repr: {repr(content[:200])}")
            # Try fixing unescaped newlines in string values
            try:
                fixed = _fix_unescaped_newlines_in_json(content)
                logger.info(f"      Fixed content first 200 chars repr: {repr(fixed[:200])}")
                parsed = json.loads(fixed)
                if isinstance(parsed, dict):
                    logger.info("      ✓ Parsed JSON after fixing unescaped newlines")
                    return parsed
            except json.JSONDecodeError as e2:
                logger.info(f"      Newline fix also failed: {e2}")

        # Try to extract JSON from markdown code blocks (greedy match to handle nested blocks)
        # Multiple patterns to handle different LLM formatting styles
        code_block_patterns = [
            # Anchored match from first ``` to last ```
            r"^```(?:json|JSON)?\s*\n?(.*)\n?```\s*$",
            # Non-anchored: find ```json anywhere and extract to closing ```
            r"```(?:json|JSON)?\s*\n([\s\S]*?)\n```",
            # Handle case where closing ``` might have trailing content
            r"```(?:json|JSON)?\s*\n([\s\S]*?)\n```",
        ]
        for pattern in code_block_patterns:
            code_block_match = re.search(pattern, content, re.DOTALL)
            if code_block_match:
                try:
                    extracted = code_block_match.group(1).strip()
                    if extracted:  # Skip empty matches
                        # Try direct parse first, then with newline fix
                        try:
                            parsed = json.loads(extracted)
                        except json.JSONDecodeError:
                            parsed = json.loads(_fix_unescaped_newlines_in_json(extracted))
                        if isinstance(parsed, dict):
                            return parsed
                except json.JSONDecodeError:
                    pass

        # Try to find JSON object by matching balanced braces (use module-level helper)
        json_str = find_json_object(content)
        if json_str:
            try:
                # Try direct parse first, then with newline fix
                try:
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    parsed = json.loads(_fix_unescaped_newlines_in_json(json_str))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Try stripping markdown prefix and finding JSON from there
        # This handles cases like "```json\n{...}" where regex might fail
        if "```" in content:
            # Find position after ```json or ``` marker
            json_start = content.find("{")
            if json_start > 0:
                # Extract from first { to end, then find balanced JSON
                json_str = find_json_object(content[json_start:])
                if json_str:
                    try:
                        # Try direct parse first, then with newline fix
                        try:
                            parsed = json.loads(json_str)
                        except json.JSONDecodeError:
                            parsed = json.loads(_fix_unescaped_newlines_in_json(json_str))
                        if isinstance(parsed, dict):
                            logger.info(
                                "      ✓ Extracted JSON via brace matching after markdown strip"
                            )
                            return parsed
                    except json.JSONDecodeError:
                        pass

        # All local extraction failed - use LLM as last resort
        import os

        from framework.llm.litellm import LiteLLMProvider

        logger.info(f"      cleanup_llm_model param: {cleanup_llm_model}")

        # Use configured cleanup model, or fall back to defaults
        if cleanup_llm_model:
            # Use the configured cleanup model (LiteLLM handles API keys via env vars)
            cleaner_llm = LiteLLMProvider(model=cleanup_llm_model)
            logger.info(f"      Using configured cleanup LLM: {cleanup_llm_model}")
        else:
            # Fall back to default logic: Cerebras preferred, then Haiku
            api_key = os.environ.get("CEREBRAS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError(
                    "Cannot parse JSON and no API key for LLM cleanup "
                    "(set CEREBRAS_API_KEY or ANTHROPIC_API_KEY, or configure cleanup_llm_model)"
                )

            if os.environ.get("CEREBRAS_API_KEY"):
                cleaner_llm = LiteLLMProvider(
                    api_key=os.environ.get("CEREBRAS_API_KEY"),
                    model="cerebras/llama-3.3-70b",
                )
            else:
                cleaner_llm = LiteLLMProvider(
                    api_key=api_key,
                    model="claude-3-5-haiku-20241022",
                )

        prompt = f"""Extract the JSON object from this LLM response.

Expected output keys: {output_keys}

LLM Response:
{raw_response}

Output ONLY the JSON object, nothing else.
If no valid JSON object exists in the response, output exactly: {{"error": "NO_JSON_FOUND"}}
Do NOT fabricate data or return empty objects."""

        try:
            result = cleaner_llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="Extract JSON from text. Output only valid JSON.",
                json_mode=True,
            )

            cleaned = result.content.strip() if result.content else ""

            # Check for empty response
            if not cleaned:
                logger.warning("      ⚠ LLM cleanup returned empty response")
                raise ValueError(
                    f"LLM cleanup returned empty response. "
                    f"Raw response starts with: {raw_response[:200]}..."
                )

            # Remove markdown if LLM added it
            if cleaned.startswith("```"):
                match = re.search(r"^```(?:json)?\s*\n([\s\S]*?)\n```\s*$", cleaned)
                if match:
                    cleaned = match.group(1).strip()
                else:
                    # Fallback: strip first/last lines
                    lines = cleaned.split("\n")
                    if lines[0].startswith("```") and lines[-1].strip() == "```":
                        cleaned = "\n".join(lines[1:-1]).strip()

            # Try balanced brace extraction if still not valid JSON
            if not cleaned.startswith("{"):
                json_str = find_json_object(cleaned)
                if json_str:
                    cleaned = json_str

            if not cleaned:
                raise ValueError(
                    f"Could not extract JSON from LLM cleanup response. "
                    f"Raw response starts with: {raw_response[:200]}..."
                )

            # Try direct parse first, then with newline fix
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                parsed = json.loads(_fix_unescaped_newlines_in_json(cleaned))

            # Validate LLM didn't return empty or fabricated data
            if parsed.get("error") == "NO_JSON_FOUND":
                raise ValueError("Cannot parse JSON from response")
            if not parsed or parsed == {}:
                raise ValueError("Cannot parse JSON from response")
            if all(v is None for v in parsed.values()):
                raise ValueError("Cannot parse JSON from response")
            logger.info("      ✓ LLM cleaned JSON output")
            return parsed

        except json.JSONDecodeError as e:
            logger.warning(f"      ⚠ LLM cleanup response not valid JSON: {e}")
            raise ValueError(
                f"LLM cleanup response not valid JSON: {e}. Expected keys: {output_keys}"
            ) from e
        except ValueError:
            raise  # Re-raise our descriptive error
        except Exception as e:
            logger.warning(f"      ⚠ LLM JSON extraction failed: {e}")
            raise

    def _build_messages(self, ctx: NodeContext) -> list[dict]:
        """Build the message list for the LLM."""
        # Use Haiku to intelligently format inputs from memory
        user_content = self._format_inputs_with_haiku(ctx)
        return [{"role": "user", "content": user_content}]

    def _format_inputs_with_haiku(self, ctx: NodeContext) -> str:
        """Use Haiku to intelligently extract and format inputs from memory."""
        if not ctx.node_spec.input_keys:
            return str(ctx.input_data)

        # Read all memory for context
        memory_data = ctx.memory.read_all()

        # If memory is empty or very simple, just use raw data
        if not memory_data or len(memory_data) <= 2:
            # Simple case - just format the input keys directly
            parts = []
            for key in ctx.node_spec.input_keys:
                value = ctx.memory.read(key)
                if value is not None:
                    parts.append(f"{key}: {value}")
            return "\n".join(parts) if parts else str(ctx.input_data)

        # Use Haiku to intelligently extract relevant data
        import os

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            # Fallback to simple formatting if no API key
            parts = []
            for key in ctx.node_spec.input_keys:
                value = ctx.memory.read(key)
                if value is not None:
                    parts.append(f"{key}: {value}")
            return "\n".join(parts)

        # Build prompt for Haiku to extract clean values
        import json

        # Smart truncation: truncate values rather than corrupting JSON
        def truncate_value(v, max_len=500):
            s = str(v)
            return s[:max_len] + "..." if len(s) > max_len else v

        truncated_data = {k: truncate_value(v) for k, v in memory_data.items()}
        memory_json = json.dumps(truncated_data, indent=2, default=str)

        required_fields = ", ".join(ctx.node_spec.input_keys)
        prompt = (
            f"Extract the following information from the memory context:\n\n"
            f"Required fields: {required_fields}\n\n"
            f"Memory context (may contain nested data, JSON strings, "
            f"or extra information):\n{memory_json}\n\n"
            "Extract ONLY the clean values for the required fields. "
            "Ignore nested structures, JSON wrappers, and irrelevant data.\n\n"
            "Output as JSON with the exact field names requested."
        )

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse Haiku's response
            response_text = message.content[0].text.strip()

            # Try to extract JSON using balanced brace matching
            json_str = find_json_object(response_text)
            if json_str:
                extracted = json.loads(json_str)
                # Format as key: value pairs
                parts = [f"{k}: {v}" for k, v in extracted.items() if k in ctx.node_spec.input_keys]
                if parts:
                    return "\n".join(parts)

        except Exception as e:
            # Fallback to simple formatting on error
            logger.warning(f"Haiku formatting failed: {e}, falling back to simple format")

        # Fallback: simple key-value formatting
        parts = []
        for key in ctx.node_spec.input_keys:
            value = ctx.memory.read(key)
            if value is not None:
                parts.append(f"{key}: {value}")
        return "\n".join(parts) if parts else str(ctx.input_data)

    def _build_system_prompt(self, ctx: NodeContext) -> str:
        """Build the system prompt."""
        from datetime import datetime

        parts = []

        if ctx.node_spec.system_prompt:
            # Format system prompt with values from memory (for input_keys placeholders)
            prompt = ctx.node_spec.system_prompt
            if ctx.node_spec.input_keys:
                # Build formatting context from memory
                format_context = {}
                for key in ctx.node_spec.input_keys:
                    value = ctx.memory.read(key)
                    if value is not None:
                        format_context[key] = value

                # Try to format, but fallback to raw prompt if formatting fails
                try:
                    prompt = prompt.format(**format_context)
                except (KeyError, ValueError):
                    # Placeholders don't match or formatting error - use raw prompt
                    pass

            parts.append(prompt)

        # Inject current datetime so LLM knows "now"
        utc_dt = datetime.now(UTC)
        local_dt = datetime.now().astimezone()
        local_tz_name = local_dt.tzname() or "Unknown"
        parts.append("\n## Runtime Context")
        parts.append(f"- Current Date/Time (UTC): {utc_dt.isoformat()}")
        parts.append(f"- Local Timezone: {local_tz_name}")
        parts.append(f"- Current Date/Time (Local): {local_dt.isoformat()}")

        if ctx.goal_context:
            parts.append("\n# Goal Context")
            parts.append(ctx.goal_context)

        return "\n".join(parts)


class RouterNode(NodeProtocol):
    """
    A node that routes to different next nodes based on conditions.

    The router examines the current state and decides which
    node should execute next.

    Can use either:
    1. Simple condition matching (deterministic)
    2. LLM-based routing (goal-aware, adaptive)

    Set node_spec.routes to a dict of conditions -> target nodes.
    If node_spec.system_prompt is provided, LLM will choose the route.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute routing logic."""
        ctx.runtime.set_node(ctx.node_id)

        # Build options from routes
        options = []
        for condition, target in ctx.node_spec.routes.items():
            options.append(
                {
                    "id": condition,
                    "description": f"Route to {target} when condition '{condition}' is met",
                    "target": target,
                }
            )

        # Check if we should use LLM-based routing
        if ctx.node_spec.system_prompt and ctx.llm:
            # LLM-based routing (goal-aware)
            chosen_route = await self._llm_route(ctx, options)
        else:
            # Simple condition-based routing (deterministic)
            route_value = ctx.input_data.get("route_on") or ctx.memory.read("route_on")
            chosen_route = None
            for condition, target in ctx.node_spec.routes.items():
                if self._check_condition(condition, route_value, ctx):
                    chosen_route = (condition, target)
                    break

            if chosen_route is None:
                # Default route
                chosen_route = ("default", ctx.node_spec.routes.get("default", "end"))

        decision_id = ctx.runtime.decide(
            intent="Determine next node in graph",
            options=options,
            chosen=chosen_route[0],
            reasoning=f"Routing decision: {chosen_route[0]}",
        )

        ctx.runtime.record_outcome(
            decision_id=decision_id,
            success=True,
            result=chosen_route[1],
            summary=f"Routing to {chosen_route[1]}",
        )

        return NodeResult(
            success=True,
            next_node=chosen_route[1],
            route_reason=f"Chose route: {chosen_route[0]}",
        )

    async def _llm_route(
        self,
        ctx: NodeContext,
        options: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """
        Use LLM to choose the best route based on goal and context.

        Returns:
            Tuple of (chosen_condition, target_node)
        """
        import json

        # Build routing options description
        options_desc = "\n".join(
            [f"- {opt['id']}: {opt['description']} → goes to '{opt['target']}'" for opt in options]
        )

        # Build context
        context_data = {
            "input": ctx.input_data,
            "memory_keys": list(ctx.memory.read_all().keys())[:10],
        }

        prompt = f"""You are a routing agent deciding which path to take in a workflow.

**Goal**: {ctx.goal.name}
{ctx.goal.description}

**Current Context**:
{json.dumps(context_data, indent=2, default=str)}

**Available Routes**:
{options_desc}

Based on the goal and current context, which route should we take?

Respond with ONLY a JSON object:
{{"chosen": "route_id", "reasoning": "brief explanation"}}"""

        logger.info("      🤔 Router using LLM to choose path...")

        try:
            response = ctx.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=ctx.node_spec.system_prompt
                or "You are a routing agent. Respond with JSON only.",
                max_tokens=150,
            )

            # Parse response using balanced brace matching
            json_str = find_json_object(response.content)
            if json_str:
                data = json.loads(json_str)
                chosen = data.get("chosen", "default")
                reasoning = data.get("reasoning", "")

                logger.info(f"      → Chose: {chosen}")
                logger.info(f"         Reason: {reasoning}")

                # Find the target for this choice
                target = ctx.node_spec.routes.get(
                    chosen, ctx.node_spec.routes.get("default", "end")
                )
                return (chosen, target)

        except Exception as e:
            logger.warning(f"      ⚠ LLM routing failed, using default: {e}")

        # Fallback to default
        default_target = ctx.node_spec.routes.get("default", "end")
        return ("default", default_target)

    def _check_condition(
        self,
        condition: str,
        value: Any,
        ctx: NodeContext,
    ) -> bool:
        """Check if a routing condition is met."""
        if condition == "default":
            return True
        if condition == "success" and value is True:
            return True
        if condition == "failure" and value is False:
            return True
        if condition == "error" and isinstance(value, Exception):
            return True

        # String matching
        if isinstance(value, str) and condition in value:
            return True

        return False


class FunctionNode(NodeProtocol):
    """
    A node that executes a Python function.

    For deterministic operations that don't need LLM reasoning.
    """

    def __init__(self, func: Callable):
        self.func = func

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute the function."""
        import time

        ctx.runtime.set_node(ctx.node_id)

        decision_id = ctx.runtime.decide(
            intent=f"Execute function {ctx.node_spec.function or 'unknown'}",
            options=[
                {
                    "id": "execute",
                    "description": f"Run function with inputs: {list(ctx.input_data.keys())}",
                }
            ],
            chosen="execute",
            reasoning="Deterministic function execution",
        )

        start = time.time()

        try:
            # Filter input_data to only declared input_keys to prevent
            # leaking extra memory keys from upstream nodes.
            if ctx.node_spec.input_keys:
                filtered = {
                    k: v for k, v in ctx.input_data.items() if k in ctx.node_spec.input_keys
                }
            else:
                filtered = ctx.input_data

            # Call the function (supports both sync and async)
            result = self.func(**filtered)
            if inspect.isawaitable(result):
                result = await result

            latency_ms = int((time.time() - start) * 1000)

            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=True,
                result=result,
                latency_ms=latency_ms,
            )

            # Write to output keys
            output = {}
            if ctx.node_spec.output_keys:
                key = ctx.node_spec.output_keys[0]
                output[key] = result
                ctx.memory.write(key, result)
            else:
                output = {"result": result}

            return NodeResult(success=True, output=output, latency_ms=latency_ms)

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=False,
                error=str(e),
                latency_ms=latency_ms,
            )
            return NodeResult(success=False, error=str(e), latency_ms=latency_ms)
