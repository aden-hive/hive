"""Node definitions for Email Reply Agent."""

from framework.orchestrator import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Gather email filter criteria from user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["batch_complete", "restart"],
    output_keys=["filter_criteria"],
    nullable_output_keys=["batch_complete", "restart"],
    success_criteria="Filter criteria is specific enough to search Gmail (sender, subject, date range, or keywords).",
    system_prompt="""\
You are an intake specialist for email replies. Your ONLY job is to gather filter criteria and call set_output.

If the user has already provided criteria in their message, IMMEDIATELY call:
set_output("filter_criteria", {"sender_pattern": "...", "date_range": "...", "max_results": 50, "tone_guidance": "..."})

DO NOT:
- Read files
- Search files  
- List directories
- Ask for confirmation if criteria are already provided

If you need more information, ask ONE brief question. Otherwise, call set_output immediately.

After batch_complete or restart, acknowledge and ask for next criteria.
""",
    tools=[],
)

# Node 2: Search (autonomous)
search_node = NodeSpec(
    id="search",
    name="Search Emails",
    description="Search Gmail for unreplied emails matching filter criteria",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["filter_criteria"],
    output_keys=["email_list"],
    nullable_output_keys=[],
    success_criteria="Found unreplied emails matching criteria with sender, subject, snippet, message_id.",
    system_prompt="""\
You are a Gmail search agent. Find unreplied emails matching the user's filter criteria.

## Workflow:
1. Build Gmail search query from filter_criteria:
   - Use "is:unread" to find unreplied (standard proxy for unreplied)
   - Add sender: from:(pattern) if sender_pattern provided
   - Add subject: subject:(keywords) if subject_keywords provided
   - Add after: after:YYYY/MM/DD if date_range provided
   - Limit to max_results (default 50)
2. Call gmail_list_messages with the query
3. For each message_id, call gmail_get_message to get full content (sender, subject, body)
4. Build a structured list of emails

## Output:
set_output("email_list", JSON list with fields for each email:
- message_id
- sender (email address)
- sender_name (if available)
- subject
- snippet (first 200 chars of body)
- received_date (ISO format)
)

If no emails found, set empty array: set_output("email_list", [])
""",
    tools=["gmail_list_messages", "gmail_get_message", "gmail_batch_get_messages"],
)

# Node 3: Confirm & Reply (client-facing)
confirm_draft_node = NodeSpec(
    id="confirm-draft",
    name="Confirm & Reply",
    description="Present emails for confirmation, send personalized replies",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["email_list", "filter_criteria"],
    output_keys=["batch_complete", "restart"],
    nullable_output_keys=["batch_complete", "restart"],
    success_criteria="User confirmed recipients and personalized replies sent for each.",
    system_prompt="""\
You are a Gmail reply assistant. Present emails for confirmation, then send personalized replies.

**STEP 1 — Present for confirmation (text only, NO tool calls):**
1. Show the email list in readable format:
   - #. Sender Name <email> - Subject (Date)
   - Snippet: first 150 chars
2. Ask: "These are the emails to reply to. Confirm? Any tone preferences or specific messages?"
3. Wait for user response

**STEP 2 — Handle user response:**

If user CONFIRMS (says yes, go ahead, sounds good, etc.):
For EACH email in email_list:
1. Read the subject and snippet
2. Use tone_guidance from filter_criteria + any user-specified preferences
3. Call gmail_reply_email with:
   - message_id: the email's message_id
   - html: personalized 2-4 sentence reply based on email context
   (The tool automatically handles recipient, subject, and threading)
4. After all replies sent, call: set_output("batch_complete", True)

If user wants to CHANGE LOGIC/FILTER (says change filter, different criteria, not these emails, wrong emails, etc.):
1. Acknowledge their request
2. Call: set_output("restart", True)

Personalization rules:
- Reference specific details from their email (questions asked, topics mentioned)
- Match their formality level (formal→formal, casual→casual)
- If tone_guidance specifies style, follow it
- Keep replies concise but warm
""",
    tools=["gmail_reply_email"],
)

__all__ = ["intake_node", "search_node", "confirm_draft_node"]
