# Architecture Pattern: Longitudinal Personal Assistant

> How to build a persistent personal assistant on Hive that maintains context, emotional awareness, and behavioral continuity across months of user interaction.

## The Gap in Current Agent Design

Most agent frameworks optimize for task completion within a single session. A user describes a goal, the agent executes, the session ends.

This works for business process automation. It does not work for personal assistants serving users through sustained life transitions — relocation, career pivots, health journeys, financial recovery — where the value compounds over time and the assistant's understanding of the user is the product.

A longitudinal assistant must:
- **Remember** across sessions, weeks, and months
- **Connect** seemingly unrelated inputs through associative retrieval
- **Evaluate** every response against safety criteria before delivery (emotional context makes bad output costly)
- **Evolve** its behavior while preserving safety invariants
- **Maintain identity** — one coherent companion, not a stateless function call

## Why Hive Fits

Hive's architecture maps to these requirements more cleanly than any other framework evaluated. Here's how:

### 1. Judge Node → Emotional Safety Gate

In a longitudinal assistant, the user shares vulnerable context over time. A bad response isn't just unhelpful — it damages trust that took weeks to build.

Hive's Judge node provides the right abstraction:

- **Criteria** evaluate specific response properties against defined behavioral and safety standards
- **Principles** enforce absolute constraints that no criterion evaluation can override
- **Event loop + scheduler** allow both synchronous (pre-delivery) and asynchronous (post-delivery audit) evaluation patterns

**Pattern:** Define a governing principle (e.g., "never position the user against a past or future version of themselves") as a Hive Principle with absolute override. Define contextual evaluation rules as Criteria. The Judge runs on every response before delivery.

### 2. Shared Memory → External Semantic Entity Store

The default Shared Memory model (file/RAM) works for session-scoped agents. Longitudinal assistants need:

- **Durable storage** that survives restarts, crashes, and deployments
- **Semantic retrieval** — not just key lookup, but meaning-based search
- **Typed entities** across multiple life-relevant categories, with extensible metadata
- **Emotional context** — each entity carries a valence score indicating whether the associated context is energizing or difficult for the user

**Proposed implementation:** PostgreSQL + pgvector as the Shared Memory backend.

The entity store uses typed entries (people, places, projects, challenges, behavioral patterns), each carrying a vector embedding, emotional valence score, domain tag, and extensible metadata. HNSW indexing enables sub-50ms semantic search across thousands of entities. Upsert-on-conflict ensures continuous memory refinement without duplicates.

**Open question for Hive team:** What is the recommended adapter pattern for external Shared Memory backends? Can PostgreSQL serve as the primary store with full SDK integration, or does the current architecture require routing through the file/RAM layer?

### 3. Agent Graph → Deterministic Response Pipeline

Longitudinal assistants cannot skip steps. The memory retrieval step cannot be omitted. The Judge step cannot be bypassed. The routing decision must happen after context enrichment, not before.

Hive's graph execution model enforces this:

```
Message Intake
    │
    ▼
Memory Retrieval (entity store query, context enrichment)
    │
    ▼
Model Router (depth path vs. speed path based on enriched context)
    │
    ▼
Response Generation (context-aware, memory-enriched)
    │
    ▼
Judge Node (criteria evaluation, pass/rewrite gate)
    │
    ▼
Delivery (channel-specific formatting, Telegram/WhatsApp)
```

Each node is an SDK-wrapped Hive node with access to Shared Memory, monitoring, and tool registry. The graph connections ensure ordering invariants.

### 4. Evolution Loop → Controlled Improvement with Frozen Constraints

The Evolution loop is Hive's most powerful feature — and the most dangerous one for this use case.

A business process agent can evolve freely: if the new version processes invoices faster, ship it. A personal assistant cannot: if the evolution relaxes an emotional safety criterion, the user pays the cost.

**Pattern: Frozen Criteria**

Partition criteria into two categories:
- **Evolvable criteria** — can be calibrated by the evolution loop (e.g., response length, vocabulary complexity, follow-up question frequency)
- **Frozen criteria** — must survive any number of evolution cycles without modification (e.g., governing safety constraints that protect the user's emotional state and identity)

**Open question for Hive team:** Does the evolution loop support frozen/immutable criteria? If not, what's the recommended pattern for evolution-resistant safety gates?

## Multi-Model Routing

Longitudinal assistants handle two fundamentally different types of interaction:

| Type | Characteristics | Optimal Model | Why |
|---|---|---|---|
| **Depth** | Emotional reasoning, life decisions, identity questions, complex context | Claude | Strongest at nuanced reasoning with extensive context |
| **Speed** | Scheduling, factual lookups, status checks, simple follow-ups | Groq/Llama | Sub-second latency, sufficient quality for bounded tasks |

The routing decision should happen *after* memory retrieval — the enriched context determines whether this is a depth or speed interaction. Hive's Worker Bee LLM configuration supports this via per-node model assignment.

## Observability Requirements

Longitudinal assistants need different metrics than task-completion agents:

| Metric | Why It Matters |
|---|---|
| **Memory retrieval relevance** | Are the right entities surfacing? Low relevance = degrading context quality |
| **Judge pass rate by criterion** | Which criteria are triggering most rewrites? Identifies response generation weaknesses |
| **Evolution drift detection** | Are safety criteria being preserved across evolution cycles? |
| **User re-engagement rate** | Are users returning after days/weeks? The core retention signal |
| **Emotional charge distribution** | Is the entity store balanced or skewing negative? Indicates whether the assistant is overindexing on problems |

## Infrastructure Considerations

This pattern has been developed on a production environment running **9 concurrent AI agents** on a single Oracle Cloud ARM instance with:
- PM2 and systemd for process management
- PostgreSQL + pgvector for memory
- Multi-model API routing (Claude, Groq, GPT)
- Telegram and WhatsApp as primary channels

The key constraint: the entire system runs on free-tier infrastructure. Cost efficiency is an architectural requirement, not a nice-to-have. Hive's cost controls and model degradation policies are directly relevant.

## Summary

| Hive Feature | Longitudinal Assistant Application |
|---|---|
| Judge Node | Pre-delivery safety evaluation with absolute-override principles |
| Shared Memory | External PostgreSQL + pgvector as durable, semantic, emotion-aware entity store |
| Agent Graph | Deterministic 6-stage pipeline with ordering invariants |
| Evolution Loop | Controlled improvement with frozen safety criteria |
| SDK-Wrapped Nodes | Memory access, monitoring, and tool registry per pipeline stage |
| Cost Controls | Essential for free-tier infrastructure deployment |

## Status

This pattern is being actively implemented. Phase 0 (Judge node + entity store) is complete. Phase 1 (Telegram production loop with full pipeline) is in progress.

Contributions planned:
- PostgreSQL + pgvector Shared Memory adapter (code + docs)
- Judge latency benchmark under messaging-style load
- Adversarial test suite pattern for Judge criteria validation

---

*Author: [Elena Revicheva](https://github.com/ElenaRevicheva) — building [AELA](https://github.com/ElenaRevicheva/AELA), a longitudinal personal assistant on Hive.*
