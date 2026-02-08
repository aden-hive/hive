"""Node definitions for Tech & AI News Reporter."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Brief conversation to understand what topics the user cares about.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Greet the user and ask if they have specific tech/AI topics to focus on, or if they want a general news roundup.",
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["research_brief"],
    system_prompt="""\
You are the intake assistant for a Tech & AI News Reporter agent.

**STEP 1 — Greet and ask the user:**
Greet the user and ask what kind of tech/AI news they're interested in today. Offer options like:
- General tech & AI roundup (covers everything notable)
- Specific topics (e.g., LLMs, robotics, startups, cybersecurity, semiconductors)
- A particular company or product

Keep it brief and friendly. If the user already stated a preference in their initial message, acknowledge it.

After your greeting, call ask_user() to wait for the user's response.

**STEP 2 — After the user responds, call set_output:**
- set_output("research_brief", "<a clear, concise description of what to search for based on the user's preferences>")

If the user just wants a general roundup, set: "General tech and AI news roundup covering the most notable stories from the past week"
""",
    tools=[],
)

# Node 2: Research
# Scrapes known tech news sites directly — no API keys needed.
research_node = NodeSpec(
    id="research",
    name="Research",
    description="Scrape well-known tech news sites for recent articles and extract key information including titles, summaries, sources, and topics.",
    node_type="event_loop",
    input_keys=["research_brief"],
    output_keys=["articles_data"],
    system_prompt="""\
You are a news researcher for a Tech & AI News Reporter agent.

Your task: Find and summarize recent tech/AI news based on the research_brief.
You do NOT have web search — instead, scrape news directly from known sites.

**Instructions:**
1. Use web_scrape to fetch the front/latest pages of these tech news sources.
   IMPORTANT: Always set max_length=5000 and include_links=true for front pages
   so you get headlines and links without blowing up context.

   Scrape these (pick 3-4, not all 5, to stay efficient):
   - https://news.ycombinator.com (Hacker News — tech community picks)
   - https://techcrunch.com (startups, AI, tech industry)
   - https://www.theverge.com/tech (consumer tech, AI, policy)
   - https://arstechnica.com (in-depth tech, science, AI)
   - https://www.technologyreview.com (MIT — AI, emerging tech)

   If the research_brief requests specific topics, also try relevant category pages
   (e.g., https://techcrunch.com/category/artificial-intelligence/).

2. From the scraped front pages, identify the most interesting and recent headlines.
   Pick 5-8 article URLs total across all sources, prioritizing:
   - Relevance to the research_brief
   - Recency (past week)
   - Significance and diversity of topics

3. For each selected article, use web_scrape with max_length=3000 on the
   individual article URL to get the content. Extract: title, source name,
   URL, publication date, a 2-3 sentence summary, and the main topic category.

**Output format:**
Use set_output("articles_data", <JSON string>) with this structure:
```json
{
  "articles": [
    {
      "title": "Article Title",
      "source": "Source Name",
      "url": "https://...",
      "date": "2026-02-05",
      "summary": "2-3 sentence summary of the key points.",
      "topic": "AI / Semiconductors / Startups / etc."
    }
  ],
  "search_date": "2026-02-06",
  "topics_covered": ["AI", "Semiconductors", "..."]
}
```

**Rules:**
- Only include REAL articles with REAL URLs you scraped. Never fabricate.
- Focus on news from the past week.
- Aim for at least 3 distinct topic categories.
- Keep summaries factual and concise.
- If a site fails to load, skip it and move on to the next.
- Always use max_length to limit scraped content (5000 for front pages, 3000 for articles).
- Work in batches: scrape front pages first, then articles. Don't scrape everything at once.
""",
    tools=["web_scrape"],
)

# Node 3: Compile Report
# Turns research into a polished HTML report and delivers it.
# Not client-facing: it does autonomous work (no user interaction needed).
compile_report_node = NodeSpec(
    id="compile-report",
    name="Compile Report",
    description="Organize the researched articles into a structured HTML report, save it, and deliver a clickable link to the user.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["articles_data"],
    output_keys=["report_file"],
    system_prompt="""\
You are the report compiler for a Tech & AI News Reporter agent.

Your task: Turn the articles_data into a polished, readable HTML report and deliver it to the user.

**Instructions:**
1. Parse the articles_data JSON to get the list of articles.
2. Generate a well-structured HTML report with:
   - A header with the report title and date
   - A table of contents / summary section listing topics covered
   - Articles grouped by topic category
   - For each article: title (linked to source URL), source name, date, and summary
   - Clean, readable styling (inline CSS)
3. Use save_data to save the HTML report as "tech_news_report.html".
4. Use serve_file_to_user to get a clickable link for the user.

**STEP 1 — Respond to the user (text only, NO tool calls):**
Present a brief text summary of the report highlights — how many articles, what topics are covered, and a few headline highlights. Tell the user you're generating their full report now.

**STEP 2 — After presenting the summary, save and serve the report:**
- save_data(filename="tech_news_report.html", data=<html_content>, data_dir=<data_dir>)
- serve_file_to_user(filename="tech_news_report.html", data_dir=<data_dir>, label="Tech & AI News Report", open_in_browser=True)
- set_output("report_file", "tech_news_report.html")

The report will auto-open in the user's default browser. Let them know the report has been opened.
""",
    tools=["save_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "research_node",
    "compile_report_node",
]
