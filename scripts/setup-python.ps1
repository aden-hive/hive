#
# setup-python.ps1 - Python Environment Setup for Aden Agent Framework
#
# This script sets up the Python environment with all required packages
# for building and running goal-driven agents.
#

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$SCRIPT_DIR = $PSScriptRoot
$PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Aden Agent Framework - Python Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check for Python
$pythonCmd = $null
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} else {
    Write-Host "Error: Python is not installed." -ForegroundColor Red
    Write-Host "Please install Python 3.11+ from https://python.org"
    exit 1
}

# Check Python version
$pythonVersionOutput = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pythonMajor = & $pythonCmd -c "import sys; print(sys.version_info.major)"
$pythonMinor = & $pythonCmd -c "import sys; print(sys.version_info.minor)"

Write-Host "Detected Python: $pythonVersionOutput" -ForegroundColor Blue

if ([int]$pythonMajor -lt 3 -or ([int]$pythonMajor -eq 3 -and [int]$pythonMinor -lt 11)) {
    Write-Host "Error: Python 3.11+ is required (found $pythonVersionOutput)" -ForegroundColor Red
    Write-Host "Please upgrade your Python installation"
    exit 1
}

if ([int]$pythonMinor -lt 11) {
    Write-Host "Warning: Python 3.11+ is recommended for best compatibility" -ForegroundColor Yellow
    Write-Host "You have Python $pythonVersionOutput which may work but is not officially supported" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "✓ Python version check passed" -ForegroundColor Green
Write-Host ""

# Check for pip
$pipCheck = & $pythonCmd -m pip --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: pip is not installed" -ForegroundColor Red
    Write-Host "Please install pip for Python $pythonVersionOutput"
    exit 1
}

Write-Host "✓ pip detected" -ForegroundColor Green
Write-Host ""

# Upgrade pip, setuptools, and wheel
Write-Host "Upgrading pip, setuptools, and wheel..."
$upgradeResult = & $pythonCmd -m pip install --upgrade pip setuptools wheel 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Failed to upgrade pip. Please check your python/venv configuration." -ForegroundColor Red
    exit 1
}
Write-Host "✓ Core packages upgraded" -ForegroundColor Green
Write-Host ""

# Install core framework package
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Installing Core Framework Package" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Push-Location "$PROJECT_ROOT\core"

if (Test-Path "pyproject.toml") {
    Write-Host "Installing framework from core/ (editable mode)..."
    $installResult = & $pythonCmd -m pip install -e . 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Framework package installed" -ForegroundColor Green
    } else {
        Write-Host "⚠ Framework installation encountered issues (may be OK if already installed)" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠ No pyproject.toml found in core/, skipping framework installation" -ForegroundColor Yellow
}
Pop-Location
Write-Host ""

# Install tools package
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Installing Tools Package (aden_tools)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Push-Location "$PROJECT_ROOT\tools"

if (Test-Path "pyproject.toml") {
    Write-Host "Installing aden_tools from tools/ (editable mode)..."
    $installResult = & $pythonCmd -m pip install -e . 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Tools package installed" -ForegroundColor Green
    } else {
        Write-Host "✗ Tools installation failed" -ForegroundColor Red
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
Write-Host "Fixing Package Compatibility" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check openai version
$openaiVersion = & $pythonCmd -c "import openai; print(openai.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
    $openaiVersion = "not_installed"
}

if ($openaiVersion -eq "not_installed") {
    Write-Host "Installing openai package..."
    & $pythonCmd -m pip install "openai>=1.0.0" *>$null
    Write-Host "✓ openai package installed" -ForegroundColor Green
} elseif ($openaiVersion -match "^0\.") {
    Write-Host "Found old openai version: $openaiVersion" -ForegroundColor Yellow
    Write-Host "Upgrading to openai 1.x+ for litellm compatibility..."
    & $pythonCmd -m pip install --upgrade "openai>=1.0.0" *>$null
    $openaiVersion = & $pythonCmd -c "import openai; print(openai.__version__)" 2>$null
    Write-Host "✓ openai upgraded to $openaiVersion" -ForegroundColor Green
} else {
    Write-Host "✓ openai $openaiVersion is compatible" -ForegroundColor Green
}
Write-Host ""

# Verify installations
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Verifying Installation" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $PROJECT_ROOT

# Test framework import
$frameworkTest = & $pythonCmd -c "import framework; print('framework OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ framework package imports successfully" -ForegroundColor Green
} else {
    Write-Host "✗ framework package import failed" -ForegroundColor Red
    Write-Host "  Note: This may be OK if you don't need the framework" -ForegroundColor Yellow
}

# Test aden_tools import
$toolsTest = & $pythonCmd -c "import aden_tools; print('aden_tools OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ aden_tools package imports successfully" -ForegroundColor Green
} else {
    Write-Host "✗ aden_tools package import failed" -ForegroundColor Red
    Pop-Location
    exit 1
}

# Test litellm + openai compatibility
$litellmTest = & $pythonCmd -c "import litellm; print('litellm OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ litellm package imports successfully" -ForegroundColor Green
} else {
    Write-Host "⚠ litellm import had issues (may be OK if not using LLM features)" -ForegroundColor Yellow
}

Pop-Location
Write-Host ""

# Print agent commands
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Python packages installed:"
Write-Host "  • framework (core agent runtime)"
Write-Host "  • aden_tools (tools and MCP servers)"
Write-Host "  • All dependencies and compatibility fixes applied"
Write-Host ""
Write-Host "To run agents, use:"
Write-Host ""
Write-Host "  # From project root:" -ForegroundColor Blue
Write-Host "  `$env:PYTHONPATH=`"core;exports`"; python -m agent_name validate"
Write-Host "  `$env:PYTHONPATH=`"core;exports`"; python -m agent_name info"
Write-Host "  `$env:PYTHONPATH=`"core;exports`"; python -m agent_name run --input '{...}'"
Write-Host ""
Write-Host "Available commands for your new agent:"
Write-Host "  `$env:PYTHONPATH=`"core;exports`"; python -m support_ticket_agent validate"
Write-Host "  `$env:PYTHONPATH=`"core;exports`"; python -m support_ticket_agent info"
Write-Host "  `$env:PYTHONPATH=`"core;exports`"; python -m support_ticket_agent run --input '{`"ticket_content`":`"...`",`"customer_id`":`"...`",`"ticket_id`":`"...`"}'"
Write-Host ""
Write-Host "To build new agents, use Claude Code skills:"
Write-Host "  • /building-agents - Build a new agent"
Write-Host "  • /testing-agent   - Test an existing agent"
Write-Host ""
Write-Host "Documentation: $PROJECT_ROOT\README.md"
Write-Host "Agent Examples: $PROJECT_ROOT\exports\"
Write-Host ""
