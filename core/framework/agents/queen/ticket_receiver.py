"""Queen's ticket receiver entry point.

When the Worker Health Judge emits a WORKER_ESCALATION_TICKET event on the
shared EventBus, this entry point fires and routes to the ``ticket_triage``
node, where the Queen deliberates and decides whether to notify the operator.

Isolation level is ``isolated`` — the queen's triage memory is kept separate
from the worker's shared memory. Each ticket triage runs in its own context.
"""

from __future__ import annotations

from framework.graph.edge import AsyncEntryPointSpec

TICKET_RECEIVER_ENTRY_POINT = AsyncEntryPointSpec(
    id="ticket_receiver",
    name="Worker Escalation Ticket Receiver",
    entry_node="ticket_triage",
    trigger_type="event",
    trigger_config={
        "event_types": ["worker_escalation_ticket"],
        # Do not fire on our own graph's events (prevents loops if queen
        # somehow emits a worker_escalation_ticket for herself)
        "exclude_own_graph": True,
    },
    isolation_level="isolated",
)
