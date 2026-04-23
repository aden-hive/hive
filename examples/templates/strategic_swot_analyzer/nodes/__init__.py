"""Node definitions for Strategic SWOT Analysis Agent."""

from framework.graph import NodeSpec

# Node 1: Identify
identify_node: NodeSpec = NodeSpec(
    id="identify-competitors",
    name="Competitor Discovery",
    description="Uses search to dynamically identify the top 3 market competitors",
    node_type="llm_generate",
    input_keys=["target_company"],
    output_keys=["competitors"],
    system_prompt="""\
You are a strategic market researcher. Your goal is to identify the competitive landscape.

**Process:**
1. Use web_search to identify the top 3 direct competitors for {target_company}.
2. If competitors were already provided, verify their official URLs.
3. Output a clean JSON list containing the competitor names and URLs.
""",
    tools=["web_search"],
)

# Node 2: Research
research_node: NodeSpec = NodeSpec(
    id="research-competitors",
    name="Deep Research",
    description="Scrapes competitor websites for pricing, features, and positioning",
    node_type="llm_generate",
    input_keys=["competitors"],
    output_keys=["raw_research"],
    system_prompt="""\
You are an intelligence gatherer. For each competitor in {competitors}, systematically extract data.

**Process:**
1. Use web_search and web_scrape to find and read their current pricing pages and feature lists.
2. Focus strictly on factual data: pricing tiers, core features, and recent blog announcements.
3. Output a JSON object mapping each competitor to their extracted data.
""",
    tools=["web_search", "web_scrape"],
)

# Node 3: Synthesize
synthesis_node: NodeSpec = NodeSpec(
    id="synthesize-swot",
    name="SWOT Synthesis",
    description="Generates the SWOT matrix and calculates historical deltas",
    node_type="llm_generate",
    input_keys=["raw_research", "previous_run_summary"],
    output_keys=["swot_analysis"],
    system_prompt="""\
You are a Lead Strategic Analyst. Analyze the {raw_research} data to build a formal framework.

**Process:**
1. Generate a structured SWOT (Strengths, Weaknesses, Opportunities, Threats) matrix.
2. **Delta Tracking:** If {previous_run_summary} contains data from a past run, you MUST compare it against current findings. 
3. Explicitly highlight what has changed (e.g., "Competitor A increased pricing by $5").
4. Output the markdown-formatted analysis.
""",
    tools=[],
)

# Node 4: Report
report_node: NodeSpec = NodeSpec(
    id="report-results",
    name="Executive Report Generation",
    description="Formats and persists the final intelligence artifact",
    node_type="llm_generate",
    input_keys=["swot_analysis"],
    output_keys=["final_report"],
    system_prompt="""\
You are an executive assistant. Format the final artifact for leadership.

**Process:**
1. Take the {swot_analysis} and format it into a highly readable, professional Executive Markdown report.
2. Use clear headers, bold text for emphasis, and bullet points.
3. Save the formatted report using the save_data tool to the agent's storage directory.
""",
    tools=["save_data"],
)

__all__ = [
    "identify_node",
    "research_node",
    "synthesis_node",
    "report_node",
]