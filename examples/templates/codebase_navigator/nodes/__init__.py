"""Node definitions for Codebase Navigator Agent."""

from __future__ import annotations

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Codebase Intake",
    description="Ask what the user wants to understand about the codebase",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["question"],
    output_keys=["question"],
    nullable_input_keys=["question"],
    success_criteria="A clear, specific question about the codebase has been captured.",
    system_prompt="""\
You are a codebase navigation specialist. The user wants to understand an unfamiliar codebase.

**STEP 1 — Respond with text only, NO tool calls:**
1. If question is already provided (e.g. from run --question), confirm it and proceed
2. Otherwise ask: "What would you like to understand about this codebase?" (entry points, config, a module, dependencies, etc.)
3. Keep it short. Don't over-ask.

**STEP 2 — After you have a clear question, call set_output:**
- set_output("question", "<the user's question about the codebase>")
""",
    tools=[],
)

# Node 2: Explore
explore_node = NodeSpec(
    id="explore",
    name="Explore Structure",
    description="Map the repository structure using list_dir",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["question"],
    output_keys=["structure"],
    success_criteria="Directory layout of root and key dirs (src, lib, app, etc.) has been captured.",
    system_prompt="""\
You are mapping the codebase structure. Use the list_dir tool to explore.

**Strategy:**
1. List the root directory (path=".") to see top-level layout
2. List common dirs if they exist: src, lib, app, packages, core, etc.
3. Build a JSON-like summary of the structure: which dirs exist, what they likely contain

**Rules:**
- Work in batches of 2-4 list_dir calls per turn
- Paths are relative to the workspace root (e.g. ".", "src", "lib")
- Don't recurse exhaustively — focus on the layout the user needs

**When done, call set_output:**
- set_output("structure", "<JSON summary of dir layout: root and key subdirs>")
""",
    tools=["list_dir"],
)

# Node 3: Search
search_node = NodeSpec(
    id="search",
    name="Search for Relevant Files",
    description="Use grep_search to find files matching the question",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["question", "structure"],
    output_keys=["candidate_files"],
    success_criteria="A list of relevant file paths has been identified for the question.",
    system_prompt="""\
You are searching the codebase for files relevant to the user's question.

**Inputs:**
- question: What the user wants to understand
- structure: The dir layout from explore

**Strategy:**
1. Derive grep patterns from the question
2. Use grep_search with path="." and recursive=True for broad search
3. Narrow with path="src" or similar if structure suggests it
4. Collect the most relevant file paths (limit to ~10-15)

**When done, call set_output:**
- set_output("candidate_files", ["path/to/file1", "path/to/file2", ...])
""",
    tools=["grep_search"],
)

# Node 4: Synthesize
synthesize_node = NodeSpec(
    id="synthesize",
    name="Synthesize Answer",
    description="Read candidate files with view_file and produce a summary with citations",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["candidate_files", "question"],
    output_keys=["answer", "sources"],
    success_criteria="Answer includes file:line citations for key information. Sources are listed.",
    system_prompt="""\
You are synthesizing an answer from the codebase. Use the view_file tool.

**Strategy:**
1. Read the candidate files (up to ~8 files; prioritize by relevance)
2. Extract the information that answers the user's question
3. For each key fact, cite the source as [file:line] or [path:line]
4. Produce a clear summary with bullet points or sections

**When done, call set_output (one key per call):**
- set_output("answer", "<structured summary with [file:line] citations>")
- set_output("sources", [{"path": "...", "lines": [...], "summary": "..."}])
""",
    tools=["view_file"],
)

# Node 5: Deliver (client-facing)
deliver_node = NodeSpec(
    id="deliver",
    name="Deliver Report",
    description="Builds an HTML report and serves it to the user. Run ends here.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["answer", "sources", "question", "structure"],
    output_keys=["report_served"],
    nullable_input_keys=["structure"],
    success_criteria="HTML report saved and served. Run ends; no prompt for next action.",
    system_prompt="""\
Deliver the codebase report to the user. You are the FINAL node — the run ends when you complete.

**CRITICAL: You MUST build the file in multiple append_data calls. NEVER try to write the \
entire HTML in a single save_data call — it will exceed the output token limit and fail.**

IMPORTANT: save_data and append_data require TWO separate arguments: filename and data.
Call like: save_data(filename="codebase_report.html", data="<html>...")
Do NOT use _raw, do NOT nest arguments inside a JSON string.
Do NOT include data_dir in tool calls — it is auto-injected.

**PROCESS (follow exactly):**

**Step 1 — Write HTML head + executive summary (save_data):**
Call save_data to create the file with the HTML head, CSS, title, and the user's question.
```
save_data(filename="codebase_report.html", data="<!DOCTYPE html>\\n<html>...")
```

Include: DOCTYPE, head with ALL styles below, Mermaid script \
`<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>`, \
opening body, h1 title "Codebase Report", date, and the user's question in an \
executive-summary block. End after the question.

**CSS to use (copy exactly — same as deep_research_agent):**
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
.references{margin-top:40px;padding-top:20px;border-top:2px solid #333}
.references ol{padding-left:20px}
.references li{margin:8px 0;font-size:0.95em}
.references a{color:#1a73e8;text-decoration:none}
.references a:hover{text-decoration:underline}
.structure-block{background:#f5f5f5;padding:16px;border-radius:6px;font-family:monospace;\
font-size:0.85em;overflow-x:auto;margin:20px 0;white-space:pre-wrap}
.mermaid{margin:24px 0;text-align:center}
.footer{text-align:center;color:#999;border-top:1px solid #ddd;\
padding-top:20px;margin-top:50px;font-size:0.85em;font-family:sans-serif}
```

**Step 2 — Append answer (append_data):**
```
append_data(filename="codebase_report.html", data="<h2>Answer</h2>...")
```
Use finding-section pattern. Include the full synthesized answer with [file:line] citations.
```
<div class="finding-section">
  <p>{answer text with <a class="citation" href="#ref-1">[path:line]</a> citations}</p>
</div>
```

**Step 3 — Append sources (append_data):**
```
append_data(filename="codebase_report.html", data="<div class='references'>...")
```
Pattern:
```
<div class="references">
  <h2>Sources</h2>
  <ol>
    <li id="ref-1"><strong>{path}</strong> (lines {lines}) — {summary}</li>
  </ol>
</div>
```

**Step 4 — Append diagram + structure + footer (append_data):**
```
append_data(filename="codebase_report.html", data="<h2>Diagram</h2>...")
```
Include: (a) a Mermaid diagram for whatever flows need description given the question.

The diagram should visualize the flows, processes, or relationships the answer describes — \
e.g. entry-point flow, auth flow, config loading, module dependencies, data pipeline. \
Choose the diagram type that fits: flowchart (processes), graph (dependencies), sequence (calls).

Examples: `flowchart LR` for config→load→use; `flowchart TB` for entry→router→handlers; \
`graph LR` for A-->B-->C dependencies. Keep it focused on what the user asked about.

Mermaid pattern:
```
<div class="mermaid">
flowchart LR
  A[entry] --> B[router]
  B --> C[handler]
</div>
```
Then add `<h2>Structure</h2>` and `<pre class="structure-block">` with dir layout. End with \
`<script>mermaid.initialize({startOnLoad:true});</script>` and \
`<div class="footer">Codebase Report</div></body></html>`.

**Step 5 — Serve the file:**
```
serve_file_to_user(filename="codebase_report.html", label="Codebase Report", open_in_browser=true)
```
**CRITICAL: Print the file_path from the serve_file_to_user result in your response.**

**Step 6 — Done:**
Say "Your report is ready." Then call set_output("report_served", True)
Do NOT ask what the user wants to do next.

**If an append_data call fails with a truncation error, break it into smaller chunks.**
""",
    tools=["save_data", "append_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "explore_node",
    "search_node",
    "synthesize_node",
    "deliver_node",
]
