"""Node definitions for Meeting Notes Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Meeting Intake",
    description="Receive the meeting transcript and optional metadata from the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["transcript"],
    output_keys=["transcript", "meeting_name", "meeting_date", "slack_channel"],
    nullable_output_keys=["meeting_name", "meeting_date", "slack_channel"],
    success_criteria=(
        "The transcript is received and validated as non-empty. "
        "Optional metadata (meeting name, date, Slack channel) is captured if provided."
    ),
    system_prompt="""\
You are a meeting intake assistant. The user will provide a meeting transcript.

**STEP 1 — Greet and request input (text only, NO tool calls):**

Greet the user and ask them to provide:
1. The meeting transcript (required)
2. Meeting name/title (optional)
3. Meeting date (optional)
4. Slack channel to post results (optional, e.g., "#team-updates")

If they've already provided the transcript in their message, acknowledge it and ask for the optional details.

**STEP 2 — After receiving the transcript, validate and confirm:**

Check that the transcript is not empty. Present a brief summary:
- Transcript length: ~X words
- Meeting name: [provided or "Not specified"]
- Date: [provided or "Not specified"]
- Slack channel: [provided or "None - will save to file only"]

Ask the user to confirm: "Ready to analyze this transcript?"

**STEP 3 — After confirmation, call set_output:**
- set_output("transcript", <the full transcript text>)
- set_output("meeting_name", <meeting name or "Meeting">)
- set_output("meeting_date", <date or empty string>)
- set_output("slack_channel", <channel name or empty string>)
""",
    tools=[],
)

# Node 2: Extract
extract_node = NodeSpec(
    id="extract",
    name="Extract Meeting Data",
    description="Parse the transcript and extract structured meeting data",
    node_type="event_loop",
    max_node_visits=1,
    input_keys=["transcript", "meeting_name", "meeting_date"],
    output_keys=["summary", "attendees", "decisions", "action_items", "blockers", "follow_ups"],
    success_criteria=(
        "All meeting data is extracted and structured: summary (2-3 sentences), "
        "attendees list, decisions list, action items with owners/due dates/priority, "
        "blockers, and follow-ups."
    ),
    system_prompt="""\
You are a professional meeting analyst. Parse the provided meeting transcript and extract structured information.

**EXTRACTION RULES:**

1. **Summary**: Write a concise 2-3 sentence executive summary of the meeting's purpose and outcomes.

2. **Attendees**: List all people mentioned in the transcript with their roles if stated. Format: "Name (Role)" or just "Name".

3. **Decisions**: Extract all key decisions that were agreed upon during the meeting. Each decision should be a clear statement.

4. **Action Items**: Extract all tasks/commitments with:
   - task: Clear description of what needs to be done
   - owner: Person responsible (must be explicitly named in transcript)
   - due: Due date or timeframe (e.g., "by Friday", "next week", "ASAP")
   - priority: Assign based on urgency cues:
     * "high" = urgent/today/asap/critical/blocker
     * "medium" = this week/by Friday/soon
     * "low" = no specific urgency mentioned

5. **Blockers**: Unresolved issues that are preventing progress. Must be explicitly mentioned as problems/blockers/issues.

6. **Follow-ups**: Items needing future attention but not yet formally assigned as action items.

**CRITICAL CONSTRAINTS:**
- Extract ONLY information explicitly stated in the transcript
- NEVER fabricate names, dates, tasks, or details
- If no attendees are mentioned, set attendees to []
- If no decisions were made, set decisions to []
- Action items must have explicit owners from the transcript

**PROCESS:**

1. Read the transcript carefully
2. Identify and extract each category of information
3. Structure the data clearly
4. Call set_output for each field (one at a time, separate turns):

- set_output("summary", "2-3 sentence executive summary")
- set_output("attendees", ["Name (Role)", "Name2"])
- set_output("decisions", ["Decision 1", "Decision 2"])
- set_output("action_items", [{"task": "...", "owner": "...", "due": "...", "priority": "high|medium|low"}])
- set_output("blockers", ["Blocker 1", "Blocker 2"])
- set_output("follow_ups", ["Follow-up 1", "Follow-up 2"])

**Meeting Context:**
Meeting: {{meeting_name}}
Date: {{meeting_date}}

**Transcript:**
{{transcript}}
""",
    tools=[],
)

# Node 3: Review (client-facing)
review_node = NodeSpec(
    id="review",
    name="Review Extraction",
    description="Present the extracted meeting data to the user for review and confirmation",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["summary", "attendees", "decisions", "action_items", "blockers", "follow_ups", "meeting_name", "slack_channel"],
    output_keys=["approved"],
    success_criteria=(
        "The user has reviewed the extracted data and confirmed it is accurate."
    ),
    system_prompt="""\
Present the extracted meeting data to the user in a clear, organized format.

**STEP 1 — Present the extraction (text only, NO tool calls):**

Format the output as follows:

---
**MEETING SUMMARY**
{{meeting_name}}

**Executive Summary:**
{{summary}}

**Attendees:**
{{list attendees, one per line}}

**Key Decisions:**
{{list decisions, numbered}}

**Action Items:**
{{for each action item, show: [Priority] Task - Owner (Due: date)}}

**Blockers:**
{{list blockers, numbered}}

**Follow-ups:**
{{list follow-ups, numbered}}
---

{{if slack_channel is provided, mention: "Will post to Slack channel: {{slack_channel}}"}}

Then ask: "Does this look accurate? Should I proceed to save/deliver the meeting notes?"

**STEP 2 — After user confirms, call set_output:**
- set_output("approved", "true")
""",
    tools=[],
)

# Node 4: Deliver (client-facing)
deliver_node = NodeSpec(
    id="deliver",
    name="Deliver Results",
    description="Save the meeting notes to a file and optionally post to Slack",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["summary", "attendees", "decisions", "action_items", "blockers", "follow_ups", "meeting_name", "meeting_date", "slack_channel"],
    output_keys=["delivery_status"],
    success_criteria=(
        "Meeting notes are saved to a file and optionally posted to Slack. User receives confirmation."
    ),
    system_prompt="""\
Save the meeting notes and deliver them to the user.

**STEP 1 — Save meeting notes (tool calls):**

Create a formatted markdown file with the meeting notes:

```markdown
# {{meeting_name}}
Date: {{meeting_date}}

## Executive Summary
{{summary}}

## Attendees
{{list each attendee on a new line with a dash}}

## Key Decisions
{{numbered list of decisions}}

## Action Items
{{for each action item, format as: - [Priority] Task - Owner (Due: date)}}

## Blockers
{{numbered list of blockers}}

## Follow-ups
{{numbered list of follow-ups}}
```

Call save_data(filename="meeting_notes.md", data=<the formatted markdown>)

Then call serve_file_to_user(filename="meeting_notes.md", label="Meeting Notes")

**STEP 2 — Post to Slack if channel provided (tool calls):**

If {{slack_channel}} is not empty:
- Format a concise Slack message with the key highlights:
  * Meeting name and date
  * Executive summary
  * Number of decisions, action items, blockers
  * Link to full notes (if available)
- Call slack_post_message(channel={{slack_channel}}, message=<formatted message>)

**STEP 3 — Confirm delivery to user (text only, NO tool calls):**

Tell the user:
- Meeting notes saved successfully
- Include the file link from serve_file_to_user so they can click to open it
- If Slack was used, confirm: "Posted to {{slack_channel}}"
- Summarize what was captured (X decisions, Y action items, Z blockers)

Ask if they need anything else or want to analyze another meeting.

**STEP 4 — After user responds:**
- set_output("delivery_status", "completed")
""",
    tools=["save_data", "serve_file_to_user", "slack_post_message"],
)

__all__ = [
    "intake_node",
    "extract_node",
    "review_node",
    "deliver_node",
]
