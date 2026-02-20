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
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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

    end = text.rfind("}")
    if end == -1 or end < start:
        return None

    # Fast path: try json.loads directly (C extension, handles 1MB in ~14ms)
    try:
        candidate = text[start : end + 1]
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        pass

    # Fall back to existing brace matching
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
            node_type="event_loop",
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
        default="event_loop",
        description="Type: 'event_loop' (recommended), 'router', 'human_input'.",
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

    # For router nodes
    routes: dict[str, str] = Field(
        default_factory=dict, description="Condition -> target_node_id mapping for routers"
    )

    # Retry behavior
    max_retries: int = Field(default=3)
    retry_on: list[str] = Field(default_factory=list, description="Error types to retry on")

    # Visit limits (for feedback/callback edges)
    max_node_visits: int = Field(
        default=0,
        description=(
            "Max times this node executes in one graph run. "
            "0 = unlimited (default, required for forever-alive agents). "
            "Set >1 for one-shot agents with feedback loops."
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

    # Phase completion criteria for conversation-aware judge (Level 2)
    success_criteria: str | None = Field(
        default=None,
        description=(
            "Natural-language criteria for phase completion. When set, the "
            "implicit judge upgrades to Level 2: after output keys are satisfied, "
            "a fast LLM evaluates whether the conversation meets these criteria."
        ),
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

    # Runtime logging (optional)
    runtime_logger: Any = None  # RuntimeLogger | None — uses Any to avoid import

    # Pause control (optional) - asyncio.Event for pause requests
    pause_event: Any = None  # asyncio.Event | None

    # Continuous conversation mode
    continuous_mode: bool = False  # True when graph has conversation_mode="continuous"
    inherited_conversation: Any = None  # NodeConversation | None (from prior node)
    cumulative_output_keys: list[str] = field(default_factory=list)  # All output keys from path

    # Event-triggered execution (no interactive user attached)
    event_triggered: bool = False


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

    # Continuous conversation mode: return conversation for threading to next node
    conversation: Any = None  # NodeConversation | None

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
