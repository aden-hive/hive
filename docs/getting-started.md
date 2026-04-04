# Getting Started with Hive

> **Important:** Hive uses a `uv` workspace layout. Do **not** use `pip install .` — it will fail. Use the commands in this guide instead.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ (3.12 recommended) | [python.org](https://www.python.org/downloads/) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| git | any | [git-scm.com](https://git-scm.com/) |
| Node.js | 20+ | Required only if running the frontend dashboard |

---

## 1. Clone and Install

```bash
git clone https://github.com/aden-hive/hive.git
cd hive

# Sets up the full uv workspace (both `framework` and `aden_tools` packages)
uv sync
```

Verify the install:

```bash
uv run python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

> **Windows (PowerShell):** Use `.\quickstart.ps1` instead of `uv sync`. If you see "running scripts is disabled", first run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

---

## 2. Set Your LLM API Key

Hive needs at least one LLM provider to run agents:

```bash
# Pick one (Anthropic recommended for best compatibility)
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."           # Optional
export OPENROUTER_API_KEY="..."          # Optional
```

Add to `~/.zshrc` or `~/.bashrc` to persist across sessions.

Get your key:
- Anthropic → [console.anthropic.com](https://console.anthropic.com/)
- OpenAI → [platform.openai.com](https://platform.openai.com/)
- OpenRouter → [openrouter.ai/keys](https://openrouter.ai/keys)

Quickstart can configure this interactively — see [configuration.md](./configuration.md) for all provider options including Hive LLM.

---

## 3. Run Your First Agent (No API Key Required)

Hive ships with a minimal example that runs entirely in Python — no LLM calls, no setup:

```bash
uv run python core/examples/manual_agent.py
```

**Expected output:**

```text
Setting up Manual Agent...
Executing agent with input: name='Alice'...

Success!
Path taken: greeter -> uppercaser
Final output: HELLO, ALICE!
```

This is the core runtime loop: a two-node graph where the first node greets and the second uppercases the result. It demonstrates `NodeSpec`, `EdgeSpec`, `GraphSpec`, `GraphExecutor`, and `NodeProtocol` — the primitives your real agents are built from.

---

## 4. Use a Template Agent

Templates are production-ready agent scaffolds you can run immediately.

```bash
# Copy a template into exports/ (the directory for your agents)
cp -r examples/templates/deep_research_agent exports/my_researcher

# Validate it loads correctly
uv run python -m framework info exports/my_researcher
```

Available templates in `examples/templates/`:

| Template | What it does |
|----------|-------------|
| `deep_research_agent` | Multi-step research with web search |
| `tech_news_reporter` | Monitors and summarizes tech news |
| `email_reply_agent` | Drafts context-aware email replies |
| `job_hunter` | Searches and tracks job listings |
| `competitive_intel_agent` | Gathers competitor intelligence |
| `meeting_scheduler` | Automates scheduling workflows |

Run a template (requires LLM API key):

```bash
uv run python -m framework run exports/my_researcher --input '{"topic": "LLM agent frameworks 2025"}'
```

---

## 5. Open the Dashboard

The Hive UI gives you a visual interface to build, monitor, and run agents:

```bash
# Installs frontend deps (first time only)
make frontend-install

# Starts the dev server
make frontend-dev
```

Or use the `hive` CLI:

```bash
./hive open
```

---

## Project Structure

```text
hive/
├── core/                    # Core framework package (`framework`)
│   ├── framework/           # Runtime, graph executor, LLM providers
│   └── examples/            # Runnable examples (start here)
│
├── tools/                   # MCP tools package (`aden_tools`)
│   └── src/aden_tools/      # Web search, PDF, file system, etc.
│
├── examples/
│   ├── templates/           # Ready-to-run agent scaffolds
│   └── recipes/             # Design patterns (not runnable, for learning)
│
├── exports/                 # Your agents live here (gitignored)
├── docs/                    # Documentation
├── pyproject.toml           # uv workspace config (not a pip package)
└── hive / hive.ps1          # CLI entry point
```

> `exports/` is gitignored — it's where your custom agents are generated or placed.

---

## Build an Agent From a Goal

The recommended workflow for new agents uses the `coder-tools` MCP server with Claude Code or Cursor:

**Claude Code:**
```text
Use the `initialize_and_build_agent` coder-tools MCP tool
Goal: "An agent that monitors Hacker News for AI articles and sends a daily digest"
```

**Or build manually** by creating a folder under `exports/` with:
- `agent.py` — graph definition (nodes, edges, goal)
- `nodes/` — node logic (each node is a `NodeProtocol` subclass)
- `config.py` — model and tool config
- `__main__.py` — CLI entry point

See [developer-guide.md](./developer-guide.md) for the full agent structure reference.

---

## Test Your Agent

```bash
# Validate structure (no LLM required)
PYTHONPATH=exports uv run python -m my_agent validate

# Run constraint tests
PYTHONPATH=exports uv run python -m my_agent test --type constraint

# Run success tests
PYTHONPATH=exports uv run python -m my_agent test --type success
```

---

## Common Commands

```bash
uv sync                                                   # Install / refresh all deps
uv run python core/examples/manual_agent.py               # Run the no-key example
uv run python -m framework info exports/<agent>           # Inspect an agent
uv run python -m framework run exports/<agent> --input …  # Run an agent
make test                                                 # Run core + tools test suites
make frontend-dev                                         # Start the frontend
./hive open                                               # Open dashboard in browser
```

---

## Troubleshooting

**`pip install .` fails with "Multiple top-level packages"**
This is expected. Hive is a `uv` workspace, not a pip package. Use `uv sync` instead.

**`ModuleNotFoundError: No module named 'framework'`**
```bash
uv sync   # From the repository root
```

**`ModuleNotFoundError: No module named 'my_agent'`**
Always run from the repo root and include `PYTHONPATH`:
```bash
PYTHONPATH=exports uv run python -m my_agent validate
```

**API key not found**
```bash
echo $ANTHROPIC_API_KEY   # Should print your key, not empty
```
If empty, re-export it or add it to your shell profile.

**Frontend won't start**
```bash
make frontend-install   # Run this first, then make frontend-dev
```

---

## Next Steps

- **[environment-setup.md](./environment-setup.md)** — Detailed setup, virtualenvs, Alpine/WSL
- **[configuration.md](./configuration.md)** — All LLM provider configs, per-agent settings
- **[developer-guide.md](./developer-guide.md)** — Full agent structure, node types, edge routing
- **[Discord](https://discord.com/invite/MXE49hrKDk)** — Community support
