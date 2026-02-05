<#

setup-python.ps1 - Python Environment Setup for Aden Agent Framework

This script sets up the Python environment with all required packages
for building and running goal-driven agents.
#>

$ErrorActionPreference = "Stop"

# Colors for output
$RED    = "Red"
$GREEN  = "Green"
$YELLOW = "Yellow"
$BLUE   = "Cyan"

# Get the directory where this script is located
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR

Write-Host ""
Write-Host "=================================================="
Write-Host "  Aden Agent Framework - Python Setup"
Write-Host "=================================================="
Write-Host ""

# Check for Python
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
}

if (-not $pythonCmd) {
    Write-Host "Error: Python is not installed." -ForegroundColor $RED
    Write-Host "Please install Python 3.11+ from https://python.org"
    exit 1
}

# Check Python version
$versionInfo = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$major = & $pythonCmd -c "import sys; print(sys.version_info.major)"
$minor = & $pythonCmd -c "import sys; print(sys.version_info.minor)"

Write-Host "Detected Python: $versionInfo" -ForegroundColor $BLUE

if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    Write-Host "Error: Python 3.11+ is required (found $versionInfo)" -ForegroundColor $RED
    Write-Host "Please upgrade your Python installation"
    exit 1
}

if ($minor -lt 11) {
    Write-Host "Warning: Python 3.11+ is recommended for best compatibility" -ForegroundColor $YELLOW
    Write-Host "You have Python $versionInfo which may work but is not officially supported" -ForegroundColor $YELLOW
    Write-Host ""
}

Write-Host "[OK] Python version check passed" -ForegroundColor $GREEN
Write-Host ""

# Create and activate virtual environment
Write-Host "=================================================="
Write-Host "Setting up Python Virtual Environment"
Write-Host "=================================================="
Write-Host ""

$VENV_PATH = Join-Path $PROJECT_ROOT ".venv"
$VENV_PYTHON = Join-Path $VENV_PATH "Scripts\python.exe"
$VENV_ACTIVATE = Join-Path $VENV_PATH "Scripts\Activate.ps1"

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Host "Creating virtual environment at .venv..."
    & $pythonCmd -m venv $VENV_PATH
    Write-Host "[OK] Virtual environment created" -ForegroundColor $GREEN
}
else {
    Write-Host "[OK] Virtual environment already exists" -ForegroundColor $GREEN
}

# Activate venv
Write-Host "Activating virtual environment..."
& $VENV_ACTIVATE
Write-Host "[OK] Virtual environment activated" -ForegroundColor $GREEN

# From here on, always use venv python
$pythonCmd = $VENV_PYTHON

Write-Host ""

# Check for pip
try {
    & $pythonCmd -m pip --version | Out-Null
}
catch {
    Write-Host "Error: pip is not installed" -ForegroundColor $RED
    Write-Host "Please install pip for Python $versionInfo"
    exit 1
}

Write-Host "[OK] pip detected" -ForegroundColor $GREEN
Write-Host ""

# Upgrade pip, setuptools, and wheel
Write-Host "Upgrading pip, setuptools, and wheel..."
& $pythonCmd -m pip install --upgrade pip setuptools wheel 
Write-Host "[OK] Core packages upgraded" -ForegroundColor $GREEN
Write-Host ""

# Install core framework package
Write-Host "=================================================="
Write-Host "Installing Core Framework Package"
Write-Host "=================================================="
Write-Host ""

Set-Location "$PROJECT_ROOT\core"

if (Test-Path "pyproject.toml") {
    Write-Host "Installing framework from core/ (editable mode)..."
    & $pythonCmd -m pip install -e . | Out-Null
    Write-Host "[OK] Framework package installed" -ForegroundColor $GREEN
}
else {
    Write-Host "[WARN] No pyproject.toml found in core/, skipping framework installation" -ForegroundColor $YELLOW
}

Write-Host ""

# Install tools package
Write-Host "=================================================="
Write-Host "Installing Tools Package (aden_tools)"
Write-Host "=================================================="
Write-Host ""

Set-Location "$PROJECT_ROOT\tools"

if (Test-Path "pyproject.toml") {
    Write-Host "Installing aden_tools from tools/ (editable mode)..."
    & $pythonCmd -m pip install -e . | Out-Null
    Write-Host "[OK] Tools package installed" -ForegroundColor $GREEN
}
else {
    Write-Host "Error: No pyproject.toml found in tools/" -ForegroundColor $RED
    exit 1
}

Write-Host ""

# Fix openai version compatibility with litellm
Write-Host "=================================================="
Write-Host "Fixing Package Compatibility"
Write-Host "=================================================="
Write-Host ""

try {
    $openaiVersion = & $pythonCmd -c "import openai; print(openai.__version__)"
}
catch {
    $openaiVersion = "not_installed"
}

if ($openaiVersion -eq "not_installed") {
    Write-Host "Installing openai package..."
    & $pythonCmd -m pip install "openai>=1.0.0" | Out-Null
    Write-Host "[OK] openai package installed" -ForegroundColor $GREEN
}
elseif ($openaiVersion.StartsWith("0.")) {
    Write-Host "Found old openai version: $openaiVersion" -ForegroundColor $YELLOW
    Write-Host "Upgrading to openai 1.x+ for litellm compatibility..."
    & $pythonCmd -m pip install --upgrade "openai>=1.0.0" | Out-Null
    $openaiVersion = & $pythonCmd -c "import openai; print(openai.__version__)"
    Write-Host "[OK] openai upgraded to $openaiVersion" -ForegroundColor $GREEN
}
else {
    Write-Host "[OK] openai $openaiVersion is compatible" -ForegroundColor $GREEN
}

Write-Host ""

# Verify installations
Write-Host "=================================================="
Write-Host "Verifying Installation"
Write-Host "=================================================="
Write-Host ""

Set-Location $PROJECT_ROOT

# Test framework import
& $pythonCmd -c "import framework" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] framework package imports successfully" -ForegroundColor Green
}
else {
    Write-Host "[FAIL] framework package import failed" -ForegroundColor Red
}

# Test aden_tools import
& $pythonCmd -c "import aden_tools" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] aden_tools package imports successfully" -ForegroundColor Green
}
else {
    Write-Host "[FAIL] aden_tools package import failed" -ForegroundColor Red
    exit 1
}

# Test litellm
& $pythonCmd -c "import litellm" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] litellm package imports successfully" -ForegroundColor $GREEN
}
else {
    Write-Host "[WARN] litellm import had issues (may be OK if not using LLM features)" -ForegroundColor $YELLOW
}

Write-Host ""

# Print agent commands
Write-Host "=================================================="
Write-Host "  Setup Complete!"
Write-Host "=================================================="
Write-Host ""
Write-Host "Python packages installed:"
Write-Host "  - framework (core agent runtime)"
Write-Host "  - aden_tools (tools and MCP servers)"
Write-Host "  - All dependencies and compatibility fixes applied"
Write-Host ""
Write-Host "To run agents on Windows (PowerShell):"
Write-Host ""
Write-Host "1. From the project root, set PYTHONPATH:"
Write-Host "   `$env:PYTHONPATH=`"exports`""
Write-Host ""
Write-Host "2. Run an agent command:"
Write-Host "   uv run python -m agent_name validate"
Write-Host "   uv run python -m agent_name info"
Write-Host "   uv run python -m agent_name run --input '{...}'"
Write-Host ""
Write-Host "Example (support_ticket_agent):"
Write-Host "   uv run python -m support_ticket_agent validate"
Write-Host "   uv run python -m support_ticket_agent info"
Write-Host "   uv run python -m support_ticket_agent run --input '{""ticket_content"":""..."",""customer_id"":""..."",""ticket_id"":""...""}'"
Write-Host ""
Write-Host "Notes:"
Write-Host "  - Ensure the virtual environment is activated (.venv)"
Write-Host "  - PYTHONPATH must be set in each new PowerShell session"
Write-Host ""
Write-Host "Documentation:"
Write-Host "  $PROJECT_ROOT\README.md"
Write-Host ""
Write-Host "Agent Examples:"
Write-Host "  $PROJECT_ROOT\exports\"
Write-Host ""
