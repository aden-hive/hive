"""Node definitions for Online Research Agent."""
from framework.graph import NodeSpec

# Node 1: Parse Query
parse_query_node = NodeSpec(
    id="parse-query",
    name="Parse Query",
    description="Analyze the research topic and generate 3-5 diverse search queries to cover different aspects",
    node_type="llm_generate",
    input_keys=["topic"],
    output_keys=["search_queries", "research_focus", "key_aspects"],
    output_schema={
        "research_focus": {"type": "string", "required": True, "description": "Brief statement of what we're researching"},
        "key_aspects": {"type": "array", "required": True, "description": "List of 3-5 key aspects to investigate"},
        "search_queries": {"type": "array", "required": True, "description": "List of 3-5 search queries"},
    },
    system_prompt="""\
You are a research query strategist. Given a research topic, analyze it and generate search queries.

Your task:
1. Understand the core research question
2. Identify 3-5 key aspects to investigate
3. Generate 3-5 diverse search queries that will find comprehensive information

CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks.

Return this JSON structure:
{
  "research_focus": "Brief statement of what we're researching",
  "key_aspects": ["aspect1", "aspect2", "aspect3"],
  "search_queries": [
    "query 1 - broad overview",
    "query 2 - specific angle",
    "query 3 - recent developments",
    "query 4 - expert opinions",
    "query 5 - data/statistics"
  ]
}
""",
    tools=[],
    max_retries=3,
)

# Node 2: Search Sources
search_sources_node = NodeSpec(
    id="search-sources",
    name="Search Sources",
    description="Execute web searches using the generated queries to find 15+ source URLs",
    node_type="llm_tool_use",
    input_keys=["search_queries", "research_focus"],
    output_keys=["source_urls", "search_results_summary"],
    output_schema={
        "source_urls": {"type": "array", "required": True, "description": "List of source URLs found"},
        "search_results_summary": {"type": "string", "required": True, "description": "Brief summary of what was found"},
    },
    system_prompt="""\
You are a research assistant executing web searches. Use the web_search tool to find sources.

Your task:
1. Execute each search query using web_search tool
2. Collect URLs from search results
3. Aim for 15+ diverse sources

After searching, return JSON with found sources:
{
  "source_urls": ["url1", "url2", ...],
  "search_results_summary": "Brief summary of what was found"
}
""",
    tools=["web_search"],
    max_retries=3,
)

# Node 3: Fetch Content
fetch_content_node = NodeSpec(
    id="fetch-content",
    name="Fetch Content",
    description="Fetch and extract content from the discovered source URLs",
    node_type="llm_tool_use",
    input_keys=["source_urls", "research_focus"],
    output_keys=["fetched_sources", "fetch_errors"],
    output_schema={
        "fetched_sources": {"type": "array", "required": True, "description": "List of fetched source objects with url, title, content"},
        "fetch_errors": {"type": "array", "required": True, "description": "List of URLs that failed to fetch"},
    },
    system_prompt="""\
You are a content fetcher. Use web_scrape tool to retrieve content from URLs.

Your task:
1. Fetch content from each source URL using web_scrape tool
2. Extract the main content relevant to the research focus
3. Track any URLs that failed to fetch

After fetching, return JSON:
{
  "fetched_sources": [
    {"url": "...", "title": "...", "content": "extracted text..."},
    ...
  ],
  "fetch_errors": ["url that failed", ...]
}
""",
    tools=["web_scrape"],
    max_retries=3,
)

# Node 4: Evaluate Sources
evaluate_sources_node = NodeSpec(
    id="evaluate-sources",
    name="Evaluate Sources",
    description="Score sources for relevance and quality, filter to top 10",
    node_type="llm_generate",
    input_keys=["fetched_sources", "research_focus", "key_aspects"],
    output_keys=["ranked_sources", "source_analysis"],
    output_schema={
        "ranked_sources": {"type": "array", "required": True, "description": "List of ranked sources with scores"},
        "source_analysis": {"type": "string", "required": True, "description": "Overview of source quality and coverage"},
    },
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

Return JSON:
{
  "ranked_sources": [
    {"url": "...", "title": "...", "content": "...", "score": 8.5, "unique_value": "..."},
    ...
  ],
  "source_analysis": "Overview of source quality and coverage"
}
""",
    tools=[],
    max_retries=3,
)

# Node 5: Synthesize Findings
synthesize_findings_node = NodeSpec(
    id="synthesize-findings",
    name="Synthesize Findings",
    description="Extract key facts from sources and identify common themes",
    node_type="llm_generate",
    input_keys=["ranked_sources", "research_focus", "key_aspects"],
    output_keys=["key_findings", "themes", "source_citations"],
    output_schema={
        "key_findings": {"type": "array", "required": True, "description": "List of key findings with sources and confidence"},
        "themes": {"type": "array", "required": True, "description": "List of themes with descriptions and supporting sources"},
        "source_citations": {"type": "object", "required": True, "description": "Map of facts to supporting URLs"},
    },
    system_prompt="""\
You are a research synthesizer. Analyze multiple sources to extract insights.

Your task:
1. Identify key facts from each source
2. Find common themes across sources
3. Note contradictions or debates
4. Build a citation map (fact -> source URL)

Return JSON:
{
  "key_findings": [
    {"finding": "...", "sources": ["url1", "url2"], "confidence": "high/medium/low"},
    ...
  ],
  "themes": [
    {"theme": "...", "description": "...", "supporting_sources": ["url1", ...]},
    ...
  ],
  "source_citations": {
    "fact or claim": ["supporting url1", "url2"],
    ...
  }
}
""",
    tools=[],
    max_retries=3,
)

# Node 6: Write Report
write_report_node = NodeSpec(
    id="write-report",
    name="Write Report",
    description="Generate a narrative report with proper citations",
    node_type="llm_generate",
    input_keys=["key_findings", "themes", "source_citations", "research_focus", "ranked_sources"],
    output_keys=["report_content", "references"],
    output_schema={
        "report_content": {"type": "string", "required": True, "description": "Full markdown report text with citations"},
        "references": {"type": "array", "required": True, "description": "List of reference objects with number, url, title"},
    },
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

Return JSON:
{
  "report_content": "Full markdown report text with citations...",
  "references": [
    {"number": 1, "url": "...", "title": "..."},
    ...
  ]
}
""",
    tools=[],
    max_retries=3,
)

# Node 7: Quality Check
quality_check_node = NodeSpec(
    id="quality-check",
    name="Quality Check",
    description="Verify all claims have citations and report is coherent",
    node_type="llm_generate",
    input_keys=["report_content", "references", "source_citations"],
    output_keys=["quality_score", "issues", "final_report"],
    output_schema={
        "quality_score": {"type": "number", "required": True, "description": "Quality score 0-1"},
        "issues": {"type": "array", "required": True, "description": "List of issues found and fixed"},
        "final_report": {"type": "string", "required": True, "description": "Corrected full report"},
    },
    system_prompt="""\
You are a quality assurance reviewer. Check the research report for issues.

Check for:
1. Uncited claims (factual statements without [n] citation)
2. Broken citations (references to non-existent numbers)
3. Coherence (logical flow between sections)
4. Completeness (all key aspects covered)
5. Accuracy (claims match source content)

If issues found, fix them in the final report.

Return JSON:
{
  "quality_score": 0.95,
  "issues": [
    {"type": "uncited_claim", "location": "paragraph 3", "fixed": true},
    ...
  ],
  "final_report": "Corrected full report with all issues fixed..."
}
""",
    tools=[],
    max_retries=3,
)

# Node 8: Save Report
save_report_node = NodeSpec(
    id="save-report",
    name="Save Report",
    description="Write the final report to a local markdown file",
    node_type="llm_tool_use",
    input_keys=["final_report", "references", "research_focus"],
    output_keys=["file_path", "save_status"],
    output_schema={
        "file_path": {"type": "string", "required": True, "description": "Path where report was saved"},
        "save_status": {"type": "string", "required": True, "description": "Status of save operation"},
    },
    system_prompt="""\
You are a file manager. Save the research report to disk.

Your task:
1. Generate a filename from the research focus (slugified, with date)
2. Use the write_to_file tool to save the report as markdown
3. Save to the ./research_reports/ directory

Filename format: research_YYYY-MM-DD_topic-slug.md

Return JSON:
{
  "file_path": "research_reports/research_2026-01-23_topic-name.md",
  "save_status": "success"
}
""",
    tools=["write_to_file"],
    max_retries=3,
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
