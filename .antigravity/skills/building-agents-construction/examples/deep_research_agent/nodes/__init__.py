"""Node definitions for Deep Research Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Brief conversation to clarify what the user wants researched.
intake_node = NodeSpec(
    id="intake",
    name="Research Intake",
    description="Discuss the research topic with the user, clarify scope, and confirm direction",
    node_type="event_loop",
    client_facing=True,
    input_keys=["topic"],
    output_keys=["research_brief"],
    system_prompt="""\
You are a research intake specialist. The user wants to research a topic.
Have a brief conversation to clarify what they need.

**STEP 1 — Read and respond (text only, NO tool calls):**
1. Read the topic provided
2. If it's vague, ask 1-2 clarifying questions (scope, angle, depth)
3. If it's already clear, confirm your understanding and ask the user to confirm

Keep it short. Don't over-ask.

**STEP 2 — After the user confirms, call set_output:**
- set_output("research_brief", "A clear paragraph describing exactly what to research, \
what questions to answer, what scope to cover, and how deep to go.")
""",
    tools=[],
)

# Node 2: Research
# The workhorse — searches the web, fetches content, analyzes sources.
# One node with both tools avoids the context-passing overhead of 5 separate nodes.
research_node = NodeSpec(
    id="research",
    name="Research",
    description="Search the web, fetch source content, and compile findings",
    node_type="event_loop",
    max_node_visits=3,
    input_keys=["research_brief", "feedback"],
    output_keys=["findings", "sources", "gaps"],
    nullable_output_keys=["feedback"],
    system_prompt="""\
You are a research agent. Given a research brief, find and analyze sources.

If feedback is provided, this is a follow-up round — focus on the gaps identified.

Work in phases:
1. **Search**: Use web_search with 3-5 diverse queries covering different angles.
   Prioritize authoritative sources (.edu, .gov, established publications).
2. **Fetch**: Use web_scrape on the most promising URLs (aim for 5-8 sources).
   Skip URLs that fail. Extract the substantive content.
3. **Analyze**: Review what you've collected. Identify key findings, themes,
   and any contradictions between sources.

Important:
- Work in batches of 3-4 tool calls at a time to manage context
- After each batch, assess whether you have enough material
- Prefer quality over quantity — 5 good sources beat 15 thin ones
- Track which URL each finding comes from (you'll need citations later)

When done, use set_output:
- set_output("findings", "Structured summary: key findings with source URLs for each claim. \
Include themes, contradictions, and confidence levels.")
- set_output("sources", [{"url": "...", "title": "...", "summary": "..."}])
- set_output("gaps", "What aspects of the research brief are NOT well-covered yet, if any.")
""",
    tools=["web_search", "web_scrape", "load_data", "save_data", "list_data_files"],
)

# Node 3: Review (client-facing)
# Shows the user what was found and asks whether to dig deeper or proceed.
review_node = NodeSpec(
    id="review",
    name="Review Findings",
    description="Present findings to user and decide whether to research more or write the report",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=3,
    input_keys=["findings", "sources", "gaps", "research_brief"],
    output_keys=["needs_more_research", "feedback"],
    system_prompt="""\
Present the research findings to the user clearly and concisely.

**STEP 1 — Present (your first message, text only, NO tool calls):**
1. **Summary** (2-3 sentences of what was found)
2. **Key Findings** (bulleted, with confidence levels)
3. **Sources Used** (count and quality assessment)
4. **Gaps** (what's still unclear or under-covered)

End by asking: Are they satisfied, or do they want deeper research? \
Should we proceed to writing the final report?

**STEP 2 — After the user responds, call set_output:**
- set_output("needs_more_research", "true")  — if they want more
- set_output("needs_more_research", "false") — if they're satisfied
- set_output("feedback", "What the user wants explored further, or empty string")
""",
    tools=[],
)

# Node 4: Report (client-facing)
# Writes the final report and presents it to the user.
report_node = NodeSpec(
    id="report",
    name="Write & Deliver Report",
    description="Write a cited report from the findings and present it to the user",
    node_type="event_loop",
    client_facing=True,
    input_keys=["findings", "sources", "research_brief"],
    output_keys=["delivery_status"],
    system_prompt="""\
Write a comprehensive research report and present it to the user.

**STEP 1 — Write and present the report (text only, NO tool calls):**

Report structure:
1. **Executive Summary** (2-3 paragraphs)
2. **Findings** (organized by theme, with [n] citations)
3. **Analysis** (synthesis, implications, areas of debate)
4. **Conclusion** (key takeaways, confidence assessment)
5. **References** (numbered list of sources cited)

Requirements:
- Every factual claim must cite its source with [n] notation
- Be objective — present multiple viewpoints where sources disagree
- Distinguish well-supported conclusions from speculation
- Answer the original research questions from the brief

End by asking the user if they have questions or want to save the report.

**STEP 2 — After the user responds:**
- Answer follow-up questions from the research material
- If they want to save, use write_to_file tool
- When the user is satisfied: set_output("delivery_status", "completed")
""",
    tools=["write_to_file"],
)

__all__ = [
    "intake_node",
    "research_node",
    "review_node",
    "report_node",
]
