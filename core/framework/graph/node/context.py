"""Node execution context.

Contains everything a node needs to execute, including runtime,
memory, LLM access, tools, and goal context.
"""

from dataclasses import dataclass, field
from typing import Any

from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime

from .memory import SharedMemory
from .spec import NodeSpec


@dataclass
class NodeContext:
    """Everything a node needs to execute.

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


__all__ = ["NodeContext"]
