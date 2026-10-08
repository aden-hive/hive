# How a Colony Improves

Agents fail. Real-world variables — a private profile, a changed API schema, a model hallucination — are impossible to anticipate in a vacuum. The first version of any process is a happy-path draft. What matters is how a [colony](./colony.md) gets *better* over time.

Hive improves a colony through four in-band mechanisms — all part of the running system, none requiring you to hand-edit a workflow or retrain a model. Two operate *within* a session; two carry improvement *across* sessions.

> **Note:** earlier versions of Hive described improvement as "evolution" — a coding agent that rewrote an agent's *graph* between generations. There is no graph in Hive today, and no cross-generation code rewriting. Improvement now happens through the mechanisms below.

## Within a session

### 1. Reflexion

The [agent loop](./the_loop.md) evaluates its own output every turn. When the judge issues a **retry**, its feedback is injected back into the conversation, so on the next turn the agent sees its previous attempt *and* the critique and adjusts. This is in-context learning — the agent gets it right on the second or third try without anyone intervening. It handles the bumps *within* a single run. (See [The Loop → self-correction](./the_loop.md#self-correction-the-reflexion-pattern).)

## Across sessions

### 2. Scoped, evolving memory

As a [Queen](./queen.md) works, a cooldown-gated reflection step writes durable notes into scoped markdown memory — per-global, per-colony, per-queen. A recall selector surfaces the relevant notes on later sessions. Over time a Queen accumulates real context about you, your business, and what worked before, and brings it to new work. This is improvement by *remembering*, not by rewriting.

### 3. Learned, tool-gated skills

When a Queen proves out a way of doing something, it can become a **skill** — a reusable protocol that joins her baseline. Skills are **tool-gated**: a skill only activates when the tools it needs are actually present, so a Queen never tries to run a protocol she isn't equipped for. Learned skills mean the *next* time a similar task shows up, the colony already knows the drill.

### 4. Systematization (the playbook)

This is the big one, and it's the whole point of the [execute-first-then-systematize](./colony.md#how-a-colony-grows-execute-first-then-systematize) arc. Once the Queen has piloted a unit of work and proven the path, she factors it into a skill plus a **playbook** — a deterministic runner that converges the rest of the batch across [worker clones](./worker_agent.md).

The playbook owns no state of its own: the [tracker](./coordination.md#the-tracker) is the source of truth. It dispatches one worker per unit of work, with retry, backoff, and a dead-letter path for the ones that can't be resolved. And because "what's left" is always a fresh tracker query, **re-running a playbook is resume by construction** — run it again and it picks up exactly the work that isn't done yet. A one-off success becomes a repeatable, self-resuming process.

## Improvement ≠ general intelligence

An important distinction: these mechanisms make a colony more *reliable*, not more generally intelligent. The colony isn't learning to reason better in the abstract — it's remembering what worked, encoding it as skills, and turning proven pilots into repeatable processes. That's improvement on the *kinds* of problems the colony has already encountered.

For genuinely novel situations, that's what [human-in-the-loop](./coordination.md#human-in-the-loop-sentinel) is for — and every time a human steps in, that decision becomes context the Queen can remember and reuse.

## Learn more

- [The Colony](./colony.md) — the maturation arc in context.
- [The Loop](./the_loop.md) — reflexion within a session.
- [The Queen](./queen.md) — personas and memory.
- [Coordination](./coordination.md) — the tracker that makes playbooks resumable.
