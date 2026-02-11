"""Node definitions for Blog Writer Agent."""

from framework.graph import NodeSpec

# Node 1: Analyze Topic
analyze_topic_node = NodeSpec(
    id="analyze-topic",
    name="Analyze Topic",
    description="Parse the blog topic to extract keywords, angles, target audience, and content type",
    node_type="llm_generate",
    input_keys=["topic"],
    output_keys=["keywords", "angles", "target_audience", "content_type"],
    output_schema={
        "keywords": {
            "type": "array",
            "required": True,
            "description": "List of 5-10 SEO-relevant keywords and phrases",
        },
        "angles": {
            "type": "array",
            "required": True,
            "description": "List of 3-5 content angles to cover",
        },
        "target_audience": {
            "type": "string",
            "required": True,
            "description": "Description of the target audience persona",
        },
        "content_type": {
            "type": "string",
            "required": True,
            "description": "Blog format: 'how-to', 'listicle', 'deep-dive', 'opinion', or 'guide'",
        },
    },
    system_prompt="""\
You are a content strategist specializing in SEO blog planning. Given a blog topic, analyze it thoroughly.

Your task:
1. Extract 5-10 SEO-relevant keywords and long-tail phrases
2. Identify 3-5 unique content angles to make the post comprehensive
3. Define the target audience persona (who would search for this?)
4. Determine the best content format (how-to, listicle, deep-dive, opinion, guide)

CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks.

Return this JSON structure:
{
  "keywords": ["primary keyword", "secondary keyword", "long-tail phrase", ...],
  "angles": ["angle 1 - overview", "angle 2 - practical tips", "angle 3 - expert insights"],
  "target_audience": "Description of who this post is for, their knowledge level, and what they want to learn",
  "content_type": "deep-dive"
}
""",
    tools=[],
    max_retries=3,
)

# Node 2: Research Topic
research_topic_node = NodeSpec(
    id="research-topic",
    name="Research Topic",
    description="Execute web searches using keywords to find 5+ authoritative sources",
    node_type="llm_tool_use",
    input_keys=["keywords", "angles", "topic"],
    output_keys=["search_results", "source_urls"],
    output_schema={
        "search_results": {
            "type": "string",
            "required": True,
            "description": "Summary of what was found across searches",
        },
        "source_urls": {
            "type": "array",
            "required": True,
            "description": "List of source URLs discovered",
        },
    },
    system_prompt="""\
You are a research assistant for blog writing. Use the web_search tool to find authoritative sources.

Your task:
1. Search using the provided keywords and topic
2. Focus on finding authoritative, recent, and diverse sources
3. Aim for 5+ unique sources covering different angles
4. Prefer sources with data, expert opinions, and practical examples

After searching, return JSON with found sources:
{
  "search_results": "Brief summary of what information was found",
  "source_urls": ["url1", "url2", "url3", ...]
}
""",
    tools=["web_search"],
    max_retries=3,
)

# Node 3: Fetch Sources
fetch_sources_node = NodeSpec(
    id="fetch-sources",
    name="Fetch Sources",
    description="Fetch and extract content from discovered source URLs",
    node_type="llm_tool_use",
    input_keys=["source_urls", "keywords"],
    output_keys=["fetched_sources", "fetch_errors"],
    output_schema={
        "fetched_sources": {
            "type": "array",
            "required": True,
            "description": "List of fetched source objects with url, title, and relevant content excerpts",
        },
        "fetch_errors": {
            "type": "array",
            "required": True,
            "description": "List of URLs that failed to fetch",
        },
    },
    system_prompt="""\
You are a content fetcher for blog research. Use web_scrape tool to retrieve content from URLs.

Your task:
1. Fetch content from each source URL using web_scrape tool
2. Extract the most relevant excerpts related to the keywords
3. Note the title and key data points from each source
4. Track any URLs that failed to fetch

After fetching, return JSON:
{
  "fetched_sources": [
    {"url": "...", "title": "...", "content": "relevant excerpts and key data points..."},
    ...
  ],
  "fetch_errors": ["url that failed", ...]
}
""",
    tools=["web_scrape"],
    max_retries=3,
)

# Node 4: Create Outline
create_outline_node = NodeSpec(
    id="create-outline",
    name="Create Outline",
    description="Structure the blog post with H2/H3 sections, intro, body, and conclusion",
    node_type="llm_generate",
    input_keys=["fetched_sources", "angles", "target_audience", "content_type", "topic"],
    output_keys=["outline", "section_count", "estimated_word_count"],
    output_schema={
        "outline": {
            "type": "array",
            "required": True,
            "description": "Ordered list of sections with heading, level (h2/h3), key points, and target word count",
        },
        "section_count": {
            "type": "number",
            "required": True,
            "description": "Total number of sections in the outline",
        },
        "estimated_word_count": {
            "type": "number",
            "required": True,
            "description": "Estimated total word count for the blog post",
        },
    },
    system_prompt="""\
You are a content architect. Create a detailed blog post outline optimized for the content type and audience.

Your task:
1. Structure the post with clear H2 and H3 sections
2. Include an engaging introduction hook
3. Organize body sections by the identified angles
4. Add a strong conclusion with a call to action
5. Target 1500-3000 words total
6. Note which sources support each section

CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks.

Return JSON:
{
  "outline": [
    {"heading": "Introduction: Hook the reader", "level": "h2", "key_points": ["hook", "thesis", "preview"], "target_words": 200},
    {"heading": "Section Title", "level": "h2", "key_points": ["point 1", "point 2"], "target_words": 400},
    {"heading": "Sub-section", "level": "h3", "key_points": ["detail"], "target_words": 200},
    ...
    {"heading": "Conclusion", "level": "h2", "key_points": ["summary", "call to action"], "target_words": 150}
  ],
  "section_count": 8,
  "estimated_word_count": 2000
}
""",
    tools=[],
    max_retries=3,
)

# Node 5: Write Draft
write_draft_node = NodeSpec(
    id="write-draft",
    name="Write Draft",
    description="Generate a 1500-3000 word blog post with inline citations following the outline",
    node_type="llm_generate",
    input_keys=["outline", "fetched_sources", "target_audience", "topic"],
    output_keys=["draft_content", "citations", "word_count"],
    output_schema={
        "draft_content": {
            "type": "string",
            "required": True,
            "description": "Full markdown blog post with inline citations [n]",
        },
        "citations": {
            "type": "array",
            "required": True,
            "description": "List of citation objects with number, url, and title",
        },
        "word_count": {
            "type": "number",
            "required": True,
            "description": "Actual word count of the draft",
        },
    },
    system_prompt="""\
You are an expert blog writer. Write a compelling, well-researched blog post following the provided outline.

Your task:
1. Follow the outline structure exactly (use the headings as markdown ## and ###)
2. Write engaging, clear prose for the target audience
3. Include inline citations as [1], [2], etc. for all factual claims
4. Use smooth transitions between sections
5. Write an attention-grabbing introduction
6. End with a strong conclusion and call to action
7. Target 1500-3000 words

Writing style:
- Professional but conversational
- Use short paragraphs (2-4 sentences)
- Include bullet points or numbered lists where appropriate
- Add relevant examples and data points from sources

CRITICAL: Return ONLY raw JSON. NO markdown wrapping around the JSON itself.

Return JSON:
{
  "draft_content": "# Blog Title\\n\\n## Introduction\\n\\nEngaging opening paragraph [1]...\\n\\n## Section...\\n",
  "citations": [
    {"number": 1, "url": "https://...", "title": "Source Title"},
    ...
  ],
  "word_count": 2100
}
""",
    tools=[],
    max_retries=3,
)

# Node 6: SEO Optimize
seo_optimize_node = NodeSpec(
    id="seo-optimize",
    name="SEO Optimize",
    description="Add meta description, optimize headers for keywords, and suggest tags",
    node_type="llm_generate",
    input_keys=["draft_content", "keywords", "topic"],
    output_keys=["optimized_content", "meta_description", "seo_title", "suggested_tags"],
    output_schema={
        "optimized_content": {
            "type": "string",
            "required": True,
            "description": "SEO-optimized blog content with improved headers and keyword placement",
        },
        "meta_description": {
            "type": "string",
            "required": True,
            "description": "Meta description for SEO (150-160 characters)",
        },
        "seo_title": {
            "type": "string",
            "required": True,
            "description": "SEO-optimized title tag (50-60 characters)",
        },
        "suggested_tags": {
            "type": "array",
            "required": True,
            "description": "List of 5-8 tags/categories for the post",
        },
    },
    system_prompt="""\
You are an SEO specialist. Optimize the blog post for search engines while maintaining readability.

Your task:
1. Optimize the H1 title for the primary keyword (50-60 characters)
2. Ensure H2/H3 headers include relevant keywords naturally
3. Write a compelling meta description (150-160 characters)
4. Add keyword variations throughout the content naturally (avoid stuffing)
5. Suggest 5-8 relevant tags/categories
6. Ensure the first paragraph contains the primary keyword
7. Add a clear, keyword-rich conclusion

IMPORTANT:
- Do NOT change the meaning or factual content
- Keep all citations intact
- Maintain the original writing quality
- Keyword insertion must feel natural

CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks.

Return JSON:
{
  "optimized_content": "# SEO-Optimized Title\\n\\n## Improved Section Headers...\\n",
  "meta_description": "Compelling 150-160 character description with primary keyword",
  "seo_title": "SEO Title | Brand (50-60 chars)",
  "suggested_tags": ["tag1", "tag2", "tag3", ...]
}
""",
    tools=[],
    max_retries=3,
)

# Node 7: Quality Check
quality_check_node = NodeSpec(
    id="quality-check",
    name="Quality Check",
    description="Verify citations, check readability, and fix any issues in the blog post",
    node_type="llm_generate",
    input_keys=["optimized_content", "citations", "meta_description"],
    output_keys=["quality_score", "issues", "final_content"],
    output_schema={
        "quality_score": {
            "type": "number",
            "required": True,
            "description": "Quality score 0-1",
        },
        "issues": {
            "type": "array",
            "required": True,
            "description": "List of issues found and whether they were fixed",
        },
        "final_content": {
            "type": "string",
            "required": True,
            "description": "Final corrected blog post content",
        },
    },
    system_prompt="""\
You are a blog editor and quality assurance reviewer. Check the blog post thoroughly.

Check for:
1. Uncited claims (factual statements without [n] citation)
2. Broken citations (references to non-existent numbers)
3. Readability (clear prose, good paragraph length, logical flow)
4. Grammar and spelling errors
5. SEO elements (meta description length, keyword presence in headers)
6. Completeness (intro, body sections, conclusion, call to action)
7. Consistency (tone, formatting, citation style)

If issues are found, fix them in the final content.

CRITICAL: Return ONLY raw JSON. NO markdown, NO code blocks.

Return JSON:
{
  "quality_score": 0.92,
  "issues": [
    {"type": "uncited_claim", "location": "paragraph 3", "description": "Added citation [4]", "fixed": true},
    {"type": "readability", "location": "section 2", "description": "Split long paragraph", "fixed": true},
    ...
  ],
  "final_content": "Corrected full blog post with all issues fixed..."
}
""",
    tools=[],
    max_retries=3,
)

# Node 8: Save Blog
save_blog_node = NodeSpec(
    id="save-blog",
    name="Save Blog",
    description="Write the final blog post to a local markdown file with YAML frontmatter",
    node_type="llm_tool_use",
    input_keys=["final_content", "meta_description", "seo_title", "suggested_tags", "citations", "topic"],
    output_keys=["file_path", "save_status"],
    output_schema={
        "file_path": {
            "type": "string",
            "required": True,
            "description": "Path where blog post was saved",
        },
        "save_status": {
            "type": "string",
            "required": True,
            "description": "Status of save operation",
        },
    },
    system_prompt="""\
You are a file manager. Save the blog post to disk as a polished markdown file.

Your task:
1. Generate a filename from the topic (slugified, with date)
2. Add YAML frontmatter with title, description, tags, date, and author
3. Append the references section at the bottom
4. Use the write_to_file tool to save as markdown
5. Save to the ./blog_posts/ directory

Filename format: blog_YYYY-MM-DD_topic-slug.md

File structure:
---
title: "SEO Title"
description: "Meta description"
date: YYYY-MM-DD
tags: [tag1, tag2, ...]
author: "Hive Blog Writer Agent"
---

[Blog content here]

## References

1. [Title](url)
2. [Title](url)
...

Return JSON:
{
  "file_path": "blog_posts/blog_2026-02-10_topic-name.md",
  "save_status": "success"
}
""",
    tools=["write_to_file"],
    max_retries=3,
)

__all__ = [
    "analyze_topic_node",
    "research_topic_node",
    "fetch_sources_node",
    "create_outline_node",
    "write_draft_node",
    "seo_optimize_node",
    "quality_check_node",
    "save_blog_node",
]
