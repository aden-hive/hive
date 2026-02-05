# Build Your First Agent Challenge - Part 4 Answers

## Task 4.1: Failure Evolution Design 🔄

### 1. Failure Classification Taxonomy

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     CONTENT MARKETING AGENT FAILURE TAXONOMY                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ CATEGORY 1: LLM FAILURES                                                │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Code │ Type              │ Recoverable │ Action                         │   │
│  │──────┼───────────────────┼─────────────┼────────────────────────────────│   │
│  │ L001 │ Rate Limit        │ Yes         │ Exponential backoff + retry    │   │
│  │ L002 │ Content Filter    │ No          │ Escalate to human              │   │
│  │ L003 │ Hallucination     │ Yes         │ Fact-check + regenerate        │   │
│  │ L004 │ Context Overflow  │ Yes         │ Truncate input + retry         │   │
│  │ L005 │ Invalid JSON      │ Yes         │ Parse cleanup + retry          │   │
│  │ L006 │ Model Unavailable │ Yes         │ Fallback to alternate model    │   │
│  │ L007 │ Timeout           │ Yes         │ Retry with shorter max_tokens  │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ CATEGORY 2: TOOL FAILURES                                               │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Code │ Type              │ Recoverable │ Action                         │   │
│  │──────┼───────────────────┼─────────────┼────────────────────────────────│   │
│  │ T001 │ API Unavailable   │ Yes         │ Retry with backoff, then skip  │   │
│  │ T002 │ Invalid Response  │ Yes         │ Validate + retry or skip       │   │
│  │ T003 │ Timeout           │ Yes         │ Retry with longer timeout      │   │
│  │ T004 │ Auth Failure      │ No          │ Alert ops, pause agent         │   │
│  │ T005 │ Rate Limited      │ Yes         │ Queue + backoff                │   │
│  │ T006 │ Data Not Found    │ Maybe       │ Use fallback data or proceed   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ CATEGORY 3: LOGIC FAILURES                                              │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Code │ Type              │ Recoverable │ Action                         │   │
│  │──────┼───────────────────┼─────────────┼────────────────────────────────│   │
│  │ G001 │ Wrong Output Fmt  │ Yes         │ Cleanse output + retry         │   │
│  │ G002 │ Missing Data      │ Yes         │ Fetch missing + retry          │   │
│  │ G003 │ Validation Failed │ Yes         │ Feedback to LLM + retry        │   │
│  │ G004 │ Routing Error     │ Maybe       │ Re-evaluate route decision     │   │
│  │ G005 │ Infinite Loop     │ No          │ Kill execution, alert          │   │
│  │ G006 │ State Corruption  │ No          │ Reset state, restart run       │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ CATEGORY 4: HUMAN REJECTION (Most valuable for learning!)               │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Code │ Type              │ Recoverable │ Action                         │   │
│  │──────┼───────────────────┼─────────────┼────────────────────────────────│   │
│  │ H001 │ Quality Issues    │ Yes         │ Store feedback, rewrite        │   │
│  │ H002 │ Off-Brand Tone    │ Yes         │ Update style guidelines, retry │   │
│  │ H003 │ Factual Error     │ Yes         │ Flag sources, fact-check more  │   │
│  │ H004 │ Too Promotional   │ Yes         │ Add to avoid list, retry       │   │
│  │ H005 │ Wrong Audience    │ Yes         │ Adjust persona, retry          │   │
│  │ H006 │ Sensitive Topic   │ No          │ Escalate, don't auto-retry     │   │
│  │ H007 │ Legal/Compliance  │ No          │ Escalate to legal, halt        │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Learning Storage - Data Stored Per Failure Type

```python
# Schema for failure storage in LTM

failure_storage_schema = {
    # ================================================================
    # LLM FAILURES - Store for pattern detection, not learning
    # ================================================================
    "llm_failures": {
        "rate_limits": [
            {
                "timestamp": "2026-01-29T10:30:00Z",
                "model": "claude-sonnet-4-20250514",
                "request_count_before": 45,  # Helps predict limits
                "retry_succeeded": True,
                "backoff_ms": 5000,
            }
        ],
        "hallucinations": [
            {
                "timestamp": "2026-01-29T11:00:00Z",
                "claim": "Acme Corp was founded in 1985",
                "actual": "Acme Corp was founded in 2010",
                "source_used": "none",  # Helps identify when to force search
                "detection_method": "fact_check_tool",
            }
        ],
        "content_filters": [
            {
                "timestamp": "2026-01-29T12:00:00Z",
                "trigger_phrase": "...",  # What caused the filter
                "news_topic": "layoffs",  # Sensitive topic detection
                "escalated_to": "editor@acme.com",
            }
        ],
    },
    
    # ================================================================
    # TOOL FAILURES - Store for reliability monitoring
    # ================================================================
    "tool_failures": {
        "by_tool": {
            "web_search": {
                "failure_count_24h": 3,
                "last_failure": "2026-01-29T09:00:00Z",
                "common_errors": ["timeout", "rate_limit"],
                "avg_retry_count": 1.5,
            },
            "wordpress_publish": {
                "failure_count_24h": 0,
                "last_failure": None,
                "common_errors": [],
                "avg_retry_count": 0,
            },
        },
        "circuit_breaker_state": {
            "web_search": "closed",  # closed, open, half-open
            "wordpress_publish": "closed",
        },
    },
    
    # ================================================================
    # HUMAN REJECTIONS - Most valuable! Store everything for learning
    # ================================================================
    "human_rejections": {
        # Aggregate patterns
        "rejection_rate_7d": 0.23,  # 23% rejection rate
        "top_rejection_reasons": [
            {"reason": "too_promotional", "count": 12},
            {"reason": "off_brand_tone", "count": 8},
            {"reason": "factual_error", "count": 3},
        ],
        
        # Individual rejections (for few-shot learning)
        "recent_rejections": [
            {
                "id": "rej_001",
                "timestamp": "2026-01-28T15:00:00Z",
                "news_item_id": "news_abc123",
                "rejection_code": "H002",  # Off-brand tone
                "human_feedback": "Too formal and corporate. Our voice is casual.",
                "rejected_draft": {
                    "title": "Acme Corporation Announces Strategic Initiative",
                    "body_excerpt": "We are pleased to announce...",  # First 500 chars
                },
                "rewrite_approved": True,
                "approved_draft": {
                    "title": "Big News: We're Changing How You Work",
                    "body_excerpt": "You asked, we listened...",
                },
                "learnings_extracted": [
                    "Avoid 'pleased to announce'",
                    "Use 'you' more than 'we'",
                    "Start with reader benefit, not company action",
                ],
            },
        ],
        
        # Learned style rules (accumulated from rejections)
        "style_rules": {
            "avoid_phrases": [
                "pleased to announce",
                "strategic initiative", 
                "leverage",
                "synergy",
                "circle back",
            ],
            "prefer_phrases": [
                {"instead_of": "utilize", "use": "use"},
                {"instead_of": "implement", "use": "add"},
                {"instead_of": "enterprise solution", "use": "tool"},
            ],
            "tone_guidelines": [
                "Address reader as 'you' within first 2 sentences",
                "Max 1 company mention per paragraph",
                "Questions > Statements for engagement",
            ],
        },
        
        # Good examples (approved posts for few-shot)
        "approved_examples": [
            {
                "id": "post_xyz789",
                "title": "3 Ways AI is Actually Making Your Job Easier",
                "excerpt": "Forget the hype. Here's what's really working...",
                "approval_date": "2026-01-27",
                "quality_score": 0.92,
                "engagement_metrics": {
                    "views": 1250,
                    "avg_time_on_page": 180,
                    "shares": 45,
                },
            },
        ],
    },
}
```

---

### 3. Evolution Strategy - How the Coding Agent Improves the System

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           EVOLUTION STRATEGY                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  TRIGGER: Rejection rate > 20% over 7 days OR same error 3x in 24h             │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │ PHASE 1: ANALYSIS (Coding Agent)                                         │  │
│  │                                                                          │  │
│  │ 1. Query failure storage for patterns:                                   │  │
│  │    - Most common rejection reasons                                       │  │
│  │    - Recurring error codes                                               │  │
│  │    - Time-based patterns (failures at certain times?)                    │  │
│  │                                                                          │  │
│  │ 2. Compare rejected vs approved drafts:                                  │  │
│  │    - What differs in structure?                                          │  │
│  │    - What phrases appear in rejected but not approved?                   │  │
│  │    - What's the reading level difference?                                │  │
│  │                                                                          │  │
│  │ 3. Identify root cause:                                                  │  │
│  │    - Is it the system prompt?                                            │  │
│  │    - Is it missing context?                                              │  │
│  │    - Is it the quality threshold?                                        │  │
│  │    - Is it a specific news type that fails?                              │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                              │                                                  │
│                              ▼                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │ PHASE 2: PROPOSE CHANGES                                                 │  │
│  │                                                                          │  │
│  │ Coding Agent generates specific changes:                                 │  │
│  │                                                                          │  │
│  │ A. PROMPT UPDATES                                                        │  │
│  │    - Add new style rules to system prompt                                │  │
│  │    - Include more/better few-shot examples                               │  │
│  │    - Adjust output format requirements                                   │  │
│  │                                                                          │  │
│  │ B. GRAPH MODIFICATIONS                                                   │  │
│  │    - Add new validation node before human review                         │  │
│  │    - Add fact-checking step for certain topics                           │  │
│  │    - Adjust routing thresholds                                           │  │
│  │                                                                          │  │
│  │ C. THRESHOLD ADJUSTMENTS                                                 │  │
│  │    - Lower quality_threshold if too many false negatives                 │  │
│  │    - Raise confidence_threshold if too many bad posts slip through       │  │
│  │                                                                          │  │
│  │ D. TOOL USAGE CHANGES                                                    │  │
│  │    - Force web_search for certain topic types                            │  │
│  │    - Add company_knowledge search before writing                         │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                              │                                                  │
│                              ▼                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │ PHASE 3: VALIDATION (Before Deployment)                                  │  │
│  │                                                                          │  │
│  │ 1. Run proposed changes against historical failures:                     │  │
│  │    - Would the new prompt have prevented rejection X?                    │  │
│  │    - Simulate with past inputs, check outputs                            │  │
│  │                                                                          │  │
│  │ 2. A/B test with shadow traffic:                                         │  │
│  │    - Run both old and new versions                                       │  │
│  │    - Compare quality scores (don't publish new version yet)              │  │
│  │                                                                          │  │
│  │ 3. Human approval for significant changes:                               │  │
│  │    - Prompt changes > 20% different → require approval                   │  │
│  │    - New nodes added → require approval                                  │  │
│  │    - Threshold changes > 0.1 → require approval                          │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                              │                                                  │
│                              ▼                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │ PHASE 4: DEPLOYMENT                                                      │  │
│  │                                                                          │  │
│  │ 1. Deploy with canary (10% traffic for 24h)                              │  │
│  │ 2. Monitor key metrics vs baseline                                       │  │
│  │ 3. Auto-rollback if rejection rate increases                             │  │
│  │ 4. Full rollout after canary success                                     │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Concrete Example:**

```python
# Coding Agent analyzes failures and proposes this change:

evolution_proposal = {
    "trigger": "rejection_rate_exceeded",
    "analysis": {
        "rejection_rate_7d": 0.28,
        "top_reason": "too_promotional (45%)",
        "pattern": "Posts about product launches have 3x rejection rate",
    },
    "proposed_changes": [
        {
            "type": "prompt_update",
            "target": "content_writer.system_prompt",
            "change": "Add explicit instruction: 'For product announcements, "
                     "focus 80% on user benefits, 20% on features. Never use "
                     "phrases: revolutionary, game-changing, best-in-class.'",
            "expected_impact": "Reduce promotional rejections by 50%",
        },
        {
            "type": "add_node",
            "node_spec": {
                "id": "promotion_detector",
                "node_type": "function",
                "description": "Scan for promotional language before human review",
                "function": "detect_promotional_content",
            },
            "insert_after": "quality_review",
            "expected_impact": "Catch promotional content before human sees it",
        },
    ],
    "validation_results": {
        "historical_replay": "15/20 past rejections would have been caught",
        "shadow_test": "Quality score improved 0.72 → 0.81",
    },
    "requires_human_approval": True,
    "rollback_plan": "Revert to previous agent.json version",
}
```

---

### 4. Guardrails - Preventing System Degradation

```python
guardrails = {
    # ================================================================
    # GUARDRAIL 1: Rate Limiting Changes
    # ================================================================
    "change_rate_limits": {
        "max_prompt_changes_per_week": 3,
        "max_threshold_changes_per_day": 1,
        "max_node_additions_per_week": 2,
        "cooldown_after_rollback_hours": 48,
    },
    
    # ================================================================
    # GUARDRAIL 2: Validation Requirements
    # ================================================================
    "validation_requirements": {
        "min_historical_test_cases": 20,
        "min_improvement_percent": 10,  # Must show 10% improvement
        "max_regression_allowed_percent": 5,  # Can't make anything 5% worse
        "require_shadow_test": True,
        "shadow_test_duration_hours": 24,
    },
    
    # ================================================================
    # GUARDRAIL 3: Human Approval Thresholds
    # ================================================================
    "human_approval_required": {
        "prompt_change_diff_percent": 20,  # >20% prompt change needs approval
        "new_node_addition": True,  # Always need approval for new nodes
        "threshold_change_delta": 0.1,  # >0.1 change needs approval
        "tool_addition_removal": True,  # Always need approval
        "any_change_to_hitl_node": True,  # Always need approval
    },
    
    # ================================================================
    # GUARDRAIL 4: Automatic Rollback Triggers
    # ================================================================
    "auto_rollback_triggers": {
        "rejection_rate_increase_percent": 20,  # Rollback if rejections up 20%
        "error_rate_increase_percent": 50,  # Rollback if errors up 50%
        "latency_increase_percent": 100,  # Rollback if 2x slower
        "cost_increase_percent": 50,  # Rollback if 50% more expensive
        "monitoring_window_hours": 24,  # Check over 24h window
    },
    
    # ================================================================
    # GUARDRAIL 5: Immutable Constraints
    # ================================================================
    "immutable_constraints": {
        "always_require_human_approval_before_publish": True,
        "max_retries_per_rejection": 3,  # Don't retry forever
        "max_auto_generated_content_length": 3000,  # Cap content length
        "required_fields_in_output": ["title", "body", "excerpt"],
        "banned_topics_require_human": ["legal", "financial", "medical"],
    },
    
    # ================================================================
    # GUARDRAIL 6: Audit Trail
    # ================================================================
    "audit_requirements": {
        "log_all_evolution_proposals": True,
        "log_all_approvals_rejections": True,
        "log_all_rollbacks": True,
        "retention_days": 90,
        "require_reason_for_manual_override": True,
    },
}
```

---

## Task 4.2: Cost Optimization 💰

### 1. Model Selection Strategy

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         MODEL SELECTION DECISION TREE                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  INPUT: Task type + Quality requirements + Budget status                        │
│                                                                                 │
│                        ┌─────────────────┐                                      │
│                        │  Is this a      │                                      │
│                        │  retry after    │                                      │
│                        │  rejection?     │                                      │
│                        └────────┬────────┘                                      │
│                                 │                                               │
│                    ┌────────────┴────────────┐                                  │
│                    │ YES                 NO  │                                  │
│                    ▼                         ▼                                  │
│           ┌───────────────┐        ┌─────────────────┐                          │
│           │ Use BEST model│        │ Check task type │                          │
│           │ (Claude Sonnet│        └────────┬────────┘                          │
│           │  or GPT-4o)   │                 │                                   │
│           │               │    ┌────────────┼────────────┐                      │
│           │ Rationale:    │    │            │            │                      │
│           │ Already failed│    ▼            ▼            ▼                      │
│           │ once, invest  │  WRITE      REVIEW       PARSE/                     │
│           │ in quality    │  CONTENT    CONTENT      CLASSIFY                   │
│           └───────────────┘    │            │            │                      │
│                                ▼            ▼            ▼                      │
│                         ┌──────────┐ ┌──────────┐ ┌──────────┐                  │
│                         │ Sonnet   │ │ Haiku    │ │ Haiku    │                  │
│                         │ $3/1M in │ │ $0.25/1M │ │ $0.25/1M │                  │
│                         │ $15/1M ou│ │ $1.25/1M │ │ $1.25/1M │                  │
│                         │          │ │          │ │          │                  │
│                         │ Creative │ │ Analysis │ │ Fast &   │                  │
│                         │ writing  │ │ checking │ │ cheap    │                  │
│                         │ needs    │ │ is more  │ │ for      │                  │
│                         │ best     │ │ formulaic│ │ structured│                 │
│                         │ model    │ │          │ │ tasks    │                  │
│                         └──────────┘ └──────────┘ └──────────┘                  │
│                                                                                 │
│  BUDGET OVERRIDE:                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐    │
│  │ IF budget_remaining < 20%:                                             │    │
│  │   → Downgrade Sonnet tasks to Haiku                                    │    │
│  │   → Add warning to output: "Generated with budget constraints"         │    │
│  │                                                                        │    │
│  │ IF budget_remaining < 5%:                                              │    │
│  │   → Pause non-critical tasks                                           │    │
│  │   → Alert operations team                                              │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Model Assignment Table:**

| Agent/Task | Default Model | Fallback Model | Rationale |
|------------|---------------|----------------|-----------|
| News Monitor (classify) | Haiku | - | Simple classification |
| Content Writer (create) | Sonnet | Haiku (budget mode) | Creative quality matters |
| Content Writer (rewrite) | Sonnet | Opus (if 2nd retry) | Invest more on retries |
| Quality Review (analyze) | Haiku | - | Structured analysis |
| Quality Review (fact-check) | Sonnet | - | Accuracy critical |
| Feedback Learner (extract) | Haiku | - | Pattern extraction |
| SEO Analysis | Haiku | - | Formulaic checks |
| JSON Cleanup | Haiku | - | Simple parsing |

---

### 2. Caching Strategy

```python
caching_strategy = {
    # ================================================================
    # LAYER 1: Static Content Caching (TTL: 24 hours)
    # ================================================================
    "static_cache": {
        "style_guidelines": {
            "ttl_hours": 24,
            "invalidate_on": "human_updates_guidelines",
            "storage": "redis",
        },
        "brand_voice_examples": {
            "ttl_hours": 24,
            "invalidate_on": "new_approved_post",
            "storage": "redis",
        },
        "avoid_phrases_list": {
            "ttl_hours": 12,  # Shorter - updated by learning
            "invalidate_on": "new_rejection_pattern",
            "storage": "redis",
        },
        "company_knowledge_embeddings": {
            "ttl_hours": 168,  # 1 week
            "invalidate_on": "knowledge_base_update",
            "storage": "vector_db",
        },
    },
    
    # ================================================================
    # LAYER 2: Semantic Caching (Similar inputs → cached outputs)
    # ================================================================
    "semantic_cache": {
        "enabled": True,
        "similarity_threshold": 0.92,  # 92% similar = cache hit
        "what_to_cache": [
            {
                "task": "news_classification",
                "cache_key": "embedding(news_title + news_summary)",
                "ttl_hours": 168,  # Same news won't change classification
            },
            {
                "task": "seo_keyword_extraction",
                "cache_key": "embedding(topic + industry)",
                "ttl_hours": 72,
            },
        ],
        "what_not_to_cache": [
            "content_writing",  # Must be unique
            "human_feedback_processing",  # Context-dependent
        ],
    },
    
    # ================================================================
    # LAYER 3: Request Deduplication
    # ================================================================
    "deduplication": {
        "enabled": True,
        "window_seconds": 60,
        "key_fields": ["news_item_id"],
        "action_on_duplicate": "return_in_progress_result",
    },
    
    # ================================================================
    # ESTIMATED SAVINGS
    # ================================================================
    "expected_savings": {
        "static_cache_hit_rate": 0.80,  # 80% of guideline loads cached
        "semantic_cache_hit_rate": 0.15,  # 15% of classifications cached
        "dedup_rate": 0.05,  # 5% duplicate requests caught
        "total_llm_call_reduction": "~25%",
        "monthly_cost_savings": "$150-300 at 1000 posts/month",
    },
}
```

---

### 3. Batching Strategy

```python
batching_strategy = {
    # ================================================================
    # BATCH 1: News Processing (collect before processing)
    # ================================================================
    "news_batch": {
        "trigger": "time_based",
        "interval_minutes": 15,  # Process news every 15 min
        "max_batch_size": 10,
        "process_as": "parallel",  # Process all at once
        "benefits": [
            "Single LTM load for all items",
            "Shared style guidelines fetch",
            "Better rate limit management",
        ],
    },
    
    # ================================================================
    # BATCH 2: Quality Reviews (batch similar content)
    # ================================================================
    "review_batch": {
        "trigger": "queue_size",
        "min_batch_size": 3,
        "max_wait_minutes": 5,
        "process_as": "single_prompt",  # Review multiple in one call
        "prompt_template": """
Review these {n} blog posts for quality:

POST 1:
{post_1}

POST 2:
{post_2}

...

For each post, provide: quality_score, issues, recommendation
""",
        "benefits": [
            "Reduced per-item overhead",
            "Consistent scoring across batch",
            "~40% token reduction vs individual calls",
        ],
    },
    
    # ================================================================
    # BATCH 3: Learning Updates (aggregate before storing)
    # ================================================================
    "learning_batch": {
        "trigger": "count_based",
        "batch_size": 5,  # Aggregate 5 rejections before updating LTM
        "max_wait_hours": 24,  # Or daily if fewer rejections
        "process_as": "aggregate_then_store",
        "benefits": [
            "Reduces LTM writes",
            "Patterns more reliable with more data",
            "Single prompt to extract learnings from multiple rejections",
        ],
    },
}
```

---

### 4. Budget Rules

```python
budget_rules = {
    # ================================================================
    # BUDGET ALLOCATION
    # ================================================================
    "monthly_budget_usd": 500,
    "allocation": {
        "content_writing": 0.50,  # 50% = $250
        "quality_review": 0.20,   # 20% = $100
        "research_tools": 0.15,   # 15% = $75
        "learning_evolution": 0.10,  # 10% = $50
        "buffer": 0.05,           # 5% = $25 emergency
    },
    
    # ================================================================
    # SPENDING CONTROLS
    # ================================================================
    "controls": {
        "daily_limit_usd": 25,  # Max $25/day
        "per_post_limit_usd": 2,  # Max $2 per post (including retries)
        "per_retry_limit_usd": 0.75,  # Retries should be cheaper
        "alert_thresholds": {
            "daily_50_percent": "slack_notification",
            "daily_80_percent": "email_alert",
            "daily_100_percent": "pause_non_critical",
        },
    },
    
    # ================================================================
    # DEGRADATION POLICIES
    # ================================================================
    "degradation_policies": [
        {
            "trigger": "budget_remaining < 30%",
            "actions": [
                "Switch Sonnet → Haiku for first drafts",
                "Reduce max_tokens 4096 → 2048",
                "Disable semantic search (use keyword only)",
            ],
        },
        {
            "trigger": "budget_remaining < 10%",
            "actions": [
                "Process only high-priority news",
                "Skip quality self-assessment",
                "Alert team for budget increase",
            ],
        },
        {
            "trigger": "budget_remaining < 5%",
            "actions": [
                "Pause all non-critical processing",
                "Queue incoming news for next budget cycle",
                "Emergency alert to finance",
            ],
        },
    ],
    
    # ================================================================
    # COST TRACKING
    # ================================================================
    "tracking": {
        "granularity": "per_execution",
        "dimensions": ["agent", "model", "news_type", "is_retry"],
        "store_in": "metrics_db",
        "retention_days": 90,
    },
}
```

---

## Task 4.3: Observability Dashboard 📊

### 1. Performance Metrics (7 metrics)

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|-----------------|
| **P1: End-to-End Latency** | Time from news detection to published post | < 30 min | > 60 min |
| **P2: Per-Node Latency** | Execution time of each agent node | Varies by node | > 2x baseline |
| **P3: Throughput** | Posts processed per hour | 4 posts/hour | < 2 posts/hour |
| **P4: Queue Depth** | Pending news items awaiting processing | < 10 items | > 25 items |
| **P5: Retry Rate** | % of nodes requiring retry | < 10% | > 25% |
| **P6: LLM Token Usage** | Tokens consumed per post (in + out) | ~8K tokens | > 15K tokens |
| **P7: Tool Success Rate** | % of tool calls that succeed | > 95% | < 90% |

---

### 2. Quality Metrics (5 metrics)

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|-----------------|
| **Q1: First-Pass Approval Rate** | % approved without revision | > 75% | < 60% |
| **Q2: Rejection Rate** | % rejected by humans | < 15% | > 25% |
| **Q3: Average Quality Score** | Self-assessed quality (0-1) | > 0.80 | < 0.70 |
| **Q4: Factual Accuracy Rate** | % posts with no fact-check issues | > 95% | < 90% |
| **Q5: Post Engagement Score** | Views × (avg_time / 60) + shares×10 | Trend ↑ | 20% decline week-over-week |

---

### 3. Cost Metrics (4 metrics)

| Metric | Description | Target | Alert Threshold |
|--------|-------------|--------|-----------------|
| **C1: Cost Per Post** | Total $ spent per published post | < $1.50 | > $2.50 |
| **C2: Daily Spend** | Total daily API costs | < $20 | > $30 |
| **C3: Budget Utilization** | % of monthly budget used | Linear (day/30) | > 120% of expected |
| **C4: Cost Per Retry** | Additional cost when human rejects | < $0.50 | > $1.00 |

---

### 4. Alert Conditions

```python
alert_conditions = {
    # ================================================================
    # CRITICAL ALERTS (Page on-call immediately)
    # ================================================================
    "critical": [
        {
            "name": "Publishing Pipeline Down",
            "condition": "no_posts_published_in_4_hours AND queue_depth > 5",
            "action": "page_oncall",
            "runbook": "https://docs.internal/runbooks/pipeline-down",
        },
        {
            "name": "Budget Exhausted",
            "condition": "budget_remaining_percent < 5",
            "action": "page_oncall + pause_processing",
            "runbook": "https://docs.internal/runbooks/budget-emergency",
        },
        {
            "name": "Mass Rejection Event",
            "condition": "rejection_rate_1h > 80%",
            "action": "page_oncall + pause_processing",
            "runbook": "https://docs.internal/runbooks/quality-crisis",
        },
    ],
    
    # ================================================================
    # WARNING ALERTS (Slack notification)
    # ================================================================
    "warning": [
        {
            "name": "Elevated Rejection Rate",
            "condition": "rejection_rate_24h > 25%",
            "action": "slack_channel(#content-ops)",
        },
        {
            "name": "High Latency",
            "condition": "p95_latency > 45_minutes",
            "action": "slack_channel(#content-ops)",
        },
        {
            "name": "Tool Degradation",
            "condition": "any_tool_success_rate < 90%",
            "action": "slack_channel(#content-ops)",
        },
        {
            "name": "Budget Warning",
            "condition": "budget_remaining_percent < 20",
            "action": "slack_channel(#content-ops) + email(finance)",
        },
        {
            "name": "Quality Score Declining",
            "condition": "avg_quality_score_7d < avg_quality_score_30d - 0.1",
            "action": "slack_channel(#content-ops)",
        },
    ],
    
    # ================================================================
    # INFO ALERTS (Dashboard highlight only)
    # ================================================================
    "info": [
        {
            "name": "Evolution Triggered",
            "condition": "coding_agent_proposed_change",
            "action": "dashboard_highlight + slack(#content-evolution)",
        },
        {
            "name": "New Pattern Learned",
            "condition": "ltm_style_rules_updated",
            "action": "dashboard_highlight",
        },
        {
            "name": "High Engagement Post",
            "condition": "post_engagement_score > p90",
            "action": "dashboard_highlight + slack(#content-wins)",
        },
    ],
}
```

---

### Dashboard Visualization

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    CONTENT MARKETING AGENT DASHBOARD                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ 📊 KEY METRICS (Last 24h)                                               │   │
│  ├──────────────┬──────────────┬──────────────┬──────────────┬─────────────┤   │
│  │ Posts        │ Approval     │ Avg Quality  │ Cost/Post    │ Budget      │   │
│  │ Published    │ Rate         │ Score        │              │ Remaining   │   │
│  │              │              │              │              │             │   │
│  │    12        │    78%       │    0.84      │   $1.23      │    67%      │   │
│  │   ↑ 2        │   ↑ 3%       │   ↑ 0.02     │   ↓ $0.15    │             │   │
│  │ vs yesterday │              │              │              │             │   │
│  └──────────────┴──────────────┴──────────────┴──────────────┴─────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │ 📈 APPROVAL RATE (7 days)       │  │ 💰 DAILY COST TREND                 │  │
│  │                                 │  │                                     │  │
│  │  80% ┤      ╭─╮    ╭──          │  │  $30 ┤                              │  │
│  │  70% ┤  ╭───╯ ╰────╯            │  │  $20 ┤  ▄▄  ▄▄  ██  ▄▄  ██  ▄▄     │  │
│  │  60% ┤──╯                       │  │  $10 ┤  ██  ██  ██  ██  ██  ██     │  │
│  │      └──────────────────────    │  │      └──────────────────────────    │  │
│  │        M  T  W  T  F  S  S      │  │        M  T  W  T  F  S  S          │  │
│  └─────────────────────────────────┘  └─────────────────────────────────────┘  │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ 🔴 ACTIVE ALERTS                                                        │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ ⚠️  WARNING: web_search tool success rate at 88% (threshold: 90%)       │   │
│  │     Started: 2h ago | Acknowledged by: @ops-team                        │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ 🔄 RECENT EVOLUTION ACTIVITY                                            │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ • 2h ago: Coding Agent proposed prompt update (pending approval)        │   │
│  │ • 1d ago: Added 3 phrases to avoid_list from rejection feedback         │   │
│  │ • 3d ago: Quality threshold adjusted 0.70 → 0.72 (auto-approved)        │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ 📋 PROCESSING QUEUE                                                     │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │ Pending: 3 │ In Progress: 2 │ Awaiting Approval: 1 │ Failed: 0          │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Source Files Referenced

| Topic | Source File |
|-------|-------------|
| Decision recording schema | [core/framework/schemas/decision.py](core/framework/schemas/decision.py) |
| Runtime problem reporting | [core/framework/runtime/core.py](core/framework/runtime/core.py) |
| LLM provider abstraction | [core/framework/llm/provider.py](core/framework/llm/provider.py) |
| Graph execution metrics | [core/framework/graph/executor.py](core/framework/graph/executor.py) |
| Challenge requirements | [docs/quizzes/03-build-your-first-agent.md](docs/quizzes/03-build-your-first-agent.md) |
| Cost control features | [README.md](README.md) - "Cost & Budget Control" |
| HITL article | [docs/articles/human-in-the-loop-ai-agents.md](docs/articles/human-in-the-loop-ai-agents.md) |
