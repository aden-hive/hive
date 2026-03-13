"""Node definitions for SDR Agent."""

from framework.graph import NodeSpec

# ---------------------------------------------------------------------------
# Node 1: Research the Prospect
# ---------------------------------------------------------------------------
research_node = NodeSpec(
    id="research-prospect",
    name="Research Prospect",
    description="Research the prospect's company, recent news, and role to gather context.",
    node_type="llm_generate",
    input_keys=["company_name", "prospect_name", "prospect_role"],
    output_keys=["research_summary", "company_context"],
    system_prompt="""\
You are an expert Sales Researcher. Your goal is to gather relevant information about a prospect and their company to enable hyper-personalized outreach.

Prospect: {prospect_name} ({prospect_role})
Company: {company_name}

Perform a deep analysis using your tools (or mock knowledge if tools unavailable) to find:
1. What the company does and their target market.
2. Recent news, funding, or product launches (last 6 months).
3. Potential pain points consistent with their industry and stage.
4. Relevance of the prospect's role to purchasing decisions.

Output as raw JSON (no markdown):
{{
  "research_summary": {{
    "industry": "...",
    "key_findings": ["..."],
    "recent_news": "...",
    "pain_points": ["..."]
  }},
  "company_context": "Detailed summary..."
}}
""",
    tools=["web_search"],  # Ideally uses the web search tool
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 2: Qualify Lead
# ---------------------------------------------------------------------------
qualify_node = NodeSpec(
    id="qualify-lead",
    name="Qualify Lead",
    description="Evaluate if the prospect matches the Ideal Customer Profile (ICP) based on research.",
    node_type="llm_generate",
    input_keys=["research_summary", "icp_criteria"],
    output_keys=["is_qualified", "qualification_reason", "score"],
    system_prompt="""\
You are a Lead Qualification Expert. Evaluate if the prospect is a good fit.

Research: {research_summary}
ICP Criteria: {icp_criteria}

Determine if this prospect is worth pursuing.
- Score from 0-100.
- Provide a clear reason for qualification or disqualification.

Output as raw JSON (no markdown):
{{
  "is_qualified": true,
  "score": 85,
  "qualification_reason": "Matches size and industry criteria..."
}}
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 3: Generate Outreach
# ---------------------------------------------------------------------------
outreach_node = NodeSpec(
    id="generate-outreach",
    name="Generate Outreach",
    description="Draft a personalized email sequence for qualified leads.",
    node_type="llm_generate",
    input_keys=["prospect_name", "research_summary", "value_proposition", "sender_name"],
    output_keys=["email_draft", "subject_line"],
    system_prompt="""\
You are a world-class SDR copywriter. Write a personalized cold email to the prospect.

Prospect: {prospect_name}
Research: {research_summary}
Our Value Prop: {value_proposition}
Sender: {sender_name}

Guidelines:
- Keep it under 150 words.
- Focus on THEIR problems, not just our features.
- unexpected, personal opening based on the research.
- Clear Call to Action (CTA).

Output as raw JSON (no markdown):
{{
  "subject_line": "...",
  "email_draft": "Hi {prospect_name},\n\n..."
}}
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 4: Review Draft (HITL)
# ---------------------------------------------------------------------------
review_node = NodeSpec(
    id="review-draft",
    name="Review Email Draft",
    description="Human review of the generated email draft before sending.",
    node_type="human_input",
    input_keys=["email_draft", "prospect_name"],
    output_keys=["feedback", "approved"],
    system_prompt="""
Please review the generated email draft for {prospect_name}.
Draft:
{email_draft}

Do you approve this draft? (yes/no)
If no, provide feedback for regeneration.
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Node 5: Send Email & Update CRM
# ---------------------------------------------------------------------------
send_node = NodeSpec(
    id="send-email",
    name="Send Email & CRM Update",
    description="Simulate sending the email and updating the CRM status.",
    node_type="llm_generate",
    input_keys=["email_draft", "prospect_name", "approved"],
    output_keys=["crm_status", "delivery_status"],
    system_prompt="""
You are a CRM Integration System.
Action: Send Email and Update Status.

Prospect: {prospect_name}
Email Status: {approved} (If not approved, do not send)

1. If approved: Simulate sending the email.
2. Update CRM status to "Outreach Sent".
3. Log the timestamp.

Output as raw JSON:
{{
  "crm_status": "Outreach Sent",
  "delivery_status": "Sent",
  "timestamp": "2024-..."
}}
""",
    tools=[],
    max_retries=2,
)

# All nodes for easy import
all_nodes = [
    research_node,
    qualify_node,
    outreach_node,
    review_node,
    send_node,
]
