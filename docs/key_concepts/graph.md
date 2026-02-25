# The Agent Graph

## Why a Graph

Real business processes aren't linear. A sales outreach might go: research a prospect, draft a message, realize the research is thin, go back and dig deeper, draft again, get human approval, send. There are loops, branches, fallbacks, and decision points.

Hive models this as a directed graph. Nodes do work, edges connect them, and shared memory lets them pass data. The framework walks this structure — running nodes, following edges, managing retries — until the agent reaches its goal or exhausts its step budget.

Edges can loop back, creating feedback cycles where an agent retries a step or takes a different path. That's intentional. A graph that only moves forward can't self-correct.

## Nodes

A node is a unit of work. Each node reads inputs from shared memory, does something, and writes outputs back.

**`event_loop`** — This is the only node type in Hive. It's a multi-turn LLM loop where the model reasons about the current state, calls tools, observes results, and keeps going until it has produced the required outputs. All agent behavior happens in these nodes. They handle long-running tasks, manage their own context window, and can recover from crashes mid-conversation.

Event loop nodes are highly configurable:
- **Tools** — Give the node access to specific capabilities (web search, API calls, database queries, etc.)
- **Client-facing** — Set `client_facing=True` to make the node interact directly with humans (see [Human-in-the-Loop](#human-in-the-loop))
- **Custom logic** — Implement the `NodeProtocol` interface to wrap deterministic functions or any custom behavior
- **Judge** — Configure evaluation criteria to control when the node accepts its output vs. retries

### Self-Correction Within a Node

The most important behavior in an `event_loop` node is the ability to self-correct. After each iteration, the node evaluates its own output: did it produce what was needed? If yes, it's done. If not, it tries again — but this time it sees what went wrong and adjusts.

This is the **reflexion pattern**: try, evaluate, learn from the result, try again. It's cheaper and more effective than starting over. An agent that takes three attempts to get something right is still more useful than one that fails on the first try and gives up.

Within a single node, the outcomes are:

- **Accept** — Output meets the bar. Move on.
- **Retry** — Not good enough, but recoverable. Try again with feedback.
- **Escalate** — Something is fundamentally broken. Hand off to error handling.

This is self-correction *within a session* — the agent adapting in real time. It's different from [evolution](./evolution.md), which improves the agent *across sessions* by rewriting its code between generations. Both matter: reflexion handles the bumps in a single run, evolution handles the patterns that keep recurring across many runs.

## Edges

Edges control flow between nodes. Each edge has a condition:

- **On success** — follow this edge if the source node succeeded
- **On failure** — follow if the source failed (this is how you wire up fallback paths and error recovery)
- **Conditional** — follow if an expression is true (e.g., route high-confidence results one way, low-confidence results another)
- **LLM-decided** — let the LLM choose which path based on the [goal](./goals_outcome.md) and current context

Edges also handle data plumbing between nodes — mapping one node's outputs to another node's expected inputs, so each node has a clean interface without needing to know where its data came from.

When a node has multiple outgoing edges, the framework can run those branches in parallel and reconverge when they're all done. This is useful for tasks like researching a prospect from multiple sources simultaneously.

## Shared Memory

Shared memory is how nodes communicate. It's a key-value store scoped to a single [session](./worker_agent.md). Every node declares which keys it reads and which it writes, and the framework enforces those boundaries — a node can't quietly access data it hasn't declared.

Data flows through the graph in a natural way: input arrives at the start, each node reads what it needs and writes what it produces, and edges map outputs to inputs as data moves between nodes. At the end, the full memory state is the execution result.

## Human-in-the-Loop

Human-in-the-loop (HITL) is enabled by setting `client_facing=True` on an event loop node. These nodes pause and ask a person for input. This isn't a blunt "stop everything" — the framework supports structured questions: open-ended text, multiple choice, yes/no approvals, and multi-field forms.

When the agent hits a client-facing node, it saves its entire state and presents the output or questions directly to the user. The session can sit paused for minutes, hours, or days. When the human responds, execution picks up exactly where it left off.

This is what makes Hive agents supervisable in production. You place client-facing nodes at critical decision points — before sending a message, before making a purchase, before any action that's hard to undo. The agent handles the routine work autonomously; humans weigh in on the decisions that matter. And every time a human provides input, that decision becomes data the [evolution](./evolution.md) process can learn from.

## The Shape of an Agent

A typical agent graph looks something like this:

```
intake → research → draft → [human review] → send → done
                ↑                                 |
                └──── on failure ─────────────────┘
```

An entry node where work begins. A chain of nodes that do the real work. HITL nodes at approval gates. Failure edges that loop back for another attempt. Terminal nodes where execution ends.

The framework tracks everything as it walks the graph: which nodes ran, how many retries each needed, how much the LLM calls cost, how long each step took. This metadata feeds into the [worker agent runtime](./worker_agent.md) for monitoring and into the [evolution](./evolution.md) process for improvement.
