"""Node definitions for the B2B Sales Prospecting & Outreach Agent."""

from core.framework.graph import NodeSpec


# =========================
# Node 1: Intake (client-facing)
# =========================
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect target audience, value proposition, and outreach goals from the user",
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["target_audience", "value_proposition", "outreach_goals"],
    system_prompt="""\
You are a B2B Sales Intake assistant. Your goal is to gather the necessary information to start a prospecting campaign.

**STEP 1 — Respond to the user (text only, NO tool calls):**
Ask the user for the following information:
1. **Target Audience**: Who are we looking for?
2. **Value Proposition**: What are we offering? Why should they care?
3. **Outreach Goals**: What is the desired outcome?

Be professional and helpful. If the user provides partial info, ask for the missing pieces.

**STEP 2 — After the user provides the information, call set_output:**
- set_output("target_audience", "<detailed target audience>")
- set_output("value_proposition", "<clear value proposition>")
- set_output("outreach_goals", "<specific goals>")
""",
    tools=[],
)


# =========================
# Node 2: Lead Search
# =========================
lead_search_node = NodeSpec(
    id="lead_search",
    name="Lead Search",
    description="Search for B2B leads using Apollo based on the target audience",
    node_type="event_loop",
    input_keys=["target_audience"],
    output_keys=["leads_list"],
    system_prompt="""\
You are a Lead Generation Specialist. Your task is to find high-quality B2B leads.

1. Use the `apollo_search_people` tool to find individuals matching the target audience.
2. Consider job title, company size, industry, and location if specified.
3. Extract name, title, company, and contact info (if available) for up to 5 leads.
4. Compile the leads into a structured list.

If the `apollo_search_people` tool is unavailable or returns no results,
generate 3 realistic mock leads for testing purposes.

Each mock lead must include:
- name
- title
- company
- placeholder email address (e.g., name@company.com)

Clearly indicate that the leads are mock data for testing.

Use set_output("leads_list", <JSON string or structured list>) to store your findings.
""",
    tools=["apollo_search_people"],
)


# =========================
# Node 3: Company Research
# =========================
company_research_node = NodeSpec(
    id="company_research",
    name="Company Research",
    description="Research the companies of the identified leads to personalize outreach",
    node_type="event_loop",
    input_keys=["leads_list"],
    output_keys=["company_research_data"],
    system_prompt="""\
You are a Business Researcher. Your task is to find personalization hooks.

For each company in the `leads_list`:
1. Use `web_scrape` to understand their product, mission, and recent news.
2. Use `apollo_enrich_company` to get firmographic data.
3. Identify challenges relevant to our value proposition.

Compile a research summary for each company.

If `web_scrape` or `apollo_enrich_company` tools are unavailable,
generate reasonable mock research summaries based on company name,
industry, and common business challenges for testing purposes.

Clearly indicate that this is mock research data.

Use set_output("company_research_data", <detailed research summary>) to store your findings.
""",
    tools=["web_scrape", "apollo_enrich_company"],
)


# =========================
# Node 4: Draft Email
# =========================
draft_email_node = NodeSpec(
    id="draft_email",
    name="Draft Email",
    description="Draft personalized outreach emails for each lead",
    node_type="event_loop",
    input_keys=[
        "leads_list",
        "company_research_data",
        "value_proposition",
        "outreach_goals",
    ],
    output_keys=["email_drafts"],
    system_prompt="""\
You are an expert Sales Copywriter.

For each lead:
1. Use company research to create a personalized opening.
2. Clearly explain the value proposition.
3. Include a clear CTA based on outreach goals.
4. Keep emails concise, professional, and authentic.

Draft a complete email including subject line.

Use set_output("email_drafts", <JSON list of drafts>) to store the results.
""",
    tools=[],
)


# =========================
# Node 5: Human Approval (client-facing)
# =========================
human_approval_node = NodeSpec(
    id="human_approval",
    name="Human Approval",
    description="Present email drafts to the user for approval or feedback",
    node_type="event_loop",
    client_facing=True,
    input_keys=["email_drafts"],
    output_keys=["approved_emails"],
    system_prompt="""\
You are a Sales Coordinator.

STEP 1 — Present drafts to the user (text only):
Show the drafted emails and ask for approval or changes.

STEP 2 — If changes are requested:
Update drafts according to feedback.

STEP 3 — After approval:
set_output("approved_emails", <final approved emails>)
""",
    tools=[],
)


# =========================
# Node 6: Send Email
# =========================
send_email_node = NodeSpec(
    id="send_email",
    name="Send Email",
    description="Send the approved outreach emails",
    node_type="event_loop",
    input_keys=["approved_emails"],
    output_keys=["send_results"],
    system_prompt="""\
You are responsible for final email delivery.

For each approved email:
1. Use the `send_email` tool.
2. Ensure recipient, subject, and body are correct.

If the `send_email` tool is unavailable,
simulate sending and return a success status for testing purposes
without actually sending emails.

Use set_output("send_results", <delivery summary>) to store results.
""",
    tools=["send_email"],
)


__all__ = [
    "intake_node",
    "lead_search_node",
    "company_research_node",
    "draft_email_node",
    "human_approval_node",
    "send_email_node",
]
