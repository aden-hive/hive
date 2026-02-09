## First 15 Minutes with Hive

This guide is for engineers who already understand AI agents in general and want a **clear mental model** of Hive before touching any setup scripts.

The goal: after this page, you should know **why Hive exists**, **when to use it**, and **how the main pieces fit together**.

---

## 1. What problem does Hive solve?

Most agent frameworks make *you* do the wiring:

- Design node graphs and workflows by hand  
- Glue LLM calls, tools, retries, and logging together  
- Handle failures and evaluation as an afterthought  

Hive flips this:

- You describe **goals and outcomes** in natural language.
- A **coding agent** (Claude / Cursor) generates **worker agents** and wiring on top of the Hive runtime.
- When things fail, Hive records rich telemetry so your agents can be **evaluated and evolved**, not just retried.

In short: **Hive is for production‑grade, self‑improving agents**, not one‑off chains or scripts.

Use Hive when you care about:

- Long‑running agents that own a workflow (not just “answer this question”)
- Multiple agents working together on real business processes
- Observability, cost control, and adaptation based on failures

---

## 2. High‑level architecture (mental model)

At a high level, you can picture Hive as three layers:

- **You & your team** – define business goals, constraints, and success criteria.
- **Coding agent** – turns those goals into concrete agents and tests.
- **Hive runtime** – executes those agents as **graphs of nodes** with full logging and storage.

A simplified flow:

1. You describe a goal:  
   “Handle inbound support emails and draft prioritized responses.”
2. A coding agent uses Hive’s tools to:
   - Create a **goal** with success criteria and constraints.
   - Generate a **worker agent** (code + `agent.json` graph).
   - Add **tests** for the critical flows.
3. Hive runs that agent:
   - Executes a **graph of nodes** (LLM/tool/human‑in‑the‑loop).
   - Records every decision and outcome into storage.
4. When something fails, the coding agent:
   - Reads the stored runs and failures.
   - Proposes **changes to the graph, prompts, or tools**.

You don’t manage a monolithic “agent brain”; you manage **goals + graphs** that are iterated on with real execution data.

---

## 3. Core building blocks

You’ll see these terms throughout the repo and docs:

- **Goal** – what the agent should accomplish, plus:
  - Success criteria (how we know it worked)
  - Constraints (what must never happen)

- **Node** – a single step the agent can take:
  - Call an LLM
  - Run a Python function
  - Call a tool via MCP
  - Pause for human approval

- **Graph** – nodes + edges:
  - Described in `agent.json` inside each agent package.
  - Executed by the **GraphExecutor** in the framework.

- **Agent package** – a folder under `exports/`:
  - Contains `agent.json`, optional `tools.py`, tests, and docs.
  - Is what `hive run` or `python -m my_agent run` actually executes.

- **Runtime** – the engine that:
  - Logs decisions, retries, and outcomes
  - Writes runs to `~/.hive/storage`

- **Tools & MCP servers** – capabilities the agent can use:
  - File system, web search/scrape, PDFs/CSVs, email, etc.
  - Exposed via the `aden_tools` MCP server so coding agents can safely use them.

---

## 4. When to use Hive vs. simpler approaches

Hive is **overkill** if:

- You just need a single prompt‑in / answer‑out script.
- You’re manually calling an API like `openai.ChatCompletion` in a small utility.

Hive shines when:

- You have **business workflows**: onboarding, sales, support, research, reporting.
- You need agents to **run repeatedly**, not just once.
- Failures should feed back into **better agents**, not just logs.
- Multiple agents (e.g., “researcher”, “writer”, “reviewer”) should coordinate.

If you can describe your problem as:

> “We want an AI‑powered worker that continuously does X, subject to Y constraints, and we’d like it to improve over time.”

…then you’re in Hive territory.

---

## 5. A concrete example: follow‑up workflow

Imagine a **customer success follow‑up** flow:

- Goal: “Within 24 hours of a support ticket closing, send a personalized follow‑up email if the customer’s satisfaction looks at risk.”

In Hive‑terms:

- A **goal** describes:
  - Success: “At‑risk customers get timely, high‑quality follow‑ups.”
  - Constraints: “Never include internal notes or PII in the email body,” etc.
- A **worker agent** graph might:
  1. Fetch recent closed tickets (tool call).
  2. Score risk using an LLM node.
  3. For high‑risk tickets:
     - Draft email (LLM node).
     - Pause for human approval (HITL node).
     - Send email via an integration tool.
  4. Log outcomes and satisfaction metrics.

Hive’s runtime:

- Records which tickets were flagged, what drafts were generated, who approved what, and how customers responded.
- Gives you a rich history for adapting:
  - Tightening constraints
  - Changing prompts or nodes
  - Adding tests for known failure patterns

---

## 6. How the coding agent fits in

You don’t have to hand‑edit every graph or write every test from scratch.

Instead, you typically:

- Open **Claude Code** or **Cursor** in the repo.
- Use skills such as:
  - `/building-agents-construction` – guides you through defining a goal and generating a new agent.
  - `/testing-agent` – helps you generate and run tests against that agent.

These skills:

- Call Hive’s MCP servers and tools on your behalf.
- Read/write files in `exports/`, `tests/`, and config.
- Keep you in a conversational, goal‑driven loop while still producing real, version‑controlled code.

Think of the coding agent as a **pair‑programmer that specializes in Hive** and uses MCP tools instead of a mouse.

---

## 7. Where to look in the repo

Once this mental model feels solid, it’s worth skimming the actual layout:

- `core/framework/` – the runtime:
  - `graph/` – node + graph definitions and executor.
  - `runner/` – `AgentRunner` and CLI integration (`hive run`, `hive list`, etc.).
  - `runtime/` + `storage/` – run tracking and persistence.
  - `llm/` – provider abstraction via LiteLLM.

- `tools/src/aden_tools/` – MCP tools:
  - `tools/` – individual tools (web search, web scrape, file system, etc.).
  - `mcp_server.py` – server that exposes these tools.

- `exports/` – your agents:
  - Created by skills or manually.
  - Safe place to experiment; not part of the repo’s tracked source.

You don’t need to understand every module to be effective, but knowing **where each concern lives** will speed up navigation a lot.

---

## 8. What to do next (practical path)

In order:

1. **Run the quickstart** to install dependencies and configure your default LLM:
   - See [Getting Started](../getting-started.md#quick-start).
2. **Build one agent** using `/building-agents-construction`:
   - Aim for a small but real workflow (e.g., summarize docs + send an email draft).
3. **Run and test that agent**:
   - Use the CLI (`hive run` or `python -m my_agent run`) and `/testing-agent`.
4. **Inspect how it’s wired**:
   - Open the generated `exports/my_agent/agent.json` and `tools.py`.
5. **Pick an issue or enhancement**:
   - For example, improving a tool, docs, or an example agent.

From here, you’ll have both **the mental model** and **a concrete agent** to anchor future learning.

