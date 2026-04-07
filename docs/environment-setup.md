# Agent Development Environment Setup

Complete setup guide for building and running goal-driven agents with the Aden Agent Framework.

## Quick Setup

```bash
# Run the automated setup script
./quickstart.sh
```

> **Note for Windows Users:**
> Native Windows is supported via `quickstart.ps1`. Run it in PowerShell 5.1+. Disable "App Execution Aliases" in Windows settings to avoid Python path conflicts.

This will:

- Check Python version (requires 3.11+)
- Install the core framework package (`framework`)
- Install the tools package (`aden_tools`)
- Initialize encrypted credential store (`~/.hive/credentials`)
- Configure default LLM provider
- Fix package compatibility issues (openai + litellm)
- Verify all installations

## Windows Setup

Native Windows is supported. Run the PowerShell quickstart:

```powershell
.\quickstart.ps1
```

Alternatively, you can use WSL:

1. [Install WSL 2](https://learn.microsoft.com/en-us/windows/wsl/install):
   ```powershell
   wsl --install
   ```
2. Open your WSL terminal, clone the repo, and run:
   ```bash
   ./quickstart.sh
   ```

## Alpine Linux Setup

If you are using Alpine Linux (e.g., inside a Docker container), you must install system dependencies and use a virtual environment before running the setup script:

1. Install System Dependencies:

```bash
apk update
apk add bash git python3 py3-pip nodejs npm curl build-base python3-dev linux-headers libffi-dev
```

2. Set up Virtual Environment (Required for Python 3.12+):

```
uv venv
source .venv/bin/activate
# uv handles pip/setuptools/wheel automatically
```

3. Run the Quickstart Script:

```
./quickstart.sh
```

## Requirements

### Python Version

- **Minimum:** Python 3.11
- **Recommended:** Python 3.11 or 3.12
- **Tested on:** Python 3.11, 3.12, 3.13

### System Requirements

- pip (latest version)
- 2GB+ RAM
- Internet connection (for LLM API calls)
- For Windows users: PowerShell 5.1+ (native) or WSL 2.

### API Keys

We recommend using `quickstart.sh` for LLM API credential setup and the credentials UI/tooling for tool credentials.

## Building New Agents and Run Flow

Build and run an agent using Claude Code CLI with the agent building skills:

### 1. Install Claude Skills (One-time)

```bash
./quickstart.sh
```

This sets up the MCP tools and workflows for building agents.

### Cursor IDE Support

MCP tools are also available in Cursor. To enable:

1. Open Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`)
2. Run `MCP: Enable` to enable MCP servers
3. Restart Cursor to load the MCP servers from `.cursor/mcp.json`
4. Open Agent chat and verify MCP tools are available

### 2. Build an Agent

**Claude Code:**
```
Use the coder-tools initialize_and_build_agent tool to scaffold a new agent
```

**Codex CLI:**
```
Start Codex in the repo root and use the configured MCP tools
```

Follow the prompts to:

1. Define your agent's goal
2. Design the workflow nodes
3. Connect nodes with edges
4. Generate the agent package under `exports/`

This step creates the initial agent structure required for further development.

### 3. Define Agent Logic

```
claude> architecture guidance
```

Follow the prompts to:

1. Understand the agent architecture and file structure
2. Define the agent's goal, success criteria, and constraints
3. Learn node types (event_loop only)
4. Discover and validate available tools before use

This step establishes the core concepts and rules needed before building an agent.

## Troubleshooting

### "externally-managed-environment" error (PEP 668)

**Cause:** Python 3.12+ on macOS/Homebrew, WSL, or some Linux distros prevents system-wide pip installs.

**Solution:** Create and use a virtual environment:

```bash
# Create virtual environment
uv venv

# Activate it
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Then run setup
./quickstart.sh
```

Always activate the venv before running agents:

```bash
source .venv/bin/activate
PYTHONPATH=exports uv run python -m your_agent_name demo
```

### PowerShell: “running scripts is disabled on this system”

Run once per session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### "ModuleNotFoundError: No module named 'framework'"

**Solution:** Sync the workspace dependencies:

```bash
# From repository root
uv sync
```

### "ModuleNotFoundError: No module named 'aden_tools'"

**Solution:** Sync the workspace dependencies:

```bash
# From repository root
uv sync
```

Or run the setup script:

```bash
./quickstart.sh
```

### "ModuleNotFoundError: No module named 'openai.\_models'"

**Cause:** Outdated `openai` package (0.27.x) incompatible with `litellm`

**Solution:** Upgrade openai:

```bash
uv pip install --upgrade "openai>=1.0.0"
```

### "No module named 'your_agent_name'"

**Cause:** Not running from project root, missing PYTHONPATH, or agent not yet created

**Solution:** Ensure you're in `/hive/` and use:

Linux/macOS:

```bash
PYTHONPATH=exports uv run python -m your_agent_name validate
```

Windows:

```powershell
$env:PYTHONPATH="core;exports"
python -m support_ticket_agent validate
```

### Agent imports fail with "broken installation"

**Symptom:** `pip list` shows packages pointing to non-existent directories

**Solution:** Reinstall packages properly:

```bash
# Remove broken installations
uv pip uninstall framework tools

# Reinstall correctly
./quickstart.sh
```

## Package Structure

The Hive framework consists of three Python packages:

```
hive/
├── .venv/                   # Single workspace venv (created by uv sync)
├── core/                    # Core framework (runtime, graph executor, LLM providers)
│   ├── framework/
│   └── pyproject.toml
│
├── tools/                   # Tools and MCP servers
│   ├── src/
│   │   └── aden_tools/     # Actual package location
│   └── pyproject.toml
│
├── exports/                 # Agent packages (user-created, gitignored)
│   └── your_agent_name/     # Created via coder-tools workflow
│
└── examples/
    └── templates/           # Pre-built template agents
```

## Virtual Environment Setup

Hive uses **uv workspaces** to manage dependencies. When you run `uv sync` from the repository root, a **single `.venv`** is created at the root containing both packages.

### Benefits of Workspace Mode

- **Single environment** - No need to switch between multiple venvs
- **Unified dependencies** - Consistent package versions across core and tools
- **Simpler development** - One activation, access to everything

### How It Works

When you run `./quickstart.sh` or `uv sync`:

1. **/.venv/** - Single root virtual environment is created
2. Both `framework` (from core/) and `aden_tools` (from tools/) are installed
3. All dependencies (anthropic, litellm, beautifulsoup4, pandas, etc.) are resolved together

If you need to refresh the environment:

```bash
# From repository root
uv sync
```

### Cross-Package Imports

The `core` and `tools` packages are **intentionally independent**:

- **No cross-imports**: `framework` does not import `aden_tools` directly, and vice versa
- **Communication via MCP**: Tools are exposed to agents through MCP servers, not direct Python imports
- **Runtime integration**: The agent runner loads tools via the MCP protocol at runtime

If you need to use both packages in a single script (e.g., for testing), prefer `uv run` with `PYTHONPATH`:

```bash
PYTHONPATH=tools/src uv run python your_script.py
```

### MCP Server Configuration

The `.mcp.json` at project root configures MCP servers to run through `uv run` in each package directory:

```json
{
  "mcpServers": {
    "coder-tools": {
      "command": "uv",
      "args": ["run", "coder_tools_server.py", "--stdio"],
      "cwd": "tools"
    },
    "tools": {
      "command": "uv",
      "args": ["run", "mcp_server.py", "--stdio"],
      "cwd": "tools"
    }
  }
}
```

This ensures each MCP server runs with the correct project environment managed by `uv`.

### Why PYTHONPATH is Required

The packages are installed in **editable mode** (`uv pip install -e`), which means:

- `framework` and `aden_tools` are globally importable (no PYTHONPATH needed)
- `exports` is NOT installed as a package (PYTHONPATH required)

This design allows agents in `exports/` to be:

- Developed independently
- Version controlled separately
- Deployed as standalone packages

## Development Workflow

### 1. Setup (Once)

```bash
./quickstart.sh
```

### 2. Build Agent (Claude Code)

```
Use the coder-tools initialize_and_build_agent tool
Enter goal: "Build an agent that processes customer support tickets"
```

### 3. Validate Agent

```bash
PYTHONPATH=exports uv run python -m your_agent_name validate
```

### 4. Test Agent

```
claude> test workflow
```

### 5. Run Agent

```bash
# Interactive dashboard
hive open

# Or run directly
hive run exports/your_agent_name --input '{"task": "..."}'
```

## Testing with Dummy Agents

The repository includes a suite of dummy agents under `core/tests/dummy_agents/` for end-to-end testing against real LLM providers. These are **not** part of CI — they make real API calls and are meant to be run manually to verify the executor works correctly.

### Running the Tests

```bash
cd core && uv run python tests/dummy_agents/run_all.py
```

The script auto-detects available LLM credentials and prompts you to pick a provider. You need at least one of:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `KIMI_API_KEY`
- `ZAI_API_KEY`
- A Claude Code, Codex, or Kimi subscription

For verbose output with live LLM logs, tool calls, and node traversal details:

```bash
cd core && uv run python tests/dummy_agents/run_all.py --verbose
```

### What's Covered

| Agent          | Tests | Coverage                                          |
| -------------- | ----- | ------------------------------------------------- |
| echo           | 2     | Single-node lifecycle, basic `set_output`          |
| pipeline       | 4     | Multi-node traversal, `input_mapping`, conversation modes |
| branch         | 3     | Conditional edges, LLM-driven routing              |
| parallel_merge | 4     | Fan-out/fan-in, failure strategies                  |
| retry          | 4     | Retry mechanics, exhaustion, `ON_FAILURE` edges     |
| feedback_loop  | 3     | Feedback cycles, `max_node_visits`                  |
| worker         | 4     | Real MCP tools (`example_tool`, `get_current_time`, `save_data`/`load_data`) |

Typical runtime is 1–3 minutes depending on provider latency.

### Running Individual Test Files

You can also run a specific dummy agent test with pytest directly:

```bash
cd core && uv run pytest tests/dummy_agents/test_echo.py -v
```

> **Note:** Individual pytest runs require the LLM provider to be configured via the `conftest.py` fixture. The `run_all.py` script handles this automatically.

## Environment Variables

### Required for LLM Operations

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENROUTER_API_KEY="your-openrouter-key"  # Optional
export HIVE_API_KEY="your-hive-key"              # Optional
```

Quickstart also supports selecting OpenRouter and Hive LLM interactively. See [configuration.md](./configuration.md) for the full configuration examples.

### Optional Configuration

```bash
# Fernet encryption key for credential store at ~/.hive/credentials
export HIVE_CREDENTIAL_KEY="your-fernet-key"

# Agent storage location (default: /tmp)
export AGENT_STORAGE_PATH="/custom/storage"
```

## Support

- **Issues:** https://github.com/adenhq/hive/issues
- **Discord:** https://discord.com/invite/MXE49hrKDk
- **Documentation:** https://docs.adenhq.com/
