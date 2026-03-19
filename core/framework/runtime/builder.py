"""
Builder — automatic agent graph improvement based on evaluation history.

The Builder analyses evaluation results and improvement plans to produce
concrete modifications to node specifications (prompts, retry config,
tool assignments, graph structure).  It is the final piece of the
self-improvement loop:

    Execute → Evaluate → Diagnose → **Build** → (next execution)

The Builder operates at two levels:

1. **Prompt tuning** (safe, always enabled):
   Injects guidance into node system prompts based on failure patterns.

2. **Graph restructuring** (requires explicit opt-in):
   Adjusts max_retries, splits nodes, or re-routes edges.

Design constraints:
- Never deletes nodes or edges — only augments.
- All modifications are logged and reversible (via graph versioning).
- LLM-based rewriting is optional — works with deterministic rules too.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Modification:
    """A single change to be applied to a graph."""

    node_id: str
    modification_type: str  # "prompt_augment", "retry_adjust", "add_guidance"
    description: str
    before: str = ""
    after: str = ""
    applied: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BuildResult:
    """Result of a builder run."""

    modifications: list[Modification] = field(default_factory=list)
    graph_version_before: str = ""
    graph_version_after: str = ""
    improvement_plan_used: bool = False

    @property
    def modification_count(self) -> int:
        return sum(1 for m in self.modifications if m.applied)

    def summary(self) -> str:
        applied = [m for m in self.modifications if m.applied]
        if not applied:
            return "No modifications applied."
        lines = [f"Applied {len(applied)} modification(s):"]
        for m in applied:
            lines.append(f"  - [{m.modification_type}] {m.node_id}: {m.description}")
        return "\n".join(lines)


class AgentBuilder:
    """Produces graph modifications from evaluation diagnostics.

    Usage:
        builder = AgentBuilder()
        result = builder.build(graph_spec, improvement_plan)
        # result.modifications contains the changes made
        # graph_spec is modified in-place

    The builder is intentionally conservative — it augments rather than
    replaces, and logs every modification for auditability.
    """

    def build(
        self,
        graph_spec: Any,
        improvement_plan: Any,
        *,
        allow_restructure: bool = False,
    ) -> BuildResult:
        """Apply improvements to a graph specification.

        Args:
            graph_spec: A GraphSpec with .nodes list of NodeSpec objects.
            improvement_plan: An ImprovementPlan from the evaluator.
            allow_restructure: If True, allow max_retries adjustments
                and structural changes. If False, only augment prompts.

        Returns:
            BuildResult with the list of modifications applied.
        """
        result = BuildResult(
            graph_version_before=getattr(graph_spec, "version", ""),
            improvement_plan_used=True,
        )

        nodes_by_id: dict[str, Any] = {}
        for node in getattr(graph_spec, "nodes", []):
            nodes_by_id[node.id] = node

        # --- 1. Augment prompts for failing criteria ---
        for cid in getattr(improvement_plan, "failing_criteria", []):
            # Find nodes whose success_criteria mention this criterion
            for node in nodes_by_id.values():
                sc = getattr(node, "success_criteria", None) or ""
                if cid.lower() in (sc.lower() if isinstance(sc, str) else ""):
                    mod = self._augment_prompt_for_criterion(node, cid, improvement_plan)
                    if mod:
                        result.modifications.append(mod)

        # --- 2. Add guidance to bottleneck nodes ---
        for nid in getattr(improvement_plan, "bottleneck_nodes", []):
            node = nodes_by_id.get(nid)
            if node:
                mod = self._add_retry_guidance(node, improvement_plan)
                if mod:
                    result.modifications.append(mod)

                # Optionally adjust retry config
                if allow_restructure:
                    mod2 = self._adjust_retries(node)
                    if mod2:
                        result.modifications.append(mod2)

        # --- 3. Inject general improvement context into all nodes ---
        recommendations = getattr(improvement_plan, "recommendations", [])
        if recommendations:
            for node in nodes_by_id.values():
                mod = self._inject_improvement_context(node, recommendations)
                if mod:
                    result.modifications.append(mod)

        # Update graph version
        old_version = getattr(graph_spec, "version", "1.0.0")
        if result.modification_count > 0:
            new_version = self._bump_version(old_version)
            if hasattr(graph_spec, "version"):
                graph_spec.version = new_version
            result.graph_version_after = new_version

        logger.info(
            "Builder: %d modifications applied (version %s → %s)",
            result.modification_count,
            result.graph_version_before,
            result.graph_version_after or "(unchanged)",
        )

        return result

    # ----- modification strategies -----

    def _augment_prompt_for_criterion(
        self, node: Any, criterion_id: str, plan: Any
    ) -> Modification | None:
        """Add guidance to a node's system prompt about a failing criterion."""
        current_prompt = getattr(node, "system_prompt", None) or ""
        marker = f"<!-- builder:criterion:{criterion_id} -->"

        # Don't apply the same augmentation twice
        if marker in current_prompt:
            return None

        guidance = (
            f"\n\n{marker}\n"
            f"IMPORTANT: The criterion '{criterion_id}' has been failing in recent executions. "
            f"Pay extra attention to satisfying this requirement. "
            f"Recent success rate: {getattr(plan, 'recent_success_rate', 'N/A'):.0%}.\n"
        )

        node.system_prompt = current_prompt + guidance

        return Modification(
            node_id=node.id,
            modification_type="prompt_augment",
            description=f"Added guidance for failing criterion '{criterion_id}'",
            before=current_prompt[-200:] if len(current_prompt) > 200 else current_prompt,
            after=node.system_prompt[-200:],
            applied=True,
        )

    def _add_retry_guidance(self, node: Any, plan: Any) -> Modification | None:
        """Add guidance to a node that has high retry rates."""
        current_prompt = getattr(node, "system_prompt", None) or ""
        marker = "<!-- builder:retry_guidance -->"

        if marker in current_prompt:
            return None

        guidance = (
            f"\n\n{marker}\n"
            "NOTE: This node has experienced frequent retries in recent executions. "
            "Be more careful with output formatting and validation requirements. "
            "Double-check your output matches the expected schema before completing.\n"
        )

        node.system_prompt = current_prompt + guidance

        return Modification(
            node_id=node.id,
            modification_type="add_guidance",
            description="Added retry-reduction guidance",
            before="",
            after=guidance.strip(),
            applied=True,
        )

    def _adjust_retries(self, node: Any) -> Modification | None:
        """Increase max_retries for a bottleneck node (structural change)."""
        current = getattr(node, "max_retries", 3)
        if current >= 5:
            return None  # Already at reasonable max

        new_retries = min(current + 1, 5)
        old_val = str(current)
        node.max_retries = new_retries

        return Modification(
            node_id=node.id,
            modification_type="retry_adjust",
            description=f"Increased max_retries from {current} to {new_retries}",
            before=f"max_retries={old_val}",
            after=f"max_retries={new_retries}",
            applied=True,
        )

    def _inject_improvement_context(
        self, node: Any, recommendations: list[str]
    ) -> Modification | None:
        """Inject improvement recommendations as a prompt appendix."""
        current_prompt = getattr(node, "system_prompt", None) or ""
        marker = "<!-- builder:improvement -->"

        # Replace existing improvement block or add new one
        if marker in current_prompt:
            # Strip old improvement block
            parts = current_prompt.split(marker)
            if len(parts) >= 3:
                current_prompt = parts[0] + parts[2]  # Keep before and after
            else:
                current_prompt = parts[0]

        rec_text = "\n".join(f"- {r}" for r in recommendations[:3])
        improvement_block = (
            f"\n\n{marker}\n"
            f"## Improvement Notes (auto-generated)\n{rec_text}\n"
            f"{marker}\n"
        )

        node.system_prompt = current_prompt + improvement_block

        return Modification(
            node_id=node.id,
            modification_type="add_guidance",
            description="Injected improvement recommendations",
            applied=True,
        )

    @staticmethod
    def _bump_version(version: str) -> str:
        """Bump the patch version: 1.0.0 → 1.0.1."""
        try:
            parts = version.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        except (ValueError, IndexError):
            return version + ".1"
