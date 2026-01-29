"""
Reusable building blocks for agent nodes.

Provides presets for retry, approval/HITL, and validation that can be applied
to nodes via MCP (apply_block) or used as reference when configuring add_node/update_node.

Blocks are configuration deltas only; the executor already respects NodeSpec fields
like max_retries, pause_for_hitl, output_schema, etc.
"""

from framework.blocks.registry import BlockSpec, get_block, list_blocks

__all__ = ["BlockSpec", "get_block", "list_blocks"]
