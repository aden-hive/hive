# Why Hive? Positioning & Comparisons

This page clarifies how Hive differs from other agent and automation tools and points to materials for adoption and go-to-market.

## Core positioning

**Hive is a goal-driven, self-improving agent framework.** You define outcomes (success criteria and constraints); a coding agent generates the agent graph and connection code. When agents fail, the framework captures failure data, evolves the graph, and redeploys. It is not:

- A **task-chaining or workflow library** (e.g. LangChain chains, LangGraph) — you don’t manually wire steps.
- A **visual workflow engine** (e.g. n8n, Zapier) — workflows are generated from goals, not drawn.
- A **generic multi-agent chat framework** (e.g. AutoGen) — focus is on outcome evaluation and evolution, not conversation patterns alone.
- A **RAG/component toolkit** — Hive can use RAG via tools, but its differentiator is goal → graph → execute → evaluate → evolve.

**One-line:** *Describe the outcome; Hive generates and evolves the agent system.*

## Framework comparisons

Detailed, objective comparisons:

| Comparison | Focus | Link |
|------------|--------|-----|
| **Aden vs LangChain** | Goal-driven agents vs component-based LLM apps; RAG, chains, observability | [aden-vs-langchain.md](articles/aden-vs-langchain.md) |
| **Aden vs CrewAI** | Goal-driven graphs vs role-based agent crews | [aden-vs-crewai.md](articles/aden-vs-crewai.md) |
| **Aden vs AutoGen** | Outcome-driven systems vs conversational multi-agent | [aden-vs-autogen.md](articles/aden-vs-autogen.md) |

More conceptual and how-to content: [Articles README](articles/README.md) (self-improving vs static agents, human-in-the-loop, cost management, production agents, etc.).

## GTM & adoption materials (outline)

These outlines can be turned into concrete assets for trust, correct usage, and long-term engagement.

### 1. Competitive battle cards

**Purpose:** Help sales and users answer “Why Hive over X?” quickly.

**Suggested structure per competitor (e.g. LangChain, n8n, CrewAI, AutoGen):**

- **What they do well** — one line.
- **Where Hive fits** — goal-driven, generated graph, evolution, built-in observability/cost/HITL.
- **Key differentiators** — 3–5 bullets (e.g. “No manual graph definition”, “Failure → evolution loop”, “Native cost and HITL”).
- **When to choose Hive** — 3–5 scenarios (e.g. production agents that must improve over time, outcome-based evaluation, need for built-in monitoring).
- **When to choose them** — 2–3 scenarios (e.g. maximum control over every step, RAG-heavy with existing ecosystem).
- **Link** — to full comparison article.

**Existing input:** Use the “When to Choose Aden” / “When to Choose [Competitor]” sections and summary tables from [aden-vs-langchain](articles/aden-vs-langchain.md), [aden-vs-crewai](articles/aden-vs-crewai.md), and [aden-vs-autogen](articles/aden-vs-autogen.md).

### 2. Buyer / user persona positioning

**Purpose:** Align messaging to who is evaluating Hive.

**Suggested personas:**

- **Developer** — “Ship production agents without hardcoding workflows; get generated graphs and evolution from failures.”
- **Engineering / platform lead** — “Observability, cost control, and human-in-the-loop built in; fewer custom integrations.”
- **Product / ops** — “Agents that are evaluated by business outcomes and improve when they fail.”

**Per persona:** 2–3 value bullets, 1–2 objections (“Isn’t this like LangChain?” → point to [How Hive is Different](../README.md#how-hive-is-different) and comparison docs).

### 3. ROI / TCO framework

**Purpose:** Explain why goal-driven + evolution can reduce long-term cost and increase reliability.

**Suggested angles:**

- **Less manual workflow maintenance** — graph and connections generated from goals; evolution updates the agent from failure data.
- **Fewer one-off integrations** — built-in monitoring, budgets, degradation, HITL.
- **Outcome-based evaluation** — success = goal met, not “steps ran”; fewer dead ends and rework.
- **Self-improvement** — failures feed evolution; over time, fewer manual fixes and firefights.

**Format:** Short narrative plus optional one-pager (problem → Hive approach → impact).

### 4. Demo scripts by business outcome

**Purpose:** Show Hive in action for outcomes people care about (not just “run an agent”).

**Suggested outcomes:**

- **Reliability** — “Agent that handles edge cases and improves when it fails” (show evolution loop, decision logging).
- **Control** — “Agent with spending limits and human approval steps” (show budget, HITL nodes).
- **Speed to production** — “From goal to running agent in one flow” (show goal → generated graph → run).
- **Observability** — “See what the agent did and why” (show TUI / dashboard, logs).

**Per script:** 1) outcome in one sentence, 2) 3–5 demo steps, 3) one “ask” or next step (e.g. try quickstart, read comparison doc).

### 5. Migration guides

**Purpose:** Lower friction for teams already using another framework.

**Suggested guides:**

- **From LangChain (or similar)** — “Bring your tools and prompts; we’ll help map chains to goals and nodes.” Link to [LangChain comparison](articles/aden-vs-langchain.md#migration-considerations). Outline: goal definition, node design, tool reuse, running in parallel.
- **From workflow engines (e.g. n8n)** — “From drawn workflows to described outcomes.” Outline: express current workflow as outcomes and constraints, generate agent, iterate.
- **From CrewAI / AutoGen** — “From roles/conversations to goal-driven graphs.” Link to [CrewAI](articles/aden-vs-crewai.md) and [AutoGen](articles/aden-vs-autogen.md) comparisons; outline: map roles/tasks to nodes and edges, define goal and criteria.

**Format:** Short “Before / After” plus step-by-step checklist and links to key_concepts (goals, graph, evolution).

---

If you want to draft or expand any of these (e.g. battle card text, persona bullets, or a migration checklist), open an issue or PR and reference this doc.
