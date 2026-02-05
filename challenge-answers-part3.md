# Build Your First Agent Challenge - Part 3 Answers

## Task 3.1: Agent Pseudocode 💻

### Content Writer Agent - Full Implementation

```python
"""
Content Writer Agent - Worker Agent #2 in the Content Marketing System

This agent takes news items and writes engaging blog posts that match
the company's brand voice. It learns from rejection feedback via LTM.

Node Type: llm_generate
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.graph.node import NodeContext, NodeResult, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime


@dataclass
class ContentWriterConfig:
    """Configuration for the Content Writer Agent."""
    
    company_name: str = "Acme Corp"
    min_word_count: int = 300
    max_word_count: int = 1500
    target_reading_level: str = "general audience"
    max_retries: int = 3
    confidence_threshold: float = 0.7


class ContentWriterAgent:
    """
    Agent that takes news items and writes blog posts.
    
    Inputs (from SharedMemory):
        - news_item: dict with title, summary, source_url, publish_date
        - company_context: str with relevant company background
        - style_guidelines: dict loaded from LTM (optional)
        - rejection_feedback: str from previous attempt (optional)
    
    Outputs (to SharedMemory):
        - draft_post: dict with title, body, excerpt, tags
        - seo_metadata: dict with meta_description, keywords
        - confidence_score: float 0-1
    """

    def __init__(self, config: ContentWriterConfig):
        self.config = config
        self.node_spec = NodeSpec(
            id="content_writer",
            name="Content Writer Agent",
            description="Writes blog posts from news items with brand voice",
            node_type="llm_generate",
            input_keys=["news_item", "company_context", "style_guidelines", "rejection_feedback"],
            output_keys=["draft_post", "seo_metadata", "confidence_score"],
            nullable_output_keys=["rejection_feedback"],  # Optional on first run
            max_retries=config.max_retries,
        )

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """
        Main execution logic for content writing.
        
        Flow:
        1. Load inputs from SharedMemory
        2. Retrieve style guidelines from LTM (if available)
        3. Build context-aware prompt
        4. Generate blog post via LLM
        5. Self-assess quality and confidence
        6. Write outputs to SharedMemory
        """
        import time
        start_time = time.time()
        
        try:
            # ============================================================
            # STEP 1: Load inputs from SharedMemory
            # ============================================================
            news_item = ctx.memory.read("news_item")
            company_context = ctx.memory.read("company_context") or ""
            rejection_feedback = ctx.memory.read("rejection_feedback")  # May be None
            
            if not news_item:
                return NodeResult(
                    success=False,
                    error="Missing required input: news_item",
                )
            
            # ============================================================
            # STEP 2: Retrieve learned style guidelines from LTM
            # ============================================================
            style_guidelines = await self._load_style_guidelines(ctx)
            
            # ============================================================
            # STEP 3: Build the prompt based on context
            # ============================================================
            if rejection_feedback:
                # This is a rewrite attempt - use feedback learning prompt
                prompt = self._build_rewrite_prompt(
                    news_item=news_item,
                    company_context=company_context,
                    style_guidelines=style_guidelines,
                    feedback=rejection_feedback,
                )
                ctx.runtime.decide(
                    node_id=ctx.node_id,
                    intent="Rewrite post incorporating feedback",
                    options=[
                        {"id": "rewrite", "description": "Apply feedback and rewrite"},
                        {"id": "escalate", "description": "Feedback unclear, ask human"},
                    ],
                    chosen="rewrite",
                    reasoning=f"Feedback is actionable: {rejection_feedback[:100]}...",
                )
            else:
                # First attempt - use standard writing prompt
                prompt = self._build_writing_prompt(
                    news_item=news_item,
                    company_context=company_context,
                    style_guidelines=style_guidelines,
                )
            
            # ============================================================
            # STEP 4: Generate blog post via LLM
            # ============================================================
            system_prompt = self._get_system_prompt(style_guidelines)
            
            response = ctx.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=system_prompt,
                max_tokens=ctx.max_tokens,
                json_mode=True,  # Request structured output
            )
            
            # Parse the LLM response
            draft_post = self._parse_llm_response(response.content)
            
            # ============================================================
            # STEP 5: Self-assess quality and confidence
            # ============================================================
            confidence_score = await self._assess_quality(
                ctx=ctx,
                draft=draft_post,
                news_item=news_item,
                style_guidelines=style_guidelines,
            )
            
            # ============================================================
            # STEP 6: Write outputs to SharedMemory
            # ============================================================
            ctx.memory.write("draft_post", draft_post)
            ctx.memory.write("seo_metadata", draft_post.get("seo", {}))
            ctx.memory.write("confidence_score", confidence_score)
            
            # Record successful outcome
            latency_ms = int((time.time() - start_time) * 1000)
            
            ctx.runtime.record_outcome(
                decision_id=f"{ctx.node_id}_write",
                success=True,
                result={
                    "word_count": len(draft_post.get("body", "").split()),
                    "confidence": confidence_score,
                    "is_rewrite": rejection_feedback is not None,
                },
                summary=f"Generated blog post: '{draft_post.get('title', 'Untitled')}' "
                        f"({confidence_score:.0%} confidence)",
            )
            
            return NodeResult(
                success=True,
                output={
                    "draft_post": draft_post,
                    "seo_metadata": draft_post.get("seo", {}),
                    "confidence_score": confidence_score,
                },
                tokens_used=response.input_tokens + response.output_tokens,
                latency_ms=latency_ms,
            )
            
        except Exception as e:
            return await self.handle_failure(e, ctx)

    async def handle_failure(self, error: Exception, ctx: NodeContext) -> NodeResult:
        """
        Handle different types of failures with appropriate recovery strategies.
        """
        error_str = str(error)
        error_type = type(error).__name__
        
        # ============================================================
        # FAILURE TYPE 1: LLM Rate Limit
        # ============================================================
        if "rate_limit" in error_str.lower() or "429" in error_str:
            ctx.runtime.report_problem(
                node_id=ctx.node_id,
                problem_type="rate_limit",
                description="LLM API rate limited",
                severity="warning",
            )
            return NodeResult(
                success=False,
                error="Rate limited - will retry with backoff",
                # Framework will automatically retry based on node_spec.max_retries
            )
        
        # ============================================================
        # FAILURE TYPE 2: Content Filter / Safety
        # ============================================================
        if "content_filter" in error_str.lower() or "safety" in error_str.lower():
            ctx.runtime.report_problem(
                node_id=ctx.node_id,
                problem_type="content_filter",
                description=f"Content blocked by safety filter: {error_str}",
                severity="error",
            )
            # Don't retry - the content itself is problematic
            return NodeResult(
                success=False,
                error="Content blocked by safety filter - requires human review",
            )
        
        # ============================================================
        # FAILURE TYPE 3: Invalid LLM Response (parsing error)
        # ============================================================
        if "json" in error_str.lower() or "parse" in error_str.lower():
            ctx.runtime.report_problem(
                node_id=ctx.node_id,
                problem_type="parse_error",
                description="Failed to parse LLM response as JSON",
                severity="warning",
            )
            # Retry - LLM might produce valid JSON on next attempt
            return NodeResult(
                success=False,
                error="Failed to parse response - retrying",
            )
        
        # ============================================================
        # FAILURE TYPE 4: Unknown Error
        # ============================================================
        ctx.runtime.report_problem(
            node_id=ctx.node_id,
            problem_type="unknown",
            description=f"Unexpected error: {error_type}: {error_str}",
            severity="error",
        )
        return NodeResult(
            success=False,
            error=f"Unexpected error: {error_str}",
        )

    async def learn_from_feedback(
        self, 
        feedback: str, 
        rejected_draft: dict,
        ctx: NodeContext,
    ) -> dict:
        """
        Process rejection feedback and update LTM for future improvement.
        
        This is called by the Feedback Learner Agent, but the logic
        lives here since it's specific to content writing.
        
        Returns:
            dict with learning_summary and rewrite_instructions
        """
        # ============================================================
        # STEP 1: Classify the feedback
        # ============================================================
        classification_prompt = f"""Analyze this rejection feedback for a blog post.

Feedback: {feedback}

Classify into one or more categories:
- tone_mismatch: Wrong tone/voice for brand
- too_technical: Language too complex for audience
- too_promotional: Too sales-focused, not educational
- factual_error: Incorrect information
- structure_issue: Poor organization or flow
- length_issue: Too long or too short
- off_topic: Doesn't match the news item
- other: Describe the issue

Output JSON:
{{
    "categories": ["category1", "category2"],
    "specific_issues": ["issue1", "issue2"],
    "suggested_fixes": ["fix1", "fix2"]
}}"""
        
        response = ctx.llm.complete(
            messages=[{"role": "user", "content": classification_prompt}],
            system="You analyze content feedback and extract actionable insights.",
            json_mode=True,
        )
        
        classification = self._parse_llm_response(response.content)
        
        # ============================================================
        # STEP 2: Update LTM with learned patterns
        # ============================================================
        # Load existing patterns
        existing_patterns = await self._load_from_ltm(ctx, "rejection_patterns") or {
            "bad_phrases": [],
            "tone_issues": [],
            "structure_issues": [],
        }
        
        # Add new learnings
        for category in classification.get("categories", []):
            if category == "tone_mismatch":
                existing_patterns["tone_issues"].append({
                    "feedback": feedback,
                    "draft_excerpt": rejected_draft.get("body", "")[:200],
                    "fix": classification.get("suggested_fixes", [])[0] if classification.get("suggested_fixes") else "",
                })
            elif category == "too_promotional":
                # Extract promotional phrases to avoid
                existing_patterns["bad_phrases"].extend(
                    self._extract_promotional_phrases(rejected_draft.get("body", ""))
                )
        
        # Save updated patterns to LTM
        await self._save_to_ltm(ctx, "rejection_patterns", existing_patterns)
        
        # ============================================================
        # STEP 3: Generate rewrite instructions
        # ============================================================
        rewrite_instructions = {
            "focus_areas": classification.get("categories", []),
            "specific_changes": classification.get("suggested_fixes", []),
            "avoid": existing_patterns.get("bad_phrases", [])[-10:],  # Last 10 bad phrases
        }
        
        return {
            "learning_summary": f"Learned {len(classification.get('categories', []))} patterns from rejection",
            "rewrite_instructions": rewrite_instructions,
            "classification": classification,
        }

    # ================================================================
    # PRIVATE HELPER METHODS
    # ================================================================
    
    async def _load_style_guidelines(self, ctx: NodeContext) -> dict:
        """Load style guidelines from LTM, with defaults."""
        guidelines = await self._load_from_ltm(ctx, "style_guidelines")
        
        if not guidelines:
            # Default guidelines
            guidelines = {
                "voice": "professional yet approachable",
                "avoid_phrases": ["synergy", "leverage", "circle back"],
                "structure": "intro, 3-4 main points, conclusion with CTA",
                "example_posts": [],
            }
        
        return guidelines

    def _get_system_prompt(self, style_guidelines: dict) -> str:
        """Build the system prompt with current style guidelines."""
        return f"""You are a professional content writer for {self.config.company_name}.

Your writing style is: {style_guidelines.get('voice', 'professional yet approachable')}

Guidelines:
- Write for a {self.config.target_reading_level}
- Target length: {self.config.min_word_count}-{self.config.max_word_count} words
- Structure: {style_guidelines.get('structure', 'intro, main points, conclusion')}
- AVOID these phrases: {', '.join(style_guidelines.get('avoid_phrases', []))}

Output your response as JSON with this structure:
{{
    "title": "Engaging blog post title",
    "body": "Full blog post content in markdown",
    "excerpt": "2-3 sentence summary for previews",
    "tags": ["tag1", "tag2", "tag3"],
    "seo": {{
        "meta_description": "155 character meta description",
        "keywords": ["keyword1", "keyword2"]
    }}
}}"""

    def _build_writing_prompt(
        self,
        news_item: dict,
        company_context: str,
        style_guidelines: dict,
    ) -> str:
        """Build the prompt for initial content writing."""
        return f"""Write an engaging blog post based on this news item.

NEWS ITEM:
Title: {news_item.get('title', 'No title')}
Summary: {news_item.get('summary', 'No summary')}
Source: {news_item.get('source_url', 'Unknown')}
Date: {news_item.get('publish_date', 'Unknown')}

COMPANY CONTEXT:
{company_context or 'No additional context provided.'}

REQUIREMENTS:
1. Make the post educational, not promotional
2. Include relevant insights for our audience
3. Reference the source appropriately
4. End with a thought-provoking question or call-to-action

{self._format_example_posts(style_guidelines.get('example_posts', []))}"""

    def _build_rewrite_prompt(
        self,
        news_item: dict,
        company_context: str,
        style_guidelines: dict,
        feedback: str,
    ) -> str:
        """Build the prompt for rewriting after rejection."""
        return f"""Rewrite this blog post based on the feedback received.

ORIGINAL NEWS ITEM:
Title: {news_item.get('title', 'No title')}
Summary: {news_item.get('summary', 'No summary')}

REJECTION FEEDBACK:
{feedback}

WHAT TO FIX:
- Carefully address each point in the feedback
- Maintain the core message while fixing the issues
- Double-check against our style guidelines

COMPANY CONTEXT:
{company_context or 'No additional context provided.'}

Write an improved version that addresses the feedback."""

    def _format_example_posts(self, examples: list) -> str:
        """Format example posts for few-shot learning."""
        if not examples:
            return ""
        
        formatted = "\nEXAMPLE APPROVED POSTS (match this style):\n"
        for i, example in enumerate(examples[:2], 1):  # Max 2 examples
            formatted += f"\n--- Example {i} ---\n"
            formatted += f"Title: {example.get('title', '')}\n"
            formatted += f"Excerpt: {example.get('excerpt', '')}\n"
        
        return formatted

    def _parse_llm_response(self, content: str) -> dict:
        """Parse LLM response, handling various formats."""
        import json
        import re
        
        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code block
        code_block = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', content)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try finding JSON object with brace matching
        # (Uses framework's find_json_object helper)
        from framework.graph.node import find_json_object
        json_str = find_json_object(content)
        if json_str:
            return json.loads(json_str)
        
        raise ValueError(f"Could not parse LLM response as JSON: {content[:200]}...")

    async def _assess_quality(
        self,
        ctx: NodeContext,
        draft: dict,
        news_item: dict,
        style_guidelines: dict,
    ) -> float:
        """Self-assess the quality of the generated draft."""
        body = draft.get("body", "")
        word_count = len(body.split())
        
        # Basic checks (0-0.4 score)
        score = 0.0
        
        # Word count check
        if self.config.min_word_count <= word_count <= self.config.max_word_count:
            score += 0.15
        elif word_count > self.config.min_word_count * 0.8:
            score += 0.1
        
        # Has required fields
        if all(draft.get(k) for k in ["title", "body", "excerpt", "tags"]):
            score += 0.15
        
        # Check for avoided phrases
        avoided = style_guidelines.get("avoid_phrases", [])
        body_lower = body.lower()
        violations = sum(1 for phrase in avoided if phrase.lower() in body_lower)
        if violations == 0:
            score += 0.1
        
        # LLM self-assessment (0-0.6 score)
        assessment_prompt = f"""Rate this blog post on a scale of 0-10 for each criterion:

POST TITLE: {draft.get('title', '')}
POST BODY (first 500 chars): {body[:500]}...

ORIGINAL NEWS: {news_item.get('title', '')}

Rate:
1. Relevance to news item (0-10)
2. Readability and flow (0-10)
3. Brand voice alignment (0-10)

Output JSON: {{"relevance": X, "readability": X, "voice": X}}"""
        
        try:
            response = ctx.llm.complete(
                messages=[{"role": "user", "content": assessment_prompt}],
                system="You assess content quality objectively. Be critical.",
                max_tokens=100,
                json_mode=True,
            )
            ratings = self._parse_llm_response(response.content)
            
            # Average the ratings (normalized to 0-0.6)
            avg_rating = (
                ratings.get("relevance", 5) +
                ratings.get("readability", 5) +
                ratings.get("voice", 5)
            ) / 3
            score += (avg_rating / 10) * 0.6
            
        except Exception:
            # If self-assessment fails, use conservative estimate
            score += 0.3
        
        return min(score, 1.0)

    async def _load_from_ltm(self, ctx: NodeContext, key: str) -> Any:
        """Load a value from Long-Term Memory."""
        # In real implementation, this would use the LTM tool
        # For now, simulate with a tool call
        if hasattr(ctx, 'tool_executor') and ctx.tool_executor:
            try:
                result = await ctx.tool_executor("ltm_retrieve", {"key": key})
                return result
            except Exception:
                return None
        return None

    async def _save_to_ltm(self, ctx: NodeContext, key: str, value: Any) -> bool:
        """Save a value to Long-Term Memory."""
        if hasattr(ctx, 'tool_executor') and ctx.tool_executor:
            try:
                await ctx.tool_executor("ltm_store", {"key": key, "value": value})
                return True
            except Exception:
                return False
        return False

    def _extract_promotional_phrases(self, text: str) -> list[str]:
        """Extract promotional phrases from rejected content."""
        # Common promotional patterns
        promotional_patterns = [
            r"buy now",
            r"limited time",
            r"don't miss",
            r"act fast",
            r"exclusive offer",
            r"best in class",
            r"industry leading",
            r"revolutionary",
        ]
        
        import re
        found = []
        text_lower = text.lower()
        for pattern in promotional_patterns:
            if re.search(pattern, text_lower):
                found.append(pattern)
        
        return found
```

---

## Task 3.2: Prompt Engineering 📝

### 1. System Prompt

```
SYSTEM PROMPT:
You are a professional content writer for {company_name}, creating blog posts that 
inform and engage our audience.

VOICE & TONE:
- Professional yet approachable - like explaining to a smart friend
- Educational focus - teach, don't sell
- Confident but not arrogant
- Use "we" for company, "you" for reader

STRUCTURE REQUIREMENTS:
- Compelling headline that promises value (not clickbait)
- Opening hook: Start with a surprising fact, question, or relatable scenario
- Body: 3-4 main points with clear subheadings
- Each point should have: claim → evidence → implication for reader
- Conclusion: Summarize key takeaway + thought-provoking question OR clear CTA

FORMATTING:
- Use markdown formatting
- Include bullet points for lists
- Keep paragraphs short (3-4 sentences max)
- Target reading level: 8th grade (Flesch-Kincaid)

AVOID:
- Promotional language: "buy now", "limited time", "don't miss out"
- Jargon without explanation
- Passive voice (use active voice)
- These phrases: {avoid_phrases_list}

LENGTH: {min_words}-{max_words} words

OUTPUT FORMAT:
Always respond with valid JSON containing:
{
    "title": "Your engaging headline here",
    "body": "Full post content in markdown",
    "excerpt": "2-3 sentence preview (max 160 chars)",
    "tags": ["relevant", "tags", "max-5"],
    "seo": {
        "meta_description": "155 char description with primary keyword",
        "keywords": ["primary keyword", "secondary", "tertiary"]
    }
}
```

---

### 2. Task Prompt Template

```
TASK PROMPT TEMPLATE:

Write an engaging blog post based on the following news about our company.

═══════════════════════════════════════════════════════════════════════════
📰 NEWS ITEM
═══════════════════════════════════════════════════════════════════════════
Title: {news_item.title}
Source: {news_item.source_url}
Published: {news_item.publish_date}

Summary:
{news_item.summary}

═══════════════════════════════════════════════════════════════════════════
🏢 COMPANY CONTEXT
═══════════════════════════════════════════════════════════════════════════
{company_context}

═══════════════════════════════════════════════════════════════════════════
✍️ YOUR TASK
═══════════════════════════════════════════════════════════════════════════
Transform this news into a valuable blog post for our audience:
- Our readers are: {target_audience}
- They care about: {audience_interests}

Requirements:
1. Don't just summarize the news - add insights and context
2. Explain why this matters to our readers
3. Include 1-2 relevant examples or analogies
4. End with an engaging question or actionable takeaway
5. Naturally incorporate SEO keywords: {target_keywords}

{example_section}
```

---

### 3. Feedback Learning Prompt

```
FEEDBACK LEARNING PROMPT:

Your previous blog post was REJECTED by the editorial team.

═══════════════════════════════════════════════════════════════════════════
❌ REJECTION FEEDBACK
═══════════════════════════════════════════════════════════════════════════
{human_feedback}

═══════════════════════════════════════════════════════════════════════════
📄 YOUR REJECTED DRAFT
═══════════════════════════════════════════════════════════════════════════
Title: {rejected_draft.title}

Body (excerpt):
{rejected_draft.body[:1000]}...

═══════════════════════════════════════════════════════════════════════════
📰 ORIGINAL NEWS ITEM
═══════════════════════════════════════════════════════════════════════════
{news_item.title}
{news_item.summary}

═══════════════════════════════════════════════════════════════════════════
🔄 REWRITE INSTRUCTIONS
═══════════════════════════════════════════════════════════════════════════
Analyze the feedback carefully and rewrite the post:

1. IDENTIFY THE ISSUES
   - What specific problems did the reviewer mention?
   - What implicit issues might they have noticed?

2. PLAN YOUR FIX
   - For each issue, how will you address it?
   - What should you keep from the original?

3. REWRITE
   - Apply all fixes while maintaining the core message
   - Ensure the new version clearly addresses each feedback point

4. SELF-CHECK
   - Before submitting, verify each feedback point is addressed
   - Confirm the post still meets all standard requirements

Write the improved version now.
```

---

### 4. Quality Self-Assessment Prompt

```
QUALITY SELF-ASSESSMENT PROMPT:

Rate this blog post objectively on each criterion.
Be critical - this assessment determines if the post goes to human review.

═══════════════════════════════════════════════════════════════════════════
📄 POST TO ASSESS
═══════════════════════════════════════════════════════════════════════════
Title: {draft.title}
Word Count: {word_count}

Body:
{draft.body}

═══════════════════════════════════════════════════════════════════════════
📰 ORIGINAL NEWS (for relevance check)
═══════════════════════════════════════════════════════════════════════════
{news_item.title}: {news_item.summary}

═══════════════════════════════════════════════════════════════════════════
📊 RATE EACH CRITERION (0-10)
═══════════════════════════════════════════════════════════════════════════
Consider:

1. RELEVANCE (0-10)
   - Does it accurately reflect the news item?
   - Is the angle appropriate for our audience?
   - 10 = perfectly on-topic, 0 = completely unrelated

2. READABILITY (0-10)
   - Is it easy to follow?
   - Good structure and flow?
   - Appropriate reading level?
   - 10 = crystal clear, 0 = confusing mess

3. BRAND VOICE (0-10)
   - Does it sound like our company?
   - Educational, not promotional?
   - Professional yet approachable?
   - 10 = perfect brand voice, 0 = completely off-brand

4. ENGAGEMENT (0-10)
   - Compelling headline?
   - Strong hook?
   - Would readers share this?
   - 10 = highly shareable, 0 = boring

Output JSON:
{
    "relevance": <0-10>,
    "readability": <0-10>,
    "voice": <0-10>,
    "engagement": <0-10>,
    "concerns": ["any specific issues noticed"],
    "strengths": ["what works well"]
}
```

---

## Task 3.3: Tool Definitions 🔧

### Tool 1: Search Company Knowledge Base

```python
{
    "name": "search_company_knowledge",
    "description": "Search the internal company knowledge base for relevant context, "
                   "facts, and background information. Use this to ground blog posts "
                   "in accurate company information.",
    "parameters": {
        "query": {
            "type": "string",
            "description": "Search query - can be keywords or natural language question",
            "required": True
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results to return",
            "default": 5
        },
        "doc_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Filter by document types: 'press_release', 'product_doc', "
                          "'blog_post', 'faq', 'policy'",
            "default": None
        }
    },
    "returns": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "title": "Document title",
                "content": "Relevant excerpt (max 500 chars)",
                "source": "Document URL or ID",
                "relevance_score": "0-1 relevance score",
                "doc_type": "Type of document"
            }
        }
    },
    "example_usage": """
# Find context about a product launch
results = await tool_executor("search_company_knowledge", {
    "query": "Q4 2025 product launch features",
    "limit": 3,
    "doc_types": ["press_release", "product_doc"]
})

# Results:
[
    {
        "title": "Acme Corp Launches AI Assistant v2.0",
        "content": "Today we announced AI Assistant v2.0 featuring...",
        "source": "press/2025-10-15-ai-assistant-launch.md",
        "relevance_score": 0.92,
        "doc_type": "press_release"
    },
    ...
]
"""
}
```

---

### Tool 2: Web Search (for research)

```python
{
    "name": "web_search",
    "description": "Search the web for additional context, industry news, competitor "
                   "information, or fact verification. Use sparingly - prefer company "
                   "knowledge base for internal facts.",
    "parameters": {
        "query": {
            "type": "string",
            "description": "Search query",
            "required": True
        },
        "num_results": {
            "type": "integer",
            "description": "Number of results to return",
            "default": 5,
            "maximum": 10
        },
        "search_type": {
            "type": "string",
            "enum": ["general", "news", "academic"],
            "description": "Type of search to perform",
            "default": "general"
        },
        "time_range": {
            "type": "string",
            "enum": ["day", "week", "month", "year", "all"],
            "description": "Limit results to time range",
            "default": "all"
        }
    },
    "returns": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "title": "Page title",
                "url": "Page URL",
                "snippet": "Search result snippet",
                "published_date": "Publication date if available"
            }
        }
    },
    "example_usage": """
# Research industry context for a blog post
results = await tool_executor("web_search", {
    "query": "enterprise AI adoption trends 2026",
    "search_type": "news",
    "time_range": "month",
    "num_results": 5
})

# Verify a fact before including in blog post
verification = await tool_executor("web_search", {
    "query": "Gartner AI market size 2026 prediction",
    "search_type": "general",
    "num_results": 3
})
"""
}
```

---

### Tool 3: LTM Store (Long-Term Memory)

```python
{
    "name": "ltm_store",
    "description": "Store learned patterns, preferences, and knowledge in Long-Term "
                   "Memory for future use. Data persists across executions and helps "
                   "the agent improve over time.",
    "parameters": {
        "key": {
            "type": "string",
            "description": "Unique identifier for the stored data. Use namespaced keys "
                          "like 'style_guidelines', 'rejection_patterns', 'good_examples'",
            "required": True
        },
        "value": {
            "type": "any",
            "description": "Data to store. Can be string, number, array, or object.",
            "required": True
        },
        "merge_strategy": {
            "type": "string",
            "enum": ["replace", "append", "merge_dict"],
            "description": "How to combine with existing data: 'replace' overwrites, "
                          "'append' adds to array, 'merge_dict' deep merges objects",
            "default": "replace"
        },
        "ttl_days": {
            "type": "integer",
            "description": "Time-to-live in days. After this, data may be archived.",
            "default": None
        }
    },
    "returns": {
        "type": "object",
        "properties": {
            "success": "boolean - whether store succeeded",
            "key": "The key that was stored",
            "previous_value": "Previous value if overwritten (null if new)"
        }
    },
    "example_usage": """
# Store a learned pattern from rejection feedback
await tool_executor("ltm_store", {
    "key": "rejection_patterns",
    "value": {
        "tone_issues": [
            {"feedback": "Too promotional", "fix": "Focus on education"}
        ],
        "bad_phrases": ["buy now", "limited time"]
    },
    "merge_strategy": "merge_dict"
})

# Store an approved post as a good example
await tool_executor("ltm_store", {
    "key": "good_examples",
    "value": {
        "title": "How AI is Transforming Customer Support",
        "excerpt": "A deep dive into practical AI applications...",
        "approval_date": "2026-01-29"
    },
    "merge_strategy": "append"
})
"""
}
```

---

### Tool 4: LTM Retrieve

```python
{
    "name": "ltm_retrieve",
    "description": "Retrieve previously stored patterns, preferences, and knowledge "
                   "from Long-Term Memory. Use this to load learned behaviors and "
                   "apply past learnings to current tasks.",
    "parameters": {
        "key": {
            "type": "string",
            "description": "Key to retrieve. Use same namespaced keys as ltm_store.",
            "required": True
        },
        "default": {
            "type": "any",
            "description": "Default value to return if key doesn't exist",
            "default": None
        }
    },
    "returns": {
        "type": "any",
        "description": "The stored value, or default if not found"
    },
    "example_usage": """
# Load style guidelines before writing
guidelines = await tool_executor("ltm_retrieve", {
    "key": "style_guidelines",
    "default": {
        "voice": "professional yet approachable",
        "avoid_phrases": [],
        "structure": "intro, main points, conclusion"
    }
})

# Load rejection patterns to avoid repeating mistakes
patterns = await tool_executor("ltm_retrieve", {
    "key": "rejection_patterns",
    "default": {"tone_issues": [], "bad_phrases": []}
})

# Check phrases to avoid
for phrase in patterns["bad_phrases"]:
    if phrase in draft_body:
        # Flag for revision
        pass
"""
}
```

---

### Tool 5: SEO Analyzer

```python
{
    "name": "seo_analyzer",
    "description": "Analyze content for SEO best practices. Returns scores and "
                   "suggestions for improving search engine visibility.",
    "parameters": {
        "content": {
            "type": "object",
            "description": "Content to analyze",
            "required": True,
            "properties": {
                "title": "Page/post title",
                "body": "Main content",
                "meta_description": "Meta description",
                "target_keywords": "List of target keywords"
            }
        },
        "checks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific checks to run: 'keyword_density', 'readability', "
                          "'meta_tags', 'headings', 'links', 'images'",
            "default": ["keyword_density", "readability", "meta_tags", "headings"]
        }
    },
    "returns": {
        "type": "object",
        "properties": {
            "overall_score": "0-100 SEO score",
            "checks": {
                "keyword_density": {
                    "score": "0-100",
                    "current": "Current density %",
                    "recommended": "Recommended density %",
                    "suggestion": "How to improve"
                },
                "readability": {
                    "score": "0-100",
                    "flesch_kincaid_grade": "Reading grade level",
                    "suggestion": "How to improve"
                },
                "meta_tags": {
                    "score": "0-100",
                    "title_length": "Current title length",
                    "meta_length": "Current meta description length",
                    "suggestion": "How to improve"
                },
                "headings": {
                    "score": "0-100",
                    "h1_count": "Number of H1 tags",
                    "heading_structure": "Hierarchy assessment",
                    "suggestion": "How to improve"
                }
            }
        }
    },
    "example_usage": """
# Analyze draft before submission
seo_results = await tool_executor("seo_analyzer", {
    "content": {
        "title": draft["title"],
        "body": draft["body"],
        "meta_description": draft["seo"]["meta_description"],
        "target_keywords": ["AI customer support", "automation"]
    },
    "checks": ["keyword_density", "readability", "meta_tags"]
})

if seo_results["overall_score"] < 70:
    # Apply suggestions and regenerate
    suggestions = [c["suggestion"] for c in seo_results["checks"].values()]
"""
}
```

---

## Source Files Referenced

| Topic | Source File |
|-------|-------------|
| NodeSpec & NodeContext | [core/framework/graph/node.py](core/framework/graph/node.py) |
| NodeResult structure | [core/framework/graph/node.py#L460-L490](core/framework/graph/node.py) |
| JSON parsing helpers | [core/framework/graph/node.py#L30-L120](core/framework/graph/node.py) (`find_json_object`, `_fix_unescaped_newlines_in_json`) |
| Runtime.decide() pattern | [core/framework/runtime/core.py](core/framework/runtime/core.py) |
| Tool definition format | [core/framework/llm/provider.py](core/framework/llm/provider.py) (`Tool` dataclass) |
| Available MCP tools | [tools/README.md](tools/README.md) |
| Challenge requirements | [docs/quizzes/03-build-your-first-agent.md](docs/quizzes/03-build-your-first-agent.md) |
