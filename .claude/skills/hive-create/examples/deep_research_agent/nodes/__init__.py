"""
Improved Node Definitions for Deep Research Agent
"""

from framework.graph import NodeSpec


# ---------------------------
# Shared Utilities (Optional)
# ---------------------------

QUALITY_DOMAINS = [".edu", ".gov", ".org", "nature.com", "bbc.com", "reuters.com"]


def is_high_quality_source(url: str) -> bool:
    """Check if URL is from a trusted domain."""
    return any(domain in url for domain in QUALITY_DOMAINS)


# ---------------------------
# Node 1: Intake (Improved)
# ---------------------------

intake_node = NodeSpec(
    id="intake",
    name="Research Intake",
    description="Clarify research topic and scope",
    node_type="event_loop",
    client_facing=True,
    input_keys=["topic"],
    output_keys=["research_brief"],

    system_prompt="""
You are a research intake expert.

Goals:
- Understand exactly what the user wants
- Keep language simple
- Avoid unnecessary questions

Steps:
1. Read the topic
2. Ask max 2 questions if unclear
3. Confirm if clear
4. Wait for approval
5. Then call set_output

Output:
One clear paragraph describing:
- Topic
- Scope
- Depth
- Focus questions
"""
)


# ---------------------------
# Node 2: Research (Improved)
# ---------------------------

research_node = NodeSpec(
    id="research",
    name="Research Engine",
    description="Search, verify, analyze, and score sources",
    node_type="event_loop",
    max_node_visits=4,

    input_keys=["research_brief", "feedback"],
    output_keys=[
        "findings",
        "sources",
        "gaps",
        "confidence_score"
    ],

    nullable_output_keys=["feedback"],

    system_prompt="""
You are a professional research agent.

Rules:

1. Search Phase
   - Run 4–6 web searches
   - Use different angles
   - Prefer trusted domains

2. Filtering Phase
   - Remove low-quality sources
   - Prioritize verified sites

3. Fetch Phase
   - Scrape 6–10 best URLs
   - Skip failures

4. Analysis Phase
   - Compare sources
   - Detect conflicts
   - Rate reliability

5. Stop Rule
   - Stop if:
     - 5+ strong sources agree
     - No major gaps

6. Summary Style
   - Use simple language
   - Short sentences

7. Confidence Score
   - Rate research quality (0–100)

Outputs:
- findings: Structured summary with citations
- sources: List with quality tags
- gaps: Missing areas
- confidence_score: Reliability number
"""
)


# ---------------------------
# Node 3: Review (Improved)
# ---------------------------

review_node = NodeSpec(
    id="review",
    name="Review Results",
    description="User review and feedback",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=3,

    input_keys=[
        "findings",
        "sources",
        "gaps",
        "confidence_score",
        "research_brief"
    ],

    output_keys=[
        "needs_more_research",
        "feedback"
    ],

    system_prompt="""
You are presenting research to a user.

Format:

1. Summary (2 sentences, simple English)
2. Key Points (bullets + confidence)
3. Source Quality (good/medium/weak)
4. Confidence Score
5. Gaps

Ask:
- Continue research?
- Write final report?

Keep it clear and short.
"""
)


# ---------------------------
# Node 4: Report (Improved)
# ---------------------------

report_node = NodeSpec(
    id="report",
    name="Write Report",
    description="Generate clean HTML report",
    node_type="event_loop",
    client_facing=True,

    input_keys=[
        "findings",
        "sources",
        "research_brief",
        "confidence_score"
    ],

    output_keys=["delivery_status"],

    system_prompt="""
You are a technical report writer.

Step 1: Generate HTML

Rules:
- Simple layout
- Mobile friendly
- Clear sections
- Highlight confidence score
- Easy language

Sections:
- Title + Date
- Summary
- Research Question
- Findings
- Conflicts
- Confidence
- Conclusion
- References

Step 2:
Save as report.html

Step 3:
Serve file and notify user

Step 4:
Answer questions

Finally:
set_output("delivery_status", "completed")
"""
)


# ---------------------------
# Export
# ---------------------------

__all__ = [
    "intake_node",
    "research_node",
    "review_node",
    "report_node"
]
