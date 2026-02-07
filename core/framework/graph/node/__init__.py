"""Node module - The building blocks of agent graphs.

A Node is a unit of work that:
1. Receives context (goal, shared memory, input)
2. Makes decisions (using LLM, tools, or logic)
3. Produces results (output, state changes)
4. Records everything to the Runtime

Nodes are composable and reusable. The same node can appear
in different graphs for different goals.

This package provides:
- NodeSpec: Declarative specification of a node
- SharedMemory: Thread-safe state sharing between nodes
- NodeContext: Execution context passed to nodes
- NodeResult: Output of node execution
- NodeProtocol: Abstract interface all nodes implement
- LLMNode: Node that uses LLM with tools
- RouterNode: Node that routes to different paths
- FunctionNode: Node that executes a Python function

Protocol:
    Every node must implement the NodeProtocol interface.
    The framework provides NodeContext with everything the node needs.
"""

# Re-export all public classes for backwards compatibility
from .context import NodeContext
from .memory import MemoryWriteError, SharedMemory
from .protocol import FunctionNode, LLMNode, NodeProtocol, RouterNode
from .result import NodeResult
from .spec import NodeSpec
from .utils import find_json_object, fix_unescaped_newlines_in_json

# Backwards compatibility alias
_fix_unescaped_newlines_in_json = fix_unescaped_newlines_in_json

__all__ = [
    # Core types
    "NodeSpec",
    "SharedMemory",
    "MemoryWriteError",
    "NodeContext",
    "NodeResult",
    # Protocols and implementations
    "NodeProtocol",
    "LLMNode",
    "RouterNode",
    "FunctionNode",
    # Utilities
    "find_json_object",
    "fix_unescaped_newlines_in_json",
    "_fix_unescaped_newlines_in_json",
]
