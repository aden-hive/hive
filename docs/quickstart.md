# Quickstart Guide

A step-by-step guide for new users: from cloning the repo to running your first agent.

---

## 1. Clone and Set Up

```bash
git clone https://github.com/aden-hive/hive.git
cd hive
./quickstart.sh          # Linux / macOS
# .\quickstart.ps1       # Windows PowerShell
```

### What `quickstart.sh` does

The setup script performs these steps in order:

| Step | What happens |
|------|--------------|
| **1 — Python check** | Verifies Python 3.11+ is available |
| **2 — Install packages** | Installs `framework` (core) and `aden_tools` (tools) into separate `uv` virtual environments |
| **3 — Verify imports** | Runs a smoke-test to confirm all packages import cleanly |
| **4 — Claude Code skills** | Links the built-in skills so Claude Code can build agents for you |
| **5 — Credential store** | Initializes `~/.hive/credentials` — an encrypted store for your API keys |
| **6 — Verify install** | Final health check; prints a success banner |

After setup the script opens the web dashboard in your default browser.

---

## 2. Choose an LLM Provider

Hive needs an LLM to power the Queen agent. During quickstart you are prompted to choose a provider; you can also configure it later:

```bash
hive configure            # Re-open the interactive setup wizard
```

Or set the key directly in the credential store:

```bash
hive credentials set anthropic    # prompts for your Anthropic API key
hive credentials set openai       # prompts for your OpenAI API key
```

Alternatively, export the key as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # add to ~/.bashrc or ~/.zshrc to persist
```

Supported providers: **Anthropic (Claude)**, **OpenAI (GPT)**, **Google (Gemini)**, any LiteLLM-compatible provider.

---

## 3. Launch the Dashboard

```bash
hive serve        # starts the API server and opens the browser
hive open         # re-opens the browser without restarting the server
```

The dashboard runs at `http://localhost:8787` by default.

### Dashboard navigation

| Page | What it does |
|------|--------------|
| **Home** | Type a natural-language goal to create a new agent, or pick a sample prompt |
| **My Agents** | List of all agents you have created; click one to open its workspace |
| **Templates** | Pre-built agent templates — try one in one click |
| **Credentials** | Manage and test your API keys |
| **Settings** | Configure the default LLM model and server options |

---

## 4. Run a Template Agent

The fastest way to see Hive in action:

1. Click **Templates** in the sidebar
2. Choose **Tech & AI News Reporter** (or any other template)
3. Click **Run** — the agent launches in the Workspace

You will see:
- **Chat panel** (left) — the Queen agent asks for your topic preferences
- **Execution log** (right) — live node transitions, tool calls, and decisions
- **Graph view** — visual representation of the node graph

---

## 5. Create Your First Agent

### Option A: Web UI (easiest)

1. Go to the **Home** page
2. Type your goal, for example:
   > "Summarize my GitHub notifications and email me a daily digest"
3. The Queen agent builds the node graph, reviews it with you, then runs it

### Option B: Claude Code (recommended for developers)

Install [Claude Code](https://docs.anthropic.com/claude/docs/claude-code), then from the project root:

```
Use initialize_and_build_agent with goal: "Monitor Hacker News for AI stories and post to Slack"
```

The coding agent generates a complete agent package in `exports/`.

### Option C: CLI (manual)

```bash
# Create the agent directory
mkdir -p exports/my_first_agent

# Edit exports/my_first_agent/agent.json (see developer-guide.md for schema)
# Then validate and run:
PYTHONPATH=exports uv run python -m my_first_agent validate
hive run exports/my_first_agent --input '{"task": "hello world"}'
```

---

## 6. Understand the Queen Agent

Every Hive session has a **Queen** — an LLM-powered orchestrator that:

- **Interprets your goal** and generates a worker agent graph (nodes + edges)
- **Dispatches workers** — each worker node executes one step of the workflow
- **Monitors progress** — reads worker outputs, detects failures, adapts the plan
- **Communicates with you** — client-facing nodes pause and ask for your input when needed

You interact with the Queen via the chat panel. Workers run autonomously in the background and report back through shared memory.

```
You → Queen → [Worker 1] → [Worker 2] → [Worker 3] → Result
                   ↑              ↑
             (LLM + tools)  (LLM + tools)
```

The Queen never executes tools directly; it delegates to workers. This separation keeps the orchestration logic clean and testable.

---

## 7. Next Steps

- **[Developer Guide](developer-guide.md)** — build custom agents with function nodes, write tests
- **[Configuration Guide](configuration.md)** — model selection, cost limits, storage paths
- **[Architecture Overview](architecture/README.md)** — deep-dive into the runtime internals
- **[Contributing](../CONTRIBUTING.md)** — submit your first PR
- **[Discord](https://discord.com/invite/MXE49hrKDk)** — get help and share what you build

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'framework'`

```bash
cd core && uv pip install -e .
```

### `ModuleNotFoundError: No module named 'aden_tools'`

```bash
cd tools && uv pip install -e .
```

### Dashboard won't open

```bash
hive serve --port 8080    # try a different port
# or open http://localhost:8787 manually
```

### LLM call fails with authentication error

```bash
hive credentials set anthropic    # re-enter your API key
# or verify the environment variable is set:
echo $ANTHROPIC_API_KEY
```

### Windows: browser doesn't open automatically

Run `.\hive.ps1 serve` from PowerShell — the `.ps1` wrapper sets up the correct environment and opens the browser.
