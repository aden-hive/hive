"""Custom tools for Content Marketing Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


def analyze_news_relevance(
    title: str,
    summary: str,
    company_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """
    Analyze if a news item is relevant for blog content.

    Args:
        title: News article title
        summary: News article summary
        company_keywords: Keywords related to company/brand

    Returns:
        Relevance analysis with score and topics
    """
    keywords = company_keywords or ["technology", "innovation", "growth", "product"]

    # Simple keyword matching (in production, use ML classifier)
    title_lower = title.lower()
    summary_lower = summary.lower()

    matched_keywords = [kw for kw in keywords if kw.lower() in title_lower or kw.lower() in summary_lower]
    relevance_score = min(len(matched_keywords) / max(len(keywords), 1), 1.0)

    return {
        "is_relevant": relevance_score >= 0.3,
        "relevance_score": relevance_score,
        "matched_keywords": matched_keywords,
        "suggested_topics": matched_keywords[:3],
        "timestamp": datetime.now().isoformat(),
    }


def validate_content_quality(
    content: str,
    title: str,
    brand_voice: str = "professional",
) -> dict[str, Any]:
    """
    Validate blog content quality metrics.

    Args:
        content: Blog post content (the full body text)
        title: Blog post title
        brand_voice: Expected brand voice

    Returns:
        Quality validation results with quality_score, passes_review, issues, suggestions
    """
    # Word count analysis
    words = content.split()
    word_count = len(words)

    # Basic quality checks
    has_title = bool(title and len(title) > 10)
    has_introduction = len(content) > 100
    has_structure = "##" in content or "\n\n" in content
    appropriate_length = 300 <= word_count <= 2000

    # Calculate quality score
    checks = [has_title, has_introduction, has_structure, appropriate_length]
    quality_score = sum(checks) / len(checks)

    issues = []
    if not has_title:
        issues.append("Title too short or missing")
    if not has_introduction:
        issues.append("Content too short for proper introduction")
    if not has_structure:
        issues.append("Content lacks proper structure (headings/paragraphs)")
    if not appropriate_length:
        issues.append(f"Word count ({word_count}) outside optimal range (300-2000)")

    # Use passes_review to match the expected output format
    return {
        "quality_score": quality_score,
        "word_count": word_count,
        "passes_review": quality_score >= 0.7,  # Changed from passes_threshold
        "issues": issues,
        "suggestions": [
            s for s in [
                "Add more subheadings" if not has_structure else None,
                "Expand content" if word_count < 300 else None,
                "Consider trimming" if word_count > 2000 else None,
            ] if s is not None
        ],
    }


def publish_to_wordpress(
    title: str,
    content: str,
    tags: list[str] | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """
    Publish content to WordPress (mock implementation).

    Args:
        title: Post title
        content: Post content (HTML or Markdown)
        tags: Post tags
        status: Post status ('draft', 'publish', 'pending')

    Returns:
        Publishing result with post ID and URL
    """
    # Mock implementation - in production, use WordPress REST API
    post_id = f"mock-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    return {
        "success": True,
        "post_id": post_id,
        "url": f"https://example.com/blog/{post_id}",
        "status": status,
        "title": title,
        "tags": tags or [],
        "published_at": datetime.now().isoformat(),
        "message": f"Content {'published' if status == 'publish' else 'saved as draft'} successfully",
    }


def store_feedback(
    content_id: str,
    feedback: str,
    rejection_reason: str | None = None,
    quality_issues: list[str] | None = None,
) -> dict[str, Any]:
    """
    Store feedback for learning and improvement.

    Args:
        content_id: Unique identifier for the content
        feedback: Human feedback text
        rejection_reason: Reason if content was rejected
        quality_issues: List of quality issues identified

    Returns:
        Feedback storage confirmation
    """
    feedback_entry = {
        "content_id": content_id,
        "feedback": feedback,
        "rejection_reason": rejection_reason,
        "quality_issues": quality_issues or [],
        "timestamp": datetime.now().isoformat(),
        "stored": True,
    }

    # In production, store to LTM/database
    return feedback_entry


def get_historical_feedback(
    limit: int = 10,
    rejection_only: bool = False,
) -> dict[str, Any]:
    """
    Retrieve historical feedback for learning.

    Args:
        limit: Maximum number of feedback entries
        rejection_only: Only return rejection feedback

    Returns:
        Historical feedback entries
    """
    # Mock implementation - in production, query LTM/database
    return {
        "entries": [],
        "total_count": 0,
        "patterns": {
            "common_issues": ["title clarity", "structure", "brand voice"],
            "success_factors": ["clear headlines", "proper formatting", "engaging intro"],
        },
    }


@dataclass
class ToolDef:
    """Definition of a custom tool."""

    name: str
    description: str
    function: Callable[..., Any]
    parameters: dict[str, Any] = field(default_factory=dict)


# Tool definitions for registration
CONTENT_MARKETING_TOOLS: list[ToolDef] = [
    ToolDef(
        name="analyze_news_relevance",
        description="Analyze if a news item is relevant for blog content creation",
        function=analyze_news_relevance,
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "News article title"},
                "summary": {"type": "string", "description": "News article summary"},
                "company_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords related to company/brand",
                },
            },
            "required": ["title", "summary"],
        },
    ),
    ToolDef(
        name="validate_content_quality",
        description="Validate blog content quality metrics including structure, length, and readability",
        function=validate_content_quality,
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Blog post content"},
                "title": {"type": "string", "description": "Blog post title"},
                "brand_voice": {"type": "string", "description": "Expected brand voice"},
            },
            "required": ["content", "title"],
        },
    ),
    ToolDef(
        name="publish_to_wordpress",
        description="Publish content to WordPress blog",
        function=publish_to_wordpress,
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Post title"},
                "content": {"type": "string", "description": "Post content"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Post tags",
                },
                "status": {
                    "type": "string",
                    "enum": ["draft", "publish", "pending"],
                    "description": "Post status",
                },
            },
            "required": ["title", "content"],
        },
    ),
    ToolDef(
        name="store_feedback",
        description="Store human feedback for learning and improvement",
        function=store_feedback,
        parameters={
            "type": "object",
            "properties": {
                "content_id": {"type": "string", "description": "Content identifier"},
                "feedback": {"type": "string", "description": "Human feedback text"},
                "rejection_reason": {"type": "string", "description": "Reason for rejection"},
                "quality_issues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Quality issues identified",
                },
            },
            "required": ["content_id", "feedback"],
        },
    ),
    ToolDef(
        name="get_historical_feedback",
        description="Retrieve historical feedback for learning patterns",
        function=get_historical_feedback,
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum entries to return"},
                "rejection_only": {"type": "boolean", "description": "Only return rejections"},
            },
        },
    ),
]


# =============================================================================
# Tool Helpers for Framework Integration
# =============================================================================


def get_tools() -> list:
    """Convert tool definitions to framework Tool objects."""
    from framework.llm.provider import Tool
    
    return [
        Tool(
            name=tool_def.name,
            description=tool_def.description,
            parameters=tool_def.parameters,
        )
        for tool_def in CONTENT_MARKETING_TOOLS
    ]


def get_tool_executor():
    """Create a tool executor function for the framework."""
    from framework.llm.provider import ToolResult, ToolUse
    
    # Build lookup dict
    tool_funcs = {tool_def.name: tool_def.function for tool_def in CONTENT_MARKETING_TOOLS}
    
    def executor(tool_use: ToolUse) -> ToolResult:
        """Execute a tool call and return the result."""
        if tool_use.name not in tool_funcs:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=f"Unknown tool: {tool_use.name}",
                is_error=True,
            )
        
        try:
            func = tool_funcs[tool_use.name]
            result = func(**tool_use.input)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=str(result) if not isinstance(result, str) else result,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=f"Tool error: {e}",
                is_error=True,
            )
    
    return executor
