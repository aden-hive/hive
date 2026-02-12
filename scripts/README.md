# Windows Setup Script - Quick Start Guide

This document provides step-by-step instructions for using the `install-windows.ps1` script to install Aden Hive on Windows.

**Note:** Three scripts work together in sequence:
1. `preflight-windows.ps1` - Validates your environment (recommended before installation)
2. `install-windows.ps1` - Complete installation (recommended approach)
3. `doctor-windows.ps1` - Diagnostics and troubleshooting (if issues arise)

## Quick Start (TL;DR)

```powershell
# 1. Clone the repo
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Allow script execution
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. Run setup
.\scripts\install-windows.ps1

# 4. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 5. Run tests
pytest core\tests\
```

---

## What the Script Does

The `install-windows.ps1` script automates the entire setup process:

### ✅ Step 1: Python Detection
- Searches for Python 3.11+ on your system
- Checks multiple Python executables (python3.13, python3.12, python3.11, python3, python)
- Validates Python version compatibility
- **Fails if:** Python < 3.11 or Python not found

### ✅ Step 2: Virtual Environment
- Creates `.venv` directory in the project root
- Isolates dependencies from system Python
- **Skips if:** `.venv` already exists

### ✅ Step 3: Build Tools
- Upgrades pip, setuptools, and wheel
- Ensures latest package management tools
- **Required for:** Installing packages in editable mode

### ✅ Step 4: Core Package Installation
- Installs `core/` in editable mode (`pip install -e ./core`)
- Makes the `framework` module available
- **Installs:** `framework` package with all dependencies

### ✅ Step 5: Tools Package Installation
- Installs `tools/` in editable mode (`pip install -e ./tools`)
- Makes the `aden_tools` module available
- **Installs:** MCP tools and integrations

### ✅ Step 6: Playwright Browser (Optional)
- Installs Chromium browser for web automation
- **Only if:** Playwright package was installed successfully
- **Skips if:** Playwright not found (non-critical)

### ✅ Step 7: Verification
- Tests imports: `framework`, `aden_tools`, `litellm`, `framework.mcp`
- Reports success/failure for each module
- **Fails if:** Any critical import fails

---

## Prerequisites

Before running the script, ensure you have:

### 1. Python 3.11 or Higher

**Download:** [python.org/downloads](https://www.python.org/downloads/)

**During installation:**
- ✅ Check "Add Python to PATH"
- ✅ Check "Install pip"

**Verify:**
```powershell
python --version
# Should show: Python 3.11.x or higher
```

**Troubleshooting:**
- If `python --version` opens Microsoft Store, see [Disable App Execution Aliases](#disable-app-execution-aliases)
- If `python` command not found, restart PowerShell after Python installation

### 2. PowerShell 5.1+

**Check version:**
```powershell
$PSVersionTable.PSVersion
# Should show: 5.1 or higher
```

PowerShell 5.1 is pre-installed on Windows 10/11.

### 3. Git (Optional but Recommended)

**Download:** [git-scm.com](https://git-scm.com/download/win)

**Verify:**
```powershell
git --version
```

---

## Step-by-Step Instructions

### Step 1: Clone the Repository

```powershell
# Clone the repo
git clone https://github.com/adenhq/hive.git

# Navigate to the directory
cd hive
```

Or download ZIP from GitHub and extract.

### Step 2: Allow Script Execution

By default, Windows blocks PowerShell scripts. Enable them:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**What this does:**
- Allows locally-created scripts to run
- Still requires downloaded scripts to be signed
- Only affects current user (no admin required)

**Verify:**
```powershell
Get-ExecutionPolicy -Scope CurrentUser
# Should show: RemoteSigned
```

### Step 3: Run the Setup Script

```powershell
.\scripts\setup-windows.ps1
```

**Expected output:**
```
⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢

          A D E N   H I V E

⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢

     Goal-driven AI agent framework
             Windows Setup

⬢ Step 1: Checking Python...

  ✓ Python 3.11.5 detected (python)

⬢ Step 2: Setting up virtual environment...

  Creating virtual environment...   ✓ created
  ✓ Using virtual environment: C:\...\hive\.venv

⬢ Step 3: Upgrading pip and installing build tools...

  Upgrading pip...   ✓ done

⬢ Step 4: Installing core package...

  Installing framework (editable mode)...   ✓ done

⬢ Step 5: Installing tools package...

  Installing tools (editable mode)...   ✓ done

⬢ Step 6: Installing Playwright browser...

  Checking Playwright installation...   ✓ found
  Installing Chromium browser...   ✓ done

⬢ Step 7: Verifying installation...

  Testing framework import...   ✓ OK
  Testing aden_tools import...   ✓ OK
  Testing litellm import...   ✓ OK
  Testing MCP server module...   ✓ OK

⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢

   ✓ Setup Complete!

⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢⬡⬢
```

**Duration:** 2-5 minutes depending on internet speed.

### Step 4: Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

**Expected output:**
```
(.venv) PS C:\...\hive>
```

The `(.venv)` prefix indicates the virtual environment is active.

### Step 5: Verify Installation

```powershell
# Test imports
python -c "import framework; print('✓ Framework OK')"
python -c "import aden_tools; print('✓ Tools OK')"

# List installed packages
pip list
```

---

## Common Issues and Solutions

### Issue 1: Python Not Found

**Error:**
```
✗ Python 3.11+ is required but not found
```

**Solutions:**

1. **Install Python 3.11+**
   - Download from [python.org](https://www.python.org/downloads/)
   - Check "Add Python to PATH" during installation

2. **Disable App Execution Aliases**
   - Open Windows Settings
   - Go to Apps → App Execution Aliases
   - Disable `python.exe` and `python3.exe`
   - Restart PowerShell

3. **Use `py` launcher**
   ```powershell
   py --version
   # Edit the script to use 'py' instead of 'python'
   ```

### Issue 2: Script Execution Policy Error

**Error:**
```
File setup-windows.ps1 cannot be loaded because running scripts is disabled
```

**Solution:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue 3: Virtual Environment Creation Fails

**Error:**
```
✗ Failed to create virtual environment
```

**Solutions:**

1. **Clear existing `.venv`**
   ```powershell
   Remove-Item -Recurse -Force .venv
   .\scripts\setup-windows.ps1
   ```

2. **Use full Python path**
   ```powershell
   C:\Python311\python.exe -m venv .venv
   ```

### Issue 4: Package Installation Fails

**Error:**
```
✗ Failed to install core package
```

**Solutions:**

1. **Run verbose installation**
   ```powershell
   .\.venv\Scripts\pip.exe install -e .\core -v
   ```

2. **Check internet connection**
   - Ensure you can access PyPI (python.org)
   - Check firewall/proxy settings

3. **Manual installation**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   pip install --upgrade pip
   pip install -e .\core
   pip install -e .\tools
   ```

### Issue 5: Import Errors After Setup

**Error:**
```
ModuleNotFoundError: No module named 'framework'
```

**Solutions:**

1. **Activate virtual environment**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

2. **Reinstall packages**
   ```powershell
   pip install -e .\core
   pip install -e .\tools
   ```

3. **Check Python path**
   ```powershell
   python -c "import sys; print('\n'.join(sys.path))"
   ```

---

## After Setup: Next Steps

### 1. Configure LLM Provider

Set your API key as an environment variable:

```powershell
# For current session
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"

# Or permanently (User level)
[System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'sk-ant-...', 'User')
```

### 2. Run Tests

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run all tests
pytest core\tests\

# Run specific test
pytest core\tests\test_graph_executor.py -v
```

### 3. Try Examples

```powershell
# Run a demo
python core\examples\manual_agent.py

# Or use MCP integration
python core\examples\mcp_integration_example.py
```

### 4. Build Your First Agent

Using Claude Code or Cursor:
```
claude> /hive
```

---

## Script Options and Customization

The `setup-windows.ps1` script currently has no command-line options but can be customized:

### Skip Playwright Installation

Edit the script and comment out Step 6:

```powershell
# ============================================================
# Step 6: Install Playwright Browser
# ============================================================

# Write-Header "Step 6: Installing Playwright browser..."
# ... (comment out all Playwright installation code)
```

### Use Different Python Version

Edit the script and modify the `$PythonCandidates` array:

```powershell
$PythonCandidates = @("python3.12", "python3.11", "python3", "python")
```

### Change Virtual Environment Location

Edit the script and modify `$VenvPath`:

```powershell
$VenvPath = Join-Path $ScriptDir "my_custom_venv"
```

---

## Comparison: install-windows.ps1 vs Manual Setup

| Task | Manual Steps | Using Script |
|------|--------------|--------------|
| Check Python | `python --version` | ✅ Automatic |
| Create venv | `python -m venv .venv` | ✅ Automatic |
| Upgrade pip | `pip install --upgrade pip` | ✅ Automatic |
| Install core | `pip install -e .\core` | ✅ Automatic |
| Install tools | `pip install -e .\tools` | ✅ Automatic |
| Install Playwright | `playwright install chromium` | ✅ Automatic |
| Verify imports | Manual testing | ✅ Automatic |
| **Total time** | ~15 minutes | ~3 minutes |

---

## Troubleshooting Resources

- **Windows Setup Guide:** [docs/WINDOWS_SETUP.md](../WINDOWS_SETUP.md)
- **General Setup Guide:** [docs/environment-setup.md](environment-setup.md)
- **Developer Guide:** [docs/developer-guide.md](developer-guide.md)
- **GitHub Issues:** [github.com/adenhq/hive/issues](https://github.com/adenhq/hive/issues)

---

## Additional Notes

### Virtual Environment Location

The script creates `.venv` in the project root:
```
hive/
├── .venv/              ← Virtual environment
├── core/
├── tools/
└── scripts/
    ├── preflight-windows.ps1
    ├── install-windows.ps1
    └── doctor-windows.ps1
```

### Editable Mode Installation

Both packages are installed in "editable" mode (`-e` flag):
- Changes to source code take effect immediately
- No need to reinstall after editing
- Ideal for development

### What Gets Installed

**Core package** (`core/`):
- `framework` - Main agent runtime
- `pydantic`, `anthropic`, `litellm` - Core dependencies
- `textual` - TUI dashboard
- `pytest` - Testing framework

**Tools package** (`tools/`):
- `aden_tools` - MCP tools library
- `playwright` - Web automation
- `beautifulsoup4`, `pypdf` - Data extraction
- `fastmcp` - MCP server framework

---

## Getting Help

If you encounter issues not covered in this guide:

1. Check [docs/WINDOWS_SETUP.md](../WINDOWS_SETUP.md) for detailed Windows troubleshooting
2. Search [GitHub Issues](https://github.com/adenhq/hive/issues)
3. Ask in [Discord](https://discord.com/invite/MXE49hrKDk)
4. Create a new issue with:
   - Script output (copy full error message)
   - Python version (`python --version`)
   - PowerShell version (`$PSVersionTable.PSVersion`)
   - Windows version (`winver`)
