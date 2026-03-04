"""Node definitions for AI Paper Research Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Research Objective Intake",
    description=(
        "Clarify the ML research objective, target audience background, and desired depth"
    ),
    node_type="event_loop",
    client_facing=True,
    input_keys=["objective", "paper_pdf_paths"],
    output_keys=["research_objective", "target_topics", "difficulty_profile"],
    nullable_output_keys=["paper_pdf_paths"],
    system_prompt="""\
You are an AI research intake specialist helping a machine learning researcher.

Goal:
Turn the user's objective into a precise research objective for deep paper analysis.

STEP 1 (message only, no tools):
1. Restate the objective in your own words.
2. Ask up to 2 clarifying questions only if needed:
   - Which sub-topics matter most?
   - What prior background should be assumed?
   - Is the focus understanding ideas, reproducing methods, or comparing papers?
3. Keep messages concise and researcher-friendly.
4. Call ask_user() to wait for user response.

STEP 2 (after user confirms):
- set_output("research_objective", "One paragraph with exact research objective and scope.")
- set_output("target_topics", "Bullet list of prioritized technical topics to study.")
- set_output("difficulty_profile", "Expected math and systems depth for explanations.")
""",
    tools=[],
)

# Node 2: Discover papers
# Uses academic search + web search to build a strong shortlist.
discover_papers_node = NodeSpec(
    id="discover-papers",
    name="Discover Candidate Papers",
    description="Find high-value recent and foundational papers from academic and web search",
    node_type="event_loop",
    input_keys=["research_objective", "target_topics"],
    output_keys=["paper_candidates", "selection_rationale"],
    system_prompt="""\
You discover high-quality papers for the objective.

Use these tools:
- scholar_search for academic discovery and citation-aware results.
- web_search for broader discovery (especially arXiv and project pages).
- web_scrape to inspect abstracts or paper pages for relevance.

Process:
1. Generate 5-8 targeted search queries from the objective.
2. Search and shortlist 6-10 papers (mix recent + influential).
3. For each paper capture:
   - title
   - url
   - venue/year if available
   - why it matters for this objective
4. Prioritize arXiv, conference/journal pages, and official project pages.

Output:
- set_output("paper_candidates", "JSON-like list of paper entries with metadata and links")
- set_output("selection_rationale", "Why this shortlist best covers the objective")
""",
    tools=["scholar_search", "web_search", "web_scrape"],
)

# Node 3: Analyze papers deeply
analyze_papers_node = NodeSpec(
    id="analyze-papers",
    name="Analyze Paper Content",
    description=(
        "Extract key methods, assumptions, results, and limitations from selected papers"
    ),
    node_type="event_loop",
    input_keys=["paper_candidates", "paper_pdf_paths", "research_objective", "difficulty_profile"],
    output_keys=["paper_breakdowns", "cross_paper_map", "open_questions"],
    nullable_output_keys=["paper_pdf_paths"],
    system_prompt="""\
You are a technical paper analyst.

Use:
- web_scrape for arXiv abstract pages / project pages / online paper text.
- pdf_read only when local PDF paths are provided in paper_pdf_paths.

Analysis requirements for each key paper:
1. Problem and motivation
2. Method (architecture, objective, algorithmic steps)
3. Data/experimental setup
4. Results and what is statistically or empirically convincing
5. Limitations, assumptions, and failure modes
6. Relevance to the research objective

Cross-paper synthesis:
- Compare approaches, trade-offs, and disagreements.
- Identify what remains unclear or under-evaluated.

Output:
- set_output("paper_breakdowns", "Structured per-paper technical breakdowns")
- set_output("cross_paper_map", "Comparison table across methods, assumptions, compute, and results")
- set_output("open_questions", "Important unresolved questions and replication risks")
""",
    tools=["web_scrape", "pdf_read"],
)

# Node 4: Convert analysis into teachable understanding
build_learning_brief_node = NodeSpec(
    id="build-learning-brief",
    name="Build Learning Brief",
    description="Translate deep analysis into clear explanations and a practical study path",
    node_type="event_loop",
    input_keys=["paper_breakdowns", "cross_paper_map", "open_questions", "research_objective"],
    output_keys=["teaching_note", "study_plan", "recommended_next_papers"],
    system_prompt="""\
You are a research mentor for machine learning scientists.

Produce a deep but understandable learning brief:
1. Explain the core ideas in plain technical language.
2. Highlight equations or mechanisms that matter most.
3. Provide intuition, then formal detail.
4. Connect papers into a single conceptual map.
5. Include a step-by-step study plan for mastering the topic.

Output:
- set_output("teaching_note", "Clear, layered explanation of the paper set")
- set_output("study_plan", "Actionable reading/reproduction plan with milestones")
- set_output("recommended_next_papers", "3-5 follow-up papers with reasons")
""",
    tools=[],
)

# Node 5: Deliver report (client-facing)
deliver_research_brief_node = NodeSpec(
    id="deliver-brief",
    name="Deliver Research Brief",
    description="Write and deliver a structured HTML brief, then answer follow-up questions",
    node_type="event_loop",
    client_facing=True,
    input_keys=["teaching_note", "study_plan", "recommended_next_papers", "open_questions"],
    output_keys=["delivery_status"],
    system_prompt="""\
Create and deliver a final research brief.

STEP 1 (tool calls first):
1. Build a full HTML report with:
   - Objective and scope
   - Paper-by-paper breakdown
   - Cross-paper comparison matrix
   - Key insights and open questions
   - Study plan and next-paper recommendations
2. Save it with save_data(filename="ai_paper_research_brief.html", data=<html>). 
3. Share it with serve_file_to_user(filename="ai_paper_research_brief.html", label="AI Paper Deep Research Brief").

STEP 2 (message user):
- Share the link, summarize key takeaways in 5-8 bullets, and ask for follow-up questions.
- Use ask_user() for follow-up.

STEP 3:
- Answer follow-up questions from the analyzed material.
- When done, set_output("delivery_status", "completed").
""",
    tools=["save_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "discover_papers_node",
    "analyze_papers_node",
    "build_learning_brief_node",
    "deliver_research_brief_node",
]
