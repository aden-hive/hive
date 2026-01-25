# Windows Setup Guide

This guide provides detailed instructions for setting up and running the Aden Agent Framework on Windows using native PowerShell.

## Prerequisites

### Required Software

1. **Python 3.11 or later**
   - Download from [python.org](https://www.python.org/downloads/)
   - During installation, check "Add Python to PATH"
   - Verify installation: `python --version`

2. **Git for Windows**
   - Download from [git-scm.com](https://git-scm.com/download/win)
   - Use default installation options
   - Verify installation: `git --version`

3. **PowerShell 5.1 or later** (included with Windows 10/11)
   - Verify version: `$PSVersionTable.PSVersion`

### Optional Software

- **Docker Desktop** for containerized tools
- **Visual Studio Code** for code editing
- **Windows Terminal** for better terminal experience

## Quick Start

Open PowerShell and run:

```powershell
# Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# Run automated setup
.\scripts\setup-python.ps1

# Verify installation
python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

## Detailed Setup

### Step 1: Clone the Repository

```powershell
# Clone to your preferred location
git clone https://github.com/adenhq/hive.git
cd hive
```

### Step 2: Run Setup Script

The setup script will:

- Check Python version (requires 3.11+)
- Install core framework package
- Install aden_tools package
- Fix package compatibility
- Verify installations

```powershell
.\scripts\setup-python.ps1
```

### Step 3: Install Claude Code Skills (Optional)

If you plan to use Claude Code for agent building:

```powershell
.\quickstart.ps1
```

This installs:

- `/building-agents-core` - Fundamental concepts
- `/building-agents-construction` - Step-by-step build guide
- `/building-agents-patterns` - Best practices
- `/testing-agent` - Test and validate agents
- `/agent-workflow` - Complete workflow

Skills are installed to: `$env:USERPROFILE\.claude\skills\`

## Environment Variables

### Setting Environment Variables

**For Current PowerShell Session:**

```powershell
$env:ANTHROPIC_API_KEY="your-key-here"
$env:OPENAI_API_KEY="your-key-here"
$env:BRAVE_SEARCH_API_KEY="your-key-here"
```

**Permanently (User Level):**

```powershell
[System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'your-key-here', 'User')
[System.Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'your-key-here', 'User')
```

**Permanently (System Level - Requires Admin):**

```powershell
# Run PowerShell as Administrator
[System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'your-key-here', 'Machine')
```

### PYTHONPATH on Windows

Windows uses semicolons (`;`) to separate paths, not colons (`:`).

**Correct:**

```powershell
$env:PYTHONPATH="core;exports"
```

**Incorrect:**

```powershell
$env:PYTHONPATH="core:exports"  # This won't work on Windows!
```

## Running Agents

All agent commands must be run from the project root with `PYTHONPATH` set.

### Basic Commands

```powershell
# Navigate to project root
cd C:\path\to\hive

# Validate agent structure
$env:PYTHONPATH="core;exports"; python -m agent_name validate

# Show agent information
$env:PYTHONPATH="core;exports"; python -m agent_name info

# Run agent
$env:PYTHONPATH="core;exports"; python -m agent_name run --input '{...}'

# Run in mock mode (no LLM calls)
$env:PYTHONPATH="core;exports"; python -m agent_name run --mock --input '{...}'
```

### Example: Support Ticket Agent

```powershell
# Validate
$env:PYTHONPATH="core;exports"; python -m support_ticket_agent validate

# Show info
$env:PYTHONPATH="core;exports"; python -m support_ticket_agent info

# Run with input
$env:PYTHONPATH="core;exports"; python -m support_ticket_agent run --input '{
  "ticket_content": "My login is broken. Error 401.",
  "customer_id": "CUST-123",
  "ticket_id": "TKT-456"
}'

# Run in mock mode
$env:PYTHONPATH="core;exports"; python -m support_ticket_agent run --mock --input '{
  "ticket_content": "Test ticket",
  "customer_id": "CUST-123",
  "ticket_id": "TKT-456"
}'
```

### Convenience Function

To avoid typing `$env:PYTHONPATH="core;exports"` repeatedly, create a PowerShell function:

```powershell
# Add to your PowerShell profile ($PROFILE)
function Run-Agent {
    param([Parameter(ValueFromRemainingArguments=$true)]$args)
    $env:PYTHONPATH="core;exports"
    python -m @args
}

# Usage:
Run-Agent support_ticket_agent validate
Run-Agent support_ticket_agent run --input '{...}'
```

## Building New Agents

### Using Claude Code

```powershell
# Start Claude Code in project directory
cd C:\path\to\hive
claude

# In Claude Code:
claude> /building-agents-construction

# Follow the prompts to build your agent
```

### Testing Your Agent

```powershell
# Using Claude Code
claude> /testing-agent

# Or manually
$env:PYTHONPATH="core;exports"; python -m my_agent test

# Specific test types
$env:PYTHONPATH="core;exports"; python -m my_agent test --type constraint
$env:PYTHONPATH="core;exports"; python -m my_agent test --type success
```

## Troubleshooting

### Python Not Found

**Error:** `python : The term 'python' is not recognized...`

**Solution:**

1. Reinstall Python with "Add to PATH" checked
2. Or add Python manually to PATH:
   - Search "Environment Variables" in Windows
   - Edit "Path" variable
   - Add: `C:\Users\YourUser\AppData\Local\Programs\Python\Python311`
   - Add: `C:\Users\YourUser\AppData\Local\Programs\Python\Python311\Scripts`

### Module Not Found

**Error:** `ModuleNotFoundError: No module named 'framework'`

**Solution:**

```powershell
# Reinstall packages
cd C:\path\to\hive\core
pip install -e .

cd ..\tools
pip install -e .
```

### Permission Denied

**Error:** `cannot be loaded because running scripts is disabled`

**Solution:**

```powershell
# Check execution policy
Get-ExecutionPolicy

# Set to RemoteSigned (recommended) or Unrestricted
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Import Errors

**Error:** `ImportError: cannot import name 'X' from 'framework'`

**Solution:**

```powershell
# Ensure PYTHONPATH uses semicolons
$env:PYTHONPATH="core;exports"  # Correct

# Verify you're in the project root
pwd  # Should be C:\...\hive

# Reinstall packages
.\scripts\setup-python.ps1
```

### Package Compatibility Issues

**Error:** OpenAI/litellm version conflicts

**Solution:**

```powershell
# Upgrade OpenAI package
pip install --upgrade "openai>=1.0.0"

# Or re-run setup script
.\scripts\setup-python.ps1
```

### Long Path Issues

Windows has a 260-character path limit that can cause issues.

**Solution:**

1. Clone to a shorter path (e.g., `C:\hive` instead of `C:\Users\...\hive`)
2. Or enable long paths:
   ```powershell
   # Run as Administrator
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
   ```

### Claude Code Skills Not Found

**Error:** Skills not appearing in Claude Code

**Solution:**

```powershell
# Verify skills directory exists
Test-Path "$env:USERPROFILE\.claude\skills"

# Re-run quickstart
.\quickstart.ps1

# List installed skills
Get-ChildItem "$env:USERPROFILE\.claude\skills"
```

## PowerShell Profile Setup

Add these functions to your PowerShell profile for convenience:

```powershell
# Open profile
notepad $PROFILE

# Add these functions:
function hive {
    cd C:\path\to\hive
}

function Run-Agent {
    param([Parameter(ValueFromRemainingArguments=$true)]$args)
    $env:PYTHONPATH="core;exports"
    python -m @args
}

# Usage:
# hive                           # Navigate to project
# Run-Agent my_agent validate    # Run agent commands
```

## Differences from Unix/Linux

Key differences when working on Windows:

1. **Path separators:**
   - Unix: `/` and `:`
   - Windows: `\` and `;`

2. **Script extensions:**
   - Unix: `.sh`
   - Windows: `.ps1`

3. **Environment variables:**
   - Unix: `export VAR=value`
   - Windows: `$env:VAR="value"`

4. **Script execution:**
   - Unix: `./script.sh`
   - Windows: `.\script.ps1`

5. **Home directory:**
   - Unix: `~` or `$HOME`
   - Windows: `$env:USERPROFILE`

## Next Steps

1. **Build your first agent**: Follow the [getting-started guide](getting-started.md)
2. **Explore examples**: Check out `/exports` for working agents
3. **Read the docs**: See `/docs` for detailed documentation
4. **Join the community**: [Discord](https://discord.com/invite/MXE49hrKDk)

## Additional Resources

- **Main README**: [README.md](../README.md)
- **Environment Setup**: [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md)
- **Developer Guide**: [DEVELOPER.md](../DEVELOPER.md)
- **Architecture**: [docs/architecture.md](architecture.md)

## Getting Help

- **GitHub Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)
- **Documentation**: Check the `/docs` folder
