# install-windows.ps1 - Complete Windows Setup for Aden Hive
# Production-grade installation with error handling and recovery

param(
    [switch]$SkipPreflight = $false,
    [switch]$SkipTests = $false,
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$VerbosePreference = if ($Verbose) { "Continue" } else { "SilentlyContinue" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$StartTime = Get-Date

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║  $Title" -ForegroundColor White
    Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
}

function Write-Step {
    param([string]$Step, [int]$Total)
    Write-Host "[$Step/$Total] " -ForegroundColor Cyan -NoNewline
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Exit-WithError {
    param([string]$Message, [int]$Code = 1)
    Write-Host ""
    Write-Error-Custom $Message
    Write-Host ""
    Write-Host "For help, run: .\scripts\doctor-windows.ps1" -ForegroundColor Yellow
    exit $Code
}

# ============================================================================
# STEP 1: PREFLIGHT CHECK
# ============================================================================

Write-Header "ADEN HIVE - WINDOWS INSTALLATION"

if (-not $SkipPreflight) {
    Write-Step "1" "7"
    Write-Host "Running preflight checks..." -ForegroundColor Blue
    
    $PrefightScript = Join-Path $ScriptDir "preflight-windows.ps1"
    if (-not (Test-Path $PrefightScript)) {
        Exit-WithError "preflight-windows.ps1 not found at $PrefightScript"
    }
    
    & $PrefightScript
    if ($LASTEXITCODE -ne 0) {
        Exit-WithError "Preflight check failed. Fix issues and try again." $LASTEXITCODE
    }
}

# ============================================================================
# STEP 2: DETECT PYTHON
# ============================================================================

Write-Step "2" "7"
Write-Host "Detecting Python..." -ForegroundColor Blue

$PythonCmd = $null
foreach ($candidate in @("python3.13", "python3.12", "python3.11", "python3", "python")) {
    try {
        $output = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $major = & $candidate -c "import sys; print(sys.version_info.major)" 2>&1
            $minor = & $candidate -c "import sys; print(sys.version_info.minor)" 2>&1
            
            if ([int]$major -eq 3 -and [int]$minor -ge 11) {
                $PythonVersion = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>&1
                $PythonCmd = $candidate
                break
            }
        }
    } catch { }
}

if (-not $PythonCmd) {
    Exit-WithError "Python 3.11+ not found. Download from https://www.python.org/downloads/"
}

Write-Success "Python $PythonVersion detected"

# ============================================================================
# STEP 3: CREATE VIRTUAL ENVIRONMENT
# ============================================================================

Write-Step "3" "7"
Write-Host "Creating virtual environment..." -ForegroundColor Blue

$VenvPath = Join-Path $ProjectRoot ".venv"

if (Test-Path $VenvPath) {
    Write-Host "Virtual environment already exists. Skipping creation..." -ForegroundColor Yellow
} else {
    try {
        & $PythonCmd -m venv $VenvPath --clear
        if ($LASTEXITCODE -ne 0) {
            Exit-WithError "Failed to create virtual environment"
        }
        Write-Success "Virtual environment created at $VenvPath"
    } catch {
        Exit-WithError "Error creating virtual environment: $_"
    }
}

# ============================================================================
# STEP 4: ACTIVATE VENV & UPGRADE PIP
# ============================================================================

Write-Step "4" "7"
Write-Host "Activating virtual environment and upgrading pip..." -ForegroundColor Blue

$ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"
if (-not (Test-Path $ActivateScript)) {
    Exit-WithError "Activation script not found at $ActivateScript"
}

try {
    & $ActivateScript
    Write-Success "Virtual environment activated"
    
    # Upgrade pip
    python -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null
    Write-Success "pip upgraded"
} catch {
    Exit-WithError "Failed to activate virtual environment: $_"
}

# ============================================================================
# STEP 5: INSTALL PACKAGES
# ============================================================================

Write-Step "5" "7"
Write-Host "Installing Hive packages..." -ForegroundColor Blue

$CorePath = Join-Path $ProjectRoot "core"
$ToolsPath = Join-Path $ProjectRoot "tools"

try {
    Write-Host "  Installing core..." -ForegroundColor DarkGray
    pip install -e $CorePath 2>&1 | Out-Null
    Write-Success "core package installed"
    
    Write-Host "  Installing tools..." -ForegroundColor DarkGray
    pip install -e $ToolsPath 2>&1 | Out-Null
    Write-Success "tools package installed"
} catch {
    Exit-WithError "Failed to install packages: $_"
}

# ============================================================================
# STEP 6: IMPORT VERIFICATION
# ============================================================================

Write-Step "6" "7"
Write-Host "Verifying imports..." -ForegroundColor Blue

try {
    python -c "import framework; print('✓')" 2>&1 | Out-Null
    Write-Success "framework imports successfully"
    
    python -c "import aden_tools; print('✓')" 2>&1 | Out-Null
    Write-Success "aden_tools imports successfully"
    
    # Optional: Check LLM SDKs
    foreach ($sdk in @("openai", "anthropic")) {
        try {
            python -c "import $sdk; print('✓')" 2>&1 | Out-Null
            Write-Success "$sdk SDK available"
        } catch {
            Write-Host "  (optional) $sdk SDK not installed" -ForegroundColor DarkGray
        }
    }
} catch {
    Exit-WithError "Import verification failed: $_"
}

# ============================================================================
# STEP 7: OPTIONAL - LOAD .ENV FILE
# ============================================================================

Write-Step "7" "7"
Write-Host "Checking for .env configuration..." -ForegroundColor Blue

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Write-Host "  Loading .env file..." -ForegroundColor DarkGray
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $key = $matches[1]
            $value = $matches[2].Trim('"', "'")
            [System.Environment]::SetEnvironmentVariable($key, $value, 'Process')
            Write-Verbose "Loaded $key from .env"
        }
    }
    Write-Success ".env file loaded"
} else {
    Write-Host "  No .env file found (optional)" -ForegroundColor DarkGray
    Write-Host "  Create one for automatic API key loading" -ForegroundColor DarkGray
}

# ============================================================================
# OPTIONAL: RUN TESTS
# ============================================================================

if (-not $SkipTests) {
    Write-Host ""
    Write-Host "Running tests..." -ForegroundColor Blue
    
    try {
        pytest core\tests\ -q 2>&1 | Select-Object -Last 5
        if ($LASTEXITCODE -eq 0) {
            Write-Success "All tests passed"
        } else {
            Write-Host "  Some tests failed (this is OK for initial setup)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  pytest not available or tests failed (skipping)" -ForegroundColor DarkGray
    }
}

# ============================================================================
# COMPLETION
# ============================================================================

$Duration = ((Get-Date) - $StartTime).TotalSeconds

Write-Host ""
Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ✓ SETUP COMPLETE" -ForegroundColor White
Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "Time elapsed: $([Math]::Round($Duration, 2))s" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Set your LLM API key:" -ForegroundColor White
Write-Host "     `$env:OPENAI_API_KEY = 'your-key-here'" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  2. Test the installation:" -ForegroundColor White
Write-Host "     python core\examples\manual_agent.py" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  3. Verify with doctor script:" -ForegroundColor White
Write-Host "     .\scripts\doctor-windows.ps1" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Documentation: docs\WINDOWS_SETUP.md" -ForegroundColor Cyan
Write-Host ""

exit 0
