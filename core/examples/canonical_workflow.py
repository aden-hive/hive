"""Canonical workflow usage for the Hive framework."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.builder import GraphBuilder, ValidationResult
from framework.graph import (
    Goal,
    SuccessCriterion,
    Constraint,
    NodeSpec,
    EdgeSpec,
    EdgeCondition,
    GraphExecutor,
)
from framework.graph.node import NodeProtocol, NodeContext, NodeResult
from framework.runtime.core import Runtime


@dataclass
class MemoryFunctionNode(NodeProtocol):
    func: Any

    async def execute(self, ctx: NodeContext) -> NodeResult:
        import time

        ctx.runtime.set_node(ctx.node_id)

        inputs = {key: ctx.memory.read(key) for key in ctx.node_spec.input_keys}
        decision_id = ctx.runtime.decide(
            intent=f"Execute {ctx.node_spec.name}",
            options=[{
                "id": "execute",
                "description": f"Run with inputs: {sorted(list(inputs.keys()))}",
            }],
            chosen="execute",
            reasoning="Deterministic function execution",
        )

        start = time.time()
        try:
            result = self.func(**inputs)
            if not isinstance(result, dict):
                raise ValueError("Function output must be a dict")

            for key in ctx.node_spec.output_keys:
                if key in result:
                    ctx.memory.write(key, result[key])

            latency_ms = int((time.time() - start) * 1000)
            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=True,
                result=result,
                latency_ms=latency_ms,
            )
            return NodeResult(success=True, output=result, latency_ms=latency_ms)

        except Exception as exc:
            latency_ms = int((time.time() - start) * 1000)
            ctx.runtime.record_outcome(
                decision_id=decision_id,
                success=False,
                error=str(exc),
                latency_ms=latency_ms,
            )
            return NodeResult(success=False, error=str(exc), latency_ms=latency_ms)


def require_valid(validation: ValidationResult, label: str) -> None:
    if not validation.valid:
        raise RuntimeError(f"Validation failed for {label}: {validation.errors}")


def normalize_ticket(raw_ticket: dict) -> dict:
    subject = raw_ticket.get("subject", "")
    body = raw_ticket.get("body", "")
    customer_tier = raw_ticket.get("customer_tier", "standard")
    reported_impact = raw_ticket.get("reported_impact", "unknown")

    normalized = {
        "subject": subject.strip(),
        "summary": body.strip()[:280],
        "customer_tier": customer_tier,
        "reported_impact": reported_impact,
    }

    return {"normalized_ticket": normalized}


def assess_urgency(normalized_ticket: dict) -> dict:
    ticket = normalized_ticket
    impact = ticket.get("reported_impact")
    tier = ticket.get("customer_tier")

    escalation_required = impact in {"outage", "security"} or tier == "enterprise"
    urgency = "high" if escalation_required else "normal"

    assessment = {
        "urgency": urgency,
        "escalation_required": escalation_required,
        "reason": "customer tier or impact severity triggers escalation" if escalation_required else "standard priority",
    }

    return {
        "normalized_ticket": ticket,
        "urgency_assessment": assessment,
    }


def draft_response(normalized_ticket: dict, urgency_assessment: dict) -> dict:
    ticket = normalized_ticket
    urgency = urgency_assessment.get("urgency", "normal")

    response = {
        "priority": urgency,
        "response_text": (
            f"Thanks for the report on '{ticket['subject']}'. "
            "We have logged the issue and will update you within 2 hours. "
            "Next steps: confirm impact scope and provide an ETA."
        ),
    }

    return {"draft_response": response}


def escalate(normalized_ticket: dict, urgency_assessment: dict) -> dict:
    ticket = normalized_ticket
    assessment = urgency_assessment

    notice = {
        "escalation_queue": "on-call-sev1",
        "escalation_reason": assessment.get("reason"),
        "ticket_subject": ticket.get("subject"),
    }

    return {"escalation_notice": notice}


def build_workflow() -> tuple[GraphBuilder, Goal, Any]:
    builder = GraphBuilder("support-triage")

    goal = Goal(
        id="support-triage-001",
        name="Triage and respond to an outage report",
        description=(
            "Normalize an incoming support ticket, determine whether escalation is required, "
            "and produce either an escalation notice or a customer-ready response draft."
        ),
        success_criteria=[
            SuccessCriterion(
                id="decision-recorded",
                description="A clear urgency decision is recorded for every ticket",
                metric="output_contains",
                target="urgency",
            ),
            SuccessCriterion(
                id="next-step-stated",
                description="Response or escalation includes an explicit next step",
                metric="output_contains",
                target="Next steps",
            ),
        ],
        constraints=[
            Constraint(
                id="no-guessing",
                description="Do not invent customer details beyond the provided ticket",
                constraint_type="hard",
                category="quality",
                check="output only derives from input",
            )
        ],
        required_capabilities=["deterministic"],
    )

    require_valid(builder.set_goal(goal), "goal")
    if not builder.approve("Goal approved for support triage workflow"):
        raise RuntimeError("Goal approval failed")

    require_valid(
        builder.add_node(
            NodeSpec(
                id="normalize-ticket",
                name="Normalize Ticket",
                description="Normalize raw ticket input into structured fields",
                node_type="function",
                input_keys=["raw_ticket"],
                output_keys=["normalized_ticket"],
                function="normalize_ticket",
            )
        ),
        "normalize-ticket",
    )
    if not builder.approve("Normalize ticket node approved"):
        raise RuntimeError("Node approval failed: normalize-ticket")

    require_valid(
        builder.add_node(
            NodeSpec(
                id="assess-urgency",
                name="Assess Urgency",
                description="Determine escalation need based on impact and tier",
                node_type="function",
                input_keys=["normalized_ticket"],
                output_keys=["normalized_ticket", "urgency_assessment"],
                function="assess_urgency",
            )
        ),
        "assess-urgency",
    )
    if not builder.approve("Urgency assessment node approved"):
        raise RuntimeError("Node approval failed: assess-urgency")

    require_valid(
        builder.add_node(
            NodeSpec(
                id="draft-response",
                name="Draft Response",
                description="Create a customer-ready response draft",
                node_type="function",
                input_keys=["normalized_ticket", "urgency_assessment"],
                output_keys=["draft_response"],
                function="draft_response",
            )
        ),
        "draft-response",
    )
    if not builder.approve("Draft response node approved"):
        raise RuntimeError("Node approval failed: draft-response")

    require_valid(
        builder.add_node(
            NodeSpec(
                id="escalate",
                name="Escalate",
                description="Route critical tickets to the on-call queue",
                node_type="function",
                input_keys=["normalized_ticket", "urgency_assessment"],
                output_keys=["escalation_notice"],
                function="escalate",
            )
        ),
        "escalate",
    )
    if not builder.approve("Escalation node approved"):
        raise RuntimeError("Node approval failed: escalate")

    require_valid(
        builder.add_edge(
            EdgeSpec(
                id="normalize-to-assess",
                source="normalize-ticket",
                target="assess-urgency",
                condition=EdgeCondition.ON_SUCCESS,
                description="Only assess urgency after normalization succeeds",
            )
        ),
        "normalize-to-assess",
    )
    if not builder.approve("Edge approved: normalize to assess"):
        raise RuntimeError("Edge approval failed: normalize-to-assess")

    require_valid(
        builder.add_edge(
            EdgeSpec(
                id="assess-to-escalate",
                source="assess-urgency",
                target="escalate",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output['urgency_assessment']['escalation_required'] == true",
                priority=10,
                description="Escalate if the ticket requires on-call attention",
            )
        ),
        "assess-to-escalate",
    )
    if not builder.approve("Edge approved: assess to escalate"):
        raise RuntimeError("Edge approval failed: assess-to-escalate")

    require_valid(
        builder.add_edge(
            EdgeSpec(
                id="assess-to-draft",
                source="assess-urgency",
                target="draft-response",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output['urgency_assessment']['escalation_required'] == false",
                priority=0,
                description="Draft a response when escalation is not required",
            )
        ),
        "assess-to-draft",
    )
    if not builder.approve("Edge approved: assess to draft"):
        raise RuntimeError("Edge approval failed: assess-to-draft")

    validation = builder.validate()
    require_valid(validation, "full graph")

    if not builder.final_approve("Workflow validated and ready for execution"):
        raise RuntimeError("Final approval failed")

    graph = builder.export()
    return builder, goal, graph


async def run_workflow(builder: GraphBuilder, goal: Goal, graph: Any) -> None:
    runtime_dir = Path(tempfile.mkdtemp(prefix="hive-runtime-"))
    runtime = Runtime(runtime_dir)
    executor = GraphExecutor(runtime=runtime)

    executor.register_node("normalize-ticket", MemoryFunctionNode(normalize_ticket))
    executor.register_node("assess-urgency", MemoryFunctionNode(assess_urgency))
    executor.register_node("draft-response", MemoryFunctionNode(draft_response))
    executor.register_node("escalate", MemoryFunctionNode(escalate))

    print("\n=== Graph Overview ===")
    print(builder.show())

    input_payload = {
        "raw_ticket": {
            "subject": "Checkout outage affecting enterprise tenant",
            "body": "Payments failing across multiple regions since 08:15 UTC.",
            "customer_tier": "enterprise",
            "reported_impact": "outage",
        }
    }

    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data=input_payload,
    )

    output = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "path": result.path,
        "output": result.output,
    }

    print("\n=== Execution Result ===")
    print(json.dumps(output, indent=2))


def main() -> None:
    builder, goal, graph = build_workflow()
    asyncio.run(run_workflow(builder, goal, graph))


if __name__ == "__main__":
    main()
