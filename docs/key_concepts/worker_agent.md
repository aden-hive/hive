# The Worker Agent

A **worker** is a single agent the [Queen](./queen.md) spawns to do one unit of work inside a [colony](./colony.md). Workers are how a colony does things in parallel: when the Queen has 50 prospects to research, she doesn't do them one at a time — she fans out workers and each takes a share.

A worker is not a different kind of program from the Queen. It's a **clone** of her [agent loop](./the_loop.md) — same tools, same model — with a tighter budget and one task injected. What makes a worker a *worker* is what it deliberately lacks.

## What a worker is

A worker is **focused, ephemeral, and fail-fast**:

- **Focused** — it gets one task and stays strictly in scope. If it notices work outside its lane, it mentions it in its report and moves on; it doesn't chase it. (Broadening scope is how parallel workers collide.)
- **Ephemeral** — it has no memory of prior runs and no persona. It starts fresh, does the work, and terminates.
- **No escalation** — it has no live audience. It can't ask the Queen or the user a question mid-run, so it never blocks waiting for an answer.
- **Can't delegate** — a worker can't spawn its own workers. Fan-out belongs to the Queen; nesting is blocked.
- **Fail-fast** — when a tool call fails, it classifies the error (transient → retry once; structural → fix and retry once; unfixable → stop). It doesn't loop on workarounds.

## How a worker reports back

A worker's terminal action is `report_to_parent(status, summary, data)`:

- `success` — task complete, result in the summary/data;
- `partial` — some progress, but it couldn't finish;
- `failed` — couldn't make meaningful progress.

That report is delivered to the Queen as a `[WORKER_REPORT]` turn in her conversation. The worker's loop ends after it reports.

To guarantee a worker always reports — even if it runs out of iterations — its loop includes a **grace iteration**: a final wrap-up turn where the only tools available are `report_to_parent`, `task_update`, and `tracker_upsert`. Without it, a worker that hit its budget would die silently; with it, the Queen always hears back.

## How workers share results

Workers can't see or message each other, so they coordinate entirely through the colony's shared substrates:

- **The tracker** — a worker records structured findings by upserting rows into the colony's shared `tracker.db`. The Queen reads those rows directly with SQL. This is the primary channel for results — one row per unit of work, not prose.
- **Its own task list** — a worker can break its assignment into steps and track them, which also protects working memory across context pruning.

See [Coordination](./coordination.md) for how the tracker and plan tie the colony together.

## Sessions, headless execution, and resume

A **session** is one run of an agent against a specific input. Sessions are isolated — each has its own state and history — and they're **crash-safe**: state is persisted to disk, so a process crash, deploy, or restart resumes exactly where it left off rather than starting over.

A lot of colony work runs **headless** — no UI, no human at a terminal — monitoring inboxes, processing leads, watching for events around the clock. Headless doesn't mean unsupervised: when the colony hits a decision a human should make, the Queen escalates out-of-band via [Sentinel](./coordination.md#human-in-the-loop-sentinel) and the loop parks until they respond. Automate the routine; escalate the exceptions.

## The big picture

The worker model is Hive's answer to "how do you run agents like you'd run a team?" The Queen is the lead who takes the brief, does the first one herself, and then hands out well-scoped pieces to as many workers as the job needs — each doing its part, reporting results into a shared ledger, and stepping aside. When the process needs to get better, you don't debug workers line by line — the colony [improves](./improvement.md) through reflexion, memory, and systematization.

## Learn more

- [The Colony](./colony.md) — the whole that workers are part of.
- [The Queen](./queen.md) — who spawns and coordinates them.
- [The Loop](./the_loop.md) — the primitive a worker is a clone of.
- [Coordination](./coordination.md) — the tracker, plan, and event bus.
