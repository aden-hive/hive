# The Queen

Every [colony](./colony.md) has a **Queen** — the persistent, client-facing agent who leads it. She's the one you talk to. She owns the conversation, keeps the plan, does the early work herself, and spawns [workers](./worker_agent.md) when the job needs to scale. Technically she's just an [agent loop](./the_loop.md) tuned for long-running oversight — but conceptually she's the colony's lead.

## Queens are identities, not generic orchestrators

A Queen isn't an interchangeable "coordinator." She's a persona. Hive ships **13 Queens**, each a head of department with her own expertise and voice. Six are active out of the box (Growth, RevOps, Content, Lead Generation, Outbound, and Brand & Design); you can hire the rest from the Org Chart, or create your own.

| Domain | Queen role |
| --- | --- |
| RevOps · Outbound · Lead Gen | pipeline, prospecting, and outreach |
| Growth · Market Research | acquisition, experiments, and market insight |
| Finance | modeling, budgets, and fundraising |
| Legal | contracts, compliance, and risk |
| Talent | recruiting and people ops |
| Operations | process and back-office |
| Product Strategy | roadmap and positioning |
| Brand & Design · Content | brand, design, and content creation |
| Technology | engineering and technical work |

Each persona is a YAML profile — traits, background, behavior triggers — injected into her system prompt, so she brings domain judgment to the work, not just task execution.

## Choosing a Queen

You pick who to hand a request to: type it on the home screen and choose the Queen whose domain fits, or open a Queen directly from the sidebar. A prompt deployed from the Prompt Library goes straight to the Queen it was written for. (An automatic LLM router used to assign Queens; it was retired because a classifier guessing your counterpart was the wrong design for a conversation.)

## The Queen's phases

A Queen moves a piece of work through two phases (this is how a [colony grows](./colony.md#how-a-colony-grows-execute-first-then-systematize)):

1. **Independent** — she works as a standalone agent, doing the task directly. If it turns out to be parallel, recurring, or long-running, she proposes a colony.
2. **Colony** — once you confirm in the Create Colony dialog, she forks the work into a colony on disk and switches into fan-out mode, delegating to worker clones and validating their results through the tracker.

The through-line is **execute first, then systematize**: she proves the path herself, then factors it into a repeatable process. See [How a Colony Improves](./improvement.md).

## The Queen's memory

A Queen carries **scoped, evolving memory** — markdown notes kept globally (about you and your business) and per queen. A cooldown-gated reflection step writes durable notes as she works, and a recall selector surfaces the relevant ones on later sessions. She also recalls relevant excerpts of earlier conversations automatically, and can search them herself. This is how a Queen accumulates context about you and your business over time — not a vector database, just files she reflects into and reads back. (Unlike the Queen, workers are memoryless: each starts fresh.)

## What the Queen owns

- **The conversation** — she's the single client-facing surface of the colony.
- **The plan** — a persistent, file-backed [task list](./coordination.md#the-task-plan) that survives reloads.
- **The tracker** — she sets up the colony's shared [ledger](./coordination.md#the-tracker), assigns work, and validates results with SQL.
- **Questions for you** — when a decision is yours, she asks in the chat and waits. In a colony with [Sentinel](./coordination.md#human-in-the-loop) switched on, a parked Queen is nudged along or escalated to you through the Hive inbox, Telegram or Slack, and resumes when you reply.

## Learn more

- [The Colony](./colony.md) — what the Queen leads.
- [The Loop](./the_loop.md) — the primitive the Queen is an instance of.
- [The Worker Agent](./worker_agent.md) — the clones she spawns.
- [Coordination](./coordination.md) — the tracker, plan, and reminders she works through.
