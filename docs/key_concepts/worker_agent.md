# The Worker Agent

## What a Worker Agent Is

A worker agent is a specialized AI agent built to perform a specific business process. It's not a general-purpose assistant — it's purpose-built, like hiring someone for a defined role. A sales outreach agent knows how to research prospects, craft personalized messages, and follow up. A support triage agent knows how to categorize tickets, pull customer context, and route to the right team.

In Hive, a **Coding Agent** (like Claude Code or Cursor) generates worker agents from a natural language goal description. You describe what you want the agent to do, and the coding agent produces the graph, nodes, edges, and configuration. The worker agent is the thing that actually runs.

## Sessions

A session is a single execution of a worker agent against a specific input. If your outreach agent processes 50 prospects, that's 50 sessions.

Each session is isolated — it has its own shared memory, its own execution state, and its own history. This matters because sessions can be long-running. An agent might start researching a prospect, pause for human approval, wait hours or days, and then resume to send the message. The session preserves everything across that gap.

Sessions also make debugging straightforward. Every decision the agent made, every tool it called, every retry it attempted — it's all captured in the session. When something goes wrong, you can trace exactly what happened.

## Iterations

Within a session, nodes (especially `event_loop` nodes) work in iterations. An iteration is one turn of the loop: the LLM reasons about the current state, possibly calls tools, observes results, and produces output. Then the judge evaluates: is this good enough?

If not, the node iterates again. The LLM sees what went wrong and adjusts its approach. This is how agents self-correct without human intervention — through rapid iteration within a single node, not by restarting the whole process.

Iterations have limits. You set a maximum per node to prevent runaway loops. If a node can't produce acceptable output within its iteration budget, it fails and the graph's error-handling edges take over.

## Headless Execution

A lot of business processes need to run continuously — monitoring inboxes, processing incoming leads, watching for events. These agents run **headless**: no UI, no human sitting at a terminal, just the agent doing its job in the background.

Headless doesn't mean unsupervised. HITL (human-in-the-loop) nodes still pause execution and wait for human input when the agent hits a decision it shouldn't make alone. The difference is that instead of a live conversation, the agent sends a notification, waits for a response through whatever channel you've configured, and resumes when the human weighs in.

This is the operational model Hive is designed for: agents that run 24/7 as part of your business infrastructure, with humans stepping in only when needed. The goal is to automate the routine and escalate the exceptions.

## The Runtime

The worker agent runtime manages the lifecycle: starting sessions, executing the graph, handling pauses and resumes, tracking costs, and collecting metrics. It coordinates everything the agent needs — LLM access, tool execution, shared memory, credential management — so individual nodes can focus on their specific job.

Key things the runtime handles:

**Cost tracking** — Every LLM call is metered. You set budget constraints on the goal, and the runtime enforces them. An agent can't silently burn through your API credits.

**Decision logging** — Every meaningful choice the agent makes is recorded: what it was trying to do, what options it considered, what it chose, and what happened. This isn't just for debugging — it's the raw material that evolution uses to improve future generations.

**Event streaming** — The runtime emits events as the agent works. You can wire these up to dashboards, logs, or alerting systems to monitor agents in real time.

**Crash recovery** — If execution is interrupted (process crash, deployment, anything), the runtime can resume from the last checkpoint. Conversation state and memory are persisted, so the agent picks up where it left off rather than starting over.

## The Big Picture

The worker agent model is Hive's answer to a simple question: how do you run AI agents like you'd run a team?

You hire for a role (define the goal), you onboard them with context (provide tools, credentials, domain knowledge), you set expectations (success criteria and constraints), you let them work independently (headless execution), and you check in when something unusual comes up (HITL). When they're not performing well, you don't debug them line by line — you evolve them (see [Evolution](./evolution.md)).
