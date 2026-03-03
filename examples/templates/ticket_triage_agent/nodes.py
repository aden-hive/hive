"""Node definitions for Ticket Triage Agent."""

from framework.graph import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="Ticket Intake",
    description="Receive the support ticket from the user and confirm details",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["customer_name", "subject", "message"],
    output_keys=["ticket_confirmed"],
    success_criteria=(
        "The ticket has been received and the customer name, subject, "
        "and message are all present and confirmed."
    ),
    system_prompt="""\
You are a support ticket intake agent.

STEP 1 — Read the ticket details provided:
- Customer name
- Subject
- Message

Acknowledge receipt of the ticket in a brief internal note.
Confirm all three fields are present.

STEP 2 — Call set_output:
- set_output("ticket_confirmed", "true")
""",
    tools=[],
)

classify_node = NodeSpec(
    id="classify",
    name="Priority Classification",
    description="Classify the ticket priority based on the message content",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["customer_name", "subject", "message"],
    output_keys=["priority", "classification_reason"],
    success_criteria=(
        "The ticket has been assigned a priority of Critical, High, Medium, or Low "
        "with a clear reason."
    ),
    system_prompt="""\
You are a support ticket classifier.

Read this ticket:
Customer: {customer_name}
Subject: {subject}
Message: {message}

Classify the priority using these rules:
- Critical: system down, data loss, security breach, payment failure
- High: feature broken, user cannot complete a core workflow
- Medium: partial issue, workaround exists
- Low: general question, feature request, cosmetic issue

STEP 1 — Decide the priority and reason.

STEP 2 — Call set_output separately for each key:
- set_output("priority", "Critical")
- set_output("classification_reason", "Brief explanation of why this priority was chosen")
""",
    tools=[],
)

assign_node = NodeSpec(
    id="assign",
    name="Team Assignment",
    description="Assign the ticket to the correct team based on priority",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["priority"],
    output_keys=["assigned_team"],
    success_criteria="The ticket has been assigned to the correct team.",
    system_prompt="""\
You are a ticket routing agent.

The ticket priority is: {priority}

Assign to the correct team using these rules:
- Critical or High: engineering team
- Medium: support team
- Low: success team

Call set_output:
- set_output("assigned_team", "engineering team")
""",
    tools=[],
)

draft_node = NodeSpec(
    id="draft",
    name="Draft Response",
    description="Draft a professional first response to the customer",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["customer_name", "subject", "message", "priority", "assigned_team"],
    output_keys=["draft_response"],
    success_criteria="A professional draft response has been written for the customer.",
    system_prompt="""\
You are a customer support writer.

Write a professional and empathetic first response to this ticket:
Customer: {customer_name}
Subject: {subject}
Message: {message}
Priority: {priority}
Assigned team: {assigned_team}

The response must:
- Address the customer by name
- Acknowledge their issue clearly
- Set realistic expectations based on priority:
  - Critical: within 1 hour
  - High: within 4 hours
  - Medium: within 24 hours
  - Low: within 3 business days
- Be warm, concise, and professional

Call set_output:
- set_output("draft_response", "Full response text here")
""",
    tools=[],
)

approval_node = NodeSpec(
    id="approval",
    name="Human Approval",
    description="Pause for human review on Critical tickets before sending response",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["priority", "draft_response", "customer_name", "assigned_team"],
    output_keys=["approved", "final_response"],
    success_criteria="Human has reviewed and approved or edited the draft response.",
    system_prompt="""\
You are a human approval checkpoint.

Priority: {priority}
Customer: {customer_name}
Assigned team: {assigned_team}

Draft response:
{draft_response}

If priority is Critical:
- Present the draft response to the human reviewer
- Ask them to approve, edit, or reject it
- Wait for their input

If priority is NOT Critical:
- Automatically approve the draft response
- No human input needed

After decision, call set_output:
- set_output("approved", "true")
- set_output("final_response", "The final approved response text")
""",
    tools=[],
)
