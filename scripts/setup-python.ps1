$ErrorActionPreference = "Stop"

Write-Host "=================================================="
Write-Host "  Aden Agent Framework - Python Setup (Windows)"
Write-Host "=================================================="
Write-Host ""

# 1. Determine Python Command
$PYTHON_CMD = "python"
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
        $PYTHON_CMD = "py"
    }
}

try {
    & $PYTHON_CMD --version | Out-Null
} catch {
    Write-Host "Error: Python not found." -ForegroundColor Red
    exit 1
}

# 2. Check Version
$VerScript = "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"
$VersionStr = & $PYTHON_CMD -c $VerScript
Write-Host "Detected Python: $VersionStr" -ForegroundColor Cyan

$Parts = $VersionStr.Split('.')
$Major = [int]$Parts[0]
$Minor = [int]$Parts[1]

if ($Major -lt 3 -or ($Major -eq 3 -and $Minor -lt 11)) {
    Write-Host "Error: Python 3.11+ is required." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Python version OK" -ForegroundColor Green
Write-Host ""

# 3. Pip
Write-Host "Checking pip..."
& $PYTHON_CMD -m pip --version | Out-Null
Write-Host "[OK] pip detected" -ForegroundColor Green
Write-Host ""

# 4. Install Core
$ProjectRoot = Resolve-Path "."
$CoreDir = Join-Path $ProjectRoot "core"
if (Test-Path $CoreDir) {
    Write-Host "Installing framework from core/..."
    Push-Location $CoreDir
    try {
        & $PYTHON_CMD -m pip install -e .
        Write-Host "[OK] Framework installed" -ForegroundColor Green
    } catch {
        Write-Host "[!] Framework install failed" -ForegroundColor Yellow
    }
    Pop-Location
} else {
    Write-Host "[!] Core directory not found" -ForegroundColor Yellow
}

# 5. Install Tools
$ToolsDir = Join-Path $ProjectRoot "tools"
if (Test-Path $ToolsDir) {
    Write-Host "Installing tools from tools/..."
    Push-Location $ToolsDir
    try {
        & $PYTHON_CMD -m pip install -e .
        Write-Host "[OK] Tools installed" -ForegroundColor Green
    } catch {
        Write-Host "[X] Tools install failed" -ForegroundColor Red
        exit 1
    }
    Pop-Location
} else {
    Write-Host "[X] Tools directory not found" -ForegroundColor Red
    exit 1
}

# 6. OpenAI Fix
Write-Host "Checking openai..."
$CheckOpenAI = "import openai; print(openai.__version__)"
try {
    $OpenAIVer = & $PYTHON_CMD -c $CheckOpenAI 2>$null
    if ($OpenAIVer -and $OpenAIVer.StartsWith("0.")) {
        Write-Host "Upgrading openai..."
        & $PYTHON_CMD -m pip install "openai>=1.0.0"
    }
} catch {
    Write-Host "Installing openai..."
    & $PYTHON_CMD -m pip install "openai>=1.0.0"
}
Write-Host "[OK] openai check complete" -ForegroundColor Green

Write-Host ""
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "To run agents:"
Write-Host '$env:PYTHONPATH="core;exports"'
Write-Host "python -m agent_name run ..."
