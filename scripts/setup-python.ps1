# setup-python.ps1 - Python Environment Setup for Windows
# Mirrors the logic of setup-python.sh for the Aden Agent Framework

$ErrorActionPreference = "Stop"

# Colors for output
$Green = "Green"; $Red = "Red"; $Yellow = "Yellow"; $Blue = "Cyan"

Write-Host "`n==================================================" -ForegroundColor $Blue
Write-Host "   Aden Agent Framework - Windows Python Setup" -ForegroundColor $Blue
Write-Host "==================================================`n" -ForegroundColor $Blue

# 1. Check for Python
$pythonCmd = "python"
try {
    $versionStr = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $major = & $pythonCmd -c "import sys; print(sys.version_info.major)"
    $minor = & $pythonCmd -c "import sys; print(sys.version_info.minor)"
} catch {
    Write-Host "Error: Python is not installed or not in your PATH." -ForegroundColor $Red
    Write-Host "Please install Python 3.11+ from https://python.org"
    exit 1
}

Write-Host "Detected Python: $versionStr" -ForegroundColor $Blue

# 2. Version Check (3.11+)
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 11)) {
    Write-Host "Error: Python 3.11+ is required (found $versionStr)" -ForegroundColor $Red
    exit 1
}
Write-Host "Python version check passed" -ForegroundColor $Green

# 3. Upgrade Core Packages
Write-Host "`nUpgrading pip, setuptools, and wheel..."
& $pythonCmd -m pip install --upgrade pip setuptools wheel
Write-Host "Core packages upgraded" -ForegroundColor $Green

# 4. Define Paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# 5. Install Core Framework (Editable mode)
Write-Host "`n=================================================="
Write-Host "Installing Core Framework Package"
Write-Host "=================================================="
Set-Location "$ProjectRoot\core"

if (Test-Path "pyproject.toml") {
    Write-Host "Installing framework from core/ (editable mode)..."
    & $pythonCmd -m pip install -e .
    Write-Host "Framework package installed" -ForegroundColor $Green
} else {
    Write-Host "No pyproject.toml found in core/, skipping" -ForegroundColor $Yellow
}

# 6. Install Tools Package
Write-Host "`n=================================================="
Write-Host "Installing Tools Package (aden_tools)"
Write-Host "=================================================="
Set-Location "$ProjectRoot\tools"

if (Test-Path "pyproject.toml") {
    Write-Host "Installing aden_tools from tools/ (editable mode)..."
    & $pythonCmd -m pip install -e .
    Write-Host "Tools package installed" -ForegroundColor $Green
} else {
    Write-Host "Error: No pyproject.toml found in tools/" -ForegroundColor $Red
    exit 1
}

# 7. OpenAI/LiteLLM Compatibility Fix
Write-Host "`n=================================================="
Write-Host "Fixing Package Compatibility"
Write-Host "=================================================="
try {
    $openaiVer = & $pythonCmd -c "import openai; print(openai.__version__)"
    if ($openaiVer -like "0.*") {
        Write-Host "Found old openai version: $openaiVer. Upgrading..." -ForegroundColor $Yellow
        & $pythonCmd -m pip install --upgrade "openai>=1.0.0"
    } else {
        Write-Host "openai $openaiVer is compatible" -ForegroundColor $Green
    }
} catch {
    Write-Host "Installing openai package..."
    & $pythonCmd -m pip install "openai>=1.0.0"
}

# 8. Final Verification
Write-Host "`n=================================================="
Write-Host "Verifying Installation"
Write-Host "=================================================="
Set-Location $ProjectRoot

$verifyScript = @"
import framework
import aden_tools
import litellm
print('All Imports Successful')
"@

try {
    & $pythonCmd -c $verifyScript
    Write-Host "Verification successful!" -ForegroundColor $Green
} catch {
    Write-Host "erification failed. Check your environment." -ForegroundColor $Red
}

Write-Host "`nSetup Complete!" -ForegroundColor $Green
Write-Host "`nTo run agents on Windows, use these commands:" -ForegroundColor Yellow
Write-Host "  # Validate agent configuration" -ForegroundColor Gray
Write-Host "  (`$env:PYTHONPATH='core;exports'; python -m agent_name validate)" -ForegroundColor Cyan
Write-Host "  # View agent information" -ForegroundColor Gray
Write-Host "  (`$env:PYTHONPATH='core;exports'; python -m agent_name info)" -ForegroundColor Cyan
Write-Host "  # Execute an agent with input" -ForegroundColor Gray
Write-Host "  (`$env:PYTHONPATH='core;exports'; python -m agent_name run --input '{...}')" -ForegroundColor Cyan

Write-Host "`nTo build or test new agents:" -ForegroundColor Yellow
Write-Host " /building-agents - Build a new agent (Claude Code)"
Write-Host " /testing-agent   - Test an existing agent (Claude Code)"

Write-Host "`nDocumentation: $ProjectRoot\README.md"
Write-Host "Agent Examples: $ProjectRoot\exports\`n"
