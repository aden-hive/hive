 # Build Your First Agent Challenge - Part 2 Answers

## Task 2.1: Design a Multi-Agent System 🎭

### Content Marketing Agent System

**Goal:** Automatically create and publish blog posts based on company news

---

### Agent Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         CONTENT MARKETING AGENT SYSTEM                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│    ┌──────────────┐                                                             │
│    │  RSS Feed    │ (External Trigger)                                          │
│    │  Webhook     │                                                             │
│    └──────┬───────┘                                                             │
│           │                                                                     │
│           ▼                                                                     │
│    ┌──────────────────┐                                                         │
│    │  NEWS MONITOR    │  Worker Agent #1                                        │
│    │     AGENT        │                                                         │
│    │                  │  • Monitors RSS/webhooks                                │
│    │  node_type:      │  • Extracts news content                                │
│    │  llm_tool_use    │  • Filters relevant items                               │
│    └────────┬─────────┘                                                         │
│             │ on_success                                                        │
│             │ {news_item, company_context}                                      │
│             ▼                                                                   │
│    ┌──────────────────┐                                                         │
│    │  CONTENT WRITER  │  Worker Agent #2                                        │
│    │     AGENT        │                                                         │
│    │                  │  • Researches topic                                     │
│    │  node_type:      │  • Writes blog draft                                    │
│    │  llm_generate    │  • Applies brand voice                                  │
│    └────────┬─────────┘                                                         │
│             │ on_success                                                        │
│             │ {draft_post, metadata}                                            │
│             ▼                                                                   │
│    ┌──────────────────┐                                                         │
│    │  QUALITY REVIEW  │  Worker Agent #3                                        │
│    │     AGENT        │                                                         │
│    │                  │  • Checks facts                                         │
│    │  node_type:      │  • Validates SEO                                        │
│    │  llm_tool_use    │  • Scores quality                                       │
│    └────────┬─────────┘                                                         │
│             │                                                                   │
│             ▼                                                                   │
│    ┌──────────────────┐     on_failure (confidence < 0.7)                       │
│    │     ROUTER       │─────────────────────────────────┐                       │
│    │                  │                                 │                       │
│    │  node_type:      │                                 ▼                       │
│    │  router          │                     ┌──────────────────┐                │
│    └────────┬─────────┘                     │  CONTENT WRITER  │                │
│             │ on_success                    │  (retry with     │                │
│             │ (quality_score >= 0.7)        │   feedback)      │                │
│             ▼                               └──────────────────┘                │
│    ┌──────────────────┐                                                         │
│    │  🙋 HUMAN        │  HITL Checkpoint                                        │
│    │  APPROVAL NODE   │                                                         │
│    │                  │  • Shows draft to marketing team                        │
│    │  node_type:      │  • Collects approve/reject/modify                       │
│    │  human_input     │  • Timeout: 24 hours                                    │
│    └────────┬─────────┘                                                         │
│             │                                                                   │
│    ┌────────┴─────────┐                                                         │
│    │                  │                                                         │
│    ▼ approved         ▼ rejected                                                │
│  ┌─────────────┐   ┌──────────────────┐                                         │
│  │ PUBLISHER   │   │ FEEDBACK LEARNER │                                         │
│  │   AGENT     │   │     AGENT        │                                         │
│  │             │   │                  │  Worker Agent #4                        │
│  │ node_type:  │   │  • Stores feedback in LTM                                  │
│  │ function    │   │  • Updates style guidelines                                │
│  └─────────────┘   │  • Triggers rewrite                                        │
│        │           └────────┬─────────┘                                         │
│        │                    │                                                   │
│        ▼                    ▼                                                   │
│  ┌─────────────┐   ┌──────────────────┐                                         │
│  │  SUCCESS    │   │  CONTENT WRITER  │                                         │
│  │  (END)      │   │  (retry loop)    │                                         │
│  │             │   │  max_retries: 3  │                                         │
│  │ Post live!  │   └──────────────────┘                                         │
│  └─────────────┘                                                                │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### Agent Descriptions

#### 1. News Monitor Agent

| Attribute | Description |
|-----------|-------------|
| **Name** | `news_monitor_agent` |
| **Role** | Monitors RSS feeds and webhooks for company news, filters relevance, extracts structured content |
| **Node Type** | `llm_tool_use` |
| **Inputs** | `rss_feed_url`, `webhook_payload`, `relevance_criteria` |
| **Outputs** | `news_item` (title, summary, source_url, publish_date), `company_context`, `relevance_score` |
| **Tools** | `web_scrape`, `rss_fetch`, `search_company_knowledge` |
| **System Prompt** | "You monitor company news sources and extract relevant news items. Filter out items that don't relate to {company_topics}. Extract key facts and context." |

**Failure Scenarios:**
| Failure | Cause | Recovery |
|---------|-------|----------|
| RSS feed unavailable | Network/server down | Retry with exponential backoff (3 attempts), then alert |
| No relevant news found | Feed empty or off-topic | Return empty result, don't trigger downstream |
| Duplicate news item | Already processed | Check against processed_items in SharedMemory, skip duplicates |

---

#### 2. Content Writer Agent

| Attribute | Description |
|-----------|-------------|
| **Name** | `content_writer_agent` |
| **Role** | Writes engaging blog posts from news items, applies brand voice, incorporates SEO keywords |
| **Node Type** | `llm_generate` |
| **Inputs** | `news_item`, `company_context`, `style_guidelines` (from LTM), `rejection_feedback` (optional) |
| **Outputs** | `draft_post` (title, body, excerpt, tags), `seo_metadata`, `confidence_score` |
| **Tools** | `search_company_knowledge`, `web_search` (for research) |
| **System Prompt** | "You are a professional content writer for {company_name}. Write engaging blog posts that match our brand voice: {voice_guidelines}. If feedback is provided, incorporate it to improve your writing." |

**Failure Scenarios:**
| Failure | Cause | Recovery |
|---------|-------|----------|
| LLM rate limit | Too many requests | Queue request, retry after backoff |
| Content too short/long | Poor prompt following | Validate output length, retry with explicit constraints |
| Off-brand tone | Style drift | Load style examples from LTM, retry with stronger guidance |
| Hallucinated facts | LLM confabulation | Quality Review Agent catches this → triggers rewrite |

---

#### 3. Quality Review Agent

| Attribute | Description |
|-----------|-------------|
| **Name** | `quality_review_agent` |
| **Role** | Reviews drafts for factual accuracy, brand alignment, SEO optimization, and readability |
| **Node Type** | `llm_tool_use` |
| **Inputs** | `draft_post`, `news_item` (for fact-checking), `brand_guidelines` |
| **Outputs** | `quality_score` (0-1), `review_feedback`, `seo_score`, `fact_check_results`, `approved` (bool) |
| **Tools** | `web_search` (fact verification), `seo_analyzer`, `readability_scorer` |
| **System Prompt** | "You are a content quality reviewer. Check the blog post for: 1) Factual accuracy against source, 2) Brand voice alignment, 3) SEO best practices, 4) Readability. Score each area and provide actionable feedback." |

**Failure Scenarios:**
| Failure | Cause | Recovery |
|---------|-------|----------|
| Can't verify facts | Sources unavailable | Flag as "unverified", escalate to human |
| SEO tool API down | External service failure | Skip SEO check, proceed with warning |
| Conflicting quality signals | High readability but poor facts | Use weighted scoring, prioritize factual accuracy |

---

#### 4. Feedback Learner Agent

| Attribute | Description |
|-----------|-------------|
| **Name** | `feedback_learner_agent` |
| **Role** | Processes human rejection feedback, updates LTM with learned patterns, improves future writing |
| **Node Type** | `llm_tool_use` |
| **Inputs** | `rejected_draft`, `human_feedback`, `rejection_reason` |
| **Outputs** | `learning_summary`, `updated_guidelines`, `rewrite_instructions` |
| **Tools** | `ltm_store`, `ltm_retrieve`, `pattern_analyzer` |
| **System Prompt** | "Analyze why this content was rejected. Extract patterns we can learn from. Update our style guidelines to prevent similar rejections. Generate specific instructions for the rewrite." |

**Failure Scenarios:**
| Failure | Cause | Recovery |
|---------|-------|----------|
| Vague feedback | Human said "not good enough" | Ask follow-up questions via HITL |
| Contradictory feedback | Different reviewers disagree | Store both patterns, use majority rule |
| LTM storage failure | Database error | Log to fallback storage, alert operations |

---

### Human Checkpoints

| Checkpoint | Location | Purpose | Timeout | Escalation |
|------------|----------|---------|---------|------------|
| **Pre-Publish Approval** | After Quality Review | Marketing team reviews final draft | 24 hours | Auto-escalate to marketing lead |
| **Low Confidence Review** | After Content Writer (if confidence < 0.5) | Human reviews uncertain content | 4 hours | Skip this news item |
| **Rejection Clarification** | After vague rejection | Get specific feedback | 2 hours | Use generic "quality" reason |

**HITL Request Example:**
```python
HITLRequest(
    objective="Approve blog post for publication",
    current_state="Draft complete, quality score 0.85",
    questions=[
        HITLQuestion(
            id="approval",
            question="Approve this post for publication?",
            input_type=HITLInputType.APPROVAL,
            options=["Approve", "Reject", "Approve with modifications"]
        ),
        HITLQuestion(
            id="feedback",
            question="If rejecting, what should be changed?",
            input_type=HITLInputType.FREE_TEXT,
            required=False
        )
    ],
    missing_info=["Final human judgment on brand alignment"]
)
```

---

### Self-Improvement Mechanism

```
┌─────────────────────────────────────────────────────────────┐
│                   SELF-IMPROVEMENT LOOP                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. CAPTURE FAILURE                                         │
│     ┌─────────────────────────────────────────────────┐     │
│     │ Human rejects post with feedback:               │     │
│     │ "Too promotional, needs more educational value" │     │
│     └─────────────────────────────────────────────────┘     │
│                           │                                 │
│                           ▼                                 │
│  2. ANALYZE & CLASSIFY                                      │
│     ┌─────────────────────────────────────────────────┐     │
│     │ Feedback Learner Agent classifies:              │     │
│     │ - Type: "tone_mismatch"                         │     │
│     │ - Pattern: "promotional_language"               │     │
│     │ - Fix: "focus on teaching, not selling"         │     │
│     └─────────────────────────────────────────────────┘     │
│                           │                                 │
│                           ▼                                 │
│  3. UPDATE LTM                                              │
│     ┌─────────────────────────────────────────────────┐     │
│     │ Store in Long-Term Memory:                      │     │
│     │ - style_guidelines += "Avoid promotional tone"  │     │
│     │ - bad_patterns += ["buy now", "limited time"]   │     │
│     │ - good_examples += [approved_posts]             │     │
│     └─────────────────────────────────────────────────┘     │
│                           │                                 │
│                           ▼                                 │
│  4. APPLY TO FUTURE RUNS                                    │
│     ┌─────────────────────────────────────────────────┐     │
│     │ Content Writer Agent loads updated guidelines:  │     │
│     │ - Checks draft against bad_patterns            │     │
│     │ - References good_examples for tone            │     │
│     │ - Quality Agent flags promotional language     │     │
│     └─────────────────────────────────────────────────┘     │
│                           │                                 │
│                           ▼                                 │
│  5. MEASURE IMPROVEMENT                                     │
│     ┌─────────────────────────────────────────────────┐     │
│     │ Track metrics over time:                        │     │
│     │ - Rejection rate: 30% → 15% → 8%               │     │
│     │ - First-pass approval: 40% → 65% → 82%         │     │
│     │ - Avg rewrites needed: 2.1 → 1.3 → 0.9         │     │
│     └─────────────────────────────────────────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**What gets stored for learning:**
- Rejected drafts + feedback (for negative examples)
- Approved posts (for positive examples)
- Common rejection reasons (for pattern detection)
- Reviewer-specific preferences (if multiple approvers)

---

## Task 2.2: Goal Definition 🎯

### Natural Language Goal

```
"Build a content marketing system that automatically creates and publishes 
blog posts whenever news about our company appears in the press.

The system should:
1. Monitor our RSS feeds and news webhooks for mentions of our company
2. Filter out irrelevant or duplicate news items
3. Write engaging, educational blog posts that match our brand voice
4. Have a content quality agent review each draft for accuracy and SEO
5. Send posts to the marketing team for approval before publishing
6. Publish approved posts to our WordPress site with proper formatting

Success criteria:
- Posts should have a quality score of at least 0.7 before human review
- First-pass approval rate should exceed 70% within 30 days
- Published posts should achieve average engagement (comments, shares) 
  comparable to manually written posts

Failure handling:
- If a post is rejected, capture the feedback and use it to improve future posts
- If RSS feeds are unavailable, retry 3 times with exponential backoff
- If the same post is rejected 3 times, archive it and alert the team
- Never publish without human approval

Human touchpoints:
- Marketing team approves all posts before publishing (24-hour timeout)
- Escalate to marketing lead if no response within timeout
- Allow humans to provide modification feedback, not just approve/reject"
```

---

## Task 2.3: Test Cases 📋

| # | Test Case | Input | Expected Output | Success Criteria |
|---|-----------|-------|-----------------|------------------|
| **1** | **Happy Path** | News item: "Acme Corp announces Q4 earnings beat" | Published blog post on WordPress | Post live with correct title, tags, SEO metadata; quality_score >= 0.7; human approved |
| **2** | **Edge Case: Duplicate News** | Same news item submitted twice within 1 hour | Second submission ignored | No duplicate post created; log shows "duplicate detected"; first post proceeds normally |
| **3** | **Edge Case: Minimal News** | News item with only title, no body: "Acme mentioned in TechCrunch" | Draft with researched content | Writer agent uses web_search to gather context; draft has >= 300 words; quality review passes |
| **4** | **Failure: Human Rejection** | Draft post rejected with feedback: "Too technical for our audience" | Post rewritten in simpler language | Feedback stored in LTM; rewrite uses simpler vocabulary; second submission approved |
| **5** | **Failure: LLM Rate Limit** | 10 news items arrive simultaneously, exceeding API limits | All posts eventually processed | Requests queued; exponential backoff applied; all 10 posts created within 1 hour; no data loss |

### Detailed Test Specifications

#### Test 1: Happy Path
```python
def test_happy_path_news_to_published_post():
    """Complete flow from news detection to published post."""
    input_data = {
        "news_item": {
            "title": "Acme Corp Announces Record Q4 Earnings",
            "summary": "Acme Corp reported earnings of $2.5B...",
            "source_url": "https://reuters.com/acme-q4",
            "publish_date": "2026-01-29"
        }
    }
    
    # Mock human approval
    mock_hitl_response = HITLResponse(
        request_id="approval-123",
        answers={"approval": "Approve"}
    )
    
    result = await agent.run(input_data, hitl_responses=[mock_hitl_response])
    
    assert result.success
    assert result.output["post_url"].startswith("https://blog.acme.com/")
    assert result.output["quality_score"] >= 0.7
    assert "Q4" in result.output["post_title"]
```

#### Test 4: Failure - Human Rejection with Learning
```python
def test_rejection_triggers_learning_and_rewrite():
    """Rejected posts should trigger learning and rewrite."""
    input_data = {"news_item": {"title": "Acme launches new API"}}
    
    # First attempt rejected
    rejection_response = HITLResponse(
        answers={
            "approval": "Reject",
            "feedback": "Too technical. Our audience is non-developers."
        }
    )
    
    # Second attempt approved
    approval_response = HITLResponse(
        answers={"approval": "Approve"}
    )
    
    result = await agent.run(
        input_data, 
        hitl_responses=[rejection_response, approval_response]
    )
    
    assert result.success
    assert result.output["rewrites_count"] == 1
    
    # Verify learning was stored
    ltm_entry = await ltm.retrieve("rejection_patterns")
    assert "technical" in ltm_entry["patterns"]
```

#### Test 5: Failure - Rate Limit Recovery
```python
def test_rate_limit_recovery():
    """System should handle LLM rate limits gracefully."""
    # Simulate 10 concurrent news items
    news_items = [{"title": f"News {i}"} for i in range(10)]
    
    # Mock rate limit on first 5 requests
    mock_llm.set_rate_limit_for_next(5)
    
    results = await asyncio.gather(*[
        agent.run({"news_item": item}) 
        for item in news_items
    ])
    
    # All should eventually succeed
    assert all(r.success for r in results)
    
    # Check that backoff was applied
    assert mock_llm.total_retries >= 5
    assert mock_llm.max_concurrent_requests <= 3  # Throttled
```

---

## Source Files Referenced

These answers were informed by analyzing the following codebase files:

| Topic | Source File |
|-------|-------------|
| Node types & NodeSpec | [core/framework/graph/node.py](core/framework/graph/node.py) |
| Edge conditions & routing | [core/framework/graph/edge.py](core/framework/graph/edge.py) |
| HITL protocol & requests | [core/framework/graph/hitl.py](core/framework/graph/hitl.py) |
| Memory isolation levels | [core/framework/runtime/tests/test_agent_runtime.py](core/framework/runtime/tests/test_agent_runtime.py) |
| Multi-entry-point architecture | [docs/architecture/multi-entry-point-agents.md](docs/architecture/multi-entry-point-agents.md) |
| HITL best practices | [docs/articles/human-in-the-loop-ai-agents.md](docs/articles/human-in-the-loop-ai-agents.md) |
| Challenge requirements | [docs/quizzes/03-build-your-first-agent.md](docs/quizzes/03-build-your-first-agent.md) |
| Available MCP tools | [tools/README.md](tools/README.md) |
| Framework overview | [README.md](README.md) |
| SDK-wrapped node capabilities | [DEVELOPER.md](DEVELOPER.md) |
