# Getting Started

This guide will help you set up the Aden Agent Framework and build your first agent.

## Prerequisites

- **Python 3.11+** ([Download](https://www.python.org/downloads/)) - Python 3.12 or 3.13 recommended
- **pip** - Package installer for Python (comes with Python)
- **git** - Version control
- **Claude Code** ([Install](https://docs.anthropic.com/claude/docs/claude-code)) - Optional, for using building skills

## Quick Start

The fastest way to get started:

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Run automated setup
./quickstart.sh

# 3. Verify installation (optional, quickstart.sh already verifies)
uv run python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

## Windows Setup (Native)

> **Recommended:** Use WSL2 for the best experience. Native Windows is supported but requires additional configuration.

### Prerequisites
- **Python 3.11+** ([Download](https://www.python.org/downloads/)) - Python 3.12 or 3.13 recommended
- **Git** for Windows
- **PowerShell 7+** (preferred) or PowerShell 5.1+ 
- **VS Code** (recommended)

### Step 1: Install Python Correctly

1. Download Python 3.11+ from [python.org](https://www.python.org/downloads/)
2. **During installation:**
   - ✅ Check "Add Python to PATH"
   - ✅ Check "Install for all users" (requires admin)
3. Verify:
```powershell
   python --version  # Should show 3.11 or higher
```

### Step 2: Disable App Execution Aliases

Windows may intercept `python` commands and redirect to Microsoft Store.

1. Open **Settings** → **Apps** → **App Execution Aliases**
2. Turn **OFF**:
   - `python.exe`
   - `python3.exe`
3. Close and reopen PowerShell

### Step 3: Clone Repository
```powershell
git clone https://github.com/adenhq/hive.git
cd hive
```

### Step 4: Run Setup Script
```powershell
# Option A: Using Git Bash (if available)
./quickstart.sh

# Option B: Manual PowerShell setup (if quickstart.sh fails)
pip install uv
cd core
uv pip install -e .
cd ..\tools
uv pip install -e .
cd ..
```

### Step 5: Configure Environment Variables
```powershell
# Add to your PowerShell profile (~\Documents\PowerShell\Microsoft.PowerShell_profile.ps1)
$env:ANTHROPIC_API_KEY = "your-key-here"
$env:PYTHONPATH = "exports"

# Or set for current session only:
$env:PYTHONPATH = "exports"
```

**To edit your PowerShell profile:**
```powershell
notepad $PROFILE
# If file doesn't exist, create it first:
New-Item -Path $PROFILE -Type File -Force
```

### Step 6: Verify Installation
```powershell
uv run python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

### Common Windows Issues

#### Issue: ModuleNotFoundError when running agents

**Problem:** `ModuleNotFoundError: No module named 'my_agent'`

**Solution:**
```powershell
# Always set PYTHONPATH before running agents
$env:PYTHONPATH = "exports"
uv run python -m my_agent run --input '{...}'
```

**Permanent fix:** Add to your PowerShell profile:
```powershell
$env:PYTHONPATH = "exports"
```

#### Issue: Permission Errors

**Problem:** Access denied during pip install

**Solution:** Run PowerShell as Administrator or use `--user` flag:
```powershell
pip install --user uv
```

#### Issue: Path Separator Issues

**Problem:** Scripts expect `/` but Windows uses `\`

**Solution:** Python handles this automatically. Use forward slashes in code:
```python
path = "exports/my_agent"  # Works on Windows too
```

#### Issue: 'python' is not recognized

**Problem:** Command not found even after installation

**Solutions:**
1. Restart your terminal/PowerShell
2. Check Python is in PATH:
```powershell
   $env:PATH -split ';' | Select-String python
```
3. Reinstall Python and ensure "Add to PATH" is checked

#### Issue: quickstart.sh won't run

**Problem:** Script format not recognized

**Solutions:**
1. Use Git Bash (comes with Git for Windows)
2. Use manual installation (Step 4, Option B)
3. Install WSL2 for better compatibility

### Running Agents on Windows

When running agents, always remember to set PYTHONPATH:
```powershell
# Validate agent structure
$env:PYTHONPATH = "exports"
uv run python -m my_agent validate

# Run agent
$env:PYTHONPATH = "exports"
uv run python -m my_agent run --input '{"task": "Your input here"}'

# Run tests
$env:PYTHONPATH = "exports"
uv run python -m my_agent test
```

### PowerShell vs Command Prompt

**Use PowerShell** (recommended):
- Better scripting capabilities
- Native support for environment variables
- More modern tooling

**If using Command Prompt:**
```cmd
set PYTHONPATH=exports
uv run python -m my_agent run --input "{\"task\": \"Your input here\"}"
```

Note the escaped quotes (`\"`) in Command Prompt.


## Building Your First Agent

### Option 1: Using Claude Code Skills (Recommended)

```bash
# Setup already done via quickstart.sh above

# Start Claude Code and build an agent
claude> /hive
```

Follow the interactive prompts to:

1. Define your agent's goal
2. Design the workflow (nodes and edges)
3. Generate the agent package
4. Test the agent

### Option 2: Create Agent Manually

> **Note:** The `exports/` directory is where your agents are created. It is not included in the repository (gitignored) because agents are user-generated via Claude Code skills or created manually.

```bash
# Create exports directory if it doesn't exist
mkdir -p exports/my_agent

# Create your agent structure
cd exports/my_agent
# Create agent.json, tools.py, README.md (see developer-guide.md for structure)

# Validate the agent
PYTHONPATH=exports uv run python -m my_agent validate
```

### Option 3: Manual Code-First (Minimal Example)

If you prefer to start with code rather than CLI wizards, check out the manual agent example:

```bash
# View the minimal example
cat core/examples/manual_agent.py

# Run it (no API keys required)
uv run python core/examples/manual_agent.py
```

This demonstrates the core runtime loop using pure Python functions, skipping the complexity of LLM setup and file-based configuration.

## Project Structure

```
hive/
├── core/                   # Core Framework
│   ├── framework/          # Agent runtime, graph executor
│   │   ├── builder/        # Agent builder utilities
│   │   ├── credentials/    # Credential management
│   │   ├── graph/          # GraphExecutor - executes node graphs
│   │   ├── llm/            # LLM provider integrations
│   │   ├── mcp/            # MCP server integration
│   │   ├── runner/         # AgentRunner - loads and runs agents
│   │   ├── runtime/        # Runtime environment
│   │   ├── schemas/        # Data schemas
│   │   ├── storage/        # File-based persistence
│   │   ├── testing/        # Testing utilities
│   │   └── tui/            # Terminal UI dashboard
│   └── pyproject.toml      # Package metadata
│
├── tools/                  # MCP Tools Package
│   ├── mcp_server.py       # MCP server entry point
│   └── src/aden_tools/     # Tools for agent capabilities
│       └── tools/          # Individual tool implementations
│           ├── web_search_tool/
│           ├── web_scrape_tool/
│           └── file_system_toolkits/
│
├── exports/                # Agent Packages (user-generated, not in repo)
│   └── your_agent/         # Your agents created via /hive
│
├── examples/
│   └── templates/          # Pre-built template agents
│
├── .claude/                # Claude Code Skills
│   └── skills/
│       ├── hive/
│       ├── hive-create/
│       ├── hive-concepts/
│       ├── hive-patterns/
│       └── hive-test/
│
└── docs/                   # Documentation
```

## Running an Agent

```bash
# Browse and run agents interactively (Recommended)
hive tui

# Run a specific agent
hive run exports/my_agent --input '{"task": "Your input here"}'

# Run with TUI dashboard
hive run exports/my_agent --tui

```

## API Keys Setup

For running agents with real LLMs:

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"        # Optional
export BRAVE_SEARCH_API_KEY="your-key-here"  # Optional, for web search
```

Get your API keys:

- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/)
- **OpenAI**: [platform.openai.com](https://platform.openai.com/)
- **Brave Search**: [brave.com/search/api](https://brave.com/search/api/)

## Testing Your Agent

```bash
# Using Claude Code
claude> /hive-test

# Or manually
PYTHONPATH=exports uv run python -m my_agent test

# Run with specific test type
PYTHONPATH=exports uv run python -m my_agent test --type constraint
PYTHONPATH=exports uv run python -m my_agent test --type success
```

## Next Steps

1. **TUI Dashboard**: Run `hive tui` to explore agents interactively
2. **Detailed Setup**: See [environment-setup.md](./environment-setup.md)
3. **Developer Guide**: See [developer-guide.md](./developer-guide.md)
4. **Build Agents**: Use `/hive` skill in Claude Code
5. **Custom Tools**: Learn to integrate MCP servers
6. **Join Community**: [Discord](https://discord.com/invite/MXE49hrKDk)

## Troubleshooting

### ModuleNotFoundError: No module named 'framework'

```bash
# Reinstall framework package
cd core
uv pip install -e .
```

### ModuleNotFoundError: No module named 'aden_tools'

```bash
# Reinstall tools package
cd tools
uv pip install -e .
```

### LLM API Errors

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

```

### Package Installation Issues

```bash
# Remove and reinstall
pip uninstall -y framework tools
./quickstart.sh
```

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)
- **Build Agents**: Use `/hive` skill to create agents
