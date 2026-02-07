"""Node execution result.

Contains the output of a node execution including success status,
output data, routing decisions, and metadata.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NodeResult:
    """The output of a node execution.

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
        """Generate a human-readable summary of this node's execution and output.

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


__all__ = ["NodeResult"]
