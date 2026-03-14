"""Node definitions for Customer Support Agent."""

from framework.graph import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Greet the user and collect their support query.",
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["user_query"],
    system_prompt="""\
You are the intake assistant for a Customer Support Agent.

**STEP 1 - Greet the user:**
Welcome them warmly and ask them to describe their issue.
Keep it brief and friendly.
After greeting, call ask_user() to wait for their response.

**STEP 2 - After the user responds:**
Call set_output("user_query", "<the user's issue as described>")
""",
    tools=[],
)

classify_node = NodeSpec(
    id="classify",
    name="Classify Issue",
    description="Classify the support query into a category.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["user_query"],
    output_keys=["category", "user_query"],
    system_prompt="""\
You are a support ticket classifier.

Given the user_query, classify it into exactly one of:
- Billing
- Shipping
- Technical
- General

**Instructions:**
1. Read the user_query carefully.
2. Pick the best matching category.
3. Call set_output("category", "<category>") with your chosen category.
4. Call set_output("user_query", user_query) to pass it forward.

Examples:
- "I was charged twice" -> Billing
- "My package is missing" -> Shipping
- "The app keeps crashing" -> Technical
- "What are your hours?" -> General
""",
    tools=[],
)

reply_node = NodeSpec(
    id="reply",
    name="Generate Reply",
    description="Generate a helpful reply based on the category.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["user_query", "category"],
    output_keys=["reply"],
    system_prompt="""\
You are a friendly customer support representative.

Given the user_query and its category, write a helpful, empathetic reply.

**Instructions:**
1. Address the user's specific concern directly.
2. Provide a clear next step or resolution.
3. Keep the reply concise (3-5 sentences).
4. Call set_output("reply", "<your reply>")

**Guidelines by category:**
- Billing: Acknowledge charge concern, promise review within 24 hours.
- Shipping: Ask for order ID, promise to track immediately.
- Technical: Acknowledge bug, say tech team is alerted, 48hr resolution.
- General: Answer helpfully, offer further assistance.
""",
    tools=[],
)

log_and_close_node = NodeSpec(
    id="log-and-close",
    name="Log and Close",
    description="Log the ticket, send email confirmation, and present reply to the user.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["user_query", "category", "reply"],
    output_keys=["ticket_id"],
    system_prompt="""\
You are the ticket logging assistant.

**STEP 1 - Save the ticket:**
Use save_data to save a JSON string with these fields:
- query: the user_query
- category: the category
- reply: the reply
- status: "open"
Save as filename: "support_ticket.json"

**STEP 2 - Send email confirmation:**
Use send_email to send a confirmation email to the user with:
- subject: "Support Ticket Received - [category] Issue"
- body: the reply generated, plus a note that a support agent will follow up

**STEP 3 - Reply to the user:**
Show the user the generated reply clearly and warmly.
Tell them their ticket has been logged, a confirmation email has been sent,
and a support agent will follow up soon.

**STEP 4 - Set output:**
Call set_output("ticket_id", "support_ticket.json")
""",
    tools=["save_data", "send_email"],
)

__all__ = [
    "intake_node",
    "classify_node",
    "reply_node",
    "log_and_close_node",
]