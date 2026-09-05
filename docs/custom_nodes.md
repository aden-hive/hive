# Creating Custom Nodes

Nodes are the building blocks of the Hive framework. This guide explains how to create custom nodes to extend the agent's capabilities.

## Overview

Every node in Hive must inherit from `NodeProtocol` (or one of its subclasses like `LLMNode`) and implement the `execute` method.

## Basic Structure

Here is a minimal example of a custom node:

```python
from framework.graph.node import NodeProtocol, NodeContext, NodeResult
import logging

logger = logging.getLogger(__name__)

class MyCustomNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        logger.info(f"Executing MyCustomNode: {ctx.node_id}")
        
        # Access input data
        params = ctx.input_data
        
        # Perform logic
        result = {"status": "ok", "processed": True}
        
        return NodeResult(success=True, output=result)
```

## Creating an LLM Node

If your node needs to use an LLM, inherit from `LLMNode`. This gives you access to built-in helper methods for managing prompts and tools.

```python
from framework.graph.node import LLMNode, NodeContext, NodeResult

class MyLLMNode(LLMNode):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        # You can override execute to customize behavior, 
        # or rely on the base LLMNode logic by configuring NodeSpec correctly.
        
        # Example: specialized validation before calling LLM
        if "required_key" not in ctx.input_data:
             return NodeResult(success=False, error="Missing required input")
             
        return await super().execute(ctx)
```

## Registering Your Node

To use your node in a graph, you must register it with the executor or define it in your agent's graph specification.

## Best Practices

1. **Idempotency**: Nodes should ideally be idempotent, as they might be retried.
2. **Error Handling**: Return `NodeResult(success=False, error=...)` instead of raising exceptions when possible, to allow the framework to handle failures gracefully.
3. **Logging**: Use the standard logger to Record what the node is doing.
