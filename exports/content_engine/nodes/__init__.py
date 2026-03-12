"""Node definitions for Content Engine."""

from framework.graph import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Analyze the user's content brief and requirements.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["task"],
    output_keys=["brief", "targets"],
    nullable_output_keys=[],
    success_criteria="The node has identified the core topic and a list of requested content formats.",
    system_prompt="""\
You are the Intake specialist for the Content Engine.

**STEP 1 — Respond to the user (text only, NO tool calls):**
Acknowledge the request. If the brief is missing key details (topic, audience, target platforms), ask for them.

**STEP 2 — After the user provides details, call set_output:**
- set_output("brief", "Detailed summary of the content requirements")
- set_output("targets", ["blog", "twitter", "linkedin"])  # Example list of target formats
""",
    tools=[],
)
research_node = NodeSpec(
    id="research",
    name="Research",
    description="Gather facts, statistics, and context for the content.",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["brief"],
    output_keys=["research_notes"],
    nullable_output_keys=[],
    success_criteria="Research notes contain specific facts, quotes, or data points relevant to the brief.",
    system_prompt="""\
You are the Research specialist. Use search tools to find high-quality information related to the brief.
Look for unique angles, statistics, and credible sources.

Consolidate your findings into a comprehensive research report and store it.
- set_output("research_notes", "The full research findings...")
""",
    tools=["web_search", "web_scrape"],
)
draft_node = NodeSpec(
    id="draft",
    name="Draft",
    description="Create the primary long-form content piece.",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["brief", "research_notes"],
    output_keys=["primary_draft"],
    nullable_output_keys=[],
    success_criteria="A high-quality, well-structured primary draft exists in shared memory.",
    system_prompt="""\
You are the Lead Author. Create the primary content piece (e.g., the blog post or article) based on the brief and research.
Focus on clarity, flow, and professional impact. Avoid all AI clichés (no 'delve', 'tapestry', 'transformative').

- set_output("primary_draft", "The full draft of the primary piece...")
""",
    tools=["save_data"],
)
repurpose_node = NodeSpec(
    id="repurpose",
    name="Repurpose",
    description="Transform the primary draft into secondary formats (social posts, threads).",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["primary_draft", "targets"],
    output_keys=["content_package"],
    nullable_output_keys=[],
    success_criteria="A dictionary or list containing all requested content formats is created.",
    system_prompt="""\
You are the Adaptation Specialist. Transform the primary draft into the requested 'targets' (e.g., Twitter thread, LinkedIn post, Email newsletter).
Each format must be optimized for its platform while maintaining the core message and tone.

- set_output("content_package", {"blog": "...", "twitter": "...", "linkedin": "..."})
""",
    tools=["save_data"],
)
deliver_node = NodeSpec(
    id="deliver",
    name="Deliver",
    description="Deliver the final content package to the user.",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["content_package"],
    output_keys=["delivery_status"],
    nullable_output_keys=[],
    success_criteria="Final content is saved to Google Docs or served to the user.",
    system_prompt="""\
You are the Delivery Specialist. 
1. Create a Google Doc containing the full content package.
2. Use serve_file_to_user to provide a reference link if applicable.
3. Confirm delivery to the user.

- set_output("delivery_status", "Success: Content package delivered via Google Doc.")
""",
    tools=["google_docs_create_document", "serve_file_to_user", "save_data"],
)

__all__ = ['intake_node', 'research_node', 'draft_node', 'repurpose_node', 'deliver_node']
