"""Node definitions for SDR Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Receives contact list and outreach goal, confirms with user before proceeding.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description=(
        "Receive the contact list and outreach goal from the user. "
        "Confirm the strategy and batch size before proceeding."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["contacts", "outreach_goal", "max_contacts", "user_background"],
    output_keys=["contacts", "outreach_goal", "max_contacts", "user_background"],
    system_prompt="""\
You are an SDR (Sales Development Representative) assistant helping automate outreach.

**STEP 1 — Respond to the user (text only, NO tool calls):**

Read the user's input from context. Confirm your understanding of:
- The contact list they provided (or ask them to provide one)
- Their outreach goal (e.g. "coffee chat", "sales pitch", "networking")
- Their background/role (used to personalize messages)
- The batch size (max_contacts). Default to 20 if not specified.

Present a summary like:
"Here's what I'll do:
1. Score and rank your contacts by priority (alumni status, connection degree, etc.)
2. Filter out suspicious or low-quality profiles (risk score ≥ 7)
3. Generate a personalized outreach message for each contact
4. Create Gmail draft emails for your review — I never send automatically

Ready to proceed with [N] contacts for [goal]?"

**STEP 2 — After the user confirms, call set_output:**

- set_output("contacts", <the contact list as a JSON string>)
- set_output("outreach_goal", <the confirmed goal, e.g. "coffee chat">)
- set_output("max_contacts", <the confirmed batch size as a string, e.g. "20">)
- set_output("user_background", <user's background/role, e.g. "Learning Technologist at UWO">)
""",
    tools=[],
)

# Node 2: Score Contacts
# Ranks contacts 0-100 based on alumni status, connection degree, domain, etc.
score_contacts_node = NodeSpec(
    id="score-contacts",
    name="Score Contacts",
    description=(
        "Score and rank each contact from 0 to 100 based on priority factors: "
        "alumni status, connection degree, domain verification, mutual connections, "
        "and active job postings."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["contacts", "outreach_goal"],
    output_keys=["scored_contacts"],
    system_prompt="""\
You are a contact prioritization engine. Score each contact from 0 to 100.

**SCORING RULES (additive):**
- Alumni of the user's school: +30 points
- 1st degree connection: +25 points
- 2nd degree connection: +20 points
- 3rd degree connection: +10 points
- Domain verified (company email matches LinkedIn company): +10 points
- Has mutual connections (1 point each, max 10): up to +10 points
- Active job posting at their company: +10 points
- Has a profile photo: +5 points
- Over 500 connections: +5 points

Cap the final score at 100.

**STEP 1 — Load the contacts:**
Call load_data(filename="contacts.jsonl") to read the contact list.
If "contacts" in context is a JSON string (not a filename), write it first:
- For each contact in the list, call append_data(filename="contacts.jsonl", data=<JSON contact object>)
Then read it back.

**STEP 2 — Score each contact:**
For each contact, calculate the priority score using the rules above.
Add a "priority_score" field to each contact object.

**STEP 3 — Write scored contacts and set output:**
- Call append_data(filename="scored_contacts.jsonl", data=<JSON contact with priority_score>) for each contact.
- Sort contacts by priority_score (highest first) in your final output.
- Call set_output("scored_contacts", "scored_contacts.jsonl")
""",
    tools=["load_data", "append_data"],
)

# Node 3: Filter Contacts (Scam Detection)
# Filters out suspicious or fake profiles using a risk scoring system.
filter_contacts_node = NodeSpec(
    id="filter-contacts",
    name="Filter Contacts",
    description=(
        "Analyze each contact for authenticity and filter out suspicious profiles. "
        "Any contact with a risk score of 7 or higher is skipped."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["scored_contacts"],
    output_keys=["safe_contacts", "filtered_count"],
    system_prompt="""\
You are a profile authenticity analyzer. Your job is to detect suspicious or fake LinkedIn profiles.

**RISK SCORING RULES (additive):**
- Fewer than 50 connections: +3 points
- No profile photo: +2 points
- Fewer than 2 positions in work history: +2 points
- Generic title (e.g. "entrepreneur", "CEO", "consultant") AND fewer than 100 connections: +2 points
- Company name appears generic or unverifiable: +2 points
- Profile text seems auto-generated or overly promotional: +2 points
- Connection count over 5000 with no mutual connections: +1 point

**DECISION RULE:**
- risk_score < 4: SAFE — include in outreach
- risk_score 4–6: CAUTION — include but flag
- risk_score ≥ 7: SKIP — exclude from outreach

**STEP 1 — Load scored contacts:**
Call load_data(filename=<the "scored_contacts" value from context>).
Process contacts chunk by chunk if has_more=true.

**STEP 2 — Analyze each contact:**
For each contact, calculate a risk_score using the rules above.
Determine: is_safe (risk_score < 7), recommendation (safe/caution/skip), flags (list of triggered rules).

**STEP 3 — Write safe contacts and set output:**
- For each contact where risk_score < 7: call append_data(filename="safe_contacts.jsonl", data=<contact JSON with risk_score and flags added>)
- Track how many contacts were filtered (risk_score ≥ 7)
- Call set_output("safe_contacts", "safe_contacts.jsonl")
- Call set_output("filtered_count", <number of skipped contacts as string>)
""",
    tools=["load_data", "append_data"],
)

# Node 4: Personalize Messages
# Generates personalized outreach messages for each safe contact.
personalize_node = NodeSpec(
    id="personalize",
    name="Personalize",
    description=(
        "Generate a personalized outreach message for each contact based on "
        "their profile, shared background, and the user's outreach goal."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["safe_contacts", "outreach_goal", "user_background"],
    output_keys=["personalized_contacts"],
    system_prompt="""\
You are a professional outreach message writer. Generate personalized messages for each contact.

**TWO-STEP PERSONALIZATION:**

For each contact, follow this two-step approach:

STEP A — Extract hooks (analyze the profile):
Look for 2-3 specific talking points from the contact's profile:
- Shared alumni connection
- Specific role, company, or career transition worth mentioning
- Any mutual interests aligned with the user's background

STEP B — Generate the message:
Write a warm, professional outreach message using the hooks.

**MESSAGE REQUIREMENTS:**
- 80-120 words (LinkedIn message length)
- Start with a specific observation ("I noticed you..." or "Fellow [school] alum here...")
- Mention the shared connection or interest naturally
- State the outreach goal clearly but softly (e.g. "Open to a brief 15-min chat?")
- Professional but warm tone — NOT templated or AI-sounding
- Do NOT mention job postings directly unless the goal is job-related
- Do NOT use generic openers like "I hope this finds you well"
- End with a low-pressure ask

**STEP 1 — Load safe contacts:**
Call load_data(filename=<the "safe_contacts" value from context>).

**STEP 2 — Generate message for each contact:**
For each contact: generate the personalized message using the two-step approach above.
Add "outreach_message" field to each contact object.

**STEP 3 — Write output and set:**
- Call append_data(filename="personalized_contacts.jsonl", data=<contact JSON with outreach_message>) for each.
- Call set_output("personalized_contacts", "personalized_contacts.jsonl")
""",
    tools=["load_data", "append_data"],
)

# Node 5: Send Outreach (Create Gmail Drafts)
# Creates Gmail draft emails for each personalized contact. Never sends automatically.
send_outreach_node = NodeSpec(
    id="send-outreach",
    name="Send Outreach",
    description=(
        "Create Gmail draft emails for each contact using their personalized message. "
        "Drafts are created for human review — emails are never sent automatically."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["personalized_contacts", "outreach_goal"],
    output_keys=["drafts_created"],
    system_prompt="""\
You are an outreach execution assistant. Create Gmail draft emails for each contact.

**CRITICAL RULE: NEVER send emails automatically. Only create drafts.**

**STEP 1 — Load personalized contacts:**
Call load_data(filename=<the "personalized_contacts" value from context>).
Process chunk by chunk if has_more=true.

**STEP 2 — Create Gmail draft for each contact:**
For each contact with an "outreach_message":
- subject: "Coffee Chat Request" (or appropriate subject based on outreach_goal)
- to: contact's email address (use LinkedIn profile URL if email not available — note this in body)
- body: the "outreach_message" from the contact object

Call gmail_create_draft(
    to=<contact email or linkedin_url as placeholder>,
    subject=<appropriate subject line>,
    body=<outreach_message>
)

Record each draft: call append_data(
    filename="drafts.jsonl",
    data=<JSON: {contact_name, contact_email, subject, status: "draft_created"}>
)

**STEP 3 — Set output:**
- Call set_output("drafts_created", "drafts.jsonl")

**IMPORTANT:** If a contact has no email address, create the draft with their LinkedIn URL as a placeholder
and add a note in the body: "Note: Please find the recipient's email before sending."
""",
    tools=["gmail_create_draft", "load_data", "append_data"],
)

# Node 6: Report (client-facing)
# Summarizes results and presents to user for review.
report_node = NodeSpec(
    id="report",
    name="Report",
    description=(
        "Generate a summary report of the outreach campaign: contacts scored, "
        "filtered, messaged, and drafts created. Present to user for review."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["drafts_created", "filtered_count", "outreach_goal"],
    output_keys=["summary_report"],
    system_prompt="""\
You are an SDR assistant. Generate a clear campaign summary report and present it to the user.

**STEP 1 — Load draft records:**
Call load_data(filename=<the "drafts_created" value from context>) to read the draft records.
If has_more=true, load additional chunks until all records are loaded.

**STEP 2 — Present the report (text only, NO tool calls):**

Present a clean summary:

📊 **SDR Campaign Summary — [outreach_goal]**

**Overview:**
- Total contacts processed: [N]
- Contacts filtered (suspicious profiles): [filtered_count]
- Safe contacts messaged: [N - filtered_count]
- Gmail drafts created: [N]

**Drafts Created:**
List each draft: Contact Name | Company | Subject

**Next Steps:**
"Your Gmail drafts are ready for review. Please:
1. Open Gmail and review each draft
2. Personalize further if needed
3. Send when ready

Would you like to run another outreach batch or adjust the strategy?"

**STEP 3 — After the user responds, call set_output:**
- set_output("summary_report", <the formatted report text>)
""",
    tools=["load_data"],
)

__all__ = [
    "intake_node",
    "score_contacts_node",
    "filter_contacts_node",
    "personalize_node",
    "send_outreach_node",
    "report_node",
]
