"""
Block registry: presets for retry, approval/HITL, and validation.

Each block is a named preset that applies a delta (dict) to a NodeSpec.
Deltas use only keys that NodeSpec supports and that can be set via MCP
(max_retries, retry_on, output_schema, max_validation_retries, pause_for_hitl, approval_message).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BlockSpec:
    """A reusable building block: id, metadata, and delta to apply to a node."""

    id: str
    name: str
    description: str
    category: str  # "retry" | "approval" | "validation"
    delta: dict[str, Any] = field(default_factory=dict)

    def apply_to_node_dict(self, node_data: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge this block's delta (and optional overrides) into a node dict. Returns a new dict."""
        out = dict(node_data)
        for key, value in self.delta.items():
            out[key] = value
        if overrides:
            for key, value in overrides.items():
                out[key] = value
        return out


# -----------------------------------------------------------------------------
# Retry blocks
# -----------------------------------------------------------------------------

RETRY_DEFAULT = BlockSpec(
    id="retry_default",
    name="Retry with backoff (default)",
    description="3 retries with exponential backoff; good for transient failures.",
    category="retry",
    delta={"max_retries": 3, "retry_on": []},
)

RETRY_AGGRESSIVE = BlockSpec(
    id="retry_aggressive",
    name="Retry aggressive",
    description="5 retries with backoff; use for flaky external APIs.",
    category="retry",
    delta={"max_retries": 5, "retry_on": []},
)

RETRY_NONE = BlockSpec(
    id="retry_none",
    name="No retries",
    description="Fail immediately on first error; use when retries are not safe.",
    category="retry",
    delta={"max_retries": 0, "retry_on": []},
)

RETRY_ON_NETWORK = BlockSpec(
    id="retry_on_network",
    name="Retry on network errors",
    description="3 retries, only on timeout/connection/rate_limit style errors.",
    category="retry",
    delta={"max_retries": 3, "retry_on": ["timeout", "connection", "rate_limit", "rate limit"]},
)

# -----------------------------------------------------------------------------
# Approval / HITL blocks
# -----------------------------------------------------------------------------

APPROVAL_REQUIRED = BlockSpec(
    id="approval_required",
    name="Human approval required",
    description="Execution pauses at this node for human approval; resume via entry point.",
    category="approval",
    delta={"pause_for_hitl": True, "approval_message": "Please review and approve to continue."},
)

APPROVAL_WITH_MESSAGE = BlockSpec(
    id="approval_with_message",
    name="Approval with custom message",
    description="Pause for approval; set approval_message via overrides when applying.",
    category="approval",
    delta={"pause_for_hitl": True, "approval_message": None},  # caller should override
)

# Approval with timeout: metadata only for future runner/CLI use (Phase 2)
APPROVAL_WITH_TIMEOUT = BlockSpec(
    id="approval_with_timeout",
    name="Approval with timeout (metadata)",
    description="Pause for approval; stores approval_timeout_seconds in extra metadata for future escalation.",
    category="approval",
    delta={
        "pause_for_hitl": True,
        "approval_message": "Please review and approve to continue (will escalate if no response).",
        # Store in model extra; executor does not use yet
        "approval_timeout_seconds": 300,
    },
)

# -----------------------------------------------------------------------------
# Validation blocks
# -----------------------------------------------------------------------------

VALIDATION_DEFAULT = BlockSpec(
    id="validation_default",
    name="Output validation (default)",
    description="Validate node output; up to 2 retries with feedback to LLM on validation failure.",
    category="validation",
    delta={"max_validation_retries": 2, "output_schema": {}},
)

VALIDATION_STRICT = BlockSpec(
    id="validation_strict",
    name="Strict output validation",
    description="Up to 3 validation retries; use when output shape must be correct.",
    category="validation",
    delta={"max_validation_retries": 3, "output_schema": {}},
)

VALIDATION_NONE = BlockSpec(
    id="validation_none",
    name="No output validation",
    description="No validation retries; use when output is free-form.",
    category="validation",
    delta={"max_validation_retries": 0, "output_schema": {}},
)

# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------

_BLOCKS: dict[str, BlockSpec] = {
    RETRY_DEFAULT.id: RETRY_DEFAULT,
    RETRY_AGGRESSIVE.id: RETRY_AGGRESSIVE,
    RETRY_NONE.id: RETRY_NONE,
    RETRY_ON_NETWORK.id: RETRY_ON_NETWORK,
    APPROVAL_REQUIRED.id: APPROVAL_REQUIRED,
    APPROVAL_WITH_MESSAGE.id: APPROVAL_WITH_MESSAGE,
    APPROVAL_WITH_TIMEOUT.id: APPROVAL_WITH_TIMEOUT,
    VALIDATION_DEFAULT.id: VALIDATION_DEFAULT,
    VALIDATION_STRICT.id: VALIDATION_STRICT,
    VALIDATION_NONE.id: VALIDATION_NONE,
}


def get_block(block_id: str) -> BlockSpec | None:
    """Return the block with the given id, or None."""
    return _BLOCKS.get(block_id)


def list_blocks(category: str | None = None) -> list[BlockSpec]:
    """Return all blocks, optionally filtered by category (retry, approval, validation)."""
    if category is None:
        return list(_BLOCKS.values())
    return [b for b in _BLOCKS.values() if b.category == category]
