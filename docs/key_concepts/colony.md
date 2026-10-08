# The Colony

A **colony** is the thing you actually build and run in Hive. It's a group of specialized agents that work together on one business process — a **Queen** who leads and talks to you, plus however many **worker** agents the job needs. You don't design a colony up front or wire it together by hand. You describe the outcome, and the Queen grows the colony around the work.

This is the core idea that everything else in Hive serves. A colony is Hive's **unit of deployment**: it lives in a single directory, it's portable, it can wake itself on a schedule, and it persists across sessions.

## Why "colony" and not "agent"

Most agent frameworks give you one of two things: a single agent (great for a personal task, but it can't scale) or a graph of hand-wired agents (powerful, but you have to design every node and edge and keep it in sync as the work changes). Real business processes don't fit either. They're parallel ("research these 200 leads"), recurring ("do this every morning"), and long-running ("watch the inbox and act"). They need more than one worker, and the shape of the work isn't known until you're in it.

A colony solves this by not fixing the shape in advance. The Queen does the work, discovers what it takes, and spawns exactly as many workers as she needs — at runtime, with a single tool call. There's no graph to author and none to maintain.

## What's inside a colony

On disk a colony is one directory, `colonies/<name>/`, holding everything its agents share:

- **The Queen** — a persistent, client-facing agent who owns the conversation, the plan, and the colony.
- **Worker clones** — ephemeral agents the Queen spawns to do units of work in parallel. See [The Worker Agent](./worker_agent.md).
- **The tracker** — one `tracker.db` (SQLite) that acts as the colony's shared ledger.
- **The task plan** — a persistent, file-backed to-do list that is the Queen's spine.

The Queen and every worker are the *same* underlying program — see the mechanism below.

## One loop controlling many loops

Here's what makes a colony elegant rather than complicated: Hive has exactly **one execution primitive**, the agent loop ([The Loop](./the_loop.md)). The Queen *is* an agent loop. Every worker is a **clone** of that same loop — same tools, same model — just with a tighter budget and one specific task injected.

So "a colony" is really **one loop controlling many loops**:

```
        ┌─────────── Queen (one long-lived loop) ───────────┐
        │  talks to you · owns the plan · reads the tracker │
        └───────────────────────┬───────────────────────────┘
                                 │  run_worker(tasks=[…])   (fire-and-forget)
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
        worker clone        worker clone        worker clone
        (one task)          (one task)          (one task)
             │                   │                   │
             └──── tracker_upsert · report_to_parent ┘
                                 ▲
                     results return to the Queen's loop
```

The Queen calls `run_worker` and keeps going — she isn't blocked while workers run. Each worker does its piece, writes its results to the shared tracker, and calls `report_to_parent`; that report lands back in the Queen's own conversation as a `[WORKER_REPORT]` turn. Workers can't see or message each other — everything they share flows through the tracker and the plan.

Because the Queen and the workers are the same primitive, every reliability feature (crash-safe resume, context compaction, cost tracking, stall detection) is built once and every agent in the colony inherits it.

## How a colony grows: execute first, then systematize

A Queen doesn't jump straight to spawning workers. She matures through three phases:

1. **Independent** — she's a normal conversational agent, doing the work herself. When a task turns out to be parallel, recurring, or long-running, she can suggest scaling up.
2. **Incubating** — a fail-closed gate checks that the plan is settled enough to commit, because forking a colony is expensive (the interactive chat ends and the colony runs unattended).
3. **Colony** — she forks the colony to disk and switches into fan-out mode.

The defining move is **execute-first-then-systematize**. The Queen does one unit of the work herself first — the **pilot** — and records the result in the tracker. Once she's proven the path, she factors it into a reusable **skill + playbook** and runs it across worker clones. Because the tracker always knows what's done and what's left, re-running a playbook simply resumes where it stopped. See [How a Colony Improves](./improvement.md) for more.

## What a colony gives you

- **Portability** — export a colony as a tarball and import it elsewhere (`POST /api/colonies/import`). A working colony is a shareable artifact.
- **Scheduling** — cron triggers fire straight into the owning Queen's session, so a colony can run itself on a clock.
- **Longevity** — the Queen persists across sessions; workers come and go with the work.
- **Oversight** — a colony can pause for human judgment at any point via out-of-band [Sentinel](./coordination.md#human-in-the-loop-sentinel) escalation (Slack/Telegram), then resume from disk.

## Learn more

- [The Loop](./the_loop.md) — the single primitive a colony is built from.
- [The Queen](./queen.md) — the colony's persistent lead: personas, routing, memory, phases.
- [The Worker Agent](./worker_agent.md) — a single ephemeral clone in a colony.
- [Coordination](./coordination.md) — the tracker, the task plan, the event bus, and the reminder hub.
- [How a Colony Improves](./improvement.md) — reflexion, memory, learned skills, and playbooks.
- [Goals & Outcomes](./goals_outcome.md) — how you tell a colony what "done" means.
- [Architecture Overview](../architecture/README.md) — the full, code-level reference.
