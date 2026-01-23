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

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from framework.runtime.core import Runtime
from framework.llm.provider import LLMProvider, Tool

logger = logging.getLogger(__name__)


def find_json_object(text: str) -> str | None:
    """Find the first valid JSON object in text using balanced brace matching.

    This handles nested objects correctly, unlike simple regex like r'\\{[^{}]*\\}'.
    """
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue

        if char == '\\' and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

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
        description="Type: 'llm_tool_use', 'llm_generate', 'function', 'router', 'human_input'"
    )

    # Data flow
    input_keys: list[str] = Field(
        default_factory=list,
        description="Keys this node reads from shared memory or input"
    )
    output_keys: list[str] = Field(
        default_factory=list,
        description="Keys this node writes to shared memory or output"
    )

    # Optional schemas for validation and cleansing
    input_schema: dict[str, dict] = Field(
        default_factory=dict,
        description="Optional schema for input validation. Format: {key: {type: 'string', required: True, description: '...'}}"
    )
    output_schema: dict[str, dict] = Field(
        default_factory=dict,
        description="Optional schema for output validation. Format: {key: {type: 'dict', required: True, description: '...'}}"
    )

    # For LLM nodes
    system_prompt: str | None = Field(
        default=None,
        description="System prompt for LLM nodes"
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names this node can use"
    )
    model: str | None = Field(
        default=None,
        description="Specific model to use (defaults to graph default)"
    )

    # For function nodes
    function: str | None = Field(
        default=None,
        description="Function name or path for function nodes"
    )

    # For router nodes
    routes: dict[str, str] = Field(
        default_factory=dict,
        description="Condition -> target_node_id mapping for routers"
    )

    # Retry behavior
    max_retries: int = Field(default=3)
    retry_on: list[str] = Field(
        default_factory=list,
        description="Error types to retry on"
    )

    model_config = {"extra": "allow"}


@dataclass
class SharedMemory:
    """
    Shared state between nodes in a graph execution.

    Nodes read and write to shared memory using typed keys.
    The memory is scoped to a single run.
    """
    _data: dict[str, Any] = field(default_factory=dict)
    _allowed_read: set[str] = field(default_factory=set)
    _allowed_write: set[str] = field(default_factory=set)

    def read(self, key: str) -> Any:
        """Read a value from shared memory."""
        if self._allowed_read and key not in self._allowed_read:
            raise PermissionError(f"Node not allowed to read key: {key}")
        return self._data.get(key)

    def write(self, key: str, value: Any) -> None:
        """Write a value to shared memory."""
        if self._allowed_write and key not in self._allowed_write:
            raise PermissionError(f"Node not allowed to write key: {key}")
        self._data[key] = value

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
        """Create a view with restricted permissions for a specific node."""
        return SharedMemory(
            _data=self._data,
            _allowed_read=set(read_keys) if read_keys else set(),
            _allowed_write=set(write_keys) if write_keys else set(),
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
            import anthropic
            import json

            node_context = ""
            if node_spec:
                node_context = f"\nNode: {node_spec.name}\nPurpose: {node_spec.description}"

            prompt = f"""Generate a 1-2 sentence human-readable summary of what this node produced.{node_context}

Node output:
{json.dumps(self.output, indent=2, default=str)[:2000]}

Provide a concise, clear summary that a human can quickly understand. Focus on the key information produced."""

            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
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

    def __init__(self, tool_executor: Callable | None = None):
        self.tool_executor = tool_executor

    def _strip_code_blocks(self, content: str) -> str:
        """Strip markdown code block wrappers from content.

        LLMs often wrap JSON output in ```json...``` blocks.
        This method removes those wrappers to get clean content.
        """
        import re
        content = content.strip()
        # Match ```json or ``` at start and ``` at end (greedy to handle nested)
        match = re.match(r'^```(?:json|JSON)?\s*\n?(.*)\n?```\s*$', content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Execute the LLM node."""
        import time

        if ctx.llm is None:
            return NodeResult(success=False, error="LLM not available")

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

            # Log the LLM call details
            logger.info("      🤖 LLM Call:")
            logger.info(f"         System: {system[:150]}..." if len(system) > 150 else f"         System: {system}")
            logger.info(f"         User message: {messages[-1]['content'][:150]}..." if len(messages[-1]['content']) > 150 else f"         User message: {messages[-1]['content']}")
            if ctx.available_tools:
                logger.info(f"         Tools available: {[t.name for t in ctx.available_tools]}")

            # Call LLM
            if ctx.available_tools and self.tool_executor:
                from framework.llm.provider import ToolUse, ToolResult

                def executor(tool_use: ToolUse) -> ToolResult:
                    logger.info(f"         🔧 Tool call: {tool_use.name}({', '.join(f'{k}={v}' for k, v in tool_use.input.items())})")
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
                )
            else:
                # Use JSON mode for llm_generate nodes with structured output
                use_json_mode = (
                    ctx.node_spec.node_type == "llm_generate"
                    and len(ctx.node_spec.output_keys) >= 1
                )
                response = ctx.llm.complete(
                    messages=messages,
                    system=system,
                    json_mode=use_json_mode,
                )

            # Log the response
            response_preview = response.content[:200] if len(response.content) > 200 else response.content
            if len(response.content) > 200:
                response_preview += "..."
            logger.info(f"      ← Response: {response_preview}")

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
            if ctx.node_spec.node_type in ("llm_generate", "llm_tool_use") and len(ctx.node_spec.output_keys) >= 1:
                try:
                    import json

                    # Try to extract JSON from response
                    parsed = self._extract_json(response.content, ctx.node_spec.output_keys)

                    # If parsed successfully, write each field to its corresponding output key
                    if isinstance(parsed, dict):
                        for key in ctx.node_spec.output_keys:
                            if key in parsed:
                                value = parsed[key]
                                # Strip code block wrappers from string values
                                if isinstance(value, str):
                                    value = self._strip_code_blocks(value)
                                ctx.memory.write(key, value)
                                output[key] = value
                            elif key in ctx.input_data:
                                # Key not in parsed JSON but exists in input - pass through input value
                                ctx.memory.write(key, ctx.input_data[key])
                                output[key] = ctx.input_data[key]
                            else:
                                # Key not in parsed JSON or input, write the whole response (stripped)
                                stripped_content = self._strip_code_blocks(response.content)
                                ctx.memory.write(key, stripped_content)
                                output[key] = stripped_content
                    else:
                        # Not a dict, fall back to writing entire response to all keys (stripped)
                        stripped_content = self._strip_code_blocks(response.content)
                        for key in ctx.node_spec.output_keys:
                            ctx.memory.write(key, stripped_content)
                            output[key] = stripped_content

                except (json.JSONDecodeError, Exception) as e:
                    # JSON extraction failed completely - still strip code blocks
                    logger.warning(f"      ⚠ Failed to extract JSON output: {e}")
                    stripped_content = self._strip_code_blocks(response.content)
                    for key in ctx.node_spec.output_keys:
                        ctx.memory.write(key, stripped_content)
                        output[key] = stripped_content
            else:
                # For non-llm_generate or single output nodes, write entire response (stripped)
                stripped_content = self._strip_code_blocks(response.content)
                for key in ctx.node_spec.output_keys:
                    ctx.memory.write(key, stripped_content)
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

    def _extract_json(self, raw_response: str, output_keys: list[str]) -> dict[str, Any]:
        """Extract clean JSON from potentially verbose LLM response.

        Tries multiple extraction strategies in order:
        1. Direct JSON parse
        2. Markdown code block extraction
        3. Balanced brace matching
        4. Haiku LLM fallback (last resort)
        """
        import json
        import re

        content = raw_response.strip()

        # Try direct JSON parse first (fast path)
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks (greedy match to handle nested blocks)
        # Use anchored match to capture from first ``` to last ```
        code_block_match = re.match(r'^```(?:json|JSON)?\s*\n?(.*)\n?```\s*$', content, re.DOTALL)
        if code_block_match:
            try:
                parsed = json.loads(code_block_match.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Try to find JSON object by matching balanced braces (use module-level helper)
        json_str = find_json_object(content)
        if json_str:
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # All local extraction methods failed - use LLM as last resort
        # Prefer Cerebras (faster/cheaper), fallback to Anthropic Haiku
        import os
        api_key = os.environ.get("CEREBRAS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Cannot parse JSON and no API key for LLM cleanup (set CEREBRAS_API_KEY or ANTHROPIC_API_KEY)")

        # Use fast LLM to clean the response (Cerebras llama-3.3-70b preferred)
        from framework.llm.litellm import LiteLLMProvider
        if os.environ.get("CEREBRAS_API_KEY"):
            cleaner_llm = LiteLLMProvider(
                api_key=os.environ.get("CEREBRAS_API_KEY"),
                model="cerebras/llama-3.3-70b",
                temperature=0.0
            )
        else:
            # Fallback to Anthropic Haiku
            from framework.llm.anthropic import AnthropicProvider
            cleaner_llm = AnthropicProvider(model="claude-3-5-haiku-20241022")

        prompt = f"""Extract the JSON object from this LLM response.

Expected output keys: {output_keys}

LLM Response:
{raw_response}

Output ONLY the JSON object, nothing else."""

        try:
            result = cleaner_llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="Extract JSON from text. Output only valid JSON.",
                json_mode=True,
            )

            cleaned = result.content.strip()
            # Remove markdown if LLM added it
            if cleaned.startswith("```"):
                match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()

            parsed = json.loads(cleaned)
            logger.info("      ✓ LLM cleaned JSON output")
            return parsed

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

        # Smart truncation: truncate individual values rather than corrupting JSON structure
        def truncate_value(v, max_len=500):
            s = str(v)
            return s[:max_len] + "..." if len(s) > max_len else v

        truncated_data = {
            k: truncate_value(v) for k, v in memory_data.items()
        }
        memory_json = json.dumps(truncated_data, indent=2, default=str)

        prompt = f"""Extract the following information from the memory context:

Required fields: {', '.join(ctx.node_spec.input_keys)}

Memory context (may contain nested data, JSON strings, or extra information):
{memory_json}

Extract ONLY the clean values for the required fields. Ignore nested structures, JSON wrappers, and irrelevant data.

Output as JSON with the exact field names requested."""

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
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
            options.append({
                "id": condition,
                "description": f"Route to {target} when condition '{condition}' is met",
                "target": target,
            })

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
        options_desc = "\n".join([
            f"- {opt['id']}: {opt['description']} → goes to '{opt['target']}'"
            for opt in options
        ])

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
                system=ctx.node_spec.system_prompt or "You are a routing agent. Respond with JSON only.",
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
                target = ctx.node_spec.routes.get(chosen, ctx.node_spec.routes.get("default", "end"))
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
            options=[{
                "id": "execute",
                "description": f"Run function with inputs: {list(ctx.input_data.keys())}",
            }],
            chosen="execute",
            reasoning="Deterministic function execution",
        )

        start = time.time()

        try:
            # Call the function
            result = self.func(**ctx.input_data)

            latency_ms = int((time.time() - start) * 1000)

            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=True,
                result=result,
                latency_ms=latency_ms,
            )

            # Write to output keys
            output = {"result": result}
            if ctx.node_spec.output_keys:
                ctx.memory.write(ctx.node_spec.output_keys[0], result)

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
