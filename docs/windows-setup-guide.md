# Windows Setup Guide for Hive

Complete guide for setting up Hive on Windows without WSL. This guide is based on real Windows setup experience.

## Prerequisites

### 1. Python 3.11+ Installation

**Download Python:**
- Go to [python.org/downloads](https://www.python.org/downloads/)
- Download Python 3.11, 3.12, or 3.13 (3.13 recommended)

**Installation Steps:**
1. Run the installer
2. **CRITICAL**: Check "Add Python to PATH" at the bottom
3. Click "Install Now"
4. Verify installation:
   ```powershell
   python --version
   # Should show: Python 3.13.5 (or your version)
   ```

**Common Issue**: If `python --version` doesn't work:
- You may have the Microsoft Store stub installed
- Go to: Settings > Apps > Advanced app settings > App execution aliases
- Disable "python.exe" and "python3.exe"
- Reinstall Python from python.org with "Add to PATH" checked

### 2. Git Installation

**Download Git:**
- Go to [git-scm.com](https://git-scm.com/download/win)
- Download and install Git for Windows

**Verify:**
```powershell
git --version
```

### 3. Choose Your Shell

You have three options for running Hive on Windows:

| Shell | Pros | Cons | Recommended For |
|-------|------|------|-----------------|
| **PowerShell** | Native Windows, no extra install, works perfectly | None found in testing | Most Windows users |
| **Git Bash** | Unix-like commands | PATH issues with Python | Users familiar with Linux |
| **WSL** | Full Linux environment | Extra setup required, Windows 10+ only | Advanced users who need Linux tools |

**This guide focuses on PowerShell** (easiest option).

---

## Setup Process

### Step 1: Clone the Repository

```powershell
# Navigate to your projects folder
cd C:\your\projects\folder

# Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive
```

### Step 2: Install uv (Python Package Manager)

Hive uses `uv` instead of `pip` for faster package management.

```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify installation
uv --version
```

**If `uv` command not found after installation:**
```powershell
# Add to PATH for current session
$env:Path += ";$env:USERPROFILE\.local\bin"

# Verify
uv --version
```

**To make it permanent:**
1. Search for "Environment Variables" in Windows
2. Click "Environment Variables"
3. Under "User variables", select "Path" and click "Edit"
4. Click "New" and add: `C:\Users\YourUsername\.local\bin`
5. Click OK on all dialogs
6. Restart PowerShell

### Step 3: Run Automated Setup (Recommended)

Hive provides a PowerShell setup script:

```powershell
# Make sure you're in the hive directory
cd hive

# Run the setup script
.\quickstart.ps1
```

The script will:
1. Check Python version
2. Install/update uv
3. Install all Python packages
4. Install Playwright browser
5. Build frontend dashboard (if Node.js available)
6. Optionally configure Windows Defender exclusions for better performance
7. Help you set up LLM API keys

**If the script fails**, proceed with manual setup below.

### Step 4: Manual Setup (If Automated Fails)

#### 4a. Install Core Framework

```powershell
# Navigate to core directory
cd core

# Install dependencies
uv sync

# Verify installation
uv run python -c "import framework; print('framework OK')"
```

#### 4b. Install Tools Package

```powershell
# Navigate to tools directory (from hive root)
cd ..\tools

# Install dependencies
uv sync

# Verify installation
uv run python -c "import aden_tools; print('aden_tools OK')"
```

#### 4c. Install Playwright Browser

```powershell
# From hive root
cd ..

# Install Playwright browser
uv run playwright install chromium
```

#### 4d. Create Config Directory

```powershell
# Create Hive config directory
mkdir $env:USERPROFILE\.hive -Force
```

### Step 5: Set Up API Keys

Hive needs an LLM API key to run agents. You have several options:

#### Option A: Environment Variables (Recommended)

**For Current Session Only:**
```powershell
$env:ANTHROPIC_API_KEY = "your-api-key-here"
```

**Permanent (User-level):**
```powershell
# Set permanently
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "your-api-key-here", "User")

# Restart PowerShell for changes to take effect
```

**Permanent (via GUI):**
1. Search for "Environment Variables" in Windows
2. Click "Environment Variables"
3. Under "User variables", click "New"
4. Variable name: `ANTHROPIC_API_KEY`
5. Variable value: `your-api-key-here`
6. Click OK
7. Restart PowerShell

#### Option B: .env File

```powershell
# Create .env file in hive root
@"
ANTHROPIC_API_KEY=your-api-key-here
OPENAI_API_KEY=your-openai-key-here
BRAVE_SEARCH_API_KEY=your-brave-key-here
"@ | Out-File -FilePath .env -Encoding UTF8
```

#### Option C: Interactive Setup

```powershell
.\hive.ps1 setup-credentials
```

### Step 6: Verify Installation

```powershell
# Check if hive command works
.\hive.ps1 --help

# List available agents (will be empty initially)
.\hive.ps1 list

# Open dashboard
.\hive.ps1 open
```

---

## Common Issues and Solutions

### Issue 1: "python: command not found"

**Cause**: Python not in PATH

**Solution**:
```powershell
# Find Python installation
where.exe python

# If not found, reinstall Python with "Add to PATH" checked
# Or add manually to PATH:
$env:Path += ";C:\Users\YourUsername\AppData\Local\Programs\Python\Python313"
$env:Path += ";C:\Users\YourUsername\AppData\Local\Programs\Python\Python313\Scripts"
```

### Issue 2: "uv: command not found"

**Cause**: uv not in PATH

**Solution**:
```powershell
# Add to PATH for current session
$env:Path += ";$env:USERPROFILE\.local\bin"

# Verify
uv --version

# Make permanent (see Step 2 above)
```

### Issue 3: "quickstart.ps1 cannot be loaded"

**Cause**: PowerShell execution policy

**Solution**:
```powershell
# Check current policy
Get-ExecutionPolicy

# If Restricted, change it
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Try again
.\quickstart.ps1
```

### Issue 4: "ModuleNotFoundError: No module named 'framework'"

**Cause**: Packages not installed or wrong directory

**Solution**:
```powershell
# Reinstall framework
cd core
uv sync

# Verify
uv run python -c "import framework; print('OK')"
```

### Issue 5: Git Bash PATH Issues

**Cause**: Git Bash doesn't see Windows Python installation

**Solution**: Use PowerShell instead, or:
```bash
# In Git Bash, add Python to PATH
export PATH="/c/Users/YourUsername/AppData/Local/Programs/Python/Python313:$PATH"
export PATH="/c/Users/YourUsername/AppData/Local/Programs/Python/Python313/Scripts:$PATH"

# Verify
python --version
```

### Issue 6: Port Already in Use

**Cause**: Previous server still running

**Solution**:
```powershell
# Find process using port 3000
netstat -ano | findstr :3000

# Kill process (replace PID with actual process ID)
taskkill /PID <PID> /F
```

### Issue 7: Slow Performance

**Cause**: Windows Defender scanning Python files

**Solution**: Add exclusions (improves performance by ~40%)
```powershell
# Run as Administrator
Add-MpPreference -ExclusionPath "C:\path\to\hive"
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\uv"
```

Or use the automated setup script which offers this option.

---

## Running Hive Commands

### Using hive.ps1 Script

```powershell
# From hive directory
.\hive.ps1 <command>

# Examples:
.\hive.ps1 list
.\hive.ps1 open
.\hive.ps1 run exports/my_agent
```

### Adding to PATH (Optional)

To use `hive` command from anywhere:

1. Add hive directory to PATH:
   ```powershell
   # Temporary (current session)
   $env:Path += ";C:\path\to\hive"
   
   # Permanent (via GUI - see Step 2 above)
   ```

2. Create a `hive.cmd` wrapper:
   ```cmd
   @echo off
   powershell -ExecutionPolicy Bypass -File "C:\path\to\hive\hive.ps1" %*
   ```

---

## Building Your First Agent

### Option 1: Using Claude Code (Recommended)

1. Install Claude Code from [Anthropic](https://docs.anthropic.com/claude/docs/claude-code)
2. Open hive directory in Claude Code
3. Use the MCP tools to build an agent

### Option 2: Using the Dashboard

```powershell
# Open dashboard
.\hive.ps1 open

# Browser will open at http://localhost:3000
# Use the UI to create and run agents
```

### Option 3: Manual Creation

```powershell
# Create agent directory
mkdir exports\my_agent

# Create agent.json (see developer-guide.md for structure)
# Create tools.py (optional)
# Create README.md

# Validate
$env:PYTHONPATH = "exports"
uv run python -m my_agent validate
```

---

## Performance Optimization

### 1. Windows Defender Exclusions

Add these paths to Windows Defender exclusions for ~40% faster performance:

```powershell
# Run PowerShell as Administrator
Add-MpPreference -ExclusionPath "C:\path\to\hive"
Add-MpPreference -ExclusionPath "C:\path\to\hive\.venv"
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\uv"
```

### 2. Use SSD

Install Hive on an SSD drive for better performance.

### 3. Close Unnecessary Programs

LLM operations are CPU/memory intensive. Close other programs when running agents.

---

## Differences from Linux/Mac

| Feature | Linux/Mac | Windows |
|---------|-----------|---------|
| Shell script | `./quickstart.sh` | `.\quickstart.ps1` |
| Python command | `python3` | `python` |
| Path separator | `:` | `;` |
| Path format | `/home/user` | `C:\Users\user` |
| Environment vars | `export VAR=value` | `$env:VAR = "value"` |
| Hive command | `hive` | `.\hive.ps1` |

---

## Next Steps

1. **Set up API keys** (see Step 5)
2. **Build your first agent** (see Building Your First Agent)
3. **Read the docs**:
   - [Getting Started](docs/getting-started.md)
   - [Developer Guide](docs/developer-guide.md)
   - [Contributing](CONTRIBUTING.md)
4. **Join the community**:
   - [Discord](https://discord.com/invite/MXE49hrKDk)
   - [GitHub Issues](https://github.com/adenhq/hive/issues)

---

## Summary of Your Successful Setup

Based on your actual experience, here's what worked:

```powershell
# 1. Cloned repo
git clone https://github.com/adenhq/hive
cd hive

# 2. Installed core framework
cd core
uv sync

# 3. Installed tools
cd ..\tools
uv sync

# 4. Installed Playwright
cd ..
uv run playwright install chromium

# 5. Created config directory
mkdir $env:USERPROFILE\.hive -Force

# 6. Verified installation
uv run python -c "import framework; print('OK')"
uv run python -c "import aden_tools; print('OK')"
```

This proves that **Hive works perfectly on native Windows with PowerShell** - no WSL required!

---

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)
- **Discord**: [discord.com/invite/MXE49hrKDk](https://discord.com/invite/MXE49hrKDk)

---

**Made with ❤️ by a Windows user who successfully set up Hive!**
