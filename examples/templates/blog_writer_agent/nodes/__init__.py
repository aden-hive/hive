"""Node definitions for Blog Writer Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Clarify audience, angle, CTA, and constraints for a business-focused blog post.
intake_node = NodeSpec(
    id="intake",
    name="Blog Intake",
    description="Clarify topic, audience, business angle, CTA, and constraints",
    node_type="event_loop",
    client_facing=True,
    input_keys=["topic"],
    output_keys=["brief", "audience", "angle", "cta", "tone", "length_words"],
    system_prompt="""\
You are a blog intake strategist for a business audience.
Your goal is to define a clear writing brief the rest of the pipeline can execute.

**STEP 1 — Ask or confirm (text only, NO tool calls):**
1. Read the provided topic.
2. If it is vague, ask 2-3 short questions:
   - Target audience (role/industry/seniority)
   - Desired business angle or POV
   - Primary call-to-action (CTA)
   - Desired length range (e.g., 1200–2000 words)
3. If it is clear, summarize your understanding and ask for confirmation.

Keep it concise. End by asking for confirmation.
Then call ask_user().

**STEP 2 — After the user responds, call set_output:**
- set_output("brief", "A single paragraph business-focused brief with scope and intent.")
- set_output("audience", "e.g., B2B product leaders in SaaS")
- set_output("angle", "e.g., strategic perspective or contrarian POV")
- set_output("cta", "e.g., book a demo / subscribe / download guide")
- set_output("tone", "e.g., crisp, authoritative, analytical")
- set_output("length_words", "e.g., 1500")
""",
    tools=[],
)

# Node 2: Research (tooling)
research_node = NodeSpec(
    id="research",
    name="Research Topic",
    description="Search the web, scrape sources, and extract evidence",
    node_type="event_loop",
    max_node_visits=3,
    input_keys=["brief"],
    output_keys=["findings", "sources"],
    system_prompt="""\
You are a research agent for a business blog post.
Use web_search and web_scrape to gather authoritative sources.

Work in phases:
1. Search with 3-5 diverse queries.
2. Scrape 5-8 high-quality sources.
3. Extract key evidence with URLs for citation.

Rules:
- Prefer .gov, .edu, established publications, and reputable industry reports.
- Capture direct, attributable facts (stats, benchmarks, quotes, timelines).
- Track which URL supports each claim.

When done, call set_output:
- set_output("findings", "Bullet list of key facts/insights. Each bullet must include its source URL.")
- set_output("sources", [{"url": "...", "title": "...", "summary": "..."}])
""",
    tools=["web_search", "web_scrape", "load_data", "save_data", "list_data_files"],
)

# Node 3: Positioning / Thesis
positioning_node = NodeSpec(
    id="positioning",
    name="Positioning & Thesis",
    description="Synthesize a business thesis and outline based on research",
    node_type="event_loop",
    input_keys=["brief", "findings"],
    output_keys=["thesis", "outline"],
    system_prompt="""\
You are a strategist. Turn findings into a strong business thesis and outline.

Requirements:
- The thesis must be a clear, opinionated POV suitable for a business audience.
- The outline should include 5-8 sections with H2/H3 structure.
- Each section should reference which findings it will cite.

Return:
- set_output("thesis", "1-2 sentence thesis")
- set_output("outline", "Structured outline with section titles and bullets")
""",
    tools=[],
)

# Node 4: Outline Review (client-facing)
outline_review_node = NodeSpec(
    id="outline_review",
    name="Outline Review",
    description="Present thesis + outline and gather user approval or changes",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=3,
    input_keys=["brief", "thesis", "outline"],
    output_keys=["needs_outline_changes", "outline_feedback"],
    system_prompt="""\
Present the thesis and outline for approval.

**STEP 1 — Present (text only, NO tool calls):**
1. Thesis (1-2 sentences)
2. Outline (numbered sections with brief bullets)
3. Ask: approve or request changes?

Then call ask_user().

**STEP 2 — After user responds, call set_output:**
- set_output("needs_outline_changes", "true" or "false")
- set_output("outline_feedback", "What to change, if any")
""",
    tools=[],
)

# Node 5: Draft
write_draft_node = NodeSpec(
    id="write_draft",
    name="Write Draft",
    description="Write the business blog draft with citations",
    node_type="event_loop",
    max_node_visits=3,
    input_keys=[
        "brief",
        "thesis",
        "outline",
        "findings",
        "outline_feedback",
        "revision_notes",
    ],
    output_keys=["draft_md"],
    nullable_output_keys=["outline_feedback", "revision_notes"],
    system_prompt="""\
Write a full business blog draft in Markdown.

Requirements:
- 1500–3000 words unless brief says otherwise.
- Business tone: crisp, authoritative, analytical.
- Include citations with numbered references like [1], [2] tied to sources.
- Use headings and subheadings from the outline.
- Ensure the CTA is included near the end.

If outline_feedback exists, incorporate it.
If revision_notes exists, this is a revision pass. Focus on addressing the specific
feedback in revision_notes while preserving the overall structure.

Return:
- set_output("draft_md", "Markdown draft with citations")
""",
    tools=[],
)

# Node 6: SEO Optimization
seo_optimize_node = NodeSpec(
    id="seo_optimize",
    name="SEO Optimization",
    description="Optimize title, meta description, and keywords",
    node_type="event_loop",
    input_keys=["draft_md", "brief"],
    output_keys=["optimized_md", "seo_metadata"],
    system_prompt="""\
Optimize the draft for SEO without hurting clarity.

Tasks:
- Provide an SEO title (<= 60 chars)
- Provide a meta description (<= 155 chars)
- Provide 6-10 primary keywords
- Lightly refine the draft to improve readability and keyword placement

Return:
- set_output("optimized_md", "Revised Markdown")
- set_output("seo_metadata", {"title": "...", "meta_description": "...", "keywords": ["..."]})
""",
    tools=[],
)

# Node 7: Quality Gate (client-facing)
quality_gate_node = NodeSpec(
    id="quality_gate",
    name="Quality Gate",
    description="Evaluate draft vs. brief and request revisions if needed",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=3,
    input_keys=["optimized_md", "seo_metadata", "brief"],
    output_keys=["needs_revision", "revision_notes"],
    system_prompt="""\
Review the draft against the brief and provide a structured quality check.

**STEP 1 — Present (text only, NO tool calls):**
Score the draft on:
1. Audience fit
2. Business clarity
3. Evidence + citations
4. Thesis strength
5. CTA presence
6. SEO basics

Then ask: approve for publishing or request changes?
Call ask_user().

**STEP 2 — After user responds, call set_output:**
- set_output("needs_revision", "true" or "false")
- set_output("revision_notes", "Concrete edits if changes are needed")
""",
    tools=[],
)

# Node 8: Publish (client-facing)
publish_node = NodeSpec(
    id="publish",
    name="Publish Blog",
    description="Save the blog post and provide a downloadable link",
    node_type="event_loop",
    client_facing=True,
    input_keys=["optimized_md", "seo_metadata", "sources"],
    output_keys=["delivery_status"],
    system_prompt="""\
Publish the final blog post as a Markdown file and provide a clickable link.

**STEP 1 — Save artifacts (tool calls, NO text to user yet):**
1. Save the blog:
   save_data(filename="blog_post.md", data=<optimized_md>)
2. Save metadata:
   save_data(filename="blog_metadata.json", data=<seo_metadata JSON>)
3. Serve the blog file:
   serve_file_to_user(filename="blog_post.md", label="Blog Post")

**STEP 2 — Present the link (text only):**
Provide the file:// URI from serve_file_to_user. Summarize what was delivered
(title, keywords), and ask if they want a revision.
Call ask_user().

**STEP 3 — After user responds:**
- If they want changes, set_output("delivery_status", "revision_requested")
- If satisfied, set_output("delivery_status", "completed")
""",
    tools=["save_data", "serve_file_to_user", "load_data", "list_data_files"],
)

__all__ = [
    "intake_node",
    "research_node",
    "positioning_node",
    "outline_review_node",
    "write_draft_node",
    "seo_optimize_node",
    "quality_gate_node",
    "publish_node",
]
