"""Node definitions for Meeting Scheduler."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Gather meeting details from the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["attendee_email", "meeting_duration_minutes"],
    output_keys=["attendee_email", "meeting_duration_minutes", "meeting_title"],
    nullable_output_keys=[
        "attendee_email",
        "meeting_duration_minutes",
        "meeting_title",
    ],
    success_criteria="User has provided attendee email, meeting duration, and title.",
    system_prompt="""\
You are a meeting scheduler assistant.

**STEP 1 — Use ask_user to collect meeting details:**
1. Call ask_user to ask for: attendee email, meeting duration (minutes), and meeting title
2. Wait for the user's response before proceeding

**STEP 2 — After user provides all details, call set_output:**
- set_output("attendee_email", "user's email address")
- set_output("meeting_duration_minutes", meeting duration as string)
- set_output("meeting_title", "title of the meeting")
""",
    tools=[],
)

# Node 2: Schedule (autonomous)
schedule_node = NodeSpec(
    id="schedule",
    name="Schedule",
    description="Find available time on calendar, book meeting with Google Meet, and log to Google Sheet",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["attendee_email", "meeting_duration_minutes", "meeting_title"],
    output_keys=[
        "meeting_time",
        "booking_confirmed",
        "spreadsheet_recorded",
        "email_sent",
        "meet_link",
    ],
    nullable_output_keys=[],
    success_criteria="Meeting time found, Google Meet created, Google Sheet 'Meeting Scheduler' updated with date/time/attendee/title/meet_link, and confirmation email sent.",
    system_prompt="""\
You are a meeting booking agent that creates Google Calendar events with Google Meet and logs to Google Sheets.

## STEP 1 — Calendar Operations (tool calls in this turn):

1. **Find availability and verify conflicts:**
   - Use calendar_check_availability to find potential time slots.
   - **CRITICAL:** Always search a broad window (at least 8 hours) for the target day to see the full context of the user's schedule.
   - **SECONDARY CHECK:** Before finalizing a slot, use calendar_list_events for that specific day. This ensures you catch "soft" conflicts or events not marked as 'busy' that might still be important.

2. **Create the event WITH GOOGLE MEET (AUTOMATIC):**
   - Use calendar_create_event with these parameters:
     - summary: the meeting title
     - start_time: the start datetime in ISO format (e.g., "2024-01-15T09:00:00")
     - end_time: the end datetime in ISO format
     - attendees: list with the attendee email address (e.g., ["user@example.com"])
     - timezone: user's timezone (e.g., "America/Los_Angeles")
   - IMPORTANT: The tool automatically generates a Google Meet link when attendees are provided.
     You do NOT need to pass conferenceData - it is handled automatically.
   - The response will include conferenceData.entryPoints with the Google Meet link
   - Extract the meet_link from conferenceData.entryPoints[0].uri in the response

3. **Log to Google Sheets:**
   - First, use google_sheets_get_spreadsheet with spreadsheet_id="Meeting Scheduler" to check if it exists
   - If it doesn't exist, use google_sheets_create_spreadsheet with title="Meeting Scheduler"
   - Then use google_sheets_append_values to add a row with:
     - Date, Time, Attendee Email, Meeting Title, Google Meet Link
   - The spreadsheet_id should be "Meeting Scheduler" (by name) or the ID returned from create

4. **Send confirmation email:**
   - Use send_email to send the attendee a confirmation with:
     - to: attendee email address
     - subject: "Meeting Confirmation: {meeting_title}"
     - body: Include meeting title, date/time, and Google Meet link

## STEP 2 — set_output (SEPARATE turn, no other tool calls):

After all tools complete successfully, call set_output:
- set_output("meeting_time", "YYYY-MM-DD HH:MM")
- set_output("meet_link", "https://meet.google.com/xxx/yyy")
- set_output("booking_confirmed", "true")
- set_output("spreadsheet_recorded", "true")
- set_output("email_sent", "true")

## CRITICAL: Google Meet creation
Google Meet links are AUTOMATICALLY created by calendar_create_event when attendees are provided.
Simply pass the attendees list and the tool will generate the Meet link.
""",
    tools=[
        "calendar_check_availability",
        "calendar_create_event",
        "calendar_list_events",
        "google_sheets_create_spreadsheet",
        "google_sheets_get_spreadsheet",
        "google_sheets_append_values",
        "send_email",
    ],
)

# Node 3: Confirm (client-facing)
confirm_node = NodeSpec(
    id="confirm",
    name="Confirm",
    description="Present booking confirmation to user with Google Meet link",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["meeting_time", "booking_confirmed", "meet_link"],
    output_keys=["next_action"],
    nullable_output_keys=["next_action"],
    success_criteria="User has acknowledged the booking and received the Google Meet link.",
    system_prompt="""\
You are a confirmation assistant.

**STEP 1 — Present confirmation and ask user:**
1. Show the meeting details (date, time, attendee, title)
2. Display the Google Meet link prominently
3. Confirm the booking is complete and logged to Google Sheets
4. Call ask_user to ask if they want to schedule another meeting or finish

**STEP 2 — After user responds, call set_output:**
- set_output("next_action", "another") — if booking another meeting
- set_output("next_action", "done")  — if finished
""",
    tools=[],
)

__all__ = ["intake_node", "schedule_node", "confirm_node"]
