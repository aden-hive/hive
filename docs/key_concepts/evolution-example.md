# Agent Evolution: A Concrete Example

This document provides a step-by-step walkthrough of how Hive agents evolve after encountering failures at runtime. We'll trace a realistic scenario from initial graph generation through failure, diagnosis, and evolution.

## Overview: The Evolution Cycle in Action

When an agent fails, Hive doesn't just log an error and stop. The framework captures detailed failure data, analyzes what went wrong, and then regenerates an improved version of the agent. Here's what this looks like in practice.

---

## Step 1: Define the Goal

Let's say you want an agent that monitors tech news and sends daily summaries to your email. You describe this goal to the coding agent:

```
"Create an agent that searches for tech news articles about AI and machine learning 
each morning, summarizes the top 5 articles, and emails the summary to me."
```

From this natural language goal, Hive generates:

- **Success Criteria**: What "done" looks like
- **Constraints**: What the agent must never do
- **An initial graph**: The workflow structure

---

## Step 2: The Initial Agent Graph (Version 1.0)

The coding agent generates an initial graph with 4 nodes:

```
search_news → filter_articles → summarize → send_email
```

### Graph Definition (v1.0)

```json
{
  "goal": {
    "id": "tech-news-monitor",
    "name": "Tech News Monitor",
    "description": "Search for AI/ML tech news daily and email a summary of top articles",
    "success_criteria": [
      {
        "id": "relevant-articles",
        "description": "Articles are about AI/ML topics",
        "metric": "topic_relevance",
        "target": ">=0.8"
      },
      {
        "id": "summary-quality",
        "description": "Summaries are concise and capture key points",
        "metric": "summary_score",
        "target": ">=0.75"
      },
      {
        "id": "delivery-success",
        "description": "Email is delivered successfully",
        "metric": "delivery_rate",
        "target": "=1.0"
      }
    ],
    "constraints": [
      {
        "id": "no-paywall-content",
        "description": "Don't include articles behind paywalls",
        "constraint_type": "quality",
        "category": "content_filter"
      },
      {
        "id": "fresh-content",
        "description": "Only include articles from the last 24 hours",
        "constraint_type": "temporal",
        "category": "freshness"
      }
    ]
  },
  "nodes": [
    {
      "id": "search_news",
      "name": "Search News",
      "description": "Search for tech news articles about AI/ML",
      "node_type": "event_loop",
      "system_prompt": "Search for recent tech news articles about AI and machine learning. Use web_search to find articles from the past 24 hours. Return at least 10 article candidates.",
      "tools": ["web_search"],
      "output_keys": ["article_candidates"]
    },
    {
      "id": "filter_articles",
      "name": "Filter Articles",
      "description": "Filter to top 5 most relevant articles",
      "node_type": "event_loop",
      "system_prompt": "Review the article candidates and select the 5 most relevant and interesting ones about AI/ML. Exclude paywalled content.",
      "tools": [],
      "input_keys": ["article_candidates"],
      "output_keys": ["selected_articles"]
    },
    {
      "id": "summarize",
      "name": "Summarize",
      "description": "Create a concise summary of each article",
      "node_type": "event_loop",
      "system_prompt": "For each selected article, write a 2-3 sentence summary capturing the key points.",
      "tools": ["web_scrape"],
      "input_keys": ["selected_articles"],
      "output_keys": ["summaries"]
    },
    {
      "id": "send_email",
      "name": "Send Email",
      "description": "Email the summary to the user",
      "node_type": "event_loop",
      "system_prompt": "Format the summaries into a readable email and send it using the email tool.",
      "tools": ["send_email"],
      "input_keys": ["summaries"],
      "output_keys": ["email_sent"]
    }
  ],
  "edges": [
    {"source": "search_news", "target": "filter_articles", "condition": "on_success"},
    {"source": "filter_articles", "target": "summarize", "condition": "on_success"},
    {"source": "summarize", "target": "send_email", "condition": "on_success"}
  ],
  "entry_node": "search_news",
  "terminal_nodes": ["send_email"]
}
```

### Visual Representation

```
┌──────────────┐     ┌────────────────┐     ┌────────────┐     ┌────────────┐
│ search_news  │ ──▶ │ filter_articles│ ──▶ │  summarize │ ──▶ │ send_email │
└──────────────┘     └────────────────┘     └────────────┘     └────────────┘
     │                      │                     │                   │
     ▼                      ▼                     ▼                   ▼
article_candidates    selected_articles       summaries           email_sent
```

---

## Step 3: Runtime Execution & Failure

The agent runs for the first time. Here's what happens:

### Execution Trace

| Step | Node | Status | Details |
|------|------|--------|---------|
| 1 | search_news | ✅ Success | Found 12 article candidates |
| 2 | filter_articles | ✅ Success | Selected 5 articles |
| 3 | summarize | ❌ **FAILED** | Could not scrape 3 of 5 articles |
| 4 | send_email | ⏸️ Skipped | Dependency failed |

### The Failure

The `summarize` node failed because:

1. **API Rate Limiting**: Two articles were from sites with aggressive rate limiting
2. **Paywall Detection Failure**: One article was behind a soft paywall that wasn't caught in filtering
3. **Missing Content**: Two articles loaded but the content extraction failed

**Decision Log Entry**:

```json
{
  "node_id": "summarize",
  "timestamp": "2026-02-23T08:15:32Z",
  "decision": "retry",
  "reason": "web_scrape returned empty content for 3/5 articles",
  "attempts": 3,
  "final_status": "failed",
  "error_details": {
    "type": "tool_failure",
    "tool": "web_scrape",
    "failed_urls": [
      "https://paywalled-site.com/article1",
      "https://rate-limited-site.com/article2",
      "https://rate-limited-site.com/article3"
    ],
    "errors": [
      {"url": "...", "error": "HTTP 429: Rate limited", "retry_after": 3600},
      {"url": "...", "error": "Paywall detected: subscription required"},
      {"url": "...", "error": "Empty content: JavaScript rendering required"}
    ]
  },
  "success_criteria_status": {
    "summary-quality": {"met": false, "score": 0.3, "reason": "Only 2/5 summaries generated"}
  }
}
```

---

## Step 4: Failure Diagnosis

Hive's evaluation engine analyzes the failure:

### Diagnosis Report

```
FAILURE ANALYSIS: Tech News Monitor v1.0
=========================================

Root Cause: The summarize node depends entirely on web_scrape, but this 
assumes all articles are scrapable. This assumption breaks when:

1. Sites have rate limiting
2. Content is behind paywalls (not detected during filtering)
3. Sites require JavaScript rendering

What Failed:
- Node: summarize
- Success Criterion: summary-quality (score: 0.3, target: >=0.75)
- Constraint Violated: fresh-content (couldn't get content in time)

Why It Failed:
- Filter node doesn't verify scrapability before selection
- Summarize node has no fallback when scraping fails
- No grace period between scraping requests (rate limiting)

Recommended Evolution:
1. Add pre-filtering for paywalled/scrapable content
2. Add fallback mechanism in summarize node
3. Add rate limiting awareness to the scraping process
```

---

## Step 5: Graph Evolution (Version 2.0)

The coding agent receives the diagnosis and regenerates the agent with improvements:

### What Changed

| Component | v1.0 | v2.0 | Why |
|-----------|------|------|-----|
| `filter_articles` prompt | Select 5 most relevant | Select 5 most relevant AND scrapable | Avoid selecting unscrapable articles |
| `summarize` tools | `web_scrape` only | `web_scrape`, `web_search` fallback | Generate summaries from search snippets when full content unavailable |
| New node | - | `validate_content` | Verify articles are accessible before summarizing |
| Edge | filter → summarize | filter → validate → summarize | Add content validation step |
| Edge | summarize: on_success → send | summarize: on_partial → send | Allow sending partial summaries |

### Updated Graph Definition (v2.0)

```json
{
  "version": "2.0.0",
  "evolution_reason": "Added content validation and fallback mechanisms for scraping failures",
  "nodes": [
    {
      "id": "search_news",
      "name": "Search News",
      "description": "Search for tech news articles about AI/ML",
      "node_type": "event_loop",
      "system_prompt": "Search for recent tech news articles about AI and machine learning. Use web_search to find articles from the past 24 hours. Return at least 15 article candidates to allow for filtering.",
      "tools": ["web_search"],
      "output_keys": ["article_candidates"]
    },
    {
      "id": "filter_articles",
      "name": "Filter Articles",
      "description": "Filter to top 5 most relevant AND accessible articles",
      "node_type": "event_loop",
      "system_prompt": "Review the article candidates and select the 5 most relevant articles about AI/ML. IMPORTANT: Check each article URL for signs of paywalls (domains like wsj.com, ft.com, etc.) and exclude them. Prefer articles from accessible sources.",
      "tools": [],
      "input_keys": ["article_candidates"],
      "output_keys": ["selected_articles"]
    },
    {
      "id": "validate_content",
      "name": "Validate Content",
      "description": "Verify articles are scrapable before summarizing",
      "node_type": "event_loop",
      "system_prompt": "For each selected article, attempt to scrape the content. If scraping fails (rate limit, paywall, empty content), mark that article as 'use_snippet_only'. Categorize articles into 'full_content_available' and 'snippet_only' lists.",
      "tools": ["web_scrape"],
      "input_keys": ["selected_articles"],
      "output_keys": ["articles_with_full_content", "articles_snippet_only"]
    },
    {
      "id": "summarize",
      "name": "Summarize",
      "description": "Create summaries using full content or search snippets as fallback",
      "node_type": "event_loop",
      "system_prompt": "For articles with full content: write detailed 2-3 sentence summaries. For articles marked as snippet_only: write brief 1-2 sentence summaries based on the available title and snippet. Always produce summaries for ALL 5 articles.",
      "tools": [],
      "input_keys": ["articles_with_full_content", "articles_snippet_only"],
      "output_keys": ["summaries"],
      "success_criteria": {
        "min_summaries": 5,
        "allow_partial_content": true
      }
    },
    {
      "id": "send_email",
      "name": "Send Email",
      "description": "Email the summary to the user",
      "node_type": "event_loop",
      "system_prompt": "Format the summaries into a readable email. Note which articles had limited content available. Send using the email tool.",
      "tools": ["send_email"],
      "input_keys": ["summaries"],
      "output_keys": ["email_sent"]
    }
  ],
  "edges": [
    {"source": "search_news", "target": "filter_articles", "condition": "on_success"},
    {"source": "filter_articles", "target": "validate_content", "condition": "on_success"},
    {"source": "validate_content", "target": "summarize", "condition": "on_success"},
    {"source": "validate_content", "target": "summarize", "condition": "on_partial", "note": "Continue even if some articles fail validation"},
    {"source": "summarize", "target": "send_email", "condition": "on_success"},
    {"source": "summarize", "target": "send_email", "condition": "on_partial", "note": "Send partial results rather than failing completely"}
  ],
  "entry_node": "search_news",
  "terminal_nodes": ["send_email"]
}
```

### Visual Representation (v2.0)

```
┌──────────────┐     ┌────────────────┐     ┌──────────────────┐     ┌────────────┐     ┌────────────┐
│ search_news  │ ──▶ │ filter_articles│ ──▶ │ validate_content │ ──▶ │  summarize │ ──▶ │ send_email │
└──────────────┘     └────────────────┘     └──────────────────┘     └────────────┘     └────────────┘
     │                      │                        │                      │                  │
     ▼                      ▼                        ▼                      ▼                  ▼
article_candidates    selected_articles    articles_with_full_content    summaries        email_sent
                      (paywall-aware)      articles_snippet_only       (partial OK)
```

---

## Step 6: Re-Execution with Evolved Agent

The v2.0 agent runs again with the same inputs:

### Execution Trace (v2.0)

| Step | Node | Status | Details |
|------|------|--------|---------|
| 1 | search_news | ✅ Success | Found 15 article candidates |
| 2 | filter_articles | ✅ Success | Selected 5 articles (excluded 2 paywalled) |
| 3 | validate_content | ⚠️ Partial | 3 full content, 2 snippet-only |
| 4 | summarize | ✅ Success | Generated 5 summaries (3 detailed, 2 brief) |
| 5 | send_email | ✅ Success | Email delivered with note about 2 partial articles |

### Success Criteria Evaluation (v2.0)

| Criterion | v1.0 Result | v2.0 Result | Target |
|-----------|-------------|-------------|--------|
| relevant-articles | 0.85 | 0.90 | >=0.80 ✅ |
| summary-quality | 0.30 ❌ | 0.78 | >=0.75 ✅ |
| delivery-success | 0 | 1.0 | =1.0 ✅ |

**The agent now succeeds!** Even though 2 articles couldn't be fully scraped, the evolved graph handles this gracefully by falling back to snippet-based summaries.

---

## Key Takeaways

### What Evolution Actually Does

1. **Adds nodes** — The `validate_content` node was added to catch problems early
2. **Modifies prompts** — Filter prompt now checks for paywalled domains
3. **Changes edge conditions** — Added `on_partial` edges to handle degraded states
4. **Adjusts success criteria** — Summarize node now accepts partial results

### What Evolution Does NOT Do

- It doesn't make the agent "smarter" in a general sense
- It doesn't anticipate novel failure modes the agent hasn't seen
- It doesn't change the fundamental goal or success criteria (those remain stable)

### The Feedback Loop

```
Execute → Evaluate → Diagnose → Regenerate → Deploy → Execute → ...
```

Each cycle makes the agent more robust against the specific failure modes it has encountered. Over generations, the agent becomes increasingly reliable for the types of tasks and edge cases it regularly faces.

### When Evolution Helps vs. When It Doesn't

| Scenario | Evolution Helps? | Why |
|----------|------------------|-----|
| API rate limiting | ✅ Yes | Add delays, fallbacks, validation |
| Paywall detection | ✅ Yes | Add domain checks, content validation |
| LLM prompt misunderstanding | ✅ Yes | Refine prompts based on actual failures |
| New API version with breaking changes | ✅ Yes | Regenerate with updated tool usage |
| Completely novel task type | ❌ No | No prior failure data to learn from |
| User goal changes | ❌ No | Requires new goal definition, not evolution |

---

## Summary

Agent evolution in Hive is a **practical, failure-driven improvement process**:

1. **Failure is inevitable** — First versions are happy-path drafts
2. **Failures are captured** — Detailed decision logs and error traces
3. **Diagnosis is specific** — Root cause analysis, not generic errors
4. **Evolution is targeted** — Changes address actual failure modes
5. **Reliability compounds** — Each generation handles more edge cases

This is why Hive agents get better over time — not through magic, but through systematic learning from real-world failures.
