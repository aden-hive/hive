"""Nodes for the Research + Summary Agent."""

from framework.graph import NodeSpec

# Node 1: Information Gathering
research_node = NodeSpec(
    id="gather_info",
    name="Information Gathering",
    description="Search the web and gather raw information about the query",
    node_type="event_loop",
    input_keys=["query"],
    output_keys=["raw_data"],
    system_prompt="""\\
You are a research assistant. Your task is to gather information on the provided user query.
Use the web_search tool to find relevant articles, blogs, or documentation.
If needed, use web_scrape on the most promising results to get detailed content.
Once you have enough information, use set_output to save the compiled raw findings.

- set_output("raw_data", "All the raw information gathered from the sources.")
""",
    tools=["web_search", "web_scrape"],
)

# Node 2: Key Point Extraction
extraction_node = NodeSpec(
    id="extract_points",
    name="Key Point Extraction",
    description="Extract key trends, tools, and main points from the raw data",
    node_type="event_loop",
    input_keys=["raw_data"],
    output_keys=["extracted_points"],
    system_prompt="""\\
You are an analytical engine. Read the provided raw_data.
Extract the most important trends, notable tools (if any), and key facts.
Do not search the web. Use ONLY the raw_data provided.

Once you have extracted the points, use set_output to save them.

- set_output("extracted_points", "A list of key trends, tools, and main points found in the raw data.")
""",
    tools=[],
)

# Node 3: Summarization
summarize_node = NodeSpec(
    id="summarize",
    name="Summarization",
    description="Format the extracted points into a final structured summary",
    node_type="event_loop",
    input_keys=["query", "extracted_points"],
    output_keys=["final_summary"],
    system_prompt="""\\
You are a technical writer. Taking the original query and the extracted points, write a concise, well-structured markdown summary.
The summary MUST include:
1. An introductory paragraph about the topic.
2. A bulleted list of Key Trends.
3. A list of Notable Tools or Technologies mentioned.
4. A brief conclusion.

Once you have drafted this summary, use set_output.

- set_output("final_summary", "The final structured markdown summary.")
""",
    tools=[],
)

__all__ = [
    "research_node",
    "extraction_node",
    "summarize_node",
]
