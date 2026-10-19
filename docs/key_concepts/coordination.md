# Coordination

A [colony](./colony.md) has no graph, no edges, and no shared data buffer. So how do a [Queen](./queen.md) and a fleet of [workers](./worker_agent.md) stay in sync? Through four lightweight substrates: a shared **tracker**, a persistent **task plan**, an **event bus**, and a **reminder hub**. Together they replace everything a compiled workflow graph used to do — with less rigidity and no wiring.

## The tracker

The tracker is the colony's **shared ledger** — one SQLite database per colony (`~/.hive/colonies/<name>/tracker/tracker.db`), and the single source of truth for "what's done and what's left."

- The **Queen** sets up the schema and declares which columns workers are allowed to write.
- **Workers** record their findings by upserting rows — one row per unit of work.
- The **Queen** validates progress by querying the tracker with SQL.

Because state lives in a real database rather than in-memory, nothing is lost to a crash, and "how far are we?" is always a fresh query. Every colony's tracker is scoped by an immutable **binding** — the colony's name, directory, and database path — that's threaded to the Queen and to every worker so both sides always resolve the *same* database. Tools that don't have a binding **refuse** to run rather than guess a path; this is what keeps two colonies (or a colony and a stray session) from ever writing to the wrong ledger.

The tracker is what lets workers coordinate without talking to each other: they never message peers, they just write rows the Queen reads.

## The task plan

The Queen keeps a **persistent, file-backed task list** — her plan for the whole conversation. It's visible to you, editable on the fly, and it survives session reloads, so the plan outlives any single run. She can stage a whole plan up front and tick items off as work completes.

Where the tracker holds *results* (structured rows), the plan holds *intent* (what the Queen means to do). Workers also keep their own small task lists to stay organized within a single assignment.

## The event bus

The event bus is the colony's real-time nervous system. Worker reports travel back to the Queen over it (as `SUBAGENT_REPORT` events), and the live transcript streams to the UI over it. It's how "many loops" surface into "one loop" and onto your screen without any shared call stack.

## The reminder hub

A single long-running loop that's fanning out dozens of workers can lose track of things — forget that workers are still running, forget to persist state before its context is pruned, forget which tools are available. Hive keeps the loop coherent by **injecting advisory reminders** at well-known moments: at session start, after tool batches, at budget checkpoints, around context compaction, and on an idle timer that can nudge even while the loop is parked.

These reminders keep the Queen **fleet-aware and disciplined** — re-surfacing in-flight workers when you re-engage (so she doesn't double-dispatch), snapshotting the tracker tables and the live worker fleet, nudging her to persist progress before pruning, suggesting she factor a proven pilot into a playbook, and listing the available tools/skills by name so the static prompt stays lean. It's engineered attention: the framework managing the model's focus across a long, high-fan-out session.

## Human in the loop

Human oversight isn't a node you place in a graph. It happens two ways:

- **The Queen asks.** When a decision is yours (which option, whether to go ahead, a missing credential), she asks in the chat, often with choices to pick from, and her loop **parks** until you answer. Workers never ask you directly: a blocked worker reports to the Queen, and she decides what to do.
- **Sentinel**, opt-in per colony, watches a colony while you're away. Whenever the Queen parks, a classifier decides whether to nudge her on, mark the work done, or escalate to you through the Hive inbox, Telegram or Slack. Your reply is injected and the loop **resumes** where it left off.

Because a parked loop is persisted to disk, a colony can wait minutes, hours, or days without losing its place.

## How it fits together

```
Queen (plan + SQL reads)  ──run_worker──►  worker clones
        ▲                                        │
        │  reports (event bus)                   │  tracker_upsert (rows)
        └──────────────── tracker.db ◄───────────┘
                    (shared ledger, source of truth)

reminders ─► keep the Queen fleet-aware      Sentinel ─► nudge a parked Queen, or escalate to you
```

## Learn more

- [The Colony](./colony.md) — the whole these substrates coordinate.
- [The Worker Agent](./worker_agent.md) — how a worker writes to the tracker and reports.
- [Architecture Overview](../architecture/README.md#coordination-what-replaces-edges-and-data-buffers) — the code-level detail.
