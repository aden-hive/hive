"""Evolution Trigger - turn FailureReports into graph-evolution requests.

When OutcomeAggregator emits a FailureReport, this module packages it into a
structured prompt and dispatches it to a coding agent. Two dispatch modes are
supported:

1. **Direct LLM mode**: call an `LLMProvider` (via `acomplete(json_mode=True)`)
   to get a structured evolution plan. Suitable for offline / CLI use where no
   live queen session exists.

2. **Queen-injection mode**: if a live queen node is supplied, fire a
   `TriggerEvent` via `queen_node.inject_trigger()` so the running queen picks
   up the failure as a new task. Mirrors how timer/webhook triggers feed into
   the queen elsewhere in the codebase.

The structured-prompt format and the `EvolutionPlan` schema are intentionally
small — the goal is to get a usable starting point for graph evolution, not to
fully automate code generation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.graph.goal import Goal
    from framework.llm.provider import LLMProvider
    from framework.schemas.failure_report import FailureReport

logger = logging.getLogger(__name__)


_EVOLUTION_SYSTEM = (
    "You are a coding agent that evolves agent graphs to fix goal failures. "
    "Given a failure report describing unmet success criteria and violated "
    "constraints, propose concrete, minimal changes to the agent's graph "
    "(nodes, edges, prompts, or success criteria) that would fix the failure. "
    "Be specific about which node IDs to modify and what the change is. "
    "Do not invent context that isn't in the report."
)

_EVOLUTION_PROMPT = """A goal-driven agent run failed. Propose graph evolution.

GOAL: {goal_name} (id={goal_id})

UNMET SUCCESS CRITERIA ({n_unmet}):
{unmet_block}

VIOLATED CONSTRAINTS ({n_violated}):
{violated_block}

RELEVANT NODE IDs FROM EXECUTION TRACE:
{node_ids}

ERROR CATEGORY: {error_category}

EXECUTION METRICS:
- decisions: {total_decisions}
- successful outcomes: {successful_outcomes}
- failed outcomes: {failed_outcomes}

SUMMARY:
{summary}

Respond in exactly this JSON format:
{{
  "diagnosis": "1-3 sentences: what went wrong and why",
  "proposed_changes": [
    {{
      "target": "node_id | edge | success_criterion | prompt",
      "target_id": "id of the thing to change, or null",
      "change_type": "add | modify | remove",
      "rationale": "why this change addresses the failure",
      "details": "concrete description of the change"
    }}
  ],
  "confidence": 0.0,
  "needs_human_review": true
}}"""


@dataclass
class ProposedChange:
    """A single graph-evolution change proposed by the coding agent."""

    target: str
    target_id: str | None
    change_type: str
    rationale: str
    details: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProposedChange:
        return cls(
            target=str(d.get("target", "")),
            target_id=d.get("target_id"),
            change_type=str(d.get("change_type", "")),
            rationale=str(d.get("rationale", "")),
            details=str(d.get("details", "")),
        )


@dataclass
class EvolutionPlan:
    """Structured response from the coding agent."""

    diagnosis: str = ""
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    confidence: float = 0.0
    needs_human_review: bool = True
    raw_response: str = ""

    def is_empty(self) -> bool:
        return not self.proposed_changes and not self.diagnosis


class EvolutionTrigger:
    """Convert FailureReports into evolution requests for a coding agent.

    Either ``llm_provider`` or ``queen_node`` must be supplied. If both are
    supplied, ``queen_node`` wins (live queen takes precedence over a one-shot
    LLM call).
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        queen_node: Any = None,
        max_tokens: int = 1024,
    ) -> None:
        if llm_provider is None and queen_node is None:
            raise ValueError(
                "EvolutionTrigger requires either llm_provider or queen_node",
            )
        self._llm = llm_provider
        self._queen = queen_node
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_prompt(self, report: FailureReport) -> str:
        """Package a FailureReport into the structured prompt."""
        unmet_lines = [
            f"- [{c.criterion_id}] {c.description} "
            f"(metric={c.metric}, target={c.target!r}, weight={c.weight})"
            for c in report.unmet_criteria
        ] or ["(none)"]

        violated_lines = [
            f"- [{c.constraint_id}] ({c.constraint_type}) {c.description} "
            f"-- {c.violation_details}"
            for c in report.violated_constraints
        ] or ["(none)"]

        node_ids = ", ".join(report.node_ids) if report.node_ids else "(none)"

        return _EVOLUTION_PROMPT.format(
            goal_name=report.goal_name,
            goal_id=report.goal_id,
            n_unmet=len(report.unmet_criteria),
            unmet_block="\n".join(unmet_lines),
            n_violated=len(report.violated_constraints),
            violated_block="\n".join(violated_lines),
            node_ids=node_ids,
            error_category=report.error_category or "(uncategorized)",
            total_decisions=report.total_decisions,
            successful_outcomes=report.successful_outcomes,
            failed_outcomes=report.failed_outcomes,
            summary=report.summary or "(no summary)",
        )

    async def trigger(self, report: FailureReport) -> EvolutionPlan:
        """Dispatch the failure report to a coding agent.

        Returns an EvolutionPlan. If queen-injection mode is used, the plan is
        empty (the queen handles the work asynchronously) but ``diagnosis``
        notes that injection succeeded.
        """
        prompt = self.build_prompt(report)

        if self._queen is not None:
            return await self._dispatch_to_queen(prompt, report)

        assert self._llm is not None  # narrow for type-checkers
        return await self._dispatch_to_llm(prompt)

    # ------------------------------------------------------------------
    # Dispatch backends
    # ------------------------------------------------------------------

    async def _dispatch_to_llm(self, prompt: str) -> EvolutionPlan:
        try:
            response = await self._llm.acomplete(  # type: ignore[union-attr]
                messages=[{"role": "user", "content": prompt}],
                system=_EVOLUTION_SYSTEM,
                max_tokens=self._max_tokens,
                json_mode=True,
                max_retries=1,
            )
        except Exception as e:
            logger.warning(f"EvolutionTrigger LLM call failed: {e}")
            return EvolutionPlan(diagnosis=f"LLM call failed: {e}")

        return self._parse_response(response.content)

    async def _dispatch_to_queen(
        self, prompt: str, report: FailureReport
    ) -> EvolutionPlan:
        # Local import — TriggerEvent lives next to the event-loop node and
        # importing eagerly would pull in heavyweight graph code.
        from framework.graph.event_loop.types import TriggerEvent

        trigger_event = TriggerEvent(
            trigger_type="evolution",
            source_id=f"failure_report:{report.goal_id}",
            payload={
                "task": prompt,
                "goal_id": report.goal_id,
                "goal_name": report.goal_name,
                "unmet_criteria": [c.model_dump() for c in report.unmet_criteria],
                "violated_constraints": [
                    c.model_dump() for c in report.violated_constraints
                ],
                "node_ids": list(report.node_ids),
                "summary": report.summary,
            },
        )

        try:
            await self._queen.inject_trigger(trigger_event)
            return EvolutionPlan(
                diagnosis="Failure report injected into queen as evolution trigger",
                needs_human_review=False,
            )
        except Exception as e:
            logger.warning(f"EvolutionTrigger queen injection failed: {e}")
            return EvolutionPlan(diagnosis=f"Queen injection failed: {e}")

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(text: str) -> EvolutionPlan:
        raw = text or ""
        cleaned = raw.strip()
        if "```" in cleaned:
            # Strip markdown code fences (```json ... ```).
            try:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()
            except IndexError:
                pass

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse evolution response: {e}")
            return EvolutionPlan(
                diagnosis="Failed to parse coding-agent response",
                raw_response=raw,
            )

        changes_raw = data.get("proposed_changes") or []
        if not isinstance(changes_raw, list):
            changes_raw = []

        return EvolutionPlan(
            diagnosis=str(data.get("diagnosis", "")),
            proposed_changes=[
                ProposedChange.from_dict(c) for c in changes_raw if isinstance(c, dict)
            ],
            confidence=float(data.get("confidence", 0.0) or 0.0),
            needs_human_review=bool(data.get("needs_human_review", True)),
            raw_response=raw,
        )


# ----------------------------------------------------------------------
# Helpers for the CLI / offline use
# ----------------------------------------------------------------------


def _bump_patch(version: str) -> str:
    """Increment the patch component of a semver string. Falls back to '+.1'."""
    parts = version.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        major, minor, patch = (int(p) for p in parts)
        return f"{major}.{minor}.{patch + 1}"
    return f"{version}.1"


def apply_plan(goal: Goal, plan: EvolutionPlan, report: FailureReport) -> Goal:
    """Apply an EvolutionPlan to a Goal, recording the version chain.

    This is intentionally minimal: it sets ``parent_version``, bumps
    ``version``, and writes ``evolution_reason`` so downstream code (and
    humans) can trace why the goal changed. Concrete graph mutations
    (nodes/edges/prompts) are appended to ``goal.context['evolution_log']``
    as a structured audit trail; the actual graph rewrite is the coding
    agent's responsibility once it picks up the trigger.

    Args:
        goal: The goal to evolve in-place.
        plan: The EvolutionPlan returned by ``EvolutionTrigger.trigger``.
        report: The FailureReport that prompted the evolution.

    Returns:
        The same goal instance, mutated.
    """
    from datetime import datetime

    if plan.is_empty():
        logger.info("apply_plan: plan is empty, skipping version bump")
        return goal

    goal.parent_version = goal.version
    goal.version = _bump_patch(goal.version)
    goal.evolution_reason = (
        plan.diagnosis
        or f"Evolved from failure report v{report.version} ({len(report.unmet_criteria)} unmet)"
    )
    goal.updated_at = datetime.now()

    log_entry = {
        "from_version": goal.parent_version,
        "to_version": goal.version,
        "failure_report_version": report.version,
        "failure_report_goal_id": report.goal_id,
        "diagnosis": plan.diagnosis,
        "confidence": plan.confidence,
        "needs_human_review": plan.needs_human_review,
        "changes": [
            {
                "target": c.target,
                "target_id": c.target_id,
                "change_type": c.change_type,
                "rationale": c.rationale,
                "details": c.details,
            }
            for c in plan.proposed_changes
        ],
        "applied_at": datetime.now().isoformat(),
    }
    evolution_log = goal.context.setdefault("evolution_log", [])
    if isinstance(evolution_log, list):
        evolution_log.append(log_entry)
    else:
        # context['evolution_log'] was set to something unexpected — overwrite
        goal.context["evolution_log"] = [log_entry]

    return goal


def compute_failure_rate(reports_dir: Path, window: int) -> tuple[float, int]:
    """Failure rate over the most recent ``window`` reports on disk.

    Returns ``(rate, count)`` where ``rate = count / window`` (capped at 1.0)
    and ``count`` is the number of failure reports found in the window.
    A higher count of recent reports => higher failure pressure => more
    reason to auto-evolve.
    """
    if window <= 0:
        return 0.0, 0
    if not reports_dir.exists() or not reports_dir.is_dir():
        return 0.0, 0

    paths = sorted(
        reports_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    count = min(len(paths), window)
    return min(count / window, 1.0), count


def load_failure_reports(reports_dir: Path) -> list[FailureReport]:
    """Load every FailureReport JSON file in ``reports_dir``, newest first."""
    from framework.schemas.failure_report import FailureReport

    if not reports_dir.exists() or not reports_dir.is_dir():
        return []

    reports: list[tuple[float, FailureReport]] = []
    for path in reports_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            reports.append((path.stat().st_mtime, FailureReport(**data)))
        except Exception as e:
            logger.warning(f"Skipping unreadable failure report {path}: {e}")

    reports.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _, r in reports]
