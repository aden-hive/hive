# The Queen

Every [colony](./colony.md) has a **Queen** — the persistent, client-facing agent who leads it. She's the one you talk to. She owns the conversation, keeps the plan, does the early work herself, and spawns [workers](./worker_agent.md) when the job needs to scale. Technically she's just an [agent loop](./the_loop.md) tuned for long-running oversight — but conceptually she's the colony's lead.

## Queens are identities, not generic orchestrators

A Queen isn't an interchangeable "coordinator." She's a persona. Hive ships **13 default Queens**, each a head-of-department with her own expertise and voice:

| Domain | Queen role |
| --- | --- |
| Sales · Outbound · Lead Gen | pipeline, prospecting, and outreach |
| Growth · Market Research | acquisition, experiments, and market insight |
| Finance & Fundraising | modeling, budgets, and fundraising |
| Legal | contracts, compliance, and risk |
| Talent | recruiting and people ops |
| Operations | process and back-office |
| Product Strategy | roadmap and positioning |
| Brand & Design · Content | brand, design, and content creation |
| Technology | engineering and technical work |

Each persona is a YAML profile — traits, background, behavior triggers — injected into her system prompt, so she brings domain judgment to the work, not just task execution.

## CEO-style routing

You don't pick a Queen from a menu. When a new request comes in, an LLM **router** reads it and assigns the best-matching Queen — the way a CEO routes work to the right department head. You describe the outcome; the routing is automatic.

## The Queen's phases

A Queen matures a piece of work through three phases (this is how a [colony grows](./colony.md#how-a-colony-grows-execute-first-then-systematize)):

1. **Independent** — she works as a standalone agent, doing the task directly. If it turns out to be parallel, recurring, or long-running, she can suggest forming a colony.
2. **Incubating** — a fail-closed gate confirms the plan is settled before committing, because forking is expensive: it ends the interactive chat and the colony then runs unattended.
3. **Colony** — she forks the colony to disk and switches into fan-out mode, delegating to worker clones and validating their results through the tracker.

The through-line is **execute first, then systematize**: she proves the path herself, then factors it into a repeatable process. See [How a Colony Improves](./improvement.md).

## The Queen's memory

A Queen carries **scoped, evolving memory** — markdown memory files kept per-global, per-colony, and per-queen. A cooldown-gated reflection step writes durable notes as she works, and a recall selector surfaces the relevant ones on later sessions. This is how a Queen accumulates context about you and your business over time — not a vector database, just structured files she reflects into and reads back. (Unlike the Queen, workers are memoryless: each starts fresh.)

## What the Queen owns

- **The conversation** — she's the single client-facing surface of the colony.
- **The plan** — a persistent, file-backed [task list](./coordination.md#the-task-plan) that survives reloads.
- **The tracker** — she sets up the colony's shared [ledger](./coordination.md#the-tracker), assigns work, and validates results with SQL.
- **Escalation** — when something needs a human, she escalates out-of-band via [Sentinel](./coordination.md#human-in-the-loop-sentinel) and resumes when they reply.

## Learn more

- [The Colony](./colony.md) — what the Queen leads.
- [The Loop](./the_loop.md) — the primitive the Queen is an instance of.
- [The Worker Agent](./worker_agent.md) — the clones she spawns.
- [Coordination](./coordination.md) — the tracker, plan, and reminders she works through.
