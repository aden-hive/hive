# preflight-windows.ps1 - Pre-flight checks before setup
# Validates environment before installation begins

param(
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$VerbosePreference = if ($Verbose) { "Continue" } else { "SilentlyContinue" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ChecksFailed = 0
$ChecksPassed = 0

function Write-Header {
    Write-Host ""
    Write-Host "════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host "  HIVE WINDOWS PREFLIGHT CHECK" -ForegroundColor White
    Write-Host "════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host ""
}

function Write-Check {
    param([string]$Name, [string]$Status, [string]$Color)
    $Symbol = if ($Status -eq "PASS") { "✓" } else { "✗" }
    Write-Host "$Symbol $Name" -ForegroundColor $Color
}

function Test-Check {
    param([string]$CheckName, [scriptblock]$Test, [string]$FailureMsg)
    
    try {
        $result = & $Test
        if ($result) {
            Write-Check $CheckName "PASS" Green
            $global:ChecksPassed++
            return $true
        } else {
            Write-Check $CheckName "FAIL" Red
            Write-Host "  → $FailureMsg" -ForegroundColor Yellow
            $global:ChecksFailed++
            return $false
        }
    }
    catch {
        Write-Check $CheckName "FAIL" Red
        Write-Host "  → $FailureMsg" -ForegroundColor Yellow
        $global:ChecksFailed++
        return $false
    }
}

# ============================================================================
# CHECKS
# ============================================================================

Write-Header

# 1. PowerShell Version
Write-Verbose "Checking PowerShell version..."
Test-Check "PowerShell 5.1+" `
    { $PSVersionTable.PSVersion.Major -ge 5 } `
    "Upgrade PowerShell: https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-windows"

# 2. Python Installation
Write-Verbose "Checking Python installation..."
$PythonFound = $false
$PythonVersion = $null
$PythonPath = $null

foreach ($candidate in @("python3.13", "python3.12", "python3.11", "python3", "python")) {
    try {
        $output = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $major = & $candidate -c "import sys; print(sys.version_info.major)" 2>&1
            $minor = & $candidate -c "import sys; print(sys.version_info.minor)" 2>&1
            
            if ([int]$major -eq 3 -and [int]$minor -ge 11) {
                $PythonVersion = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>&1
                $PythonPath = & where.exe $candidate 2>&1 | Select-Object -First 1
                $PythonFound = $true
                break
            }
        }
    } catch { }
}

if ($PythonFound) {
    Write-Check "Python 3.11+" "PASS" Green
    Write-Verbose "  Found Python $PythonVersion at $PythonPath"
    $ChecksPassed++
    
    # Check for Microsoft Store Python
    if ($PythonPath -like "*WindowsApps*") {
        Write-Check "NOT Microsoft Store Python" "FAIL" Red
        Write-Host "  → Detected Microsoft Store Python. This version has limitations." -ForegroundColor Yellow
        Write-Host "  → Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
        $ChecksFailed++
    } else {
        Write-Check "NOT Microsoft Store Python" "PASS" Green
        $ChecksPassed++
    }
} else {
    Write-Check "Python 3.11+" "FAIL" Red
    Write-Host "  → Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  → Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Yellow
    $ChecksFailed++
}

# 3. Python in PATH
if ($PythonFound) {
    Write-Verbose "Checking Python PATH..."
    Test-Check "Python in PATH" `
        { (Get-Command python -ErrorAction SilentlyContinue) -ne $null } `
        "Python not in PATH. Reinstall Python and check 'Add Python to PATH'"
}

# 4. pip Available
Write-Verbose "Checking pip..."
if ($PythonFound) {
    Test-Check "pip installed" `
        { & $PythonPath -m pip --version 2>&1 | Select-String "pip" } `
        "pip not available. Run: $PythonPath -m ensurepip"
}

# 5. Git (optional but recommended)
Write-Verbose "Checking Git..."
Test-Check "Git for Windows" `
    { (Get-Command git -ErrorAction SilentlyContinue) -ne $null } `
    "Git not found (optional). Download: https://git-scm.com/download/win"

# 6. Execution Policy
Write-Verbose "Checking execution policy..."
$ExecPolicy = Get-ExecutionPolicy -Scope CurrentUser
$PolicyOK = $ExecPolicy -in @("RemoteSigned", "Unrestricted", "Bypass")

if ($PolicyOK) {
    Write-Check "Execution Policy" "PASS" Green
    $ChecksPassed++
} else {
    Write-Check "Execution Policy" "FAIL" Red
    Write-Host "  → Current policy: $ExecPolicy (requires RemoteSigned or higher)" -ForegroundColor Yellow
    Write-Host "  → Run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
    $ChecksFailed++
}

# 7. Administrator Access (for some operations)
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($IsAdmin) {
    Write-Check "Running as Administrator" "PASS" Green
    $ChecksPassed++
} else {
    Write-Check "Running as Administrator" "WARN" Yellow
    Write-Verbose "  → Not required but recommended for some operations"
}

# 8. Disk Space (at least 2GB free)
Write-Verbose "Checking disk space..."
$DriveLetter = $ProjectRoot[0]
$Drive = Get-PSDrive -Name $DriveLetter -ErrorAction SilentlyContinue
if ($Drive) {
    $FreeGB = [math]::Round($Drive.Free / 1GB, 2)
    if ($Drive.Free -gt 2GB) {
        Write-Check "Disk Space (2GB+ free)" "PASS" Green
        Write-Verbose "  → Free space: $FreeGB GB"
        $ChecksPassed++
    } else {
        Write-Check "Disk Space (2GB+ free)" "FAIL" Red
        Write-Host "  → Only $FreeGB GB free. Need at least 2GB." -ForegroundColor Yellow
        $ChecksFailed++
    }
}

# 9. Project Structure
Write-Verbose "Checking project structure..."
$HasCore = Test-Path (Join-Path $ProjectRoot "core") -PathType Container
$HasTools = Test-Path (Join-Path $ProjectRoot "tools") -PathType Container

if ($HasCore -and $HasTools) {
    Write-Check "Project structure" "PASS" Green
    $ChecksPassed++
} else {
    Write-Check "Project structure" "FAIL" Red
    Write-Host "  → core/ or tools/ folder not found" -ForegroundColor Yellow
    $ChecksFailed++
}

# ============================================================================
# SUMMARY
# ============================================================================

Write-Host ""
Write-Host "════════════════════════════════════════" -ForegroundColor Yellow
Write-Host "  SUMMARY" -ForegroundColor White
Write-Host "════════════════════════════════════════" -ForegroundColor Yellow
Write-Host ""
Write-Host "Passed: $ChecksPassed" -ForegroundColor Green
Write-Host "Failed: $ChecksFailed" -ForegroundColor $(if ($ChecksFailed -gt 0) { "Red" } else { "Green" })
Write-Host ""

if ($ChecksFailed -gt 0) {
    Write-Host "⚠️  SETUP CANNOT PROCEED" -ForegroundColor Red
    Write-Host "Fix the issues above and run this script again." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "✓ PREFLIGHT CHECK PASSED" -ForegroundColor Green
    Write-Host "Ready to run: .\scripts\install-windows.ps1" -ForegroundColor Cyan
    Write-Host ""
    exit 0
}
