#
# quickstart.ps1 - Complete setup for Aden Agent Framework skills
#
# This script:
# 1. Installs Python dependencies (framework, aden_tools, MCP)
# 2. Installs Claude Code skills for building and testing agents
# 3. Verifies the setup is ready to use
#

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$SCRIPT_DIR = $PSScriptRoot

# Claude Code skills directory
$CLAUDE_SKILLS_DIR = "$env:USERPROFILE\.claude\skills"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Aden Agent Framework - Complete Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# Step 1: Check Python Prerequisites
# ============================================================

Write-Host "Step 1: Checking Python prerequisites..." -ForegroundColor Blue
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
$pythonVersion = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pythonMajor = & $pythonCmd -c "import sys; print(sys.version_info.major)"
$pythonMinor = & $pythonCmd -c "import sys; print(sys.version_info.minor)"

Write-Host "  Detected Python: $pythonVersion" -ForegroundColor Green

if ([int]$pythonMajor -lt 3 -or ([int]$pythonMajor -eq 3 -and [int]$pythonMinor -lt 11)) {
    Write-Host "Error: Python 3.11+ is required (found $pythonVersion)" -ForegroundColor Red
    Write-Host "Please upgrade your Python installation"
    exit 1
}

if ([int]$pythonMinor -lt 11) {
    Write-Host "  Warning: Python 3.11+ is recommended for best compatibility" -ForegroundColor Yellow
}

Write-Host "  ✓ Python version OK" -ForegroundColor Green
Write-Host ""

# Check for pip
$pipCheck = & $pythonCmd -m pip --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: pip is not installed" -ForegroundColor Red
    Write-Host "Please install pip for Python $pythonVersion"
    exit 1
}

Write-Host "  ✓ pip detected" -ForegroundColor Green
Write-Host ""

# ============================================================
# Step 2: Install Python Packages
# ============================================================

Write-Host "Step 2: Installing Python packages..." -ForegroundColor Blue
Write-Host ""

# Upgrade pip, setuptools, and wheel
Write-Host "  Upgrading pip, setuptools, wheel..."
& $pythonCmd -m pip install --upgrade pip setuptools wheel *>$null
Write-Host "  ✓ Core tools upgraded" -ForegroundColor Green

# Install framework package from core/
Write-Host "  Installing framework package from core/..."
Push-Location "$SCRIPT_DIR\core"
if (Test-Path "pyproject.toml") {
    & $pythonCmd -m pip install -e . *>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ framework package installed" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ framework installation had issues (may be OK)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ✗ No pyproject.toml in core/" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# Install aden_tools package from tools/
Write-Host "  Installing aden_tools package from tools/..."
Push-Location "$SCRIPT_DIR\tools"
if (Test-Path "pyproject.toml") {
    & $pythonCmd -m pip install -e . *>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ aden_tools package installed" -ForegroundColor Green
    } else {
        Write-Host "  ✗ aden_tools installation failed" -ForegroundColor Red
        Pop-Location
        exit 1
    }
} else {
    Write-Host "  ✗ No pyproject.toml in tools/" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# Install MCP dependencies
Write-Host "  Installing MCP dependencies..."
& $pythonCmd -m pip install mcp fastmcp *>$null
Write-Host "  ✓ MCP dependencies installed" -ForegroundColor Green

# Fix openai version compatibility
$openaiVersion = & $pythonCmd -c "import openai; print(openai.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
    $openaiVersion = "not_installed"
}

if ($openaiVersion -eq "not_installed") {
    Write-Host "  Installing openai package..."
    & $pythonCmd -m pip install "openai>=1.0.0" *>$null
    Write-Host "  ✓ openai installed" -ForegroundColor Green
} elseif ($openaiVersion -match "^0\.") {
    Write-Host "  Upgrading openai to 1.x+ for litellm compatibility..."
    & $pythonCmd -m pip install --upgrade "openai>=1.0.0" *>$null
    Write-Host "  ✓ openai upgraded" -ForegroundColor Green
} else {
    Write-Host "  ✓ openai $openaiVersion is compatible" -ForegroundColor Green
}

# Install click for CLI
& $pythonCmd -m pip install click *>$null
Write-Host "  ✓ click installed" -ForegroundColor Green

Write-Host ""

# ============================================================
# Step 3: Verify Python Imports
# ============================================================

Write-Host "Step 3: Verifying Python imports..." -ForegroundColor Blue
Write-Host ""

$importErrors = 0

# Test framework import
$frameworkTest = & $pythonCmd -c "import framework" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ framework imports OK" -ForegroundColor Green
} else {
    Write-Host "  ✗ framework import failed" -ForegroundColor Red
    $importErrors++
}

# Test aden_tools import
$toolsTest = & $pythonCmd -c "import aden_tools" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ aden_tools imports OK" -ForegroundColor Green
} else {
    Write-Host "  ✗ aden_tools import failed" -ForegroundColor Red
    $importErrors++
}

# Test litellm import
$litellmTest = & $pythonCmd -c "import litellm" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ litellm imports OK" -ForegroundColor Green
} else {
    Write-Host "  ⚠ litellm import issues (may be OK)" -ForegroundColor Yellow
}

# Test MCP server module
$mcpTest = & $pythonCmd -c "from framework.mcp import agent_builder_server" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ MCP server module OK" -ForegroundColor Green
} else {
    Write-Host "  ✗ MCP server module failed" -ForegroundColor Red
    $importErrors++
}

if ($importErrors -gt 0) {
    Write-Host ""
    Write-Host "Error: $importErrors import(s) failed. Please check the errors above." -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================================
# Step 4: Install Claude Code Skills
# ============================================================

Write-Host "Step 4: Installing Claude Code skills..." -ForegroundColor Blue
Write-Host ""

# Check if .claude/skills exists in this repo
if (-not (Test-Path "$SCRIPT_DIR\.claude\skills")) {
    Write-Host "Error: Skills directory not found at $SCRIPT_DIR\.claude\skills" -ForegroundColor Red
    exit 1
}

# Create Claude skills directory if it doesn't exist
if (-not (Test-Path $CLAUDE_SKILLS_DIR)) {
    Write-Host "  Creating Claude skills directory: $CLAUDE_SKILLS_DIR"
    New-Item -ItemType Directory -Path $CLAUDE_SKILLS_DIR -Force | Out-Null
}

# Function to install a skill
function Install-Skill {
    param(
        [string]$skillName
    )
    
    $sourceDir = "$SCRIPT_DIR\.claude\skills\$skillName"
    $targetDir = "$CLAUDE_SKILLS_DIR\$skillName"
    
    if (-not (Test-Path $sourceDir)) {
        Write-Host "  ✗ Skill not found: $skillName" -ForegroundColor Red
        return $false
    }
    
    # Check if skill already exists
    if (Test-Path $targetDir) {
        Remove-Item -Recurse -Force $targetDir
    }
    
    # Copy the skill
    Copy-Item -Recurse $sourceDir $targetDir
    Write-Host "  ✓ Installed: $skillName" -ForegroundColor Green
    return $true
}

# Install all 5 agent-related skills
Install-Skill "building-agents-core" | Out-Null
Install-Skill "building-agents-construction" | Out-Null
Install-Skill "building-agents-patterns" | Out-Null
Install-Skill "testing-agent" | Out-Null
Install-Skill "agent-workflow" | Out-Null

Write-Host ""

# ============================================================
# Step 5: Verify MCP Configuration
# ============================================================

Write-Host "Step 5: Verifying MCP configuration..." -ForegroundColor Blue
Write-Host ""

if (Test-Path "$SCRIPT_DIR\.mcp.json") {
    Write-Host "  ✓ .mcp.json found at project root" -ForegroundColor Green
    Write-Host ""
    Write-Host "  MCP servers configured:"
    $mcpConfig = Get-Content "$SCRIPT_DIR\.mcp.json" | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($mcpConfig.mcpServers) {
        $mcpConfig.mcpServers.PSObject.Properties | ForEach-Object {
            Write-Host "    - $($_.Name)"
        }
    } else {
        Write-Host "    (could not parse config)"
    }
} else {
    Write-Host "  ⚠ No .mcp.json found at project root" -ForegroundColor Yellow
    Write-Host "    Claude Code will not have access to MCP tools"
}

Write-Host ""

# ============================================================
# Step 6: Check API Key
# ============================================================

Write-Host "Step 6: Checking API key..." -ForegroundColor Blue
Write-Host ""

# Check using CredentialManager (preferred)
$apiKeyAvailable = & $pythonCmd -c @"
from aden_tools.credentials import CredentialManager
creds = CredentialManager()
print('yes' if creds.is_available('anthropic') else 'no')
"@ 2>$null

if ($LASTEXITCODE -ne 0) {
    $apiKeyAvailable = "no"
}

if ($apiKeyAvailable -eq "yes") {
    Write-Host "  ✓ ANTHROPIC_API_KEY is available" -ForegroundColor Green
} elseif ($env:ANTHROPIC_API_KEY) {
    Write-Host "  ✓ ANTHROPIC_API_KEY is set in environment" -ForegroundColor Green
} else {
    Write-Host "  ⚠ ANTHROPIC_API_KEY not found" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    For real agent testing, you'll need to set your API key:"
    Write-Host "    `$env:ANTHROPIC_API_KEY='your-key-here'" -ForegroundColor Blue
    Write-Host ""
    Write-Host "    Or add it to your .env file or credential manager."
}

Write-Host ""

# ============================================================
# Step 7: Success Summary
# ============================================================

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  ✓ Setup Complete!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Installed Python packages:"
Write-Host "  • framework (core agent runtime)"
Write-Host "  • aden_tools (tools and MCP servers)"
Write-Host "  • MCP dependencies (mcp, fastmcp)"
Write-Host ""
Write-Host "Installed Claude Code skills:"
Write-Host "  • /building-agents-core        - Fundamental concepts"
Write-Host "  • /building-agents-construction - Step-by-step build guide"
Write-Host "  • /building-agents-patterns    - Best practices"
Write-Host "  • /testing-agent               - Test and validate agents"
Write-Host "  • /agent-workflow              - Complete workflow"
Write-Host ""
Write-Host "Usage:"
Write-Host "  1. Open Claude Code in this directory:"
Write-Host "     cd $SCRIPT_DIR; claude" -ForegroundColor Blue
Write-Host ""
Write-Host "  2. Build a new agent:"
Write-Host "     /building-agents-construction" -ForegroundColor Blue
Write-Host ""
Write-Host "  3. Test an existing agent:"
Write-Host "     /testing-agent" -ForegroundColor Blue
Write-Host ""
Write-Host "  4. Or use the complete workflow:"
Write-Host "     /agent-workflow" -ForegroundColor Blue
Write-Host ""
Write-Host "MCP Tools available (when running from this directory):"
Write-Host "  • mcp__agent-builder__create_session"
Write-Host "  • mcp__agent-builder__set_goal"
Write-Host "  • mcp__agent-builder__add_node"
Write-Host "  • mcp__agent-builder__run_tests"
Write-Host "  • ... and more"
Write-Host ""
Write-Host "Documentation:"
Write-Host "  • Skills: $CLAUDE_SKILLS_DIR"
Write-Host "  • Examples: $SCRIPT_DIR\exports\"
Write-Host ""
