#
# setup-python.ps1 - Python Environment Setup for Aden Agent Framework (Windows)
#
# This script sets up the Python environment with all required packages
# for building and running goal-driven agents on Windows.
#
# Usage: .\scripts\setup-python.ps1
#

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Aden Agent Framework - Python Setup (Windows)"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check for Python
$PythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $PythonCmd = "python3"
} else {
    Write-Host "Error: Python is not installed." -ForegroundColor Red
    Write-Host "Please install Python 3.11+ from https://python.org"
    Write-Host ""
    Write-Host "TIP: Make sure to check 'Add Python to PATH' during installation."
    Write-Host "     Also disable 'App Execution Aliases' for Python in Windows Settings."
    exit 1
}

# Check Python version
$PythonVersion = & $PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$PythonMajor = & $PythonCmd -c "import sys; print(sys.version_info.major)"
$PythonMinor = & $PythonCmd -c "import sys; print(sys.version_info.minor)"

Write-Host "Detected Python: $PythonVersion" -ForegroundColor Blue

if ([int]$PythonMajor -lt 3 -or ([int]$PythonMajor -eq 3 -and [int]$PythonMinor -lt 11)) {
    Write-Host "Error: Python 3.11+ is required (found $PythonVersion)" -ForegroundColor Red
    Write-Host "Please upgrade your Python installation"
    exit 1
}

Write-Host "[OK] Python version check passed" -ForegroundColor Green
Write-Host ""

# Check for pip
try {
    $null = & $PythonCmd -m pip --version 2>&1
    Write-Host "[OK] pip detected" -ForegroundColor Green
} catch {
    Write-Host "Error: pip is not installed" -ForegroundColor Red
    Write-Host "Please install pip for Python $PythonVersion"
    exit 1
}
Write-Host ""

# Upgrade pip, setuptools, and wheel
Write-Host "Upgrading pip, setuptools, and wheel..."
try {
    & $PythonCmd -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null
    Write-Host "[OK] Core packages upgraded" -ForegroundColor Green
} catch {
    Write-Host "Error: Failed to upgrade pip. Please check your python/venv configuration." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Install core framework package
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Installing Core Framework Package"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

$CorePath = Join-Path $ProjectRoot "core"
Push-Location $CorePath

if (Test-Path "pyproject.toml") {
    Write-Host "Installing framework from core/ (editable mode)..."
    try {
        & $PythonCmd -m pip install -e . 2>&1 | Out-Null
        Write-Host "[OK] Framework package installed" -ForegroundColor Green
    } catch {
        Write-Host "[!] Framework installation encountered issues (may be OK if already installed)" -ForegroundColor Yellow
    }
} else {
    Write-Host "[!] No pyproject.toml found in core/, skipping framework installation" -ForegroundColor Yellow
}

Pop-Location
Write-Host ""

# Install tools package
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Installing Tools Package (aden_tools)"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

$ToolsPath = Join-Path $ProjectRoot "tools"
Push-Location $ToolsPath

if (Test-Path "pyproject.toml") {
    Write-Host "Installing aden_tools from tools/ (editable mode)..."
    try {
        & $PythonCmd -m pip install -e . 2>&1 | Out-Null
        Write-Host "[OK] Tools package installed" -ForegroundColor Green
    } catch {
        Write-Host "[X] Tools installation failed" -ForegroundColor Red
        Pop-Location
        exit 1
    }
} else {
    Write-Host "Error: No pyproject.toml found in tools/" -ForegroundColor Red
    Pop-Location
    exit 1
}

Pop-Location
Write-Host ""

# Fix openai version compatibility with litellm
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Fixing Package Compatibility"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

try {
    $OpenAIVersion = & $PythonCmd -c "import openai; print(openai.__version__)" 2>&1
    if ($OpenAIVersion -match "^0\.") {
        Write-Host "Found old openai version: $OpenAIVersion" -ForegroundColor Yellow
        Write-Host "Upgrading to openai 1.x+ for litellm compatibility..."
        & $PythonCmd -m pip install --upgrade "openai>=1.0.0" 2>&1 | Out-Null
        $OpenAIVersion = & $PythonCmd -c "import openai; print(openai.__version__)" 2>&1
        Write-Host "[OK] openai upgraded to $OpenAIVersion" -ForegroundColor Green
    } else {
        Write-Host "[OK] openai $OpenAIVersion is compatible" -ForegroundColor Green
    }
} catch {
    Write-Host "Installing openai package..."
    & $PythonCmd -m pip install "openai>=1.0.0" 2>&1 | Out-Null
    Write-Host "[OK] openai package installed" -ForegroundColor Green
}
Write-Host ""

# Verify installations
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Verifying Installation"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $ProjectRoot

# Test framework import
try {
    & $PythonCmd -c "import framework; print('framework OK')" 2>&1 | Out-Null
    Write-Host "[OK] framework package imports successfully" -ForegroundColor Green
} catch {
    Write-Host "[X] framework package import failed" -ForegroundColor Red
    Write-Host "    Note: This may be OK if you don't need the framework" -ForegroundColor Yellow
}

# Test aden_tools import
try {
    & $PythonCmd -c "import aden_tools; print('aden_tools OK')" 2>&1 | Out-Null
    Write-Host "[OK] aden_tools package imports successfully" -ForegroundColor Green
} catch {
    Write-Host "[X] aden_tools package import failed" -ForegroundColor Red
    Pop-Location
    exit 1
}

# Test litellm + openai compatibility
try {
    & $PythonCmd -c "import litellm; print('litellm OK')" 2>&1 | Out-Null
    Write-Host "[OK] litellm package imports successfully" -ForegroundColor Green
} catch {
    Write-Host "[!] litellm import had issues (may be OK if not using LLM features)" -ForegroundColor Yellow
}

Pop-Location
Write-Host ""

# Print agent commands
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!"
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Python packages installed:"
Write-Host "  * framework (core agent runtime)"
Write-Host "  * aden_tools (tools and MCP servers)"
Write-Host "  * All dependencies and compatibility fixes applied"
Write-Host ""
Write-Host "To run agents, use:" -ForegroundColor Blue
Write-Host ""
Write-Host "  # From project root (PowerShell):"
Write-Host '  $env:PYTHONPATH="core;exports"; python -m agent_name validate'
Write-Host '  $env:PYTHONPATH="core;exports"; python -m agent_name info'
Write-Host '  $env:PYTHONPATH="core;exports"; python -m agent_name run --input ''{"..."}'''
Write-Host ""
Write-Host "Example with support_ticket_agent:"
Write-Host '  $env:PYTHONPATH="core;exports"; python -m support_ticket_agent validate'
Write-Host '  $env:PYTHONPATH="core;exports"; python -m support_ticket_agent info'
Write-Host ""
Write-Host "To build new agents, use Claude Code skills:"
Write-Host "  * /building-agents - Build a new agent"
Write-Host "  * /testing-agent   - Test an existing agent"
Write-Host ""
Write-Host "Documentation: $ProjectRoot\README.md"
Write-Host "Agent Examples: $ProjectRoot\exports\"
Write-Host ""
