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
    max_node_visits=0,
    input_keys=["topic"],
    output_keys=["research_brief"],
    success_criteria=(
        "The research brief is specific and actionable: it states the topic, "
        "the key questions to answer, the desired scope, and depth."
    ),
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

Context management:
- Your tool results are automatically saved to files. After compaction, the file \
references remain in the conversation — use load_data() to recover any content you need.
- Use append_data('research_notes.md', ...) to maintain a running log of key findings \
as you go. This survives compaction and helps the report node produce a detailed report.

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
    description="Present findings to user and decide whether to research more or write the report",
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
# Writes an HTML report, serves the link to the user, and answers follow-ups.
report_node = NodeSpec(
    id="report",
    name="Write & Deliver Report",
    description="Write a cited HTML report from the findings and present it to the user",
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
Write a research report as an HTML file and present it to the user.

**CRITICAL: You MUST build the file in multiple append_data calls. NEVER try to write the \
entire HTML in a single save_data call — it will exceed the output token limit and fail.**

IMPORTANT: save_data and append_data require TWO separate arguments: filename and data.
Call like: save_data(filename="report.html", data="<html>...")
Do NOT use _raw, do NOT nest arguments inside a JSON string.
Do NOT include data_dir in tool calls — it is auto-injected.

**PROCESS (follow exactly):**

**Step 1 — Write HTML head + executive summary (save_data):**
Call save_data to create the file with the HTML head, CSS, title, and executive summary.
```
save_data(filename="report.html", data="<!DOCTYPE html>\\n<html>...")
```

Include: DOCTYPE, head with ALL styles below, opening body, h1 title, date, and the \
executive summary (2-3 paragraphs). End after the executive summary section.

**CSS to use (copy exactly):**
```
body{font-family:Georgia,'Times New Roman',serif;max-width:800px;margin:0 auto;\
padding:40px;line-height:1.8;color:#333}
h1{font-size:1.8em;color:#1a1a1a;border-bottom:2px solid #333;padding-bottom:10px}
h2{font-size:1.4em;color:#1a1a1a;margin-top:40px;padding-top:20px;\
border-top:1px solid #ddd}
h3{font-size:1.1em;color:#444;margin-top:25px}
p{margin:12px 0}
.date{color:#666;font-size:0.95em;margin-bottom:30px}
.executive-summary{background:#f8f9fa;padding:25px;border-radius:8px;\
margin:25px 0;border-left:4px solid #333}
.finding-section{margin:20px 0}
.citation{color:#1a73e8;text-decoration:none;font-size:0.85em}
.citation:hover{text-decoration:underline}
.analysis{background:#fff;padding:20px 0}
.references{margin-top:40px;padding-top:20px;border-top:2px solid #333}
.references ol{padding-left:20px}
.references li{margin:8px 0;font-size:0.95em}
.references a{color:#1a73e8;text-decoration:none}
.references a:hover{text-decoration:underline}
.footer{text-align:center;color:#999;border-top:1px solid #ddd;\
padding-top:20px;margin-top:50px;font-size:0.85em;font-family:sans-serif}
```

**Step 2 — Append key findings (append_data):**
```
append_data(filename="report.html", data="<h2>Key Findings</h2>...")
```

Organize findings by theme. Use [n] citation notation for every factual claim. \
Pattern per theme:
```
<div class="finding-section">
  <h3>{Theme Name}</h3>
  <p>{Finding text with <a class="citation" href="#ref-n">[n]</a> citations}</p>
</div>
```

**Step 3 — Append analysis + conclusion (append_data):**
```
append_data(filename="report.html", data="<h2>Analysis</h2>...")
```

Include: synthesis of findings, implications, and a Conclusion section with key \
takeaways. Be objective — present multiple viewpoints where sources disagree.

**Step 4 — Append references + footer (append_data):**
```
append_data(filename="report.html", data="<div class='references'>...")
```

Include: numbered reference list with clickable URLs, then footer, then \
`</body></html>`. Pattern:
```
<div class="references">
  <h2>References</h2>
  <ol>
    <li id="ref-1"><a href="{url}" target="_blank">{title}</a> — {source}</li>
  </ol>
</div>
```

**Step 5 — Serve the file:**
```
serve_file_to_user(filename="report.html", label="Research Report", open_in_browser=true)
```

**Step 6 — Present to user (text only, NO tool calls):**
**CRITICAL: Print the file_path from the serve_file_to_user result in your response** \
so the user can click it to reopen the report later. Give a brief summary of what the \
report covers. Ask if they have questions.

**Step 7 — After the user responds:**
- Answer any follow-up questions from the research material
- When the user is ready to move on, ask what they'd like to do next:
  - Research a new topic?
  - Dig deeper into the current topic?
- Then call set_output:
  - set_output("delivery_status", "completed")
  - set_output("next_action", "new_topic")       — if they want a new topic
  - set_output("next_action", "more_research")   — if they want deeper research

**IMPORTANT:**
- Every factual claim MUST cite its source with [n] notation
- Answer the original research questions from the brief
- If an append_data call fails with a truncation error, break it into smaller chunks
- If findings appear incomplete or summarized, call list_data_files() and load_data() \
to access the detailed source material from the research phase. The research node's \
tool results and research_notes.md contain the full data.
""",
    tools=[
        "save_data",
        "append_data",
        "serve_file_to_user",
        "load_data",
        "list_data_files",
    ],
)

__all__ = [
    "intake_node",
    "research_node",
    "review_node",
    "report_node",
]
