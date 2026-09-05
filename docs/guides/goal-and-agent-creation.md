# Goal and Agent Creation Guide

This guide walks you through how goals become runnable agents in the Aden Agent Framework: what a goal is, how a coding agent turns it into an agent package, what gets produced, where it lives, how to run it, and how evaluation fits in. It is aimed at first-time users and new contributors.

---

## 1. What is a "goal"?

A **goal** is the natural-language description of *what* you want the agent to achieve, not *how* it should do it.

In the framework, a goal is a structured object that includes:

- **Name and description** – Human-readable summary of the objective (e.g. "Process customer support tickets and route by priority").
- **Success criteria** – Measurable conditions that define "done" (e.g. "Ticket is categorized and assigned to the right team"). Each criterion can have a metric (`output_contains`, `llm_judge`, `custom`, etc.) and a weight.
- **Constraints** – Boundaries the agent must respect (e.g. "Never expose customer PII in logs"). Constraints can be *hard* (violation means failure) or *soft*.

You can think of the goal as the **source of truth** for agent behavior: the graph (nodes and edges) is derived from it, and evaluation checks results against the goal’s success criteria and constraints.

**In practice:** When you use the building skills (e.g. in Claude Code or Cursor), you start by describing the goal in plain language. The coding agent then turns that into a formal `Goal` and uses it to design the agent.

---

## 2. How a coding agent generates an agent from a goal

The framework does **not** require you to hand-write the graph. A **coding agent** (e.g. Claude, using the project’s skills) generates the agent for you:

1. **You provide the goal** – In natural language, via the building-agents skill (e.g. `/building-agents-construction` in Claude Code or Cursor).
2. **The coding agent designs the workflow** – It proposes *nodes* (steps like LLM calls, functions, routers) and *edges* (how execution flows: on success, on failure, or conditional).
3. **The coding agent generates the agent package** – It produces the files that the framework needs to run and test the agent (see next section).
4. **You validate and iterate** – You run `validate`, run the agent, and use the testing skill to refine.

The coding agent uses **MCP tools** (e.g. from the agent builder MCP server) to create goals, add nodes and edges, and export the agent. All of this is driven by your stated goal and success criteria.

**Recommended path:** Use the Claude Code skill `/building-agents-construction` (or the Cursor equivalent) so the coding agent can create the goal, graph, and export in one flow. See [Getting Started](../getting-started.md) and [DEVELOPER.md](../../DEVELOPER.md) for setup.

---

## 3. What files are produced

When an agent is generated (or exported), the following files are created under a single agent directory:

| File | Purpose |
|------|--------|
| **`agent.json`** | **Required.** The full agent specification: graph structure (`GraphSpec`) and goal. Defines `goal_id`, `entry_node`, `terminal_nodes`, `nodes`, `edges`, optional `pause_nodes` (HITL), and related metadata. The framework loads this to run the agent. |
| **`README.md`** | Generated documentation for the agent (name, description, how to run). |
| **`tools.py`** | Optional. Custom Python tools for this agent. If present, the runner discovers and registers them. Agents can also use MCP tools via `mcp_servers.json`. |
| **`mcp_servers.json`** | Optional. Configuration for MCP servers (e.g. `aden_tools`) so nodes can call web search, file ops, etc. |
| **`tests/`** | Optional. Test modules (e.g. `test_constraint.py`, `test_success_criteria.py`) generated from the goal’s constraints and success criteria. Used by the testing framework and the `/testing-agent` skill. |

The **minimum** you need to run an agent is a directory containing a valid `agent.json`. The other files improve documentation, capabilities, and testability.

---

## 4. Where generated agents live: `exports/`

Generated agents live under the **`exports/`** directory at the project root:

```
hive/
├── core/           # Framework
├── tools/           # MCP tools (e.g. aden_tools)
├── exports/         # Your agents (one folder per agent)
│   ├── my_agent/
│   │   ├── agent.json
│   │   ├── README.md
│   │   ├── tools.py        # optional
│   │   ├── mcp_servers.json # optional
│   │   └── tests/          # optional
│   └── support_ticket_agent/
│       └── ...
└── ...
```

- **`exports/` is gitignored** – Agents are treated as user- or coding-agent-generated output, so they are not committed by default. You can still commit an agent by adding it to version control explicitly.
- **Path convention** – When you run or validate an agent, you pass the path to the agent *folder* (e.g. `exports/my_agent`), not to `agent.json` alone. The framework looks for `agent.json` inside that folder.

---

## 5. How to run an agent

After the agent is in `exports/<agent_name>/`, you run it with the **hive** CLI (or `python -m framework` from the `core` directory).

**From the project root** (with `core` and `exports` available):

```bash
# Validate the agent (checks structure and required tools)
hive validate exports/my_agent

# Show agent info (name, description, node count, tools)
hive info exports/my_agent

# Run with JSON input
hive run exports/my_agent --input '{"ticket_content": "I cannot log in", "customer_id": "CUST-123"}'

# Run with input from a file
hive run exports/my_agent --input-file input.json

# Run in mock mode (no real LLM calls; useful for quick checks)
hive run exports/my_agent --mock --input '{}'

# List all agents in a directory
hive list exports/
```

If you are not using an installed `hive` entry point, use:

```bash
PYTHONPATH=core python -m framework run exports/my_agent --input '{...}'
```

Ensure `exports/` is on `PYTHONPATH` if the agent imports custom code (e.g. from `tools.py`). The framework’s CLI can add `core` and `exports` automatically when invoked from the project root; see [Getting Started](../getting-started.md) and [DEVELOPER.md](../../DEVELOPER.md) for full setup.

**Testing:** Use the `/testing-agent` skill to generate and run tests, or run the test suite for an agent (e.g. `hive test-run exports/my_agent --goal <goal_id>`). See the [Developer Guide](../../DEVELOPER.md#testing-agents) for manual test commands.

---

## 6. Evaluation and reflexion at a high level

When the agent runs, the framework doesn’t only execute steps—it can **evaluate** outcomes and **react** (reflexion loop):

- **Evaluation** – Results are checked against the goal: e.g. deterministic rules (constraint checks), LLM-based judgment (success criteria), and optionally human review when the system is uncertain. This “triangulated” approach is described in the architecture doc.
- **Reflexion** – After a step, the system can **ACCEPT** (continue), **RETRY** (try again with feedback), **REPLAN** (change approach), or **ESCALATE** (ask a human). So the agent can improve from failure instead of only failing.

You don’t have to implement this yourself: the framework provides the evaluation and reflexion machinery. For the theory and design (triangulated verification, worker–judge, confidence, HITL), see the [Architecture overview](../architecture/README.md).

---

## 7. Where to go next

- **[Getting Started](../getting-started.md)** – Setup, first agent, and running.
- **[DEVELOPER.md](../../DEVELOPER.md)** – Project layout, building and testing agents, code style, and common tasks.
- **[Architecture](../architecture/README.md)** – Goal-driven design, triangulated verification, reflexion loop, and roadmap.
- **[Configuration](../configuration.md)** – Configuration options for the framework and runs.
- **[CONTRIBUTING.md](../../CONTRIBUTING.md)** – How to contribute, issue assignment, and PR process.

Using the **building-agents** and **testing-agent** skills (in Claude Code or Cursor) is the most practical way to create and refine agents from goals without editing `agent.json` or graph code by hand.
