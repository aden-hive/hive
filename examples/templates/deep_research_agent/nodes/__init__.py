"""Node definitions for Deep Research Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Brief conversation to clarify what the user wants researched.
intake_node = NodeSpec(
    id="intake",
    name="Research Intake",
    description="Clarify research scope and confirm direction",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["topic"],
    output_keys=["research_brief"],
    success_criteria=(
        "The research brief is specific and actionable: it states the topic, "
        "the key questions to answer, the desired scope, and depth."
    ),
    system_prompt="""\
You are a research intake specialist. Your job: quickly produce a research brief.

**STEP 1 — Assess the topic (text only, NO tool calls):**
- If clear and specific → state your interpretation in 1-2 sentences, ask user to confirm
- If genuinely ambiguous → ask 1-2 focused clarifying questions (scope, depth, angle)
- Do NOT ask questions when a reasonable interpretation exists

**STEP 2 — After confirmation, call set_output:**
- set_output("research_brief", "Topic, key questions, scope, and depth in 2-3 sentences")
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
    max_node_visits=0,
    input_keys=["research_brief", "feedback"],
    output_keys=["findings", "sources", "gaps"],
    nullable_output_keys=["feedback"],
    success_criteria=(
        "Findings reference at least 3 distinct sources with URLs. "
        "Key claims are substantiated by fetched content, not generated."
    ),
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
- Work in batches of 3-4 tool calls at a time — never more than 10 per turn
- After each batch, assess whether you have enough material
- Prefer quality over quantity — 5 good sources beat 15 thin ones
- Track which URL each finding comes from (you'll need citations later)
- Call set_output for each key in a SEPARATE turn (not in the same turn as other tool calls)

When done, use set_output (one key at a time, separate turns):
- set_output("findings", "Structured summary: key findings with source URLs for each claim. \
Include themes, contradictions, and confidence levels.")
- set_output("sources", [{"url": "...", "title": "...", "summary": "..."}])
- set_output("gaps", "What aspects of the research brief are NOT well-covered yet, if any.")
""",
    tools=[
        "web_search",
        "web_scrape",
        "load_data",
        "save_data",
        "append_data",
        "list_data_files",
    ],
)

# Node 3: Review (client-facing)
# Shows the user what was found and asks whether to dig deeper or proceed.
review_node = NodeSpec(
    id="review",
    name="Review Findings",
    description="Present findings and get user direction",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["findings", "sources", "gaps", "research_brief"],
    output_keys=["needs_more_research", "feedback"],
    success_criteria=(
        "The user has been presented with findings and has explicitly indicated "
        "whether they want more research or are ready for the report."
    ),
    system_prompt="""\
Present findings and ask for direction.

**STEP 1 — Present findings (text only, NO tool calls):**
Structure:
- **Summary**: 2-3 sentences of what was found
- **Key Findings**: bullet points with confidence levels
- **Sources**: count and quality
- **Gaps**: what's missing (if any)

Then ask: Ready for the report, or dig deeper?

**STEP 2 — After user responds, call set_output:**
- set_output("needs_more_research", "true" or "false")
- set_output("feedback", "What to explore further, or empty string")
""",
    tools=[],
)

# Node 4: Report (client-facing)
# Writes an HTML report, serves the link to the user, and answers follow-ups.
report_node = NodeSpec(
    id="report",
    name="Write & Deliver Report",
    description="Write cited HTML report and deliver to user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["findings", "sources", "research_brief"],
    output_keys=["delivery_status", "next_action"],
    success_criteria=(
        "An HTML report has been saved, the file link has been presented to the user, "
        "and the user has indicated what they want to do next."
    ),
    system_prompt="""\
Write and deliver a research report.

**CRITICAL: Build the file in multiple append_data calls, never one giant save_data.**

**PROCESS:**
1. **save_data** — HTML head + CSS + executive summary
2. **append_data** — Key findings with [n] citations
3. **append_data** — Analysis + conclusion
4. **append_data** — References list + footer
5. **serve_file_to_user** — filename="report.html"
6. **Text response** — Include the file_path, brief summary, ask if questions
7. **After user responds** — set_output("delivery_status", "completed") and set_output("next_action", "new_topic" or "more_research")

**CSS (copy exactly):**
body{font-family:Georgia,'Times New Roman',serif;max-width:800px;margin:0 auto;padding:40px;line-height:1.8;color:#333}
h1{font-size:1.8em;color:#1a1a1a;border-bottom:2px solid #333;padding-bottom:10px}
h2{font-size:1.4em;color:#1a1a1a;margin-top:40px;padding-top:20px;border-top:1px solid #ddd}
h3{font-size:1.1em;color:#444;margin-top:25px}
p{margin:12px 0}
.executive-summary{background:#f8f9fa;padding:25px;border-radius:8px;margin:25px 0;border-left:4px solid #333}
.finding-section{margin:20px 0}
.citation{color:#1a73e8;text-decoration:none;font-size:0.85em}
.references{margin-top:40px;padding-top:20px;border-top:2px solid #333}
.references ol{padding-left:20px}
.references li{margin:8px 0;font-size:0.95em}
.references a{color:#1a73e8;text-decoration:none}
.footer{text-align:center;color:#999;border-top:1px solid #ddd;padding-top:20px;margin-top:50px;font-size:0.85em}

**Citation format:** <a class="citation" href="#ref-n">[n]</a>
""",
    tools=["save_data", "append_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "research_node",
    "review_node",
    "report_node",
]
