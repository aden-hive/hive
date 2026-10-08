# The Loop

Hive has exactly one execution primitive: the **agent loop**. It's the atom every [colony](./colony.md) is built from. The [Queen](./queen.md) is an agent loop. Every [worker](./worker_agent.md) is a clone of that same loop. There are no separate "node," "planner," or "executor" types — understand the loop and you understand how everything in Hive runs.

## What the loop does

An agent loop is a multi-turn, streaming conversation with an LLM. Each turn:

1. **Stream** the model's response (text and tool calls).
2. **Execute** any tool calls — a batch runs in parallel.
3. **Feed results back** into the conversation.
4. **Decide** whether to stop (the turn produced what was needed) or iterate again.

It keeps going until it's produced its required outputs, hit its budget, or parked to wait for something (a human answer, a credential). That's it. A one-off task and a long-running business overseer are the *same* loop with different settings.

## Self-correction: the reflexion pattern

The most important behavior in the loop is that it evaluates its own work and tries again when it falls short. After a turn, a **judge** checks the result: did it meet the bar?

- **Accept** — good enough; move on.
- **Retry** — not yet, but recoverable. The judge's feedback is injected back into the conversation as a message, so on the next turn the loop sees its previous attempt *and* the critique, and adjusts.
- **Escalate** — something is fundamentally stuck; hand off (to the Queen, or to a human via Sentinel).

This is the **reflexion pattern**: try, evaluate, learn from the result, try again — in-context, without retraining the model. An agent that takes three tries to get something right is far more useful than one that fails once and gives up. This is self-correction *within a session*; improvement *across* sessions is covered in [How a Colony Improves](./improvement.md).

The judge itself is a small pipeline — a cheap output-key check first, then an optional custom judge or a quality gate against your [success criteria](./goals_outcome.md). Details in the [Architecture Overview](../architecture/README.md#the-judge-pipeline).

## One loop, many settings

The loop is configured by a `LoopConfig`. The Queen and a worker are the same code with different budgets:

| | Queen | Worker clone |
| --- | --- | --- |
| Role | persistent, client-facing lead | ephemeral, single task |
| Iterations | effectively unbounded | ~3 work + 1 grace |
| Tool budget | generous | tight, plus a lifetime cap |
| Escalation | can escalate to a human | none — fail fast and report |
| Memory | scoped, evolving | none (fresh each run) |

The **grace iteration** on a worker is a guaranteed wrap-up turn: even if it runs out of budget, it still gets to call `report_to_parent` so it never dies silently. See [The Worker Agent](./worker_agent.md).

## Iterations and limits

Within the loop, work happens in **iterations** — one turn of reason → act → observe → judge. You cap the maximum iterations to prevent runaway loops. If a loop can't produce acceptable output within its budget, it stops cleanly (a worker reports `failed`/`partial`; the Queen surfaces the problem or escalates) rather than spinning forever. Stall and doom-loop detection catch stuck turns and repeated identical tool calls before they burn budget.

## Built-in durability

Because there's only one primitive, durability is built once and inherited everywhere. Every loop:

- **persists a cursor to disk** and can **park/resume** — a crash, restart, or deploy picks up exactly where it left off;
- **manages its own context window** through compaction and the [pointer pattern](../architecture/README.md#tool-result-truncation-and-the-pointer-pattern), so long sessions don't blow the budget;
- **meters every LLM call** so cost limits are enforced;
- **stays coherent** via framework-injected reminders (see [Coordination](./coordination.md#the-reminder-hub)).

## Learn more

- [The Colony](./colony.md) — how many loops compose into a colony.
- [The Worker Agent](./worker_agent.md) — the clone, in detail.
- [Coordination](./coordination.md) — how loops share state without a graph.
- [Architecture Overview](../architecture/README.md) — the full mechanism.
