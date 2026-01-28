# Agent Development Environment Setup

Complete setup guide for building and running goal-driven agents with the Aden Agent Framework.

## Quick Setup

```bash
# Run the automated setup script
./scripts/setup-python.sh
```

> **Note for Windows Users:**  
> Running the setup script on native Windows shells (PowerShell / Git Bash) may sometimes fail due to Python App Execution Aliases.  
> It is **strongly recommended to use WSL (Windows Subsystem for Linux)** for a smoother setup experience.

This will:

- Check Python version (requires 3.11+)
- Install the core framework package (`framework`)
- Install the tools package (`aden_tools`)
- Fix package compatibility issues (openai + litellm)
- Verify all installations

## Manual Setup (Alternative)

If you prefer to set up manually or the script fails:

### 1. Install Core Framework

```bash
cd core
pip install -e .
```

### 2. Install Tools Package

```bash
cd tools
pip install -e .
```

### 3. Upgrade OpenAI Package

```bash
# litellm requires openai >= 1.0.0
pip install --upgrade "openai>=1.0.0"
```

### 4. Verify Installation

```bash
python -c "import framework; print('✓ framework OK')"
python -c "import aden_tools; print('✓ aden_tools OK')"
python -c "import litellm; print('✓ litellm OK')"
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

### API Keys (Optional)

For running agents with real LLMs:

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

## Running Agents

All agent commands must be run from the project root with `PYTHONPATH` set:

```bash
# From /hive/ directory
PYTHONPATH=core:exports python -m agent_name COMMAND
```

### Example: Support Ticket Agent

```bash
# Validate agent structure
PYTHONPATH=core:exports python -m support_ticket_agent validate

# Show agent information
PYTHONPATH=core:exports python -m support_ticket_agent info

# Run agent with input
PYTHONPATH=core:exports python -m support_ticket_agent run --input '{
  "ticket_content": "My login is broken. Error 401.",
  "customer_id": "CUST-123",
  "ticket_id": "TKT-456"
}'

# Run in mock mode (no LLM calls)
PYTHONPATH=core:exports python -m support_ticket_agent run --mock --input '{...}'
```

### Example: Other Agents

```bash
# Market Research Agent
PYTHONPATH=core:exports python -m market_research_agent info

# Outbound Sales Agent
PYTHONPATH=core:exports python -m outbound_sales_agent validate

# Personal Assistant Agent
PYTHONPATH=core:exports python -m personal_assistant_agent run --input '{...}'
```

## Building New Agents

Use Claude Code CLI with the agent building skills:

### 1. Install Skills (One-time)

```bash
./quickstart.sh
```

This installs:

- `/building-agents` - Build new agents
- `/testing-agent` - Test agents

### 2. Build an Agent

```
claude> /building-agents-construction
```

Follow the prompts to:

1. Define your agent's goal
2. Design the workflow nodes
3. Connect edges
4. Generate the agent package

### 3. Test Your Agent

```
claude> /testing-agent
```

Creates comprehensive test suites for your agent.

## Troubleshooting

### "externally-managed-environment" error (PEP 668)

**Cause:** Python 3.12+ on macOS/Homebrew, WSL, or some Linux distros prevents system-wide pip installs.

**Solution:** Create and use a virtual environment:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Then run setup
./scripts/setup-python.sh
```

Always activate the venv before running agents:

```bash
source .venv/bin/activate
PYTHONPATH=core:exports python -m your_agent_name demo
```

### "ModuleNotFoundError: No module named 'framework'"

**Solution:** Install the core package:

```bash
cd core && pip install -e .
```

### "ModuleNotFoundError: No module named 'aden_tools'"

**Solution:** Install the tools package:

```bash
cd tools && pip install -e .
```

Or run the setup script:

```bash
./scripts/setup-python.sh
```

### "ModuleNotFoundError: No module named 'openai.\_models'"

**Cause:** Outdated `openai` package (0.27.x) incompatible with `litellm`

**Solution:** Upgrade openai:

```bash
pip install --upgrade "openai>=1.0.0"
```

### "No module named 'support_ticket_agent'"

**Cause:** Not running from project root or missing PYTHONPATH

**Solution:** Ensure you're in the project root directory and use:

```bash
PYTHONPATH=core:exports python -m support_ticket_agent validate
```

### Agent imports fail with "broken installation"

**Symptom:** `pip list` shows packages pointing to non-existent directories

**Solution:** Reinstall packages properly:

```bash
# Remove broken installations
pip uninstall -y framework tools

# Reinstall correctly
./scripts/setup-python.sh
```

## Package Structure

The Hive framework consists of three Python packages:

```
hive/
├── core/                    # Core framework (runtime, graph executor, LLM providers)
│   ├── framework/
│   ├── pyproject.toml
│   └── requirements.txt
│
├── tools/                   # Tools and MCP servers
│   ├── src/
│   │   └── aden_tools/     # Actual package location
│   ├── pyproject.toml
│   └── README.md
│
└── exports/                 # Agent packages (your agents go here)
    ├── support_ticket_agent/
    ├── market_research_agent/
    ├── outbound_sales_agent/
    └── personal_assistant_agent/
```

### Why PYTHONPATH is Required

The packages are installed in **editable mode** (`pip install -e`), which means:

- `framework` and `aden_tools` are globally importable (no PYTHONPATH needed)
- `exports` is NOT installed as a package (PYTHONPATH required)

This design allows agents in `exports/` to be:

- Developed independently
- Version controlled separately
- Deployed as standalone packages

## Development Workflow

### 1. Setup (Once)

```bash
./scripts/setup-python.sh
```

### 2. Build Agent (Claude Code)

```
claude> /building-agents-construction
Enter goal: "Build an agent that processes customer support tickets"
```

### 3. Validate Agent

```bash
PYTHONPATH=core:exports python -m support_ticket_agent validate
```

### 4. Test Agent

```
claude> /testing-agent
```

### 5. Run Agent

```bash
PYTHONPATH=core:exports python -m support_ticket_agent run --input '{...}'
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

## Additional Resources

- **Framework Documentation:** [core/README.md](core/README.md)
- **Tools Documentation:** [tools/README.md](tools/README.md)
- **Example Agents:** [exports/](exports/)
- **Agent Building Guide:** [.claude/skills/building-agents-construction/SKILL.md](.claude/skills/building-agents-construction/SKILL.md)
- **Testing Guide:** [.claude/skills/testing-agent/SKILL.md](.claude/skills/testing-agent/SKILL.md)

## Contributing

When contributing agent packages:

1. Place agents in `exports/agent_name/`
2. Follow the standard agent structure (see existing agents)
3. Include README.md with usage instructions
4. Add tests if using `/testing-agent`
5. Document required environment variables

## Support

- **Issues:** https://github.com/adenhq/hive/issues
- **Discord:** https://discord.com/invite/MXE49hrKDk
- **Documentation:** https://docs.adenhq.com/