"""Node definitions for Code Documentation Generator Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Collects the target project path and documentation preferences.
intake_node = NodeSpec(
    id="intake",
    name="Documentation Intake",
    description="Collect target project, language, and documentation preferences from the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["target"],
    output_keys=["doc_config"],
    success_criteria=(
        "A documentation configuration is produced with: target path/URL, "
        "primary language, documentation style (API ref / guide / both), "
        "and audience level (beginner / intermediate / advanced)."
    ),
    system_prompt="""\
You are a documentation intake specialist. The user wants to generate docs for their code.

**STEP 1 — Gather info (text only, NO tool calls):**
1. Read the target info provided
2. Ask what kind of documentation they want:
   - API Reference (function signatures, params, return types)
   - Architecture Overview (modules, dependencies, data flow)
   - Usage Guide (getting started, examples, tutorials)
   - All of the above
3. Ask who the audience is (team members, open source users, new developers)
4. Ask if there's anything they want to emphasize or skip

Keep it to 1-2 messages.

**STEP 2 — After the user confirms, call set_output:**
- set_output("doc_config", "JSON description: target, language, doc_type, audience, focus areas")
""",
    tools=[],
)

# Node 2: Code Analysis
# Parses the codebase to extract structure, APIs, and relationships.
code_analysis_node = NodeSpec(
    id="code_analysis",
    name="Code Analysis",
    description="Parse codebase structure, extract APIs, modules, and relationships",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["doc_config"],
    output_keys=["code_structure", "api_inventory", "architecture_map"],
    success_criteria=(
        "Complete inventory of modules, classes, functions with signatures. "
        "Dependency graph between modules is mapped. "
        "Public API surface is identified and documented."
    ),
    system_prompt="""\
You are a code analysis engine. Given a documentation config, parse the codebase
and extract all documentable elements.

**EXTRACT THE FOLLOWING:**

1. **Module Structure**
   - Directory tree with file purposes
   - Package/module hierarchy
   - Entry points (main, CLI, API endpoints)

2. **API Inventory** (for each public function/class/method):
   - Full signature (name, params with types, return type)
   - Docstring if present
   - Module path (e.g., framework.graph.executor.GraphExecutor)
   - Decorators and special attributes
   - Whether it's part of the public API

3. **Architecture Map**
   - Module dependency graph (who imports what)
   - Data flow between components
   - Key abstractions and design patterns used
   - Configuration points and extension mechanisms

4. **Code Patterns**
   - Common usage patterns found in examples/tests
   - Error handling conventions
   - Naming conventions

**PROCESS:**
1. Start with the project root — identify language, framework, and structure
2. Map the module hierarchy top-down
3. For each module, extract public API elements
4. Use save_data to store findings incrementally
5. Search web for related framework documentation if helpful

When done, use set_output (one key per turn):
- set_output("code_structure", "Directory tree with descriptions and entry points")
- set_output("api_inventory", "Structured inventory of all public APIs with signatures")
- set_output("architecture_map", "Module dependency graph and data flow description")
""",
    tools=[
        "web_search",
        "save_data",
        "append_data",
        "load_data",
        "list_data_files",
    ],
)

# Node 3: Documentation Draft
# Generates the actual documentation content from the analysis.
doc_draft_node = NodeSpec(
    id="doc_draft",
    name="Draft Documentation",
    description="Generate structured documentation content from code analysis",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["code_structure", "api_inventory", "architecture_map", "doc_config"],
    output_keys=["doc_content", "doc_outline"],
    success_criteria=(
        "Complete documentation draft covering all requested sections. "
        "API entries include descriptions, parameters, return values, and examples. "
        "Architecture section explains the system design clearly."
    ),
    system_prompt="""\
You are a technical writer. Given code analysis results, draft comprehensive documentation.

**STRUCTURE THE DOCUMENTATION AS:**

1. **Getting Started**
   - Installation / setup instructions
   - Quick start example (minimum viable usage)
   - Prerequisites and dependencies

2. **Architecture Overview** (if requested)
   - High-level system design
   - Component diagram description
   - Data flow explanation
   - Key design decisions and trade-offs

3. **API Reference** (if requested)
   For each module, in logical order:
   - Module description and purpose
   - Classes with constructor params
   - Methods with full signatures
   - Parameters table (name, type, required, description)
   - Return value documentation
   - Usage example for key functions
   - Exceptions that may be raised

4. **Usage Guide** (if requested)
   - Common workflows and patterns
   - Configuration options
   - Integration examples
   - Troubleshooting common issues

**WRITING GUIDELINES:**
- Use clear, concise language
- Include code examples for every non-trivial API
- Explain "why" not just "what"
- Cross-reference related sections
- Note any caveats or gotchas

Use save_data to store the draft in sections.

When done, use set_output (one key per turn):
- set_output("doc_content", "Complete documentation content organized by section")
- set_output("doc_outline", "Table of contents with section summaries")
""",
    tools=["save_data", "append_data", "load_data", "web_search"],
)

# Node 4: Review (client-facing)
# Presents the documentation outline and draft to the user for feedback.
review_node = NodeSpec(
    id="review",
    name="Review Documentation",
    description="Present documentation outline and draft to user for feedback",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["doc_content", "doc_outline", "doc_config"],
    output_keys=["approved", "review_feedback"],
    success_criteria=(
        "User has reviewed the documentation outline and content "
        "and either approved it or provided specific feedback."
    ),
    system_prompt="""\
Present the documentation draft to the user for review.

**STEP 1 — Present (text only, NO tool calls):**
1. **Documentation Outline**: Show the full table of contents
2. **Coverage Summary**: What's documented (modules, classes, functions)
3. **Sample Section**: Show 1-2 representative API entries as preview
4. **Gaps**: Anything that couldn't be fully documented and why

Ask the user:
- Is the coverage and depth appropriate?
- Are there sections to add, remove, or expand?
- Should we adjust the tone or detail level?
- Ready to generate the final HTML documentation?

**STEP 2 — After the user responds, call set_output:**
- set_output("approved", "true") — generate final docs
- set_output("approved", "false") — iterate on the draft
- set_output("review_feedback", "Specific changes requested, or empty string")
""",
    tools=[],
)

# Node 5: Generate Output (client-facing)
# Produces a professional HTML documentation site.
output_node = NodeSpec(
    id="output",
    name="Generate Documentation Site",
    description="Generate a professional HTML documentation site and present to user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["doc_content", "doc_outline", "doc_config", "api_inventory"],
    output_keys=["delivery_status"],
    success_criteria=(
        "A professional HTML documentation site has been generated, "
        "saved, and presented to the user."
    ),
    system_prompt="""\
Generate a professional HTML documentation site.

**CRITICAL: Build the file in multiple append_data calls. NEVER write the entire HTML \
in a single save_data call.**

IMPORTANT: save_data and append_data require TWO separate arguments: filename and data.
Do NOT include data_dir in tool calls — it is auto-injected.

**PROCESS:**

**Step 1 — HTML head + navigation (save_data):**
save_data(filename="documentation.html", data="<!DOCTYPE html>\\n<html>...")

Include: DOCTYPE, head with documentation CSS below, sticky sidebar navigation
with table of contents, and the getting started section.

**CSS to use (documentation-themed):**
```
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',-apple-system,system-ui,sans-serif;line-height:1.7;color:#24292f;\
background:#fff;display:flex}
.sidebar{position:sticky;top:0;height:100vh;width:280px;background:#f6f8fa;border-right:\
1px solid #d0d7de;padding:20px;overflow-y:auto;flex-shrink:0}
.sidebar h2{font-size:1.1em;color:#1f2328;margin-bottom:15px}
.sidebar a{display:block;padding:6px 12px;color:#656d76;text-decoration:none;font-size:0.9em;\
border-radius:6px;margin:2px 0}
.sidebar a:hover{background:#eaeef2;color:#1f2328}
.sidebar a.active{background:#ddf4ff;color:#0969da;font-weight:600}
.content{flex:1;max-width:800px;padding:40px 60px}
h1{font-size:2em;color:#1f2328;margin-bottom:8px;padding-bottom:12px;\
border-bottom:1px solid #d0d7de}
h2{font-size:1.5em;color:#1f2328;margin-top:40px;padding-top:20px}
h3{font-size:1.2em;color:#1f2328;margin-top:25px}
h4{font-size:1em;color:#57606a;margin-top:20px}
p{margin:12px 0;color:#24292f}
code{background:#f6f8fa;padding:2px 6px;border-radius:4px;font-size:0.9em;font-family:\
'Fira Code',monospace;color:#0550ae}
pre{background:#161b22;color:#e6edf3;padding:20px;border-radius:8px;overflow-x:auto;\
margin:16px 0;font-size:0.875em;line-height:1.6}
pre code{background:none;color:inherit;padding:0}
.api-entry{border:1px solid #d0d7de;border-radius:8px;margin:16px 0;overflow:hidden}
.api-header{background:#f6f8fa;padding:12px 16px;font-family:'Fira Code',monospace;\
font-size:0.9em;border-bottom:1px solid #d0d7de}
.api-body{padding:16px}
.param-table{width:100%;border-collapse:collapse;margin:12px 0}
.param-table th{background:#f6f8fa;text-align:left;padding:8px 12px;font-size:0.85em;\
border:1px solid #d0d7de}
.param-table td{padding:8px 12px;border:1px solid #d0d7de;font-size:0.9em}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.75em;\
font-weight:600}
.badge-required{background:#fde8e8;color:#cf222e}
.badge-optional{background:#ddf4ff;color:#0969da}
.badge-class{background:#e2e0ff;color:#5e3db2}
.badge-function{background:#dafbe1;color:#116329}
.note{background:#ddf4ff;border:1px solid #54aeff44;border-radius:8px;padding:16px;\
margin:16px 0}
.warning{background:#fff8c5;border:1px solid #d4a72c44;border-radius:8px;padding:16px;\
margin:16px 0}
.footer{text-align:center;color:#656d76;border-top:1px solid #d0d7de;padding:30px;\
margin-top:60px;font-size:0.85em}
```

**Step 2 — Architecture section (append_data):**
Module overview, component descriptions, data flow.

**Step 3 — API Reference entries (append_data):**
For each module/class/function, generate:
```
<div class="api-entry">
  <div class="api-header">
    <span class="badge badge-class">class</span>
    ClassName(param1: type, param2: type) → ReturnType
  </div>
  <div class="api-body">
    <p>Description</p>
    <h4>Parameters</h4>
    <table class="param-table">
      <tr><th>Name</th><th>Type</th><th>Required</th><th>Description</th></tr>
      <tr><td>param1</td><td><code>str</code></td><td>✓</td><td>...</td></tr>
    </table>
    <h4>Example</h4>
    <pre><code>usage example here</code></pre>
  </div>
</div>
```

Split into multiple append_data calls if needed.

**Step 4 — Usage guide + footer (append_data):**
Common patterns, troubleshooting, then footer + closing tags.

**Step 5 — Serve the file:**
serve_file_to_user(filename="documentation.html", label="API Documentation", \
open_in_browser=true)

**Step 6 — Present to user (text only):**
Print the file_path and summarize what's documented. Ask if they have questions.

**Step 7 — After user responds:**
- set_output("delivery_status", "completed")
""",
    tools=["save_data", "append_data", "load_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "code_analysis_node",
    "doc_draft_node",
    "review_node",
    "output_node",
]
