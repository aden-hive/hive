# Windows Setup Guide

Setup Aden Hive on native Windows without WSL. This guide documents the setup used for local development and CI testing.

## Quick Start (Recommended - 3 minutes)

```powershell
# 1. Navigate to Hive directory
cd path\to\hive

# 2. Run unified installation script
.\scripts\install-windows.ps1

# 3. Set API key
$env:OPENAI_API_KEY = "your-key-here"

# 4. Test it
python core\examples\manual_agent.py
```

**Done!** Full installation with verification.

---

## Production Setup

### Step 1: Preflight Validation

Before installation, validate your system:

```powershell
.\scripts\preflight-windows.ps1
```

This checks:
- Python 3.11+ installed and in PATH
- Not Microsoft Store Python
- PowerShell 5.1+
- Execution policy set correctly
- Disk space (2GB+)
- Project structure exists

Resolve any issues shown before proceeding to installation.

### Step 2: Run Unified Installation

```powershell
# Full installation with all steps
.\scripts\install-windows.ps1

# Or skip test suite (faster):
.\scripts\install-windows.ps1 -SkipTests

# Or skip preflight check (if you know environment is OK):
.\scripts\install-windows.ps1 -SkipPreflight
```

The script will:
1. Detect Python 3.11+
2. Create virtual environment
3. Activate venv
4. Install core and tools packages
5. Verify imports
6. Load .env file if present
7. Run optional tests

### Step 3: Configure LLM API Keys

**Option A: Session Environment Variable (Quick)**

```powershell
$env:OPENAI_API_KEY = "sk-proj-your-key-here"
```

**Option B: Persistent User Environment (Recommended)**

```powershell
# Set permanently in Windows user environment
[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'your-key', 'User')
```

Restart PowerShell and verify:
```powershell
echo $env:OPENAI_API_KEY  # Should show your key
```

**Option C: .env File (Best for Development)**

Create `.env` in project root:
```powershell
# From project root
@"
OPENAI_API_KEY=sk-proj-your-key
ANTHROPIC_API_KEY=sk-ant-your-key
"@ | Out-File .env -Encoding UTF8
```

The install script automatically loads this file.

### Step 4: Verify Installation

```powershell
.\scripts\doctor-windows.ps1
```

This checks:
- Python environment and venv status
- Package imports
- API key configuration
- Git configuration
- LLM connectivity
- Issues found and repair suggestions

Run with `-Repair` flag to attempt automatic fixes:
```powershell
.\scripts\doctor-windows.ps1 -Repair
```

---

## Prerequisites

- Python 3.11+ ([download](https://www.python.org/downloads/)) — check "Add to PATH"
- PowerShell 5.1+ (included in Windows 10/11)
- Git for Windows ([optional](https://git-scm.com/download/win))

## Troubleshooting & Diagnostics

### Quick Diagnostics

Run the doctor script for a full system check:

```powershell
.\scripts\doctor-windows.ps1
```

Shows:
- Python environment and venv status
- Installed packages
- API key configuration
- Git setup
- Import and functionality tests

Attempt automatic repairs for issues found:

```powershell
.\scripts\doctor-windows.ps1 -Repair
```

### Common Windows Issues

| Issue | Solution |
|-------|----------|
| "Cannot be loaded because running scripts is disabled" | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Preflight check fails | Fix issues shown by preflight script and re-run |
| Python not found | Install Python 3.11+ from https://www.python.org/downloads/ (check "Add to PATH") |
| Microsoft Store Python detected | Disable App Execution Aliases: Settings → Apps → App Execution Aliases → disable python.exe |
| "ModuleNotFoundError: No module named 'framework'" | Run: `pip install -e .\core` |
| Venv won't activate | Recreate: `python -m venv .venv --clear` |
| API key not recognized | Verify with: `echo $env:OPENAI_API_KEY` |
| Slow installation | Normal first time (~5-10 min). Install is cached after. |
| Permission denied errors | Run PowerShell as Administrator, or use: `pip install --user -e .\core` |

### Getting Help

If `doctor-windows.ps1` shows issues:

```powershell
# Get detailed verbose output
.\scripts\doctor-windows.ps1 -Verbose

# Check specific issue with fix attempt
.\scripts\doctor-windows.ps1 -Repair -Verbose
```

## Run Your First Agent

```powershell
# Activate venv (if not already activated)
.\.venv\Scripts\Activate.ps1

# Run example agent
python core\examples\manual_agent.py

# Expected output:
# Path taken: greeter → uppercaser
# Final output: HELLO, ALICE!
```

## Run Tests

```powershell
# All tests
pytest core\tests\

# Specific test
pytest core\tests\test_graph_executor.py -v

# With coverage
pytest core\tests\ --cov=framework
```

## MCP Tools Example

```powershell
python core\examples\mcp_integration_example.py

# You should see:
# Registered 102 tools from tools MCP server
# Available tools: web_search, web_scrape, github_*, slack_*, ...
```

## Agent Handoff Demo

```powershell
# OpenAI version (requires OPENAI_API_KEY set)
python core\demos\handoff_demo.py

# Enter a research topic when prompted (e.g., "Claude AI")
# Agent will research and analyze the topic
```

## Useful Commands

```powershell
# Check everything is installed
python -c "import framework, aden_tools; print('✓ Ready')"

# List installed packages
pip list

# Deactivate virtual environment
deactivate

# Reinstall core package
pip install -e .\core

# Reinstall tools package
pip install -e .\tools
```

## Next Steps

1. **Create an agent** - Use `/hive` command in Claude Code or Cursor
2. **Learn concepts** - Read [docs/key_concepts/](../key_concepts/)
3. **Explore examples** - Check `core/examples/` and `core/demos/`
4. **Build tools** - Add MCP tools for custom integrations
5. **Deploy** - See [docs/](../)
