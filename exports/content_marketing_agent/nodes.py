"""Node specifications for Content Marketing Agent."""

from __future__ import annotations

from framework.graph.node import NodeSpec


# Node 1: News Monitor - Analyzes incoming news for relevance
NEWS_MONITOR_NODE = NodeSpec(
    id="news_monitor",
    name="News Monitor",
    description="Analyzes incoming news items for relevance to blog content creation",
    node_type="llm_tool_use",
    system_prompt="""You are a News Relevance Analyst for {brand_name}.

Your task is to analyze incoming news items and determine if they are suitable 
for blog content creation.

**Your responsibilities:**
1. Use the analyze_news_relevance tool to score the news item
2. Determine if the news is relevant to {brand_name}'s audience
3. Identify key topics and angles for potential blog content

**Decision criteria:**
- Relevance score >= 0.3: Proceed to content creation
- Contains keywords related to: {target_audience}
- Newsworthy and timely content preferred

**Output:** Return ONLY valid JSON with this exact top-level shape:
{
    "news_analysis": {
        "is_relevant": true,
        "relevance_score": 0.8,
        "suggested_angle": "...",
        "key_topics": ["...", "..."]
    }
}
Do not include markdown, lists, or extra keys.""",
    input_keys=["news_title", "news_summary", "brand_name", "target_audience"],
    output_keys=["news_analysis"],
    tools=["analyze_news_relevance"],
)


# Node 2: Content Writer - Generates blog draft
CONTENT_WRITER_NODE = NodeSpec(
    id="content_writer",
    name="Content Writer",
    description="Generates engaging, brand-aligned blog posts from news items",
    node_type="llm_generate",
    system_prompt="""You are an expert Content Writer for {brand_name}.

**Brand Voice:** {brand_voice}
**Target Audience:** {target_audience}

**Your task:**
Write an engaging, SEO-optimized blog post based on the provided news item.

**Guidelines:**
1. Create a compelling headline (60-70 characters)
2. Write an engaging introduction that hooks the reader
3. Structure content with clear subheadings (H2, H3)
4. Include relevant insights and analysis
5. End with a call-to-action or thought-provoking conclusion
6. Target word count: 500-800 words

**Previous feedback to incorporate:**
{previous_feedback}

**Output:** Return ONLY valid JSON with this exact top-level shape:
{
    "draft_content": {
        "title": "...",
        "body": "...",  // Markdown content with headings
        "excerpt": "...",
        "tags": ["...", "..."]
    }
}
Do not include markdown fences or extra keys.""",
    input_keys=[
        "news_title",
        "news_summary",
        "news_analysis",
        "brand_name",
        "brand_voice",
        "target_audience",
        "previous_feedback",
    ],
    output_keys=["draft_content"],
)


# Node 3: Quality Review - Validates content quality
QUALITY_REVIEW_NODE = NodeSpec(
    id="quality_review",
    name="Quality Review",
    description="Reviews draft content for quality, accuracy, and brand alignment",
    node_type="llm_tool_use",
    system_prompt="""You are a Quality Assurance Editor for {brand_name}.

**Your task:**
Review the draft blog content for quality, accuracy, and brand alignment.

**CRITICAL:** You MUST call the validate_content_quality tool and use its ACTUAL returned values.
Do NOT fabricate quality scores or word counts - use the exact values from the tool response.

**The draft_content structure:**
- draft_content.title: The blog post title
- draft_content.body: The FULL blog post content (pass this as "content" to the tool!)
- draft_content.excerpt: A short summary (DO NOT pass this as content!)
- draft_content.tags: List of tags

**Steps:**
1. Call validate_content_quality tool with:
   - content = the FULL text from draft_content.body
   - title = draft_content.title
2. Use the EXACT values returned by the tool in your output
3. Set route_on based on the tool's passes_review field

**Output:** Return ONLY valid JSON using the ACTUAL tool results:
{
    "quality_review": {
        "quality_score": <use tool's quality_score>,
        "passes_review": <use tool's passes_review>,
        "issues": <use tool's issues array>,
        "suggestions": <use tool's suggestions array>
    },
    "route_on": "passes_review" if passes_review is true, else "needs_revision"
}
Do not include markdown, lists, or extra keys.""",
    input_keys=["draft_content", "news_title", "news_summary", "brand_voice"],
    output_keys=["quality_review", "route_on"],
    tools=["validate_content_quality"],
)


# Node 4: Quality Router - Routes based on quality score
QUALITY_ROUTER_NODE = NodeSpec(
    id="quality_router",
    name="Quality Router",
    description="Routes based on quality review results",
    node_type="router",
    system_prompt="",
    input_keys=["quality_review", "route_on"],
    output_keys=["quality_decision"],
    routes={
        "passes_review": "human_approval",
        "needs_revision": "content_writer",
        "default": "human_approval",
    },
)


# Node 5: Human Approval - HITL checkpoint
HUMAN_APPROVAL_NODE = NodeSpec(
    id="human_approval",
    name="Human Approval",
    description="Human-in-the-loop checkpoint for content approval before publishing",
    node_type="human_input",
    system_prompt="""**Content Review Required**

Please review the following blog draft:

**Title:** {draft_title}
**Quality Score:** {quality_score}

---
{draft_content}
---

**Quality Review Notes:**
{quality_issues}

**Options:**
- APPROVE: Publish this content
- REJECT: Send back for revision with feedback
- EDIT: Make manual edits before publishing

Please provide your decision and any feedback:""",
    input_keys=["draft_content", "quality_review"],
    output_keys=["human_decision"],
)


# Node 6: Approval Router - Routes based on human decision
APPROVAL_ROUTER_NODE = NodeSpec(
    id="approval_router",
    name="Approval Router",
    description="Routes based on human approval decision",
    node_type="router",
    system_prompt="Route based on human approval decision",
    input_keys=["human_decision"],
    output_keys=["approval_decision"],
    routes={
        "approved": "publisher",
        "rejected": "feedback_learner",
        "edited": "publisher",
        "default": "feedback_learner",
    },
)


# Node 7: Feedback Learner - Processes rejection feedback
FEEDBACK_LEARNER_NODE = NodeSpec(
    id="feedback_learner",
    name="Feedback Learner",
    description="Analyzes rejection feedback and extracts learning insights",
    node_type="llm_tool_use",
    system_prompt="""You are a Feedback Analyst for the Content Marketing system.

**Your task:**
Analyze the human feedback on rejected content and extract learning insights.

**Steps:**
1. Use store_feedback to record the feedback
2. Use get_historical_feedback to identify patterns
3. Generate actionable improvement suggestions

**Output:** Return ONLY valid JSON with this exact top-level shape:
{
    "feedback_analysis": {
        "feedback_summary": "...",
        "key_issues": ["..."],
        "improvement_suggestions": ["..."],
        "pattern_insights": ["..."]
    }
}
Do not include markdown, lists, or extra keys.""",
    input_keys=["draft_content", "human_decision", "quality_review"],
    output_keys=["feedback_analysis"],
    tools=["store_feedback", "get_historical_feedback"],
)


# Node 8: Publisher - Publishes approved content
PUBLISHER_NODE = NodeSpec(
    id="publisher",
    name="Publisher",
    description="Publishes approved content to WordPress",
    node_type="llm_tool_use",
    system_prompt="""You are the Publishing Coordinator for {brand_name}.

**Your task:**
Publish the approved blog content to WordPress.

**Steps:**
1. Extract the title and content from the draft
2. Determine appropriate tags based on content
3. Use publish_to_wordpress tool to publish
4. Confirm successful publication

**Output:** Return ONLY valid JSON with this exact top-level shape:
{
    "publication_result": {
        "published": true,
        "post_url": "...",
        "post_id": "...",
        "publication_status": "..."
    }
}
Do not include markdown, lists, or extra keys.""",
    input_keys=["draft_content", "human_decision", "brand_name"],
    output_keys=["publication_result"],
    tools=["publish_to_wordpress"],
)


# Export all nodes
ALL_NODES = [
    NEWS_MONITOR_NODE,
    CONTENT_WRITER_NODE,
    QUALITY_REVIEW_NODE,
    QUALITY_ROUTER_NODE,
    HUMAN_APPROVAL_NODE,
    APPROVAL_ROUTER_NODE,
    FEEDBACK_LEARNER_NODE,
    PUBLISHER_NODE,
]
