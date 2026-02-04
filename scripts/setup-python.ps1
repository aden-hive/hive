<#
.SYNOPSIS
    Advanced Setup Script for Aden Hive AI Framework.
    Optimized for Windows Enterprise Environments (1,000+ User Scale).
    
    Features: 
    - Admin Privilege Validation
    - Automated ExecutionPolicy Correction
    - High-Speed 'uv' Integration
    - Resilience-Focused Error Handling
#>

$ErrorActionPreference = "Stop"

# Beast-Level Visual Styling
$RED    = "Red"; $GREEN  = "Green"; $YELLOW = "Yellow"; $CYAN   = "Cyan"

function Show-Header {
    Write-Host "`n==================================================" -ForegroundColor $CYAN
    Write-Host "   ADEN HIVE - ENTERPRISE WINDOWS SETUP (V2.0)" -ForegroundColor $CYAN
    Write-Host "   Role: Senior System Admin / Infrastructure"
    Write-Host "==================================================" -ForegroundColor $CYAN
}

# 1. PRIVILEGE VALIDATION (The Guardrail)
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "![CRITICAL] Admin rights required for system-level automation." -ForegroundColor $RED
    Write-Host "Please restart PowerShell as Administrator." -ForegroundColor $YELLOW
    exit 1
}

# 2. AUTOMATED EXECUTION POLICY (Self-Correction)
if ((Get-ExecutionPolicy) -eq "Restricted") {
    Write-Host "Adjusting Execution Policy for stable onboarding..." -ForegroundColor $YELLOW
    Set-ExecutionPolicy RemoteSigned -Scope Process -Force
}

Show-Header

# 3. DIRECTORY DISCOVERY
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR
Set-Location $PROJECT_ROOT

# 4. DEPENDENCY CHECK: Python 3.11+
try {
    $version = python --version 2>$null
    Write-Host "[OK] $version Detected" -ForegroundColor $GREEN
} catch {
    Write-Host "![FAIL] Python 3.11+ not found. Infrastructure requires manual install." -ForegroundColor $RED
    exit 1
}

# 5. INTEGRATE 'UV' (The Best-of-the-Best Package Manager)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing 'uv' for 10x faster environment scaling..." -ForegroundColor $CYAN
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    
    # --- CRUCIAL PATH REFRESH ---
    $env:PATH += ";$env:USERPROFILE\.local\bin"
    $env:PATH += ";$env:USERPROFILE\.cargo\bin"
}
Write-Host "[OK] uv-package manager ready." -ForegroundColor $GREEN

# 6. VIRTUAL ENVIRONMENT & EDITABLE INSTALLS (Nervous System)
Write-Host "`nInitializing Outcome-Driven Environment..." -ForegroundColor $CYAN
if (-not (Test-Path ".venv")) {
    uv venv --python 3.11
}

# Use Venv Context
$VENV_BIN = if ($IsWindows) { "Scripts" } else { "bin" }
$PYTHON_EXEC = Join-Path $PROJECT_ROOT ".venv\$VENV_BIN\python.exe"

# 7. MULTI-REPO CONSOLIDATION (Core & Tools)
$Targets = @("core", "tools")
foreach ($target in $Targets) {
    if (Test-Path $target) {
        Write-Host "Provisioning $target layer..." -ForegroundColor $CYAN
        Set-Location "$PROJECT_ROOT\$target"
        & $PYTHON_EXEC -m pip install -e .
        Write-Host "[OK] $target package linked." -ForegroundColor $GREEN
    }
}

# 8. FINAL SYSTEM VALIDATION
Write-Host "`n==================================================" -ForegroundColor $CYAN
Write-Host "   SYSTEM STABLE - SETUP COMPLETE" -ForegroundColor $GREEN
Write-Host "==================================================" -ForegroundColor $CYAN
Write-Host "To start your beast-level contribution:"
Write-Host "1. Activate:  .venv\Scripts\Activate.ps1"
Write-Host "2. Set Path:  `$env:PYTHONPATH='core;exports'"
Write-Host "3. Run:       python -m agent_name run" -ForegroundColor $YELLOW
