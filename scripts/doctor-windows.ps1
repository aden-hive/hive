# doctor-windows.ps1 - Diagnose Hive installation issues
# Run this if you encounter problems

param(
    [switch]$Verbose = $false,
    [switch]$Repair = $false
)

$ErrorActionPreference = "Continue"
$VerbosePreference = if ($Verbose) { "Continue" } else { "SilentlyContinue" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$IssuesFound = 0

function Write-Header {
    Write-Host ""
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  HIVE DIAGNOSTICS" -ForegroundColor White
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Diagnostic {
    param([string]$Name, [string]$Result, [string]$Color = "Green")
    Write-Host "• $Name" -ForegroundColor $Color
    Write-Host "  $Result" -ForegroundColor DarkGray
}

function Write-Issue {
    param([string]$Issue, [string]$Solution)
    $global:IssuesFound++
    Write-Host "✗ ISSUE $IssuesFound: $Issue" -ForegroundColor Red
    Write-Host "  Solution: $Solution" -ForegroundColor Yellow
    Write-Host ""
}

Write-Header

# 1. Python Check
Write-Host "1. PYTHON ENVIRONMENT" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

try {
    $PythonVersion = python --version 2>&1
    Write-Diagnostic "Python found" "$PythonVersion" Green
    
    $PythonPath = (Get-Command python).Source
    Write-Diagnostic "Python path" "$PythonPath" Green
} catch {
    Write-Issue "Python not found or not in PATH" `
        "Download from https://www.python.org/downloads/ and add to PATH"
}

# 2. Virtual Environment Check
Write-Host ""
Write-Host "2. VIRTUAL ENVIRONMENT" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

$VenvPath = Join-Path $ProjectRoot ".venv"
if (Test-Path $VenvPath) {
    Write-Diagnostic "Virtual environment exists" ".venv folder found" Green
    
    $PythonVenv = Join-Path $VenvPath "Scripts\python.exe"
    if (Test-Path $PythonVenv) {
        Write-Diagnostic "Venv Python executable" "Scripts\python.exe found" Green
        
        # Check if activated
        $CurrentPython = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($CurrentPython -like "*$VenvPath*") {
            Write-Diagnostic "Venv activation status" "✓ ACTIVATED" Green
        } else {
            Write-Issue "Virtual environment not activated" `
                "Run: .\.venv\Scripts\Activate.ps1"
        }
    } else {
        Write-Issue "Venv Python not found" `
            "Recreate venv: python -m venv .venv --clear"
    }
} else {
    Write-Issue "Virtual environment not created" `
        "Create venv: python -m venv .venv"
}

# 3. Packages Check
Write-Host ""
Write-Host "3. INSTALLED PACKAGES" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

$PackagesOK = $true

# Check framework
try {
    $FrameworkVersion = python -c "import framework; print(framework.__version__ if hasattr(framework, '__version__') else 'installed')" 2>&1
    Write-Diagnostic "framework" "✓ $FrameworkVersion" Green
} catch {
    Write-Issue "framework package not found" `
        "Reinstall: pip install -e .\core"
    $PackagesOK = $false
}

# Check aden_tools
try {
    $ToolsVersion = python -c "import aden_tools; print('installed')" 2>&1
    Write-Diagnostic "aden_tools" "✓ $ToolsVersion" Green
} catch {
    Write-Issue "aden_tools package not found" `
        "Reinstall: pip install -e .\tools"
    $PackagesOK = $false
}

# Check LLM SDKs
$LlmSdks = @("openai", "anthropic")
foreach ($sdk in $LlmSdks) {
    try {
        $null = python -c "import $sdk" 2>&1
        Write-Diagnostic "$sdk SDK" "✓ installed" Green
    } catch {
        Write-Diagnostic "$sdk SDK" "✗ not installed (optional)" Yellow
    }
}

# 4. Environment Variables
Write-Host ""
Write-Host "4. ENVIRONMENT VARIABLES" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

$ApiKeys = @("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
$HasApiKey = $false

foreach ($key in $ApiKeys) {
    $value = [System.Environment]::GetEnvironmentVariable($key)
    if ($value) {
        $masked = $value.Substring(0, [Math]::Min(10, $value.Length)) + "***"
        Write-Diagnostic $key "✓ set ($masked)" Green
        $HasApiKey = $true
    }
}

if (-not $HasApiKey) {
    Write-Issue "No LLM API keys found" `
        "Set at least one: `$env:OPENAI_API_KEY = 'your-key'"
}

# Check .env file
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Write-Diagnostic ".env file" "✓ found" Green
} else {
    Write-Diagnostic ".env file" "not found (optional)" Yellow
}

# 5. Git Configuration
Write-Host ""
Write-Host "5. GIT CONFIGURATION" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

try {
    $GitVersion = git --version 2>&1
    Write-Diagnostic "Git" "✓ $GitVersion" Green
    
    # Check line ending config
    $LineEndings = git config core.safecrlf 2>&1
    if ($LineEndings -eq "warn") {
        Write-Diagnostic "CRLF settings" "✓ configured (safe)" Green
    } elseif ($LineEndings -eq "true") {
        Write-Diagnostic "CRLF settings" "configured (strict)" Yellow
    } else {
        Write-Diagnostic "CRLF settings" "not configured (default)" Yellow
    }
} catch {
    Write-Diagnostic "Git" "not installed (optional)" Yellow
}

# 6. Project Structure
Write-Host ""
Write-Host "6. PROJECT STRUCTURE" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

$Dirs = @("core", "tools", "scripts", "docs", "exports")
foreach ($dir in $Dirs) {
    $path = Join-Path $ProjectRoot $dir
    if (Test-Path $path -PathType Container) {
        Write-Diagnostic $dir "✓ found" Green
    } else {
        Write-Diagnostic $dir "✗ missing" Red
    }
}

# 7. Test Run
Write-Host ""
Write-Host "7. FUNCTIONALITY TEST" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan

# Test imports
$ImportOK = $false
try {
    python -c "import framework, aden_tools; print('✓')" 2>&1 | Out-Null
    Write-Diagnostic "Core imports" "✓ framework and aden_tools import successfully" Green
    $ImportOK = $true
} catch {
    Write-Issue "Core imports failed" `
        "Check that venv is activated and packages are installed correctly"
}

# Test LLM if API key available
if ($HasApiKey -and $ImportOK) {
    try {
        python -c @"
try:
    from openai import OpenAI
    client = OpenAI()
    print('OpenAI client initialized')
except Exception as e:
    print(f'OpenAI error: {e}')
"@ 2>&1 | Out-Null
        Write-Diagnostic "LLM SDK" "✓ can initialize client" Green
    } catch {
        Write-Diagnostic "LLM SDK" "✗ failed to initialize" Red
    }
}

# ============================================================================
# SUMMARY & REPAIR OPTION
# ============================================================================

Write-Host ""
Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  SUMMARY" -ForegroundColor White
Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

if ($IssuesFound -eq 0) {
    Write-Host "✓ NO ISSUES FOUND" -ForegroundColor Green
    Write-Host "Your Hive installation looks good!" -ForegroundColor Green
} else {
    Write-Host "⚠️  $IssuesFound ISSUE(S) FOUND" -ForegroundColor Red
    Write-Host ""
    
    if ($Repair) {
        Write-Host "Running repairs..." -ForegroundColor Yellow
        Write-Host ""
        
        # Repair: Reinstall packages
        if (-not $PackagesOK) {
            Write-Host "Reinstalling packages..." -ForegroundColor Yellow
            pip install -e "$ProjectRoot\core" 2>&1 | Out-Null
            pip install -e "$ProjectRoot\tools" 2>&1 | Out-Null
            Write-Host "✓ Packages reinstalled" -ForegroundColor Green
        }
        
        Write-Host ""
        Write-Host "Repair complete. Run doctor again to verify." -ForegroundColor Green
    } else {
        Write-Host "For automatic repair, run: .\scripts\doctor-windows.ps1 -Repair" -ForegroundColor Cyan
    }
}

Write-Host ""
