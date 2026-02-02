#
# quickstart.ps1 - Interactive onboarding for Aden Agent Framework (Windows)
#
# Native Windows PowerShell setup. Equivalent to quickstart.sh for Linux/macOS.
# Sets up: framework, aden_tools, MCP dependencies, and LLM configuration.
#
# Usage: .\quickstart.ps1
#        or: powershell -ExecutionPolicy Bypass -File .\quickstart.ps1
#

$ErrorActionPreference = "Stop"
$SCRIPT_DIR = $PSScriptRoot

# Colors (Windows compatible)
function Write-Info { param($msg) Write-Host $msg }
function Write-Ok { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host $msg -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host $msg -ForegroundColor Red }
function Write-Step { param($msg) Write-Host $msg -ForegroundColor Cyan }


Clear-Host
Write-Host ""
Write-Host "          A D E N   H I V E" -ForegroundColor Yellow
Write-Host ""
Write-Host "     Goal-driven AI agent framework" -ForegroundColor DarkGray
Write-Host ""
Write-Host "This wizard will help you set up everything you need"
Write-Host "to build and run goal-driven AI agents."
Write-Host ""

$reply = Read-Host "Ready to begin? [Y/n]"
if ($reply -match "^[Nn]") {
    Write-Host "No problem! Run this script again when you're ready."
    exit 0
}

Write-Host ""

# Step 1: Check Python


Write-Step "Step 1: Checking Python..."
Write-Host ""

$PYTHON_CMD = $null
$candidates = @("py", "python3.12", "python3.11", "python3", "python")
foreach ($cmd in $candidates) {
    try {
        if ($cmd -eq "py") {
            $version = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            $major, $minor = $version -split '\.'
        } else {
            $version = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            $major, $minor = $version -split '\.'
        }
        if ([int]$major -eq 3 -and [int]$minor -ge 11) {
            $PYTHON_CMD = if ($cmd -eq "py") { @("py", "-3") } else { @($cmd) }
            break
        }
    } catch {}
}

if (-not $PYTHON_CMD) {
    Write-Err "Python 3.11+ is required."
    Write-Host "Please install Python from https://www.python.org/downloads/"
    Write-Host "Ensure 'Add Python to PATH' is checked during installation."
    exit 1
}

$version = & $PYTHON_CMD[0] @($PYTHON_CMD[1..($PYTHON_CMD.Length-1)]) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "  Python $version"
Write-Host ""

# Check for uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Warn "  uv not found. Installing..."
    try {
        Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -UseBasicParsing | Invoke-Expression
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw "uv install may need a new shell. Run: irm https://astral.sh/uv/install.ps1 | iex"
        }
    } catch {
        Write-Err "  Failed to install uv. Install manually from https://astral.sh/uv/"
        exit 1
    }
    Write-Ok "  uv installed"
}
Write-Ok "  uv detected: $(uv --version)"
Write-Host ""

# Step 2: Install packages


Write-Step "Step 2: Installing packages..."
Write-Host ""

# Framework
Push-Location "$SCRIPT_DIR\core"
try {
    if (Test-Path "pyproject.toml") {
        uv sync 2>&1 | Out-Null
        Write-Ok "  framework package installed"
    } else {
        Write-Err "  No pyproject.toml in core/"
        exit 1
    }
} finally { Pop-Location }

# Tools
Push-Location "$SCRIPT_DIR\tools"
try {
    if (Test-Path "pyproject.toml") {
        uv sync 2>&1 | Out-Null
        Write-Ok "  aden_tools package installed"
    } else {
        Write-Err "  No pyproject.toml in tools/"
        exit 1
    }
} finally { Pop-Location }

# MCP, openai, click
& $PYTHON_CMD[0] @($PYTHON_CMD[1..($PYTHON_CMD.Length-1)]) -m pip install mcp fastmcp "openai>=1.0.0" click -q 2>$null
Write-Ok "  MCP and CLI dependencies installed"

# Tools venv - MCP deps
$TOOLS_PYTHON = "$SCRIPT_DIR\tools\.venv\Scripts\python.exe"
if (Test-Path $TOOLS_PYTHON) {
    uv pip install --python $TOOLS_PYTHON mcp fastmcp "openai>=1.0.0" click -q 2>$null
}
Write-Host ""
Write-Ok "All packages installed"
Write-Host ""

# Step 3: Verify imports


Write-Step "Step 3: Verifying installation..."
Write-Host ""

$CORE_PYTHON = "$SCRIPT_DIR\core\.venv\Scripts\python.exe"
$errors = 0

if ((Test-Path $CORE_PYTHON) -and (& $CORE_PYTHON -c "import framework" 2>$null)) {
    Write-Ok "  framework OK"
} else {
    Write-Err "  framework import failed"
    $errors++
}

if ((Test-Path $TOOLS_PYTHON) -and (& $TOOLS_PYTHON -c "import aden_tools" 2>$null)) {
    Write-Ok "  aden_tools OK"
} else {
    Write-Err "  aden_tools import failed"
    $errors++
}

if ((Test-Path $CORE_PYTHON) -and (& $CORE_PYTHON -c "from framework.mcp import agent_builder_server" 2>$null)) {
    Write-Ok "  MCP server OK"
} else {
    Write-Err "  MCP server import failed"
    $errors++
}

if ($errors -gt 0) {
    Write-Err "`n$errors import(s) failed. Check the errors above."
    exit 1
}
Write-Host ""


# Step 4: LLM configuration


$HIVE_CONFIG_DIR = Join-Path $env:USERPROFILE ".hive"
$HIVE_CONFIG_FILE = Join-Path $HIVE_CONFIG_DIR "configuration.json"

# Load .env if present
$envFiles = @("$SCRIPT_DIR\.env", "$env:USERPROFILE\.env")
foreach ($f in $envFiles) {
    if (Test-Path $f) {
        Get-Content $f | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
                $key = $matches[1].Trim()
                $value = $matches[2].Trim().Trim('"').Trim("'")
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
}

$providers = @(
    @{ env = "ANTHROPIC_API_KEY"; name = "Anthropic (Claude)"; id = "anthropic"; model = "claude-sonnet-4-5-20250929" },
    @{ env = "OPENAI_API_KEY"; name = "OpenAI (GPT)"; id = "openai"; model = "gpt-4o" },
    @{ env = "GEMINI_API_KEY"; name = "Google Gemini"; id = "gemini"; model = "gemini-3.0-flash-preview" },
    @{ env = "GROQ_API_KEY"; name = "Groq"; id = "groq"; model = "llama-3.1-70b-versatile" },
    @{ env = "CEREBRAS_API_KEY"; name = "Cerebras"; id = "cerebras"; model = "llama-3.1-70b" }
)

$found = @()
foreach ($p in $providers) {
    $val = [Environment]::GetEnvironmentVariable($p.env, "Process")
    if (-not $val) { $val = [Environment]::GetEnvironmentVariable($p.env, "User") }
    if (-not $val) { $val = [Environment]::GetEnvironmentVariable($p.env, "Machine") }
    if ($val) { $found += $p }
}

if ($found.Count -gt 0) {
    Write-Host "Found API keys:" -ForegroundColor Cyan
    $found | ForEach-Object { Write-Host "  - $($_.name)" }
    $use = Read-Host "`nUse one for default? [Y/n]"
    if ($use -notmatch "^[Nn]") {
        $selected = if ($found.Count -eq 1) { $found[0] } else {
            for ($i = 0; $i -lt $found.Count; $i++) { Write-Host "  $($i+1)) $($found[$i].name)" }
            $choice = Read-Host "Enter choice (1-$($found.Count))"
            $found[[int]$choice - 1]
        }
        New-Item -ItemType Directory -Force -Path $HIVE_CONFIG_DIR | Out-Null
        $config = @{
            llm = @{
                provider = $selected.id
                model = $selected.model
                api_key_env_var = $selected.env
            }
            created_at = (Get-Date -Format "o")
        } | ConvertTo-Json -Depth 3
        $config | Out-File -FilePath $HIVE_CONFIG_FILE -Encoding utf8
        Write-Ok "  Config saved to $HIVE_CONFIG_FILE"
    }
} else {
    Write-Warn "No API keys found in environment."
    Write-Host "Add your key to .env or environment variables, e.g.:"
    Write-Host "  `$env:ANTHROPIC_API_KEY = 'your-key'"
    Write-Host "  or create a .env file in the project root"
}

Write-Host ""

# Done


Clear-Host
Write-Host ""
Write-Host "        ADEN HIVE - READY" -ForegroundColor Green
Write-Host ""
Write-Host "Quick Start:"
Write-Host "  1. Build an agent: /building-agents-construction (in Claude/Cursor)"
Write-Host "  2. Test: /testing-agent"
Write-Host "  3. Run: `$env:PYTHONPATH='core;exports'; python -m agent_name run --input '{...}'"
Write-Host ""
Write-Host "See README.md and ENVIRONMENT_SETUP.md for more."
Write-Host ""
