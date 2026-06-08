# Agent Usage & Status Tracking — Capability Document

**Audience:** Lead software architect (paired with frontend + business requirement docs)
**Scope:** Queen agent first (default local-runtime entry point), then downstream colonies/workers
**Status:** Capability inventory + proposal — no implementation commitments
**Date:** 2026-05-04

---

## 1. Why this document exists

We have a business need to track **agent usage** (what was consumed: tokens, cost, runtime, calls) and **agent status** (what state agents are in: alive, phase, progress, blocked) starting from the Queen agent, and surface this **on the cloud** for product and business consumers. This document inventories the capabilities the runtime can expose **today** vs. what is **net-new**, so architecture can pick a scope before frontend and product write against it.

The Queen is the right anchor: every local-runtime session today starts with a Queen, and every colony/worker is forked from a Queen call — so a tracking surface rooted at the Queen automatically covers the whole agent tree.

> **Headline constraint for the architect:** the runtime is **local-by-default**. Every byte described in §3 — events, runtime logs, progress DBs, session state, LLM cost numbers — is written to the user's machine under `~/.hive/` (or the platform-specific Electron `userData` directory). **Nothing is shipped to the cloud today.** The business ask therefore implies a new local→cloud transport boundary, with the data-residency, privacy, and identity decisions that come with it. §4.5 makes the gap explicit per-surface; §8 lists the risks; §9 frames the cloud cut-over as the gating decision for any "Slice 2+" work.

---

## 2. Vocabulary — what we actually mean

| Term | Definition in this codebase |
|---|---|
| **Session** | One Queen runtime instance. ID: `session_{YYYYMMDD_HHMMSS}_{uuid8}`. Persisted at `~/.hive/sessions/{session_id}/`. |
| **Queen** | Long-lived conversational agent. One per session. Single event-loop node. Phases: `independent → incubating → working → reviewing`. See [queen/nodes/__init__.py:494-518](../../core/framework/agents/queen/nodes/__init__.py#L494-L518). |
| **Colony** | Persistent stateless container forked by `create_colony`. Has its own SQLite progress DB at `~/.hive/colonies/{colony_name}/data/progress.db`. |
| **Worker** | Ephemeral agent running inside a colony to execute a task. |
| **Run / execution** | One trigger-to-completion invocation inside a node. Carries `run_id`, `execution_id`, `trace_id` (OTel-aligned). |
| **Usage** | Quantitative consumption: input/output/cached tokens, USD cost, wall-clock latency, tool-call counts. |
| **Status** | Qualitative state: phase, alive/stalled, current task, blocked-on, queue depth, last-heartbeat. |

---

## 3. What exists today (capabilities, not commitments)

The runtime is already heavily instrumented. Most of what business wants is **already emitted** — the gap is persistence, aggregation, and a stable API surface.

### 3.1 Event Bus — the spine

[core/framework/host/event_bus.py:61-177](../../core/framework/host/event_bus.py#L61-L177) defines an in-process async pub/sub with **40+ event types** scoped by `stream_id`, `session_id`, `colony_id`, `execution_id`, `run_id`, `correlation_id`, `timestamp`.

Relevant for usage/status:

- **Lifecycle:** `EXECUTION_STARTED/COMPLETED/FAILED/PAUSED/RESUMED/RESURRECTED`
- **Queen:** `QUEEN_PHASE_CHANGED`, `QUEEN_IDENTITY_SELECTED`
- **Colony/Worker:** `COLONY_CREATED`, `WORKER_COLONY_LOADED`, `WORKER_COMPLETED`, `WORKER_FAILED`, `SUBAGENT_REPORT`
- **LLM:** `LLM_TURN_COMPLETE`, `LLM_TEXT_DELTA`, `LLM_REASONING_DELTA`, `CONTEXT_USAGE_UPDATED`
- **Tools:** `TOOL_CALL_STARTED`, `TOOL_CALL_COMPLETED`, `TOOL_CALL_REPLAY_DETECTED`
- **Health:** `NODE_STALLED`, `NODE_TOOL_DOOM_LOOP`, `STREAM_TTFT_EXCEEDED`, `STREAM_INACTIVE`, `STREAM_NUDGE_SENT`
- **Tasks (right-rail panel):** `TASK_CREATED`, `TASK_UPDATED`, `TASK_DELETED`, `TASK_LIST_RESET`
- **Triggers:** `TRIGGER_AVAILABLE/ACTIVATED/DEACTIVATED/FIRED/REMOVED/UPDATED`

> Persistence today: in-memory only, **plus** optional JSONL export when `HIVE_DEBUG_EVENTS=1` ([event_bus.py:33-54](../../core/framework/host/event_bus.py#L33-L54)). There is no SQL events table.

### 3.2 Three-level runtime logs (per session)

[core/framework/tracker/runtime_log_schemas.py](../../core/framework/tracker/runtime_log_schemas.py) defines:

| Level | Schema | File | Granularity |
|---|---|---|---|
| L1 | `RunSummaryLog` | `summary.json` | Per graph run — totals + execution_quality + trace_id |
| L2 | `NodeDetail` | `details.jsonl` | Per node — exit_status, input/output tokens, latency_ms, retry/accept/escalate/continue counts |
| L3 | `NodeStepLog` | `tool_logs.jsonl` | Per LLM step — tool calls, verdicts, error traces, latency_ms |

Storage: `~/.hive/sessions/{session_id}/logs/` ([runtime_log_store.py](../../core/framework/tracker/runtime_log_store.py)). Schemas already carry OTel fields (`trace_id`, `span_id`, `parent_span_id`) — wire-ready, not yet exported.

### 3.3 LLM call accounting

[core/framework/llm/provider.py:11-32](../../core/framework/llm/provider.py#L11-L32) — `LLMResponse` carries: `model`, `input_tokens`, `output_tokens`, `cached_tokens`, `cache_creation_tokens`, `cost_usd`, `stop_reason`. Cost is computed from [model_catalog.py](../../core/framework/llm/model_catalog.py) when the model is priced; otherwise `0.0`.

> Gap: cost lives in the response object and is rolled into L2/L3 logs, but is **not** in the event bus stream and **not** in any aggregate query surface.

### 3.4 Colony Progress DB

[core/framework/host/progress_db.py:44-110](../../core/framework/host/progress_db.py#L44-L110) — per-colony SQLite (WAL mode):

- `tasks` (id, seq, priority, goal, status: pending|claimed|started|completed|failed, worker_id, claimed_at, started_at, completed_at, retry_count, last_error)
- `steps`, `sop_checklist`, `colony_meta`

This is the closest thing we have to a status SQL store today, but it is **per-colony** and **task-shaped** — not session-shaped or usage-shaped.

### 3.5 Queen task system (right-rail panel)

The mechanism the IDE-selection prompt describes is real: each `task_update` emits `TASK_UPDATED` on the bus, which a future SSE/WS surface can stream. State transitions: `pending → in_progress → completed`. Task body carries `subject`, `active_form`, `blocks`, `blocked_by`, `metadata`. Source: [tasks/events.py:52-159](../../core/framework/tasks/events.py#L52-L159).

### 3.6 HTTP surface (already shipping)

[core/framework/server/routes_sessions.py](../../core/framework/server/routes_sessions.py):

- `POST /api/sessions` — create
- `GET /api/sessions/{session_id}` — current state including `queen_phase`, `queen_model`, `colony_id`, `uptime_seconds`
- `GET /api/sessions/{session_id}/stats` — runtime statistics (extension point)
- `GET /api/sessions/{session_id}/events/history` — replay persisted events

SSE primitive exists at [server/sse.py](../../core/framework/server/sse.py) but is **not yet wired to a global event-stream route**. This is the natural attach point for a real-time status feed.

### 3.7 Worker health snapshot

`get_worker_health_summary()` ([worker_monitoring_tools.py:71-99](../../core/framework/tools/worker_monitoring_tools.py#L71-L99)) returns: `session_id`, `session_status`, `total_steps`, `recent_verdicts`, `stall_minutes`, `evidence_snippet`. Used today by Queen during the WORKING phase; can be exposed via API.

---

## 3.8 Where every byte lives today (data residency map)

Every storage location below is **on the end-user's machine**. There is no cloud sink, no telemetry endpoint, no managed database, no analytics service. The HTTP server in [core/framework/server/](../../core/framework/server/) binds to localhost for the desktop UI; it is not a cloud API.

`HIVE_HOME` defaults to `~/.hive/` and is overridden by the desktop shell to the platform `userData` dir (e.g. `~/Library/Application Support/Hive/` on macOS, `%APPDATA%\Hive\` on Windows). Source: [config.py:20-44](../../core/framework/config.py#L20-L44).

| Data | On-disk location (per machine) | Format | Lifetime | Currently shipped off-device? |
|---|---|---|---|---|
| Event bus stream | in-process memory only | Python objects | Process lifetime | No |
| Event debug log (opt-in) | `HIVE_HOME/event_logs/<ts>.jsonl` when `HIVE_DEBUG_EVENTS=1` | JSONL | Until user deletes | No |
| Session state | `HIVE_HOME/sessions/{session_id}/state.json` | JSON | Until user deletes | No |
| Conversations | `HIVE_HOME/sessions/{session_id}/conversations/` | JSON | Until user deletes | No |
| Artifacts | `HIVE_HOME/sessions/{session_id}/artifacts/` | mixed | Until user deletes | No |
| L1 run summary (tokens, cost, quality) | `HIVE_HOME/sessions/{session_id}/logs/summary.json` | JSON | Until user deletes | No |
| L2 node details | `HIVE_HOME/sessions/{session_id}/logs/details.jsonl` | JSONL | Until user deletes | No |
| L3 step / tool logs | `HIVE_HOME/sessions/{session_id}/logs/tool_logs.jsonl` | JSONL | Until user deletes | No |
| Colony task / step / SOP state | `HIVE_HOME/colonies/{colony_name}/data/progress.db` | SQLite (WAL) | Until user deletes | No |
| Queen / colony / skill / memory configs | `HIVE_HOME/{queens,colonies,skills,memories}/` | files | Until user deletes | No |
| LLM `cost_usd` numbers | computed in-process from [model_catalog.py](../../core/framework/llm/model_catalog.py), then written into L1/L2/L3 logs above | — | Same as logs | No |

**What this means for the cloud requirement:** the question for the architect is not "where do we get the data" — the data is fully captured. The question is **"how does it leave the machine, in what shape, with whose consent, and where does it land."** That decision is upstream of every endpoint in §6 and every storage option in §5.

Three architectural shapes worth considering (architect to choose):

- **Shape A — On-device only, queried over LAN/tunnel.** Cloud product reaches into the runtime via an authenticated tunnel; no data is replicated. Strongest privacy. Hardest for cross-device rollups.
- **Shape B — Outbox push.** Runtime keeps the local store as source of truth and asynchronously pushes a redacted, billing-grade subset (no prompts, no tool args by default) to a cloud aggregate. Best fit for the typical "agent status dashboard + usage rollup" product.
- **Shape C — Cloud-first runtime.** Runtime writes events directly to a cloud bus and treats local files as a cache. Largest rewrite; not recommended for a desktop-first product.

Shape B is the lowest-friction path to the stated business outcome. The rest of this document is written with Shape B as the default and calls out where Shape A or C would change things.

---

## 4. Capability matrix — what we can offer

Each row is a candidate frontend/business surface, scored by feasibility from current state.

| # | Capability | Status | Backed by |
|---|---|---|---|
| **Status** | | | |
| S1 | Queen phase indicator (independent/incubating/working/reviewing) | **Ready** | `QUEEN_PHASE_CHANGED` event + session detail field |
| S2 | Per-task progress (right-rail) | **Ready** | `TASK_*` events |
| S3 | Live LLM streaming indicator (typing, thinking, tool-calling) | **Ready** | `LLM_TEXT_DELTA`, `LLM_REASONING_DELTA`, `TOOL_CALL_STARTED/COMPLETED` |
| S4 | Stall / stuck-agent detection | **Ready** | `NODE_STALLED`, `STREAM_INACTIVE`, `NODE_TOOL_DOOM_LOOP` |
| S5 | Colony tree (Queen → colonies → workers) snapshot | **Partial** — data exists in session/colony stores; need a join query |
| S6 | Worker health roll-up across colonies | **Partial** — per-worker tool exists; needs aggregation route |
| S7 | Liveness heartbeat ("agent X last seen Y ago") | **Net-new** — must derive from event timestamps or add a periodic ping |
| S8 | Trigger schedule (when will Queen wake next) | **Ready** | `TRIGGER_*` events |
| **Usage** | | | |
| U1 | Tokens per session (input/output/cached) | **Partial** — captured per-step in L3, summed in L1; no API |
| U2 | USD cost per session / colony / model | **Partial** — `cost_usd` per LLM call in logs; no rollup |
| U3 | Tool-call counts and types | **Partial** — events exist; no aggregate |
| U4 | Wall-clock runtime and active-time per agent | **Partial** — derivable from `EXECUTION_STARTED/COMPLETED` |
| U5 | Cost attribution per Queen-spawned colony | **Partial** — `colony_id` is on every event; needs a query |
| U6 | Per-user / per-tenant aggregation | **Net-new** — there is no user/tenant identity in events today |
| U7 | Daily / monthly usage rollups for billing | **Net-new** — requires persistent event store |
| U8 | Quota / cap enforcement (block when over budget) | **Net-new** — requires real-time meter + policy hook |

**Read of the matrix:** ~70% of "status" surfaces are **shipping-grade today** behind a thin local API. ~70% of "usage" surfaces need a **persistence + aggregation layer**. The events themselves are not the bottleneck.

**Local vs. cloud read of the same matrix.** Every "Ready" / "Partial" cell above is *ready in-process on the local machine*. Making each row visible to a **cloud** consumer adds an additional step:

| Capability class | Local (today / near-term) | Cloud (business ask) |
|---|---|---|
| Live status (S1–S4, S8) | Stream from in-process event bus over local SSE | Push events through outbox → cloud relay → cloud SSE/WS to product UI. |
| Tree / health (S5, S6) | Join local session + colony stores | Same join, but on cloud-side replica of session/colony index. |
| Liveness (S7) | Derive from local event timestamps | Requires the runtime to *post* a heartbeat; cloud cannot infer aliveness from absence. |
| Per-session usage (U1–U5) | Read L1/L2/L3 logs on disk | Outbox sends durable rows (no deltas) to cloud usage table. |
| Tenant rollups (U6–U7) | Not possible — no identity in events | Cloud-side aggregation keyed on session→user join, identity attached at outbox time. |
| Quotas (U8) | Local meter feasible, but pointless without cloud truth | Cloud is the meter of record; runtime calls home to check. |

---

## 5. Proposed data model (architect to validate)

Three new persisted entities, plus reuse of existing event types:

```
AgentSession                     UsageEvent                    StatusSnapshot
-----------                      -----------                   ---------------
session_id (PK)                  id (PK)                       session_id (FK)
queen_id                         session_id (FK)               taken_at
queen_model                      colony_id                     phase
started_at                       worker_id                     active_run_id
ended_at                         agent_role  (queen|worker)    active_node
status      (active|done|failed) event_type  (LLM|TOOL|...)    open_task_count
user_id     (when multi-tenant)  model                         in_flight_workers
tenant_id   (when multi-tenant)  input_tokens                  last_event_at
total_input_tokens               output_tokens                 stall_score
total_output_tokens              cached_tokens
total_cached_tokens              cost_usd
total_cost_usd                   latency_ms
total_tool_calls                 tool_name      (nullable)
last_event_at                    occurred_at
                                 trace_id
                                 execution_id
```

Storage choice (architect call). **All three options today are local; only Option C reaches the cloud business surface.**

- **Option A — local SQLite outbox** at `HIVE_HOME/runtime.db`. Pros: zero infra, fits desktop, makes local queries cheap. Cons: per-host; no cross-device aggregation; **does not satisfy the cloud requirement on its own.**
- **Option B — DuckDB on the existing JSONL event logs.** Pros: zero ingestion code; analyst-friendly. Cons: cold-start latency on big histories; **also local-only.**
- **Option C — push events to a managed cloud store** (Postgres, ClickHouse, BigQuery) via an outbox pattern. Pros: cross-host rollups, billing-grade, the only option that actually delivers the cloud-visible status/metrics product. Cons: introduces a new transport, identity, and privacy/redaction story; needs explicit user opt-in for desktop builds.

The realistic shape is the hybrid called out in §3.8 Shape B: **A locally** as the durable buffer and source of truth, **C in the cloud** as the business-facing aggregate, with a one-way outbox that moves a *redacted, durable-event-only* subset over the wire. This document recommends that hybrid; everything in §6 and §7 is written against it.

---

## 6. Surface API — what frontend would consume

All routes assume the event-bus → SSE bridge exists (the one missing wire — see §3.6). Frontend sees this from day one.

> **Locality note.** The `/api/...` routes below are served by the **local runtime HTTP server** today. For the cloud product, the same shapes need a cloud-side counterpart fed by the outbox. Two practical patterns: (1) cloud product calls cloud-hosted versions of these routes (against the aggregate), or (2) cloud product proxies authenticated requests back to the user's runtime. §3.8 Shape A vs. Shape B picks between them.

### Real-time channel

```
GET  /api/sessions/{session_id}/events/stream      (SSE)
       ↳ filter=phase,task,llm_stream,tool,worker,trigger,health
GET  /api/agents/queen/stream                      (SSE) — global queen events
```

### Status reads

```
GET  /api/sessions/{session_id}                    — already shipping
GET  /api/sessions/{session_id}/tree               — Queen → colonies → workers
GET  /api/sessions/{session_id}/health             — stall_score, last_event_at, in_flight
GET  /api/colonies/{colony_id}/workers             — health roll-up
```

### Usage reads

```
GET  /api/sessions/{session_id}/usage              — tokens, cost, latency, tool-calls
GET  /api/sessions/{session_id}/usage/by-model     — split by model
GET  /api/colonies/{colony_id}/usage               — same shape, colony scope
GET  /api/agents/queen/usage?range=...&group_by=... — rollup view (billing)
```

### Admin / business

```
GET  /api/usage/rollup?range=...&group_by=user|tenant|model|colony
POST /api/quotas/{tenant}                          — set caps (if quota work in scope)
```

---

## 7. Net-new work — sized in shirt-size, not days

| Workstream | Local / Cloud | Size | Depends on | Notes |
|---|---|---|---|---|
| Event-bus → local SSE bridge ([sse.py](../../core/framework/server/sse.py) exists, route does not) | Local | **S** | — | Unlocks all real-time status surfaces in the desktop UI. Highest leverage piece. |
| Persisted local event store (SQLite outbox) | Local | **M** | Decision §5 | One writer, append-only; reuse existing JSONL writer. Source of truth for cloud push. |
| Local aggregation queries + `/usage` endpoints | Local | **M** | Persisted store | Per-session usage on disk. |
| **Outbox transport (local → cloud)** | **Boundary** | **M–L** | Local store + auth | New work: durable queue, retry, redaction policy, opt-in switch, schema versioning. This is the bridge to the cloud product. |
| **Cloud event ingest + aggregate store** | **Cloud** | **L** | Outbox transport | New cloud infra (Postgres/ClickHouse/BigQuery). Hosting, ops, retention policy, access controls. |
| **Cloud-side status/usage API + dashboards** | **Cloud** | **M** | Cloud aggregate | Mirrors §6 endpoints against the cloud store; this is what business users actually see. |
| Identity layer (user_id / tenant_id on events) | Boundary | **M** | Auth model | Currently no user identity in events. Identity attaches at outbox time, not at emit time. |
| OpenTelemetry exporter (schema is ready) | Boundary | **S–M** | — | `trace_id`/`span_id` already populated; an OTel collector can be the cloud sink instead of a custom outbox. |
| Quota / policy hooks | Cloud-authoritative | **L** | Cloud store + identity | Cloud holds the meter; runtime calls home synchronously on a critical path. |
| Liveness/heartbeat (S7) | Local emit, cloud consume | **S** | Outbox | Runtime must actively post; cloud cannot infer liveness from absence. |
| Cost attribution UI rollups | Cloud | **S** | `/usage` cloud endpoints | Shared with frontend doc. |

**Critical path for first frontend release (local desktop UI):** SSE bridge → status endpoints (S1–S5) → per-session usage endpoint (U1, U2). Everything else is incremental.

**Critical path for first cloud release (business ask):** local event store → outbox transport with redaction + opt-in → cloud ingest → cloud `/usage` and `/status` endpoints. The local UI work above is *not* a prerequisite for the cloud cut, but most of the local-side primitives (event store, durable-event filtering) are shared, so doing them in order minimizes rework.

---

## 8. Risks and tradeoffs the architect should weigh

1. **Event volume.** `LLM_TEXT_DELTA` fires per token. A persisted store must filter — don't write deltas, write `LLM_TURN_COMPLETE`. This is the #1 way the table blows up.
2. **Privacy / desktop posture — the central architectural constraint.** The runtime is local by default ([config.py:20-44](../../core/framework/config.py#L20-L44)). The data inventory in §3.8 confirms that **no data leaves the user's machine today**, including the data the business ask needs in the cloud. Closing that gap is not "add a metrics push" — it is a new system boundary with: (a) explicit user opt-in (defaults must be safe for OSS / self-hosted users), (b) a documented redaction list (no prompts, no tool args, no file paths in the default payload), (c) schema versioning so cloud aggregates do not break on runtime upgrades, (d) a clear answer for self-hosted / air-gapped deployments where the cloud sink is unreachable, (e) regional data-residency rules if the product is sold internationally. This is the single largest design decision in the document.
3. **Cost-table accuracy.** `cost_usd` is computed from a static catalog. Using it for billing means committing to keeping the catalog current (or pulling from provider invoices). For *display*, the current approach is fine; for *charging*, it is not.
4. **Identity coupling.** Events are session-scoped today. Adding `user_id`/`tenant_id` everywhere is invasive. Recommend pinning identity at the *session* boundary and joining on session at query time, rather than threading identity through every event payload.
5. **Status vs. heartbeat semantics.** "Idle" is not "dead." A Queen sitting in `independent` waiting for a user message is healthy and should not page anyone. The stall-score in §5 must distinguish idle-by-design from stalled-by-bug — the existing `STREAM_INACTIVE` / `NODE_STALLED` events already make this distinction; preserve it.
6. **Backpressure from observability.** If usage tracking sits in the LLM call path (for quotas), it must not add latency. Recommend: meter is async/eventual for display; only quota checks are synchronous, and only when the customer has a quota.
7. **Worker-side gap.** Worker LLM calls are accounted in their own session's L1–L3 logs but are *not* automatically rolled into the parent Queen session. Cost attribution from Queen → spawned colony requires either (a) a parent_session_id field on the colony's session row, or (b) walking the `COLONY_CREATED` event graph at query time. (a) is cleaner.

---

## 9. Recommendation

Ship in four thin slices. The first two are local-only and unblock the desktop UI; the last two are what actually deliver the business ask of cloud-visible status and metrics.

1. **Slice 1 — Live local status (1 sprint, fully local).**
   SSE bridge + `/sessions/{id}/events/stream` + `/sessions/{id}/health` + `/sessions/{id}/tree`. Frontend (local UI) gets the right-rail and the agent-tree. No persistence work, no cloud. (S1–S5, S8.)

2. **Slice 2 — Per-session local usage store (1–2 sprints, fully local).**
   Persisted event store (SQLite outbox at `HIVE_HOME/runtime.db`), filtered to durable event types only. `/sessions/{id}/usage` + `/colonies/{id}/usage`. No identity, no rollups, **no cloud transport yet**. This is the foundation the cloud slice rides on. (U1–U5.)

3. **Slice 3 — Local→cloud outbox + cloud ingest (the cloud cut, scope-defining).**
   Durable outbox queue, redaction policy, opt-in toggle, identity attachment, schema versioning, retry/backoff. Cloud-side ingest service + aggregate store. **This is where the local-only world becomes a cloud product.** Architect must decide §3.8 Shape, §5 storage, redaction defaults, and identity model before this slice can start.

4. **Slice 4 — Cloud rollups, dashboards, quotas (scope TBD with product).**
   Tenant aggregation, daily/monthly rollups, quota enforcement, OTel export, business dashboards. (U6–U8.) Defer until business confirms billing model — the answer (per-seat vs. per-token vs. per-colony) changes the data model.

Slices 1 and 2 are mostly **wiring** — the events exist, the schemas exist, the storage paths exist. Slice 3 is the **first slice that introduces a new architectural boundary** (local→cloud transport + identity + privacy contract); everything novel about the business ask lives there. Slice 4 is **business design**, not engineering scope.

---

## 10. Open questions for the architect

The first four are direct consequences of the local-first / cloud-required gap surfaced in §3.8 and §8.2.

1. **Cloud transport shape — Shape A, B, or C from §3.8?** This decision is upstream of the entire data model. Recommend Shape B (outbox push) absent a strong privacy argument for Shape A.
2. **Redaction default for the cloud payload.** What goes (model, token counts, latency, tool names, status) vs. what stays local (prompts, tool arguments, tool results, file paths, conversation content)? Need a written allowlist before Slice 3 starts.
3. **Self-hosted / air-gapped users.** If the cloud sink is unreachable or disabled, what does the runtime do — buffer indefinitely, drop oldest, or refuse to start? Defaults differ for OSS vs. SaaS distributions.
4. **Identity binding point.** Do we attach `user_id` / `tenant_id` at event-emit time (invasive, threads identity through every node), at session-create time (clean, requires session-level auth), or at outbox-flush time (simplest, but loses per-event provenance)? Recommend session-create.
5. Do we need quota *enforcement*, or only quota *visibility* in v1?
6. Frontend doc: are status and usage rendered in the same panel or different surfaces? This affects whether we ship one merged endpoint or two.
7. Are we willing to pay the cost-table maintenance burden, or should "cost" stay labeled as estimated and not be used for invoicing?

---

## Appendix — Pointers

- Queen lifecycle: [core/framework/agents/queen/nodes/__init__.py](../../core/framework/agents/queen/nodes/__init__.py)
- Event bus + types: [core/framework/host/event_bus.py](../../core/framework/host/event_bus.py)
- Runtime log schemas: [core/framework/tracker/runtime_log_schemas.py](../../core/framework/tracker/runtime_log_schemas.py)
- Runtime log store: [core/framework/tracker/runtime_log_store.py](../../core/framework/tracker/runtime_log_store.py)
- LLM accounting: [core/framework/llm/provider.py](../../core/framework/llm/provider.py), [model_catalog.py](../../core/framework/llm/model_catalog.py)
- Colony progress DB: [core/framework/host/progress_db.py](../../core/framework/host/progress_db.py)
- Task events: [core/framework/tasks/events.py](../../core/framework/tasks/events.py)
- Session HTTP: [core/framework/server/routes_sessions.py](../../core/framework/server/routes_sessions.py)
- SSE primitive: [core/framework/server/sse.py](../../core/framework/server/sse.py)
- Worker health: [core/framework/tools/worker_monitoring_tools.py](../../core/framework/tools/worker_monitoring_tools.py)
- Config / env vars: [core/framework/config.py](../../core/framework/config.py)
