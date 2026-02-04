"""Node definitions for Online Research Agent."""

from framework.graph import NodeSpec

# Node 1: Parse Query
parse_query_node = NodeSpec(
    id="parse-query",
    name="Parse Query",
    description="Analyze the research topic and generate 3-5 diverse search queries to cover different aspects",
    node_type="event_loop",
    input_keys=["topic"],
    output_keys=["search_queries", "research_focus", "key_aspects"],
    system_prompt="""\
You are a research query strategist. Given a research topic, analyze it and generate search queries.

Your task:
1. Understand the core research question
2. Identify 3-5 key aspects to investigate
3. Generate 3-5 diverse search queries that will find comprehensive information

Use set_output to store each result:
- set_output("research_focus", "Brief statement of what we're researching")
- set_output("key_aspects", ["aspect1", "aspect2", "aspect3"])
- set_output("search_queries", ["query 1", "query 2", "query 3", "query 4", "query 5"])
""",
    tools=[],
)

# Node 2: Search Sources
search_sources_node = NodeSpec(
    id="search-sources",
    name="Search Sources",
    description="Execute web searches using the generated queries to find 15+ source URLs",
    node_type="event_loop",
    input_keys=["search_queries", "research_focus"],
    output_keys=["source_urls", "search_results_summary"],
    system_prompt="""\
You are a research assistant executing web searches. Use the web_search tool to find sources.

Your task:
1. Execute each search query using web_search tool
2. Collect URLs from search results
3. Aim for 15+ diverse sources

After searching, use set_output to store results:
- set_output("source_urls", ["url1", "url2", ...])
- set_output("search_results_summary", "Brief summary of what was found")
""",
    tools=["web_search"],
)

# Node 3: Fetch Content
fetch_content_node = NodeSpec(
    id="fetch-content",
    name="Fetch Content",
    description="Fetch and extract content from the discovered source URLs",
    node_type="event_loop",
    input_keys=["source_urls", "research_focus"],
    output_keys=["fetched_sources", "fetch_errors"],
    system_prompt="""\
You are a content fetcher. Use web_scrape tool to retrieve content from URLs.

Your task:
1. Fetch content from each source URL using web_scrape tool
2. Extract the main content relevant to the research focus
3. Track any URLs that failed to fetch

After fetching, use set_output to store results:
- set_output("fetched_sources", [{"url": "...", "title": "...", "content": "..."}])
- set_output("fetch_errors", ["url that failed", ...])
""",
    tools=["web_scrape"],
)

# Node 4: Evaluate Sources
evaluate_sources_node = NodeSpec(
    id="evaluate-sources",
    name="Evaluate Sources",
    description="Score sources for relevance and quality, filter to top 10",
    node_type="event_loop",
    input_keys=["fetched_sources", "research_focus", "key_aspects"],
    output_keys=["ranked_sources", "source_analysis"],
    system_prompt="""\
You are a source evaluator. Assess each source for quality and relevance.

Scoring criteria:
- Relevance to research focus (1-10)
- Source credibility (1-10)
- Information depth (1-10)
- Recency if relevant (1-10)

Your task:
1. Score each source
2. Rank by combined score
3. Select top 10 sources
4. Note what each source uniquely contributes

Use set_output to store results:
- set_output("ranked_sources", [{"url": "...", "title": "...", "score": 8.5}])
- set_output("source_analysis", "Overview of source quality and coverage")
""",
    tools=[],
)

# Node 5: Synthesize Findings
synthesize_findings_node = NodeSpec(
    id="synthesize-findings",
    name="Synthesize Findings",
    description="Extract key facts from sources and identify common themes",
    node_type="event_loop",
    input_keys=["ranked_sources", "research_focus", "key_aspects"],
    output_keys=["key_findings", "themes", "source_citations"],
    system_prompt="""\
You are a research synthesizer. Analyze multiple sources to extract insights.

Your task:
1. Identify key facts from each source
2. Find common themes across sources
3. Note contradictions or debates
4. Build a citation map (fact -> source URL)

Use set_output to store each result:
- set_output("key_findings", [{"finding": "...", "sources": ["url1"], "confidence": "high"}])
- set_output("themes", [{"theme": "...", "description": "...", "supporting_sources": [...]}])
- set_output("source_citations", {"fact or claim": ["url1", "url2"]})
""",
    tools=[],
)

# Node 6: Write Report
write_report_node = NodeSpec(
    id="write-report",
    name="Write Report",
    description="Generate a narrative report with proper citations",
    node_type="event_loop",
    input_keys=[
        "key_findings",
        "themes",
        "source_citations",
        "research_focus",
        "ranked_sources",
    ],
    output_keys=["report_content", "references"],
    system_prompt="""\
You are a research report writer. Create a well-structured narrative report.

Report structure:
1. Executive Summary (2-3 paragraphs)
2. Introduction (context and scope)
3. Key Findings (organized by theme)
4. Analysis (synthesis and implications)
5. Conclusion
6. References (numbered list of all sources)

Citation format: Use numbered citations like [1], [2] that correspond to the References section.

IMPORTANT:
- Every factual claim MUST have a citation
- Write in clear, professional prose
- Be objective and balanced
- Highlight areas of consensus and debate

Use set_output to store results:
- set_output("report_content", "Full markdown report text with citations...")
- set_output("references", [{"number": 1, "url": "...", "title": "..."}])
""",
    tools=[],
)

# Node 7: Quality Check
quality_check_node = NodeSpec(
    id="quality-check",
    name="Quality Check",
    description="Verify all claims have citations and report is coherent",
    node_type="event_loop",
    input_keys=["report_content", "references", "source_citations"],
    output_keys=["quality_score", "issues", "final_report"],
    system_prompt="""\
You are a quality assurance reviewer. Check the research report for issues.

Check for:
1. Uncited claims (factual statements without [n] citation)
2. Broken citations (references to non-existent numbers)
3. Coherence (logical flow between sections)
4. Completeness (all key aspects covered)
5. Accuracy (claims match source content)

If issues found, fix them in the final report.

Use set_output to store results:
- set_output("quality_score", 0.95)
- set_output("issues", [{"type": "uncited_claim", "location": "...", "fixed": true}])
- set_output("final_report", "Corrected full report with all issues fixed...")
""",
    tools=[],
)

# Node 8: Save Report
save_report_node = NodeSpec(
    id="save-report",
    name="Save Report",
    description="Write the final report to a local markdown file",
    node_type="event_loop",
    input_keys=["final_report", "references", "research_focus"],
    output_keys=["file_path", "save_status"],
    system_prompt="""\
You are a file manager. Save the research report to disk.

Your task:
1. Generate a filename from the research focus (slugified, with date)
2. Use the write_to_file tool to save the report as markdown
3. Save to the ./research_reports/ directory

Filename format: research_YYYY-MM-DD_topic-slug.md

Use set_output to store results:
- set_output("file_path", "research_reports/research_2026-01-23_topic-name.md")
- set_output("save_status", "success")
""",
    tools=["write_to_file"],
)

__all__ = [
    "parse_query_node",
    "search_sources_node",
    "fetch_content_node",
    "evaluate_sources_node",
    "synthesize_findings_node",
    "write_report_node",
    "quality_check_node",
    "save_report_node",
]
