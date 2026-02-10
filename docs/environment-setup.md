# Agent Development Environment Setup

Complete setup guide for building and running goal-driven agents with the Aden Agent Framework.

## Quick Setup

```bash
# Run the automated setup script
./quickstart.sh
```

> **Note for Windows Users:**
> Running the setup script on native Windows shells (PowerShell / Git Bash) may sometimes fail due to Python App Execution Aliases.
> It is **strongly recommended to use WSL (Windows Subsystem for Linux)** for a smoother setup experience.

This will:

- Check Python version (requires 3.11+)
- Install the core framework package (`framework`)
- Install the tools package (`aden_tools`)
- Initialize encrypted credential store (`~/.hive/credentials`)
- Configure default LLM provider
- Fix package compatibility issues (openai + litellm)
- Verify all installations

## Windows Setup

Windows users should use **WSL (Windows Subsystem for Linux)** to set up and run agents.

1. [Install WSL 2](https://learn.microsoft.com/en-us/windows/wsl/install) if you haven't already:
   ```powershell
   wsl --install
   ```
2. Open your WSL terminal, clone the repo, and run the quickstart script:
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

## Manual Setup (Alternative)

If you prefer to set up manually or the script fails:

### 1. Install Core Framework

```bash
cd core
uv pip install -e .
```

### 2. Install Tools Package

```bash
cd tools
uv pip install -e .
```

### 3. Upgrade OpenAI Package

```bash
# litellm requires openai >= 1.0.0
uv pip install --upgrade "openai>=1.0.0"
```

### 4. Verify Installation

```bash
uv run python -c "import framework; print('✓ framework OK')"
uv run python -c "import aden_tools; print('✓ aden_tools OK')"
uv run python -c "import litellm; print('✓ litellm OK')"
```

> **Windows Tip:**
> On Windows, if the verification commands fail, ensure you are running them in **WSL** or after **disabling Python App Execution Aliases** in Windows Settings → Apps → App Execution Aliases.

## Requirements

### Python Version

- **Minimum:** Python 3.11
- **Recommended:** Python 3.11 or 3.12
- **Tested on:** Python 3.11, 3.12, 3.13

### System Requirements

- pip (latest version)
- 2GB+ RAM
- Internet connection (for LLM API calls)
- For Windows users: WSL 2 is recommended for full compatibility.

### API Keys

We recommend using quickstart.sh for LLM API credential setup and /hive-credentials for the tools credentials

## Running Agents

The `hive` CLI is the primary interface for running agents:

```bash
# Browse and run agents interactively (Recommended)
hive tui

# Run a specific agent
hive run exports/my_agent --input '{"task": "Your input here"}'

# Run with TUI dashboard
hive run exports/my_agent --tui
```

### CLI Command Reference

| Command | Description |
|---------|-------------|
| `hive tui` | Browse agents and launch TUI dashboard |
| `hive run <path>` | Execute an agent (`--tui`, `--model`, `--mock`, `--quiet`, `--verbose`) |
| `hive shell [path]` | Interactive REPL (`--multi`, `--no-approve`) |
| `hive info <path>` | Show agent details |
| `hive validate <path>` | Validate agent structure |
| `hive list [dir]` | List available agents |
| `hive dispatch [dir]` | Multi-agent orchestration |

### Using Python directly (alternative)

```bash
# From /hive/ directory
PYTHONPATH=exports uv run python -m agent_name COMMAND
```

Windows (PowerShell):

```powershell
$env:PYTHONPATH="core;exports"
python -m agent_name COMMAND
```

## Building New Agents and Run Flow

Build and run an agent using Claude Code CLI with the agent building skills:

### 1. Install Claude Skills (One-time)

```bash
./quickstart.sh
```

This verifies agent-related Claude Code skills are available:

- `/hive` - Complete workflow for building agents
- `/hive-create` - Step-by-step build guide
- `/hive-concepts` - Fundamental concepts
- `/hive-patterns` - Best practices
- `/hive-test` - Test and validate agents

### Cursor IDE Support

Skills are also available in Cursor. To enable:

1. Open Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`)
2. Run `MCP: Enable` to enable MCP servers
3. Restart Cursor to load the MCP servers from `.cursor/mcp.json`
4. Type `/` in Agent chat and search for skills (e.g., `/hive-create`)

### 2. Build an Agent

```
claude> /hive
```

Follow the prompts to:

1. Define your agent's goal
2. Design the workflow nodes
3. Connect nodes with edges
4. Generate the agent package under `exports/`

This step creates the initial agent structure required for further development.

### 3. Define Agent Logic

```
claude> /hive-concepts
```

Follow the prompts to:

1. Understand the agent architecture and file structure
2. Define the agent's goal, success criteria, and constraints
3. Learn node types (LLM, tool-use, router, function)
4. Discover and validate available tools before use

This step establishes the core concepts and rules needed before building an agent.

### 4. Apply Agent Patterns

```
claude> /hive-patterns
```

Follow the prompts to:

1. Apply best-practice agent design patterns
2. Add pause/resume flows for multi-turn interactions
3. Improve robustness with routing, fallbacks, and retries
4. Avoid common anti-patterns during agent construction

This step helps optimize agent design before final testing.

### 5. Test Your Agent

```
claude> /hive-test
```

Follow the prompts to:

1. Generate test guidelines for constraints and success criteria
2. Write agent tests directly under `exports/{agent}/tests/`
3. Run goal-based evaluation tests
4. Debug failing tests and iterate on agent improvements

This step verifies that the agent meets its goals before production use.

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

**Solution:** Install the core package:

```bash
cd core && uv pip install -e .
```

### "ModuleNotFoundError: No module named 'aden_tools'"

**Solution:** Install the tools package:

```bash
cd tools && uv pip install -e .
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
├── core/                    # Core framework (runtime, graph executor, LLM providers)
│   ├── framework/
│   ├── .venv/              # Created by quickstart.sh
│   └── pyproject.toml
│
├── tools/                   # Tools and MCP servers
│   ├── src/
│   │   └── aden_tools/     # Actual package location
│   ├── .venv/              # Created by quickstart.sh
│   └── pyproject.toml
│
├── exports/                 # Agent packages (user-created, gitignored)
│   └── your_agent_name/     # Created via /hive-create
│
└── examples/
    └── templates/           # Pre-built template agents
```

## Separate Virtual Environments

Hive primarily uses **uv** to create and manage separate virtual environments for `core` and `tools`.

The project uses separate virtual environments to:

- Isolate dependencies and avoid conflicts
- Allow independent development and testing of each package
- Enable MCP servers to run with their specific dependencies

### How It Works

When you run `./quickstart.sh`, `uv` sets up:

1. **core/.venv/** - Contains the `framework` package and its dependencies (anthropic, litellm, mcp, etc.)
2. **tools/.venv/** - Contains the `aden_tools` package and its dependencies (beautifulsoup4, pandas, etc.)

If you need to refresh environments manually, use `uv`:

```bash
cd core && uv sync
cd ../tools && uv sync
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
    "agent-builder": {
      "command": "uv",
      "args": ["run", "-m", "framework.mcp.agent_builder_server"],
      "cwd": "core"
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
claude> /hive
Enter goal: "Build an agent that processes customer support tickets"
```

### 3. Validate Agent

```bash
PYTHONPATH=exports uv run python -m your_agent_name validate
```

### 4. Test Agent

```
claude> /hive-test
```

### 5. Run Agent

```bash
# Interactive dashboard
hive tui

# Or run directly
hive run exports/your_agent_name --input '{"task": "..."}'
```

## IDE Setup

### VSCode

Add to `.vscode/settings.json`:

```json
{
  "python.analysis.extraPaths": [
    "${workspaceFolder}/core",
    "${workspaceFolder}/exports"
  ],
  "python.autoComplete.extraPaths": [
    "${workspaceFolder}/core",
    "${workspaceFolder}/exports"
  ]
}
```

### PyCharm

1. Open Project Settings → Project Structure
2. Mark `core` as Sources Root
3. Mark `exports` as Sources Root

## Environment Variables

### Required for LLM Operations

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Optional Configuration

```bash
# Credentials storage location (default: ~/.aden/credentials)
export ADEN_CREDENTIALS_PATH="/custom/path"

# Agent storage location (default: /tmp)
export AGENT_STORAGE_PATH="/custom/storage"
```
## Opencode Setup

[Opencode](https://github.com/opencode-ai/opencode) is fully supported as a coding agent.

### Automatic Setup
Run the setup script in the root directory:
```bash

```

## Additional Resources

- **Framework Documentation:** [core/README.md](../core/README.md)
- **Tools Documentation:** [tools/README.md](../tools/README.md)
- **Example Agents:** [exports/](../exports/)
- **Agent Building Guide:** [.claude/skills/hive-create/SKILL.md](../.claude/skills/hive-create/SKILL.md)
- **Testing Guide:** [.claude/skills/hive-test/SKILL.md](../.claude/skills/hive-test/SKILL.md)




## Contributing

When contributing agent packages:

1. Place agents in `exports/agent_name/`
2. Follow the standard agent structure (see existing agents)
3. Include README.md with usage instructions
4. Add tests if using `/hive-test`
5. Document required environment variables

## Support

- **Issues:** https://github.com/adenhq/hive/issues
- **Discord:** https://discord.com/invite/MXE49hrKDk
- **Documentation:** https://docs.adenhq.com/
