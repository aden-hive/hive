#Requires -Version 5.1
<#
.SYNOPSIS
    quickstart.ps1 - Interactive onboarding for Aden Agent Framework (Windows)

.DESCRIPTION
    An interactive setup wizard that:
    1. Installs Python dependencies via uv
    2. Checks for Chrome/Edge browser for web automation
    3. Helps configure LLM API keys
    4. Verifies everything works

.NOTES
    Run from the project root: .\quickstart.ps1
    Requires: PowerShell 5.1+ and Python 3.11+
#>

# Use "Continue" so stderr from external tools (uv, python) does not
# terminate the script.  Errors are handled via $LASTEXITCODE checks.
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$UvHelperPath = Join-Path $ScriptDir "scripts\uv-discovery.ps1"

# Hive LLM router endpoint
$HiveLlmEndpoint = "https://api.adenhq.com"
$HiveLlmAvailabilityEndpoint = "$HiveLlmEndpoint/v1/gateway/availability"

. $UvHelperPath

function Test-HiveGatewayAvailability {
    param([string]$From)

    try {
        $url = "$HiveLlmAvailabilityEndpoint?from=$From"
        $result = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5 -ErrorAction Stop
        if ($result -eq $true) { return "available" }
        return "unavailable"
    } catch {
        return "unknown"
    }
}

# ============================================================
# Colors / helpers
# ============================================================

function Write-Color {
    param(
        [string]$Text,
        [ConsoleColor]$Color = [ConsoleColor]::White,
        [switch]$NoNewline
    )
    $prev = $Host.UI.RawUI.ForegroundColor
    $Host.UI.RawUI.ForegroundColor = $Color
    if ($NoNewline) { Write-Host $Text -NoNewline }
    else { Write-Host $Text }
    $Host.UI.RawUI.ForegroundColor = $prev
}

function Write-Step {
    param([string]$Number, [string]$Text)
    Write-Color -Text ([char]0x2B22) -Color Yellow -NoNewline
    Write-Host " " -NoNewline
    Write-Color -Text "$Text" -Color Cyan
    Write-Host ""
}

function Write-Ok {
    param([string]$Text)
    Write-Color -Text "  $([char]0x2713) $Text" -Color Green
}

function Write-Warn {
    param([string]$Text)
    Write-Color -Text "  ! $Text" -Color Yellow
}

function Write-Fail {
    param([string]$Text)
    Write-Color -Text "  X $Text" -Color Red
}

function Write-CommandFailureDetails {
    param(
        [object[]]$Output,
        [int]$Tail = 40
    )

    $lines = @($Output | Where-Object { $_ -ne $null } | ForEach-Object { "$_" })
    if ($lines.Count -eq 0) {
        return
    }

    $start = [Math]::Max(0, $lines.Count - $Tail)
    if ($start -gt 0) {
        Write-Host "    ... showing last $($lines.Count - $start) lines ..." -ForegroundColor DarkGray
    }

    for ($i = $start; $i -lt $lines.Count; $i++) {
        Write-Host "    $($lines[$i])" -ForegroundColor DarkGray
    }
}

function Test-FrontendDistReady {
    param([string]$RootDir)
    return (Test-Path (Join-Path $RootDir "core\frontend\dist\index.html"))
}

function Prompt-YesNo {
    param(
        [string]$Prompt,
        [string]$Default = "y"
    )
    if ($Default -eq "y") { $hint = "[Y/n]" } else { $hint = "[y/N]" }
    $response = Read-Host "$Prompt $hint"
    if ([string]::IsNullOrWhiteSpace($response)) { $response = $Default }
    return $response -match "^[Yy]"
}

function Prompt-Choice {
    param(
        [string]$Prompt,
        [string[]]$Options
    )
    Write-Host ""
    Write-Color -Text $Prompt -Color White
    Write-Host ""
    for ($i = 0; $i -lt $Options.Count; $i++) {
        Write-Color -Text "  $($i + 1)" -Color Cyan -NoNewline
        Write-Host ") $($Options[$i])"
    }
    Write-Host ""
    while ($true) {
        $choice = Read-Host "Enter choice (1-$($Options.Count))"
        if ($choice -match '^\d+$') {
            $num = [int]$choice
            if ($num -ge 1 -and $num -le $Options.Count) {
                return $num - 1
            }
        }
        Write-Color -Text "Invalid choice. Please enter 1-$($Options.Count)" -Color Red
    }
}

# ============================================================
# Windows Defender Exclusion Functions
# ============================================================

function Test-IsAdmin {
    <#
    .SYNOPSIS
        Check if current PowerShell session has admin privileges
    #>
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-DefenderExclusions {
    <#
    .SYNOPSIS
        Check if Windows Defender is enabled and which paths need exclusions
    .PARAMETER Paths
        Array of paths to check
    .OUTPUTS
        Hashtable with DefenderEnabled, MissingPaths, and optional Error
    #>
    param([string[]]$Paths)
    
    # Security: Define safe path prefixes (project + user directories only)
    $safePrefixes = @(
        $ScriptDir,         # Project directory
        $env:LOCALAPPDATA,  # User local appdata
        $env:APPDATA        # User roaming appdata
    )
    
    # Normalize and filter null/empty values
    $safePrefixes = $safePrefixes | Where-Object { $_ } | ForEach-Object {
        try { [System.IO.Path]::GetFullPath($_) } catch { $null }
    } | Where-Object { $_ }
    
    try {
        # Check if Defender cmdlets are available (may not exist on older Windows)
        $mpModule = Get-Module -ListAvailable -Name Defender -ErrorAction SilentlyContinue
        if (-not $mpModule) {
            return @{ 
                DefenderEnabled = $false
                Error = "Windows Defender module not available"
            }
        }
        
        # Check if Defender is running
        $status = Get-MpComputerStatus -ErrorAction Stop
        if (-not $status.RealTimeProtectionEnabled) {
            return @{ 
                DefenderEnabled = $false
                Reason = "Real-time protection is disabled"
            }
        }
        
        # Get current exclusions
        $prefs = Get-MpPreference -ErrorAction Stop
        $existing = $prefs.ExclusionPath
        if (-not $existing) { $existing = @() }
        
        # Normalize existing paths for comparison (some may contain wildcards
        # or env vars that GetFullPath rejects — skip those gracefully)
        $existing = $existing | Where-Object { $_ } | ForEach-Object {
            try { [System.IO.Path]::GetFullPath($_) } catch { $_ }
        }
        
        # Normalize paths and find missing exclusions
        $missing = @()
        foreach ($path in $Paths) {
            try {
                $normalized = [System.IO.Path]::GetFullPath($path)
            } catch {
                continue  # Skip paths with unsupported format
            }
            
            # Security: Ensure path is within safe boundaries
            $isSafe = $false
            foreach ($prefix in $safePrefixes) {
                if ($normalized -like "$prefix*") {
                    $isSafe = $true
                    break
                }
            }
            
            if (-not $isSafe) {
                Write-Warn "Security: Refusing to exclude path outside safe boundaries: $normalized"
                continue
            }
            
            # Info: Warn if path doesn't exist yet (but still process it)
            if (-not (Test-Path $path -ErrorAction SilentlyContinue)) {
                Write-Verbose "Path does not exist yet: $path (will be excluded when created)"
            }
            
            # Check if path is already excluded (or is a child of an excluded path)
            $alreadyExcluded = $false
            foreach ($excluded in $existing) {
                if ($normalized -like "$excluded*") {
                    $alreadyExcluded = $true
                    break
                }
            }
            
            if (-not $alreadyExcluded) {
                $missing += $normalized
            }
        }
        
        return @{
            DefenderEnabled = $true
            MissingPaths = $missing
            ExistingPaths = $existing
        }
    } catch {
        return @{ 
            DefenderEnabled = $false
            Error = $_.Exception.Message
        }
    }
}

function Test-IsDefenderEnabled {
    <#
    .SYNOPSIS
        Quick boolean check if Defender real-time protection is enabled
    .OUTPUTS
        Boolean - $true if enabled, $false otherwise
    #>
    try {
        $mpModule = Get-Module -ListAvailable -Name Defender -ErrorAction SilentlyContinue
        if (-not $mpModule) {
            return $false
        }
        
        $status = Get-MpComputerStatus -ErrorAction Stop
        return $status.RealTimeProtectionEnabled
    } catch {
        # If we can't check, assume disabled (fail-safe)
        return $false
    }
}

function Add-DefenderExclusions {
    <#
    .SYNOPSIS
        Add Windows Defender exclusions for specified paths
    .PARAMETER Paths
        Array of paths to exclude
    .OUTPUTS
        Hashtable with Added and Failed arrays
    #>
    param([string[]]$Paths)
    
    $added = @()
    $failed = @()
    
    foreach ($path in $Paths) {
        try {
            try {
                $normalized = [System.IO.Path]::GetFullPath($path)
            } catch {
                $normalized = $path  # Use raw path if normalization fails
            }
            Add-MpPreference -ExclusionPath $normalized -ErrorAction Stop
            $added += $normalized
        } catch {
            $failed += @{ 
                Path = $path
                Error = $_.Exception.Message
            }
        }
    }
    
    return @{ 
        Added = $added
        Failed = $failed
    }
}

# ============================================================
# Banner
# ============================================================

Clear-Host
Write-Host ""
$hex = [char]0x2B22  # filled hexagon
$hexDim = [char]0x2B21  # outline hexagon
$banner = ""
for ($i = 0; $i -lt 13; $i++) {
    if ($i % 2 -eq 0) { $banner += $hex } else { $banner += $hexDim }
}
Write-Color -Text $banner -Color Yellow
Write-Host ""
Write-Color -Text "          A D E N   H I V E" -Color White
Write-Host ""
Write-Color -Text $banner -Color Yellow
Write-Host ""
Write-Color -Text "     Goal-driven AI agent framework" -Color DarkGray
Write-Host ""
Write-Host "This wizard will help you set up everything you need"
Write-Host "to build and run goal-driven AI agents."
Write-Host ""

if (-not (Prompt-YesNo "Ready to begin?")) {
    Write-Host ""
    Write-Host "No problem! Run this script again when you're ready."
    exit 0
}
Write-Host ""

# ============================================================
# Step 1: Check Python
# ============================================================

Write-Step -Number "1" -Text "Step 1: Checking Python..."

# On Windows "python3.x" aliases don't exist; prefer "python" then "python3"
$PythonCmd = $null
foreach ($candidate in @("python", "python3", "python3.13", "python3.12", "python3.11")) {
    try {
        $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver) {
            $parts = $ver.Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -eq 3 -and $minor -ge 11) {
                $PythonCmd = $candidate
                break
            }
        }
    } catch {
        # candidate not found, continue
    }
}

if (-not $PythonCmd) {
    Write-Color -Text "Python 3.11+ is not installed or not on PATH." -Color Red
    Write-Host ""
    Write-Host "Please install Python 3.11+ from https://python.org"
    Write-Host "  - Make sure to check 'Add Python to PATH' during installation"
    Write-Host "Then run this script again."
    exit 1
}

$PythonVersion = & $PythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $PythonVersion ($PythonCmd)"
Write-Host ""

# ============================================================
# Check / install uv
# ============================================================

$uvInfo = Get-WorkingUvInfo

# If uv not in PATH, check if it exists in default location
if (-not $uvInfo) {
    $uvDir = Join-Path $env:USERPROFILE ".local\bin"
    $uvExePath = Join-Path $uvDir "uv.exe"

    if (Test-Path $uvExePath) {
        Write-Host "  uv found at $uvExePath, updating PATH..." -ForegroundColor Yellow

        # Add to User PATH
        $currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        if (-not $currentUserPath.Contains($uvDir)) {
            $newUserPath = $currentUserPath + ";" + $uvDir
            [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
        }

        # Refresh PATH for current session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $uvInfo = Get-WorkingUvInfo

        if ($uvInfo) {
            Write-Ok "uv is now in PATH"
        }
    }
}

# If still not found, install it
if (-not $uvInfo) {
    Write-Warn "uv not found. Installing..."
    try {
        # Official uv installer for Windows
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

        # Ensure uv directory is in User PATH for future sessions
        $uvDir = Join-Path $env:USERPROFILE ".local\bin"
        $currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        if (-not $currentUserPath.Contains($uvDir)) {
            $newUserPath = $currentUserPath + ";" + $uvDir
            [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
            Write-Host "  Added $uvDir to User PATH" -ForegroundColor Green
        }

        # Refresh PATH for current session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $uvInfo = Get-WorkingUvInfo
    } catch {
        Write-Color -Text "Error: uv installation failed" -Color Red
        Write-Host "Please install uv manually from https://astral.sh/uv/"
        exit 1
    }
    if (-not $uvInfo) {
        Write-Color -Text "Error: uv not found after installation" -Color Red
        Write-Host "Please close and reopen PowerShell, then run this script again."
        Write-Host "Or install uv manually from https://astral.sh/uv/"
        exit 1
    }
    Write-Ok "uv installed successfully"
}

$UvCmd = $uvInfo.Path
Write-Ok "uv detected: $($uvInfo.Version)"
Write-Host ""

# Check for Node.js (needed for frontend dashboard)
function Install-NodeViaFnm {
    <#
    .SYNOPSIS
        Install Node.js 20 via fnm (Fast Node Manager) - mirrors nvm approach in quickstart.sh
    #>
    $fnmCmd = Get-Command fnm -ErrorAction SilentlyContinue
    if (-not $fnmCmd) {
        $fnmDir = Join-Path $env:LOCALAPPDATA "fnm"
        $fnmExe = Join-Path $fnmDir "fnm.exe"
        if (-not (Test-Path $fnmExe)) {
            try {
                Write-Host "    Downloading fnm (Fast Node Manager)..." -ForegroundColor DarkGray
                $zipUrl = "https://github.com/Schniz/fnm/releases/latest/download/fnm-windows.zip"
                $zipPath = Join-Path $env:TEMP "fnm-install.zip"
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -ErrorAction Stop
                if (-not (Test-Path $fnmDir)) { New-Item -ItemType Directory -Path $fnmDir -Force | Out-Null }
                Expand-Archive -Path $zipPath -DestinationPath $fnmDir -Force
                Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            } catch {
                Write-Fail "fnm download failed"
                Write-Host "    Install Node.js 20+ manually from https://nodejs.org" -ForegroundColor DarkGray
                return $false
            }
        }
        if (Test-Path (Join-Path $fnmDir "fnm.exe")) {
            $env:PATH = "$fnmDir;$env:PATH"
        } else {
            Write-Fail "fnm binary not found after download"
            Write-Host "    Install Node.js 20+ manually from https://nodejs.org" -ForegroundColor DarkGray
            return $false
        }
    }

    try {
        $null = & fnm install 20 2>&1
        if ($LASTEXITCODE -ne 0) { throw "fnm install 20 exited with code $LASTEXITCODE" }
        & fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression
        $null = & fnm use 20 2>&1
        $testNode = Get-Command node -ErrorAction SilentlyContinue
        if ($testNode) {
            $ver = & node --version 2>$null
            Write-Ok "Node.js $ver installed via fnm"
            return $true
        }
        throw "node not found after fnm install"
    } catch {
        Write-Fail "Node.js installation failed"
        Write-Host "    Install manually from https://nodejs.org" -ForegroundColor DarkGray
        return $false
    }
}

$NodeAvailable = $false
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeVersion = & node --version 2>$null
    if ($nodeVersion -match '^v(\d+)') {
        $nodeMajor = [int]$Matches[1]
        if ($nodeMajor -ge 20) {
            Write-Ok "Node.js $nodeVersion"
            $NodeAvailable = $true
        } else {
            Write-Warn "Node.js $nodeVersion found (20+ required for frontend dashboard)"
            Write-Host "    Installing Node.js 20 via fnm..." -ForegroundColor Yellow
            $NodeAvailable = Install-NodeViaFnm
        }
    }
} else {
    Write-Warn "Node.js not found. Installing via fnm..."
    $NodeAvailable = Install-NodeViaFnm
}
Write-Host ""

# ============================================================
# Step 2: Install Python Packages
# ============================================================

Write-Step -Number "2" -Text "Step 2: Installing packages..."
Write-Color -Text "This may take a minute..." -Color DarkGray
Write-Host ""

Push-Location $ScriptDir
try {
    if (Test-Path "pyproject.toml") {
        Write-Host "  Installing workspace packages... " -NoNewline

        $syncOutput = & $UvCmd sync 2>&1
        $syncExitCode = $LASTEXITCODE

        if ($syncExitCode -eq 0) {
            Write-Ok "workspace packages installed"
        } else {
            Write-Fail "workspace installation failed"
            Write-Host $syncOutput
            exit 1
        }
    } else {
        Write-Fail "failed (no root pyproject.toml)"
        exit 1
    }

    # Keep browser setup scoped to detecting the system browser used by GCU.
    Write-Host "  Checking for Chrome/Edge browser... " -NoNewline
    $null = & $UvCmd run python -c "from gcu.browser.chrome_finder import find_chrome; assert find_chrome()" 2>&1
    $chromeCheckExit = $LASTEXITCODE
    if ($chromeCheckExit -eq 0) {
        Write-Ok "ok"
    } else {
        Write-Warn "not found - install Chrome or Edge for browser tools"
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Ok "All packages installed"
Write-Host ""

# Build frontend (if Node.js is available)
$FrontendBuilt = $false
$FrontendDistReady = Test-FrontendDistReady -RootDir $ScriptDir
if ($NodeAvailable) {
    Write-Step -Number "" -Text "Building frontend dashboard..."
    Write-Host ""
    $frontendDir = Join-Path $ScriptDir "core\frontend"
    if (Test-Path (Join-Path $frontendDir "package.json")) {
        Write-Host "  Installing npm packages... " -NoNewline
        Push-Location $frontendDir
        try {
            $installOutput = npm install --no-fund --no-audit 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "ok"
                # Clean stale tsbuildinfo cache — tsc -b incremental builds fail
                # silently when these are out of sync with source files
                Get-ChildItem -Path $frontendDir -Filter "tsconfig*.tsbuildinfo" -ErrorAction SilentlyContinue | Remove-Item -Force
                Write-Host "  Building frontend... " -NoNewline
                $buildOutput = npm run build 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Ok "ok"
                    Write-Ok "Frontend built -> core/frontend/dist/"
                    $FrontendBuilt = $true
                    $FrontendDistReady = $true
                } else {
                    Write-Warn "build failed"
                    Write-CommandFailureDetails -Output $buildOutput -Tail 60
                    Write-Host "    Quickstart will still try '.\hive.ps1 open' if Hive can rebuild the dashboard." -ForegroundColor DarkGray
                }
            } else {
                Write-Warn "npm install failed"
                Write-CommandFailureDetails -Output $installOutput -Tail 60
            }
        } finally {
            Pop-Location
        }
    }
    $FrontendDistReady = Test-FrontendDistReady -RootDir $ScriptDir
    Write-Host ""
}

# ============================================================
# Step 2.5: Windows Defender Exclusions (Optional Performance Boost)
# ============================================================

Write-Step -Number "2.5" -Text "Step 2.5: Windows Defender exclusions (optional)"
Write-Color -Text "Excluding project paths from real-time scanning can improve performance:" -Color DarkGray
Write-Host "  - uv sync: ~40% faster"
Write-Host "  - Agent startup: ~30% faster"
Write-Host ""

# Define paths to exclude
$pathsToExclude = @(
    $ScriptDir,                                      # Project directory
    (Join-Path $ScriptDir ".venv"),                  # Virtual environment
    (Join-Path $env:LOCALAPPDATA "uv")               # uv cache
)

# Check current state
$checkResult = Test-DefenderExclusions -Paths $pathsToExclude

if (-not $checkResult.DefenderEnabled) {
    if ($checkResult.Error) {
        Write-Warn "Cannot check Defender status: $($checkResult.Error)"
    } elseif ($checkResult.Reason) {
        Write-Warn "Skipping: $($checkResult.Reason)"
    }
    Write-Host ""
    # Continue installation without failing
} elseif ($checkResult.MissingPaths.Count -eq 0) {
    Write-Ok "All paths already excluded from Defender scanning"
    Write-Host ""
} else {
    # Show what will be excluded
    Write-Host "Paths to exclude:"
    foreach ($path in $checkResult.MissingPaths) {
        Write-Color -Text "  - $path" -Color Cyan
    }
    Write-Host ""
    
    # Security notice
    Write-Color -Text "⚠️  Security Trade-off:" -Color Yellow
    Write-Host "Adding exclusions improves performance but reduces real-time protection."
    Write-Host "Only proceed if you trust this project and its dependencies."
    Write-Host ""
    
    # Prompt for consent (default = No for security)
    if (Prompt-YesNo "Add these Defender exclusions?" "n") {
        Write-Host ""
        
        # Check admin privileges
        if (-not (Test-IsAdmin)) {
            Write-Warn "Administrator privileges required to modify Defender settings."
            Write-Host ""
            Write-Color -Text "To add exclusions manually, run PowerShell as Administrator and paste:" -Color White
            Write-Host ""
            
            foreach ($path in $checkResult.MissingPaths) {
                $cmd = "Add-MpPreference -ExclusionPath '$path'"
                Write-Color -Text "  $cmd" -Color Cyan
            }
            
            Write-Host ""
            Write-Color -Text "Or copy all commands to clipboard? [y/N]" -Color White
            $copyChoice = Read-Host
            if ($copyChoice -match "^[Yy]") {
                $commands = ($checkResult.MissingPaths | ForEach-Object { 
                    "Add-MpPreference -ExclusionPath '$_'" 
                }) -join "`r`n"
                
                try {
                    Set-Clipboard -Value $commands
                    Write-Ok "Commands copied to clipboard"
                } catch {
                    Write-Warn "Could not copy to clipboard. Please copy manually."
                }
            }
        } else {
            # Re-check Defender status before adding (could have changed during prompt)
            if (-not (Test-IsDefenderEnabled)) {
                Write-Warn "Defender status changed during setup (now disabled)."
                Write-Host "Skipping exclusions - they would have no effect."
                Write-Host ""
            } else {
                # Add exclusions
                Write-Host "  Adding exclusions... " -NoNewline
                
                # Re-check paths in case something changed
                $freshCheck = Test-DefenderExclusions -Paths $pathsToExclude
                if ($freshCheck.MissingPaths.Count -eq 0) {
                    Write-Ok "already added"
                    Write-Host "  (Exclusions were added by another process)"
                } else {
                    $result = Add-DefenderExclusions -Paths $freshCheck.MissingPaths
                    
                    if ($result.Added.Count -gt 0) {
                        Write-Ok "done"
                        foreach ($path in $result.Added) {
                            Write-Ok "Excluded: $path"
                        }
                    }
                    
                    if ($result.Failed.Count -gt 0) {
                        Write-Host ""
                        
                        # Calculate and show success rate
                        $totalPaths = $result.Added.Count + $result.Failed.Count
                        if ($totalPaths -gt 0) {
                            $successRate = [math]::Round(($result.Added.Count / $totalPaths) * 100)
                            Write-Warn "Only $($result.Added.Count)/$totalPaths exclusions added ($successRate%)"
                            Write-Host "Performance benefit may be reduced."
                            Write-Host ""
                        }
                        
                        Write-Warn "Failed exclusions:"
                        foreach ($failure in $result.Failed) {
                            Write-Warn "  $($failure.Path): $($failure.Error)"
                        }
                    }
                }
            }
        }
    } else {
        Write-Host ""
        Write-Warn "Skipped. You can add exclusions later for better performance."
        Write-Host "  Run this script again or add them manually via Windows Security."
    }
    Write-Host ""
}


# ============================================================
# Step 3: Verify Python Imports
# ============================================================

Write-Step -Number "3" -Text "Step 3: Verifying Python imports..."

$importErrors = 0

$imports = @(
    @{ Module = "framework";                        Label = "framework";    Required = $true },
    @{ Module = "aden_tools";                       Label = "aden_tools";   Required = $true },
    @{ Module = "litellm";                          Label = "litellm";      Required = $false }
)

# Batch check all imports in single process (reduces subprocess spawning overhead)
$modulesToCheck = @("framework", "aden_tools", "litellm")

try {
    $checkOutput = & $UvCmd run python scripts/check_requirements.py @modulesToCheck 2>&1 | Out-String
    $resultJson = $null
    
    # Try to parse JSON result
    try {
        $resultJson = $checkOutput | ConvertFrom-Json
    } catch {
        Write-Fail "Failed to parse import check results"
        Write-Host $checkOutput
        exit 1
    }
    
    # Display results for each module
    foreach ($imp in $imports) {
        Write-Host "  $($imp.Label)... " -NoNewline
        $status = $resultJson.$($imp.Module)
        
        if ($status -eq "ok") {
            Write-Ok "ok"
        } elseif ($imp.Required) {
            Write-Fail "failed"
            if ($status) {
                Write-Host "    $status" -ForegroundColor Red
            }
            $importErrors++
        } else {
            Write-Warn "issues (may be OK)"
            if ($status -and $status -ne "ok") {
                Write-Host "    $status" -ForegroundColor Yellow
            }
        }
    }
} catch {
    Write-Fail "Import check failed: $($_.Exception.Message)"
    exit 1
}

if ($importErrors -gt 0) {
    Write-Host ""
    Write-Color -Text "Error: $importErrors import(s) failed. Please check the errors above." -Color Red
    exit 1
}
Write-Host ""

# ============================================================
# Provider / model data
# ============================================================

$ProviderMap = [ordered]@{
    ANTHROPIC_API_KEY = @{ Name = "Anthropic (Claude)"; Id = "anthropic" }
    OPENAI_API_KEY    = @{ Name = "OpenAI (GPT)";       Id = "openai" }
    MINIMAX_API_KEY   = @{ Name = "MiniMax";            Id = "minimax" }
    GEMINI_API_KEY    = @{ Name = "Google Gemini";       Id = "gemini" }
    GOOGLE_API_KEY    = @{ Name = "Google AI";           Id = "google" }
    GROQ_API_KEY      = @{ Name = "Groq";               Id = "groq" }
    CEREBRAS_API_KEY  = @{ Name = "Cerebras";            Id = "cerebras" }
    OPENROUTER_API_KEY = @{ Name = "OpenRouter";          Id = "openrouter" }
    MISTRAL_API_KEY   = @{ Name = "Mistral";             Id = "mistral" }
    TOGETHER_API_KEY  = @{ Name = "Together AI";         Id = "together" }
    DEEPSEEK_API_KEY  = @{ Name = "DeepSeek";            Id = "deepseek" }
}

$DefaultModels = @{
    anthropic   = "claude-haiku-4-5-20251001"
    openai      = "gpt-5-mini"
    minimax     = "MiniMax-M2.5"
    gemini      = "gemini-3-flash-preview"
    google      = "gemini-3-flash-preview"
    groq        = "moonshotai/kimi-k2-instruct-0905"
    cerebras    = "zai-glm-4.7"
    mistral     = "mistral-large-latest"
    together    = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    deepseek    = "deepseek-chat"
}

# Model choices: array of hashtables per provider
$ModelChoices = @{
    anthropic = @(
        @{ Id = "claude-haiku-4-5-20251001";  Label = "Haiku 4.5 - Fast + cheap (recommended)"; MaxTokens = 8192;  MaxContextTokens = 180000 },
        @{ Id = "claude-sonnet-4-20250514";   Label = "Sonnet 4 - Fast + capable";              MaxTokens = 8192;  MaxContextTokens = 180000 },
        @{ Id = "claude-sonnet-4-5-20250929"; Label = "Sonnet 4.5 - Best balance";              MaxTokens = 16384; MaxContextTokens = 180000 },
        @{ Id = "claude-opus-4-6";            Label = "Opus 4.6 - Most capable";                MaxTokens = 32768; MaxContextTokens = 180000 }
    )
    openai = @(
        @{ Id = "gpt-5-mini"; Label = "GPT-5 Mini - Fast + cheap (recommended)"; MaxTokens = 16384; MaxContextTokens = 120000 },
        @{ Id = "gpt-5.2";   Label = "GPT-5.2 - Most capable";                   MaxTokens = 16384; MaxContextTokens = 120000 }
    )
    gemini = @(
        @{ Id = "gemini-3-flash-preview"; Label = "Gemini 3 Flash - Fast (recommended)"; MaxTokens = 8192; MaxContextTokens = 900000 },
        @{ Id = "gemini-3.1-pro-preview";  Label = "Gemini 3.1 Pro - Best quality";       MaxTokens = 8192; MaxContextTokens = 900000 }
    )
    groq = @(
        @{ Id = "moonshotai/kimi-k2-instruct-0905"; Label = "Kimi K2 - Best quality (recommended)"; MaxTokens = 8192; MaxContextTokens = 120000 },
        @{ Id = "openai/gpt-oss-120b";              Label = "GPT-OSS 120B - Fast reasoning";        MaxTokens = 8192; MaxContextTokens = 120000 }
    )
    cerebras = @(
        @{ Id = "zai-glm-4.7";                    Label = "ZAI-GLM 4.7 - Best quality (recommended)"; MaxTokens = 8192; MaxContextTokens = 120000 },
        @{ Id = "qwen3-235b-a22b-instruct-2507";  Label = "Qwen3 235B - Frontier reasoning";          MaxTokens = 8192; MaxContextTokens = 120000 }
    )
}

function Normalize-OpenRouterModelId {
    param([string]$ModelId)
    $normalized = if ($ModelId) { $ModelId.Trim() } else { "" }
    if ($normalized -match '(?i)^openrouter/(.+)$') {
        $normalized = $matches[1]
    }
    return $normalized
}

function Get-ModelSelection {
    param([string]$ProviderId)

    if ($ProviderId -eq "openrouter") {
        $defaultModel = ""
        if ($PrevModel -and $PrevProvider -eq $ProviderId) {
            $defaultModel = Normalize-OpenRouterModelId $PrevModel
        }
        Write-Host ""
        Write-Color -Text "Enter your OpenRouter model id:" -Color White
        Write-Color -Text "  Paste from openrouter.ai (example: x-ai/grok-4.20-beta)" -Color DarkGray
        Write-Color -Text "  If calls fail with guardrail/privacy errors: openrouter.ai/settings/privacy" -Color DarkGray
        Write-Host ""
        while ($true) {
            if ($defaultModel) {
                $rawModel = Read-Host "Model id [$defaultModel]"
                if ([string]::IsNullOrWhiteSpace($rawModel)) { $rawModel = $defaultModel }
            } else {
                $rawModel = Read-Host "Model id"
            }
            $normalizedModel = Normalize-OpenRouterModelId $rawModel
            if (-not [string]::IsNullOrWhiteSpace($normalizedModel)) {
                $openrouterKey = $null
                if ($SelectedEnvVar) {
                    $openrouterKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "Process")
                    if (-not $openrouterKey) {
                        $openrouterKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "User")
                    }
                }

                if ($openrouterKey) {
                    Write-Host "  Verifying model id... " -NoNewline
                    try {
                        $modelApiBase = if ($SelectedApiBase) { $SelectedApiBase } else { "https://openrouter.ai/api/v1" }
                        $hcResult = & uv run python (Join-Path $ScriptDir "scripts/check_llm_key.py") "openrouter" $openrouterKey $modelApiBase $normalizedModel 2>$null
                        $hcJson = $hcResult | ConvertFrom-Json
                        if ($hcJson.valid -eq $true) {
                            if ($hcJson.model) {
                                $normalizedModel = [string]$hcJson.model
                            }
                            Write-Color -Text "ok" -Color Green
                        } elseif ($hcJson.valid -eq $false) {
                            Write-Color -Text "failed" -Color Red
                            Write-Warn $hcJson.message
                            Write-Host ""
                            continue
                        } else {
                            Write-Color -Text "--" -Color Yellow
                            Write-Color -Text "  Could not verify model id (network issue). Continuing with your selection." -Color DarkGray
                        }
                    } catch {
                        Write-Color -Text "--" -Color Yellow
                        Write-Color -Text "  Could not verify model id (network issue). Continuing with your selection." -Color DarkGray
                    }
                } else {
                    Write-Color -Text "  Skipping model verification (OpenRouter key not available in current shell)." -Color DarkGray
                }

                Write-Host ""
                Write-Ok "Model: $normalizedModel"
                return @{ Model = $normalizedModel; MaxTokens = 8192; MaxContextTokens = 120000 }
            }
            Write-Color -Text "Model id cannot be empty." -Color Red
        }
    }

    $choices = $ModelChoices[$ProviderId]
    if (-not $choices -or $choices.Count -eq 0) {
        return @{ Model = $DefaultModels[$ProviderId]; MaxTokens = 8192; MaxContextTokens = 120000 }
    }
    if ($choices.Count -eq 1) {
        return @{ Model = $choices[0].Id; MaxTokens = $choices[0].MaxTokens; MaxContextTokens = $choices[0].MaxContextTokens }
    }

    # Find default index from previous model (if same provider)
    $defaultIdx = "1"
    if ($PrevModel -and $PrevProvider -eq $ProviderId) {
        for ($j = 0; $j -lt $choices.Count; $j++) {
            if ($choices[$j].Id -eq $PrevModel) {
                $defaultIdx = [string]($j + 1)
                break
            }
        }
    }

    Write-Host ""
    Write-Color -Text "Select a model:" -Color White
    Write-Host ""
    for ($i = 0; $i -lt $choices.Count; $i++) {
        Write-Color -Text "  $($i + 1)" -Color Cyan -NoNewline
        Write-Host ") $($choices[$i].Label)  " -NoNewline
        Write-Color -Text "($($choices[$i].Id))" -Color DarkGray
    }
    Write-Host ""

    while ($true) {
        $raw = Read-Host "Enter choice [$defaultIdx]"
        if ([string]::IsNullOrWhiteSpace($raw)) { $raw = $defaultIdx }
        if ($raw -match '^\d+$') {
            $num = [int]$raw
            if ($num -ge 1 -and $num -le $choices.Count) {
                $sel = $choices[$num - 1]
                Write-Host ""
                Write-Ok "Model: $($sel.Id)"
                return @{ Model = $sel.Id; MaxTokens = $sel.MaxTokens; MaxContextTokens = $sel.MaxContextTokens }
            }
        }
        Write-Color -Text "Invalid choice. Please enter 1-$($choices.Count)" -Color Red
    }
}

# ============================================================
# Configure LLM API Key
# ============================================================

Write-Step -Number "" -Text "Configuring LLM provider..."

# Hive config paths
$HiveConfigDir  = Join-Path $env:USERPROFILE ".hive"
$HiveConfigFile = Join-Path $HiveConfigDir "configuration.json"

$SelectedProviderId      = ""
$SelectedEnvVar          = ""
$SelectedModel           = ""
$SelectedMaxTokens       = 8192
$SelectedMaxContextTokens = 120000
$SelectedApiBase         = ""
$SubscriptionMode        = ""

# ── Credential detection (silent — just set flags) ───────────
$ClaudeCredDetected = $false
$claudeCredPath = Join-Path $env:USERPROFILE ".claude\.credentials.json"
if (Test-Path $claudeCredPath) { $ClaudeCredDetected = $true }

$CodexCredDetected = $false
$codexAuthPath = Join-Path $env:USERPROFILE ".codex\auth.json"
if (Test-Path $codexAuthPath) { $CodexCredDetected = $true }

$MinimaxCredDetected = $false
$minimaxKey = [System.Environment]::GetEnvironmentVariable("MINIMAX_API_KEY", "User")
if (-not $minimaxKey) { $minimaxKey = $env:MINIMAX_API_KEY }
if ($minimaxKey) { $MinimaxCredDetected = $true }

$ZaiCredDetected = $false
$zaiKey = [System.Environment]::GetEnvironmentVariable("ZAI_API_KEY", "User")
if (-not $zaiKey) { $zaiKey = $env:ZAI_API_KEY }
if ($zaiKey) { $ZaiCredDetected = $true }

$KimiCredDetected = $false
$kimiConfigPath = Join-Path $env:USERPROFILE ".kimi\config.toml"
if (Test-Path $kimiConfigPath) { $KimiCredDetected = $true }
$kimiKey = [System.Environment]::GetEnvironmentVariable("KIMI_API_KEY", "User")
if (-not $kimiKey) { $kimiKey = $env:KIMI_API_KEY }
if ($kimiKey) { $KimiCredDetected = $true }

$HiveCredDetected = $false
$hiveKey = [System.Environment]::GetEnvironmentVariable("HIVE_API_KEY", "User")
if (-not $hiveKey) { $hiveKey = $env:HIVE_API_KEY }
if ($hiveKey) { $HiveCredDetected = $true }

$AntigravityCredDetected = $false
$antigravityAuthPath = Join-Path $env:USERPROFILE ".hive\antigravity-accounts.json"
if (Test-Path $antigravityAuthPath) { $AntigravityCredDetected = $true }

# Detect API key providers
$ProviderMenuEnvVars  = @("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY")
$ProviderMenuNames    = @("Anthropic (Claude) - Recommended", "OpenAI (GPT)", "Google Gemini - Free tier available", "Groq - Fast, free tier", "Cerebras - Fast, free tier", "OpenRouter - Bring any OpenRouter model")
$ProviderMenuIds      = @("anthropic", "openai", "gemini", "groq", "cerebras", "openrouter")
$ProviderMenuUrls     = @(
    "https://console.anthropic.com/settings/keys",
    "https://platform.openai.com/api-keys",
    "https://aistudio.google.com/apikey",
    "https://console.groq.com/keys",
    "https://cloud.cerebras.ai/",
    "https://openrouter.ai/keys"
)

$OllamaDetected = $false
try {
    $null = & ollama list 2>$null
    if ($LASTEXITCODE -eq 0) { $OllamaDetected = $true }
} catch { }

# ── Read previous configuration (if any) ──────────────────────
$PrevProvider = ""
$PrevModel = ""
$PrevEnvVar = ""
$PrevSubMode = ""
if (Test-Path $HiveConfigFile) {
    try {
        $prevConfig = Get-Content -Path $HiveConfigFile -Raw | ConvertFrom-Json
        $prevLlm = $prevConfig.llm
        if ($prevLlm) {
            $PrevProvider = if ($prevLlm.provider) { $prevLlm.provider } else { "" }
            $PrevModel = if ($prevLlm.model) { $prevLlm.model } else { "" }
            $PrevEnvVar = if ($prevLlm.api_key_env_var) { $prevLlm.api_key_env_var } else { "" }
            if ($prevLlm.use_claude_code_subscription) { $PrevSubMode = "claude_code" }
            elseif ($prevLlm.use_codex_subscription) { $PrevSubMode = "codex" }
            elseif ($prevLlm.use_kimi_code_subscription) { $PrevSubMode = "kimi_code" }
            elseif ($prevLlm.use_antigravity_subscription) { $PrevSubMode = "antigravity" }
            elseif ($prevLlm.api_base -and $prevLlm.api_base -like "*api.z.ai*") { $PrevSubMode = "zai_code" }
            elseif ($prevLlm.provider -eq "minimax" -or ($prevLlm.api_base -and $prevLlm.api_base -like "*api.minimax.io*")) { $PrevSubMode = "minimax_code" }
            elseif ($prevLlm.api_base -and $prevLlm.api_base -like "*api.kimi.com*") { $PrevSubMode = "kimi_code" }
            elseif ($prevLlm.provider -eq "hive" -or ($prevLlm.api_base -and $prevLlm.api_base -like "*adenhq.com*")) { $PrevSubMode = "hive_llm" }
        }
    } catch { }
}

# Compute default menu number (only if credential is still valid)
$DefaultChoice = ""
if ($PrevSubMode -or $PrevProvider) {
    $prevCredValid = $false
    switch ($PrevSubMode) {
        "claude_code" { if ($ClaudeCredDetected) { $prevCredValid = $true } }
        "zai_code"    { if ($ZaiCredDetected)    { $prevCredValid = $true } }
        "codex"       { if ($CodexCredDetected)  { $prevCredValid = $true } }
        "minimax_code" { if ($MinimaxCredDetected) { $prevCredValid = $true } }
        "kimi_code"   { if ($KimiCredDetected)   { $prevCredValid = $true } }
        "hive_llm"    { if ($HiveCredDetected)   { $prevCredValid = $true } }
        "antigravity" { if ($AntigravityCredDetected) { $prevCredValid = $true } }
        default {
            if ($PrevProvider -eq "ollama") {
                $prevCredValid = $true
            } elseif ($PrevEnvVar) {
                $envVal = [System.Environment]::GetEnvironmentVariable($PrevEnvVar, "Process")
                if (-not $envVal) { $envVal = [System.Environment]::GetEnvironmentVariable($PrevEnvVar, "User") }
                if ($envVal) { $prevCredValid = $true }
            }
        }
    }
    if ($prevCredValid) {
        switch ($PrevSubMode) {
            "claude_code" { $DefaultChoice = "1" }
            "zai_code"    { $DefaultChoice = "2" }
            "codex"       { $DefaultChoice = "3" }
            "minimax_code" { $DefaultChoice = "4" }
            "kimi_code"   { $DefaultChoice = "5" }
            "hive_llm"    { $DefaultChoice = "6" }
            "antigravity" { $DefaultChoice = "7" }
        }
        if (-not $DefaultChoice) {
            switch ($PrevProvider) {
                "anthropic" { $DefaultChoice = "8" }
                "openai"    { $DefaultChoice = "9" }
                "gemini"    { $DefaultChoice = "10" }
                "groq"      { $DefaultChoice = "11" }
                "cerebras"  { $DefaultChoice = "12" }
                "openrouter" { $DefaultChoice = "13" }
                "ollama"     { $DefaultChoice = "14" }
                "minimax"   { $DefaultChoice = "4" }
                "kimi"      { $DefaultChoice = "5" }
                "hive"      { $DefaultChoice = "6" }
            }
        }
    }
}

$HiveGatewayAvailability = Test-HiveGatewayAvailability -From "quickstart"

# ── Show unified provider selection menu ─────────────────────
Write-Color -Text "Select your default LLM provider:" -Color White
Write-Host ""
switch ($HiveGatewayAvailability) {
    "available" { Write-Ok "Hive LLM availability check: available" }
    "unavailable" { Write-Warn "Hive LLM availability check: currently unavailable" }
    default { Write-Warn "Hive LLM availability check: could not verify" }
}
Write-Host ""
Write-Color -Text "  Subscription modes (no API key purchase needed):" -Color Cyan

# 1) Claude Code
Write-Host "  " -NoNewline
Write-Color -Text "1" -Color Cyan -NoNewline
Write-Host ") Claude Code Subscription  " -NoNewline
Write-Color -Text "(use your Claude Max/Pro plan)" -Color DarkGray -NoNewline
if ($ClaudeCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

# 2) ZAI Code
Write-Host "  " -NoNewline
Write-Color -Text "2" -Color Cyan -NoNewline
Write-Host ") ZAI Code Subscription     " -NoNewline
Write-Color -Text "(use your ZAI Code plan)" -Color DarkGray -NoNewline
if ($ZaiCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

# 3) Codex
Write-Host "  " -NoNewline
Write-Color -Text "3" -Color Cyan -NoNewline
Write-Host ") OpenAI Codex Subscription  " -NoNewline
Write-Color -Text "(use your Codex/ChatGPT Plus plan)" -Color DarkGray -NoNewline
if ($CodexCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

# 4) MiniMax Coding Key
Write-Host "  " -NoNewline
Write-Color -Text "4" -Color Cyan -NoNewline
Write-Host ") MiniMax Coding Key         " -NoNewline
Write-Color -Text "(use your MiniMax coding key)" -Color DarkGray -NoNewline
if ($MinimaxCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

# 5) Kimi Code
Write-Host "  " -NoNewline
Write-Color -Text "5" -Color Cyan -NoNewline
Write-Host ") Kimi Code Subscription     " -NoNewline
Write-Color -Text "(use your Kimi Code plan)" -Color DarkGray -NoNewline
if ($KimiCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

# 6) Hive LLM
Write-Host "  " -NoNewline
Write-Color -Text "6" -Color Cyan -NoNewline
Write-Host ") Hive LLM                   " -NoNewline
Write-Color -Text "(use your Hive API key)" -Color DarkGray -NoNewline
switch ($HiveGatewayAvailability) {
    "available" { Write-Color -Text "  (available)" -Color Green -NoNewline }
    "unavailable" { Write-Color -Text "  (unavailable)" -Color Yellow -NoNewline }
    default { Write-Color -Text "  (status unknown)" -Color Yellow -NoNewline }
}
if ($HiveCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

# 7) Antigravity
Write-Host "  " -NoNewline
Write-Color -Text "7" -Color Cyan -NoNewline
Write-Host ") Antigravity Subscription  " -NoNewline
Write-Color -Text "(use your Google/Gemini plan)" -Color DarkGray -NoNewline
if ($AntigravityCredDetected) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }

Write-Host ""
Write-Color -Text "  API key providers:" -Color Cyan

# 8-13) API key providers
for ($idx = 0; $idx -lt $ProviderMenuEnvVars.Count; $idx++) {
    $num = $idx + 8
    $envVal = [System.Environment]::GetEnvironmentVariable($ProviderMenuEnvVars[$idx], "Process")
    if (-not $envVal) { $envVal = [System.Environment]::GetEnvironmentVariable($ProviderMenuEnvVars[$idx], "User") }
    Write-Host "  " -NoNewline
    Write-Color -Text "$num" -Color Cyan -NoNewline
    Write-Host ") $($ProviderMenuNames[$idx])" -NoNewline
    if ($envVal) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }
}

# 14) Local (Ollama) - no API key needed
Write-Host "  " -NoNewline
Write-Color -Text "14" -Color Cyan -NoNewline
if ($OllamaDetected) {
    Write-Host ") Local (Ollama) - No API key needed  " -NoNewline
    Write-Color -Text "(ollama detected)" -Color Green
} else {
    Write-Host ") Local (Ollama) - No API key needed"
}

$SkipChoice = 8 + $ProviderMenuEnvVars.Count + 1
Write-Host "  " -NoNewline
Write-Color -Text "$SkipChoice" -Color Cyan -NoNewline
Write-Host ") Skip for now"
Write-Host ""

if ($DefaultChoice) {
    Write-Color -Text "  Previously configured: $PrevProvider/$PrevModel. Press Enter to keep." -Color DarkGray
    Write-Host ""
}

while ($true) {
    if ($DefaultChoice) {
        $raw = Read-Host "Enter choice (1-$SkipChoice) [$DefaultChoice]"
        if ([string]::IsNullOrWhiteSpace($raw)) { $raw = $DefaultChoice }
    } else {
        $raw = Read-Host "Enter choice (1-$SkipChoice)"
    }
    if ($raw -match '^\d+$') {
        $num = [int]$raw
        if ($num -ge 1 -and $num -le $SkipChoice) { break }
    }
    Write-Color -Text "Invalid choice. Please enter 1-$SkipChoice" -Color Red
}

switch ($num) {
    1 {
        # Claude Code Subscription
        if (-not $ClaudeCredDetected) {
            Write-Host ""
            Write-Warn "~/.claude/.credentials.json not found."
            Write-Host "  Run 'claude' first to authenticate with your Claude subscription,"
            Write-Host "  then run this quickstart again."
            Write-Host ""
            exit 1
        }
        $SubscriptionMode        = "claude_code"
        $SelectedProviderId      = "anthropic"
        $SelectedModel           = "claude-opus-4-6"
        $SelectedMaxTokens       = 32768
        $SelectedMaxContextTokens = 180000
        Write-Host ""
        Write-Ok "Using Claude Code subscription"
    }
    2 {
        # ZAI Code Subscription
        $SubscriptionMode        = "zai_code"
        $SelectedProviderId      = "openai"
        $SelectedEnvVar          = "ZAI_API_KEY"
        $SelectedModel           = "glm-5"
        $SelectedMaxTokens       = 32768
        $SelectedMaxContextTokens = 120000
        Write-Host ""
        Write-Ok "Using ZAI Code subscription"
        Write-Color -Text "  Model: glm-5 | API: api.z.ai" -Color DarkGray
    }
    3 {
        # OpenAI Codex Subscription
        if (-not $CodexCredDetected) {
            Write-Host ""
            Write-Warn "Codex credentials not found. Starting OAuth login..."
            Write-Host ""
            try {
                & $UvCmd run python (Join-Path $ScriptDir "core\codex_oauth.py") 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $CodexCredDetected = $true
                } else {
                    Write-Host ""
                    Write-Fail "OAuth login failed or was cancelled."
                    Write-Host ""
                    Write-Host "  Or run 'codex' to authenticate, then run this quickstart again."
                    Write-Host ""
                    $SelectedProviderId = ""
                }
            } catch {
                Write-Fail "OAuth login failed: $($_.Exception.Message)"
                $SelectedProviderId = ""
            }
        }
        if ($CodexCredDetected) {
            $SubscriptionMode        = "codex"
            $SelectedProviderId      = "openai"
            $SelectedModel           = "gpt-5.3-codex"
            $SelectedMaxTokens       = 16384
            $SelectedMaxContextTokens = 120000
            Write-Host ""
            Write-Ok "Using OpenAI Codex subscription"
        }
    }
    4 {
        # MiniMax Coding Key
        $SubscriptionMode        = "minimax_code"
        $SelectedProviderId      = "minimax"
        $SelectedEnvVar          = "MINIMAX_API_KEY"
        $SelectedModel           = "MiniMax-M2.5"
        $SelectedMaxTokens       = 32768
        $SelectedMaxContextTokens = 900000
        $SelectedApiBase         = "https://api.minimax.io/v1"
        Write-Host ""
        Write-Ok "Using MiniMax coding key"
        Write-Color -Text "  Model: MiniMax-M2.5 | API: api.minimax.io" -Color DarkGray
    }
    5 {
        # Kimi Code Subscription
        $SubscriptionMode        = "kimi_code"
        $SelectedProviderId      = "kimi"
        $SelectedEnvVar          = "KIMI_API_KEY"
        $SelectedModel           = "kimi-k2.5"
        $SelectedMaxTokens       = 32768
        $SelectedMaxContextTokens = 120000
        Write-Host ""
        Write-Ok "Using Kimi Code subscription"
        Write-Color -Text "  Model: kimi-k2.5 | API: api.kimi.com/coding" -Color DarkGray
    }
    6 {
        # Hive LLM
        $SubscriptionMode        = "hive_llm"
        $SelectedProviderId      = "hive"
        $SelectedEnvVar          = "HIVE_API_KEY"
        $SelectedMaxTokens       = 32768
        $SelectedMaxContextTokens = 120000
        Write-Host ""
        Write-Ok "Using Hive LLM"
        Write-Host ""
        Write-Host "  Select a model:"
        Write-Host "  " -NoNewline; Write-Color -Text "1)" -Color Cyan -NoNewline; Write-Host " queen              " -NoNewline; Write-Color -Text "(default - Hive flagship)" -Color DarkGray
        Write-Host "  " -NoNewline; Write-Color -Text "2)" -Color Cyan -NoNewline; Write-Host " kimi-2.5"
        Write-Host "  " -NoNewline; Write-Color -Text "3)" -Color Cyan -NoNewline; Write-Host " GLM-5"
        Write-Host ""
        $hiveModelChoice = Read-Host "  Enter model choice (1-3) [1]"
        if (-not $hiveModelChoice) { $hiveModelChoice = "1" }
        switch ($hiveModelChoice) {
            "2" { $SelectedModel = "kimi-2.5" }
            "3" { $SelectedModel = "GLM-5" }
            default { $SelectedModel = "queen" }
        }
        Write-Color -Text "  Model: $SelectedModel | API: $HiveLlmEndpoint" -Color DarkGray
    }
    7 {
        # Antigravity Subscription
        if (-not $AntigravityCredDetected) {
            Write-Host ""
            Write-Color -Text "  Setting up Antigravity authentication..." -Color Cyan
            Write-Host ""
            Write-Warn "A browser window will open for Google OAuth."
            Write-Host "  Sign in with your Google account that has Antigravity access."
            Write-Host ""
            try {
                $null = & $UvCmd run python (Join-Path $ScriptDir "core\antigravity_auth.py") auth account add 2>&1
                if ($LASTEXITCODE -eq 0 -and (Test-Path $antigravityAuthPath)) {
                    $AntigravityCredDetected = $true
                }
            } catch {
                $AntigravityCredDetected = $false
            }

            if (-not $AntigravityCredDetected) {
                Write-Host ""
                Write-Fail "Authentication failed or was cancelled."
                Write-Host ""
                $SelectedProviderId = ""
            }
        }

        if ($AntigravityCredDetected) {
            $SubscriptionMode        = "antigravity"
            $SelectedProviderId      = "openai"
            $SelectedModel           = "gemini-3-flash"
            $SelectedMaxTokens       = 32768
            $SelectedMaxContextTokens = 1000000
            Write-Host ""
            Write-Warn "Using Antigravity can technically cause your account suspension. Please use at your own risk."
            Write-Host ""
            Write-Ok "Using Antigravity subscription"
            Write-Color -Text "  Model: gemini-3-flash | Direct OAuth (no proxy required)" -Color DarkGray
        }
    }
    { $_ -ge 8 -and $_ -le 13 } {
        # API key providers
        $provIdx = $num - 8
        $SelectedEnvVar     = $ProviderMenuEnvVars[$provIdx]
        $SelectedProviderId = $ProviderMenuIds[$provIdx]
        $providerName       = $ProviderMenuNames[$provIdx] -replace ' - .*', ''  # strip description
        $signupUrl          = $ProviderMenuUrls[$provIdx]
        if ($SelectedProviderId -eq "openrouter") {
            $SelectedApiBase = "https://openrouter.ai/api/v1"
        } else {
            $SelectedApiBase = ""
        }

        # Prompt for key (allow replacement if already set) with verification + retry
        while ($true) {
            $existingKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "User")
            if (-not $existingKey) { $existingKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "Process") }

            if ($existingKey) {
                $masked = $existingKey.Substring(0, [Math]::Min(4, $existingKey.Length)) + "..." + $existingKey.Substring([Math]::Max(0, $existingKey.Length - 4))
                Write-Host ""
                Write-Color -Text "  $([char]0x2B22) Current key: $masked" -Color Green
                $apiKey = Read-Host "  Press Enter to keep, or paste a new key to replace"
            } else {
                Write-Host ""
                Write-Host "Get your API key from: " -NoNewline
                Write-Color -Text $signupUrl -Color Cyan
                Write-Host ""
                $apiKey = Read-Host "Paste your $providerName API key (or press Enter to skip)"
            }

            if ($apiKey) {
                [System.Environment]::SetEnvironmentVariable($SelectedEnvVar, $apiKey, "User")
                Set-Item -Path "Env:\$SelectedEnvVar" -Value $apiKey
                Write-Host ""
                Write-Ok "API key saved as User environment variable: $SelectedEnvVar"

                # Health check the new key
                Write-Host "  Verifying API key... " -NoNewline
                try {
                    if ($SelectedApiBase) {
                        $hcResult = & uv run python (Join-Path $ScriptDir "scripts/check_llm_key.py") $SelectedProviderId $apiKey $SelectedApiBase 2>$null
                    } else {
                        $hcResult = & uv run python (Join-Path $ScriptDir "scripts/check_llm_key.py") $SelectedProviderId $apiKey 2>$null
                    }
                    $hcJson = $hcResult | ConvertFrom-Json
                    if ($hcJson.valid -eq $true) {
                        Write-Color -Text "ok" -Color Green
                        break
                    } elseif ($hcJson.valid -eq $false) {
                        Write-Color -Text "failed" -Color Red
                        Write-Warn $hcJson.message
                        # Undo the save so user can retry cleanly
                        [System.Environment]::SetEnvironmentVariable($SelectedEnvVar, $null, "User")
                        Remove-Item -Path "Env:\$SelectedEnvVar" -ErrorAction SilentlyContinue
                        Write-Host ""
                        Read-Host "  Press Enter to try again"
                        # loop back to key prompt
                    } else {
                        Write-Color -Text "--" -Color Yellow
                        Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                        break
                    }
                } catch {
                    Write-Color -Text "--" -Color Yellow
                    Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                    break
                }
            } elseif (-not $existingKey) {
                # No existing key and user skipped
                Write-Host ""
                Write-Warn "Skipped. Set the environment variable manually when ready:"
                Write-Host "  [System.Environment]::SetEnvironmentVariable('$SelectedEnvVar', 'your-key', 'User')"
                $SelectedEnvVar     = ""
                $SelectedProviderId = ""
                break
            } else {
                # User pressed Enter with existing key — keep it
                break
            }
        }
    }
    14 {
        # Local (Ollama)
        if (-not $OllamaDetected) {
            Write-Host ""
            Write-Warn "Ollama depends on a local Ollama server, but 'ollama list' failed."
            Write-Host "  Please install Ollama (https://ollama.com) and start the server,"
            Write-Host "  then run this quickstart again."
            Write-Host ""
            exit 1
        }
        $SelectedProviderId = "ollama"
        Write-Host ""
        Write-Ok "Using Local (Ollama)"
        Write-Host ""

        # Fetch available models
        $ollamaModels = @()
        try {
            $listOutput = & ollama list 2>$null
            if ($listOutput.Count -gt 1) {
                for ($i = 1; $i -lt $listOutput.Count; $i++) {
                    $line = $listOutput[$i].Trim()
                    if ($line) {
                        $mName = ($line -split '\s+')[0]
                        if ($mName) { $ollamaModels += $mName }
                    }
                }
            }
        } catch { }

        if ($ollamaModels.Count -eq 0) {
            Write-Warn "No Ollama models found."
            Write-Host "  Please open another terminal, run 'ollama run <model>' (e.g. 'ollama run llama3'),"
            Write-Host "  and then run this quickstart again."
            Write-Host ""
            exit 1
        }

        # Show model picker
        Write-Host "  Select an Ollama model:"
        Write-Host ""
        $defaultIdx = "1"
        for ($i = 0; $i -lt $ollamaModels.Count; $i++) {
            Write-Color -Text "  $($i + 1)" -Color Cyan -NoNewline
            Write-Host ") $($ollamaModels[$i])"
            if ($PrevProvider -eq "ollama" -and $PrevModel -eq $ollamaModels[$i]) {
                $defaultIdx = [string]($i + 1)
            }
        }
        Write-Host ""
        
        while ($true) {
            $raw = Read-Host "Enter choice (1-$($ollamaModels.Count)) [$defaultIdx]"
            if ([string]::IsNullOrWhiteSpace($raw)) { $raw = $defaultIdx }
            if ($raw -match '^\d+$') {
                $num = [int]$raw
                if ($num -ge 1 -and $num -le $ollamaModels.Count) {
                    $SelectedModel = $ollamaModels[$num - 1]
                    Write-Host ""
                    Write-Ok "Model: $SelectedModel"
                    $SelectedMaxTokens = 8192
                    $SelectedMaxContextTokens = 16384
                    $SelectedApiBase = "http://localhost:11434"
                    break
                }
            }
            Write-Color -Text "Invalid choice. Please enter 1-$($ollamaModels.Count)" -Color Red
        }
    }
    { $_ -eq $SkipChoice } {
        Write-Host ""
        Write-Warn "Skipped. An LLM API key is required to test and use worker agents."
        Write-Host "  Add your API key later by running:"
        Write-Host ""
        Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'your-key', 'User')" -Color Cyan
        Write-Host ""
        $SelectedEnvVar     = ""
        $SelectedProviderId = ""
    }
}

# For MiniMax coding key: prompt for API key with verification + retry
if ($SubscriptionMode -eq "minimax_code") {
    while ($true) {
        $existingMinimax = [System.Environment]::GetEnvironmentVariable("MINIMAX_API_KEY", "User")
        if (-not $existingMinimax) { $existingMinimax = $env:MINIMAX_API_KEY }

        if ($existingMinimax) {
            $masked = $existingMinimax.Substring(0, [Math]::Min(4, $existingMinimax.Length)) + "..." + $existingMinimax.Substring([Math]::Max(0, $existingMinimax.Length - 4))
            Write-Host ""
            Write-Color -Text "  $([char]0x2B22) Current MiniMax key: $masked" -Color Green
            $apiKey = Read-Host "  Press Enter to keep, or paste a new key to replace"
        } else {
            Write-Host ""
            Write-Host "Get your API key from: " -NoNewline
            Write-Color -Text "https://platform.minimax.io/user-center/basic-information/interface-key" -Color Cyan
            Write-Host ""
            $apiKey = Read-Host "Paste your MiniMax API key (or press Enter to skip)"
        }

        if ($apiKey) {
            [System.Environment]::SetEnvironmentVariable("MINIMAX_API_KEY", $apiKey, "User")
            $env:MINIMAX_API_KEY = $apiKey
            Write-Host ""
            Write-Ok "MiniMax API key saved as User environment variable"

            # Health check the new key
            Write-Host "  Verifying MiniMax API key... " -NoNewline
            try {
                $hcResult = & $UvCmd run python (Join-Path $ScriptDir "scripts/check_llm_key.py") "minimax" $apiKey "https://api.minimax.io/v1" 2>$null
                $hcJson = $hcResult | ConvertFrom-Json
                if ($hcJson.valid -eq $true) {
                    Write-Color -Text "ok" -Color Green
                    break
                } elseif ($hcJson.valid -eq $false) {
                    Write-Color -Text "failed" -Color Red
                    Write-Warn $hcJson.message
                    [System.Environment]::SetEnvironmentVariable("MINIMAX_API_KEY", $null, "User")
                    Remove-Item -Path "Env:\MINIMAX_API_KEY" -ErrorAction SilentlyContinue
                    Write-Host ""
                    Read-Host "  Press Enter to try again"
                } else {
                    Write-Color -Text "--" -Color Yellow
                    Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                    break
                }
            } catch {
                Write-Color -Text "--" -Color Yellow
                Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                break
            }
        } elseif (-not $existingMinimax) {
            Write-Host ""
            Write-Warn "Skipped. Add your MiniMax API key later:"
            Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('MINIMAX_API_KEY', 'your-key', 'User')" -Color Cyan
            $SelectedEnvVar     = ""
            $SelectedProviderId = ""
            $SubscriptionMode   = ""
            break
        } else {
            break
        }
    }
}

# For ZAI subscription: prompt for API key (allow replacement if already set) with verification + retry
if ($SubscriptionMode -eq "zai_code") {
    while ($true) {
        $existingZai = [System.Environment]::GetEnvironmentVariable("ZAI_API_KEY", "User")
        if (-not $existingZai) { $existingZai = $env:ZAI_API_KEY }

        if ($existingZai) {
            $masked = $existingZai.Substring(0, [Math]::Min(4, $existingZai.Length)) + "..." + $existingZai.Substring([Math]::Max(0, $existingZai.Length - 4))
            Write-Host ""
            Write-Color -Text "  $([char]0x2B22) Current ZAI key: $masked" -Color Green
            $apiKey = Read-Host "  Press Enter to keep, or paste a new key to replace"
        } else {
            Write-Host ""
            $apiKey = Read-Host "Paste your ZAI API key (or press Enter to skip)"
        }

        if ($apiKey) {
            [System.Environment]::SetEnvironmentVariable("ZAI_API_KEY", $apiKey, "User")
            $env:ZAI_API_KEY = $apiKey
            Write-Host ""
            Write-Ok "ZAI API key saved as User environment variable"

            # Health check the new key
            Write-Host "  Verifying ZAI API key... " -NoNewline
            try {
                $hcResult = & $UvCmd run python (Join-Path $ScriptDir "scripts/check_llm_key.py") "zai" $apiKey "https://api.z.ai/api/coding/paas/v4" 2>$null
                $hcJson = $hcResult | ConvertFrom-Json
                if ($hcJson.valid -eq $true) {
                    Write-Color -Text "ok" -Color Green
                    break
                } elseif ($hcJson.valid -eq $false) {
                    Write-Color -Text "failed" -Color Red
                    Write-Warn $hcJson.message
                    # Undo the save so user can retry cleanly
                    [System.Environment]::SetEnvironmentVariable("ZAI_API_KEY", $null, "User")
                    Remove-Item -Path "Env:\ZAI_API_KEY" -ErrorAction SilentlyContinue
                    Write-Host ""
                    Read-Host "  Press Enter to try again"
                    # loop back to key prompt
                } else {
                    Write-Color -Text "--" -Color Yellow
                    Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                    break
                }
            } catch {
                Write-Color -Text "--" -Color Yellow
                Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                break
            }
        } elseif (-not $existingZai) {
            # No existing key and user skipped
            Write-Host ""
            Write-Warn "Skipped. Add your ZAI API key later:"
            Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('ZAI_API_KEY', 'your-key', 'User')" -Color Cyan
            $SelectedEnvVar     = ""
            $SelectedProviderId = ""
            $SubscriptionMode   = ""
            break
        } else {
            # User pressed Enter with existing key — keep it
            break
        }
    }
}

# For Kimi Code subscription: prompt for API key with verification + retry
if ($SubscriptionMode -eq "kimi_code") {
    while ($true) {
        $existingKimi = [System.Environment]::GetEnvironmentVariable("KIMI_API_KEY", "User")
        if (-not $existingKimi) { $existingKimi = $env:KIMI_API_KEY }

        if ($existingKimi) {
            $masked = $existingKimi.Substring(0, [Math]::Min(4, $existingKimi.Length)) + "..." + $existingKimi.Substring([Math]::Max(0, $existingKimi.Length - 4))
            Write-Host ""
            Write-Color -Text "  $([char]0x2B22) Current Kimi key: $masked" -Color Green
            $apiKey = Read-Host "  Press Enter to keep, or paste a new key to replace"
        } else {
            Write-Host ""
            Write-Host "Get your API key from: " -NoNewline
            Write-Color -Text "https://www.kimi.com/code" -Color Cyan
            Write-Host ""
            $apiKey = Read-Host "Paste your Kimi API key (or press Enter to skip)"
        }

        if ($apiKey) {
            [System.Environment]::SetEnvironmentVariable("KIMI_API_KEY", $apiKey, "User")
            $env:KIMI_API_KEY = $apiKey
            Write-Host ""
            Write-Ok "Kimi API key saved as User environment variable"

            # Health check the new key
            Write-Host "  Verifying Kimi API key... " -NoNewline
            try {
                $hcResult = & $UvCmd run python (Join-Path $ScriptDir "scripts/check_llm_key.py") "kimi" $apiKey "https://api.kimi.com/coding" 2>$null
                $hcJson = $hcResult | ConvertFrom-Json
                if ($hcJson.valid -eq $true) {
                    Write-Color -Text "ok" -Color Green
                    break
                } elseif ($hcJson.valid -eq $false) {
                    Write-Color -Text "failed" -Color Red
                    Write-Warn $hcJson.message
                    [System.Environment]::SetEnvironmentVariable("KIMI_API_KEY", $null, "User")
                    Remove-Item -Path "Env:\KIMI_API_KEY" -ErrorAction SilentlyContinue
                    Write-Host ""
                    Read-Host "  Press Enter to try again"
                } else {
                    Write-Color -Text "--" -Color Yellow
                    Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                    break
                }
            } catch {
                Write-Color -Text "--" -Color Yellow
                Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                break
            }
        } elseif (-not $existingKimi) {
            Write-Host ""
            Write-Warn "Skipped. Add your Kimi API key later:"
            Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('KIMI_API_KEY', 'your-key', 'User')" -Color Cyan
            $SelectedEnvVar     = ""
            $SelectedProviderId = ""
            $SubscriptionMode   = ""
            break
        } else {
            break
        }
    }
}

# For Hive LLM: prompt for API key with verification + retry
if ($SubscriptionMode -eq "hive_llm") {
    while ($true) {
        $existingHive = [System.Environment]::GetEnvironmentVariable("HIVE_API_KEY", "User")
        if (-not $existingHive) { $existingHive = $env:HIVE_API_KEY }

        if ($existingHive) {
            $masked = $existingHive.Substring(0, [Math]::Min(4, $existingHive.Length)) + "..." + $existingHive.Substring([Math]::Max(0, $existingHive.Length - 4))
            Write-Host ""
            Write-Color -Text "  $([char]0x2B22) Current Hive key: $masked" -Color Green
            Write-Host ""
            $apiKey = Read-Host "Paste a new Hive API key (or press Enter to keep current)"
        } else {
            Write-Host ""
            Write-Host "  Get your API key from: " -NoNewline
            Write-Color -Text "https://discord.com/invite/hQdU7QDkgR" -Color Cyan
            Write-Host ""
            $apiKey = Read-Host "Paste your Hive API key (or press Enter to skip)"
        }

        if ($apiKey) {
            [System.Environment]::SetEnvironmentVariable("HIVE_API_KEY", $apiKey, "User")
            $env:HIVE_API_KEY = $apiKey
            Write-Host ""
            Write-Ok "Hive API key saved as User environment variable"

            # Health check the new key
            Write-Host "  Verifying Hive API key... " -NoNewline
            try {
                $hcOutput = & $PythonCmd scripts/check_llm_key.py hive $apiKey "$HiveLlmEndpoint" 2>&1
                $hcJson = $hcOutput | ConvertFrom-Json
                if ($hcJson.valid -eq $true) {
                    Write-Color -Text "ok" -Color Green
                    break
                } elseif ($hcJson.valid -eq $false) {
                    Write-Color -Text "failed" -Color Red
                    Write-Warn $hcJson.message
                    [System.Environment]::SetEnvironmentVariable("HIVE_API_KEY", $null, "User")
                    Remove-Item -Path "Env:\HIVE_API_KEY" -ErrorAction SilentlyContinue
                    Write-Host ""
                    Read-Host "  Press Enter to try again"
                } else {
                    Write-Color -Text "--" -Color Yellow
                    Write-Color -Text "  Could not verify key (network issue). The key has been saved." -Color DarkGray
                    break
                }
            } catch {
                Write-Color -Text "--" -Color Yellow
                break
            }
        } elseif (-not $existingHive) {
            Write-Host ""
            Write-Warn "Skipped. Add your Hive API key later:"
            Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('HIVE_API_KEY', 'your-key', 'User')" -Color Cyan
            $SelectedEnvVar     = ""
            $SelectedProviderId = ""
            $SubscriptionMode   = ""
            break
        } else {
            break
        }
    }
}

# Prompt for model if not already selected (manual provider path)
if ($SelectedProviderId -and -not $SelectedModel) {
    $modelSel = Get-ModelSelection $SelectedProviderId
    $SelectedModel            = $modelSel.Model
    $SelectedMaxTokens        = $modelSel.MaxTokens
    $SelectedMaxContextTokens = $modelSel.MaxContextTokens
}

# Save configuration
if ($SelectedProviderId) {
    if (-not $SelectedModel) {
        $SelectedModel = $DefaultModels[$SelectedProviderId]
    }
    Write-Host ""
    Write-Host "  Saving configuration... " -NoNewline

    if (-not (Test-Path $HiveConfigDir)) {
        New-Item -ItemType Directory -Path $HiveConfigDir -Force | Out-Null
    }

    $config = @{
        llm = @{
            provider           = $SelectedProviderId
            model              = $SelectedModel
            max_tokens         = $SelectedMaxTokens
            max_context_tokens = $SelectedMaxContextTokens
        }
        created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    }

    if ($SubscriptionMode -eq "claude_code") {
        $config.llm["use_claude_code_subscription"] = $true
    } elseif ($SubscriptionMode -eq "codex") {
        $config.llm["use_codex_subscription"] = $true
    } elseif ($SubscriptionMode -eq "antigravity") {
        $config.llm["use_antigravity_subscription"] = $true
    } elseif ($SubscriptionMode -eq "zai_code") {
        $config.llm["api_base"] = "https://api.z.ai/api/coding/paas/v4"
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } elseif ($SubscriptionMode -eq "minimax_code") {
        $config.llm["api_base"] = $SelectedApiBase
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } elseif ($SubscriptionMode -eq "kimi_code") {
        $config.llm["api_base"] = "https://api.kimi.com/coding"
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } elseif ($SubscriptionMode -eq "hive_llm") {
        $config.llm["api_base"] = $HiveLlmEndpoint
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } elseif ($SelectedProviderId -eq "openrouter") {
        $config.llm["api_base"] = "https://openrouter.ai/api/v1"
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } elseif ($SelectedProviderId -eq "ollama") {
        $config.llm["api_base"] = "http://localhost:11434"
        $config.llm.Remove("api_key_env_var")
    } elseif ($SelectedEnvVar) {
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } else {
        $config.llm.Remove("api_key_env_var")
    }

    $config | ConvertTo-Json -Depth 4 | Set-Content -Path $HiveConfigFile -Encoding UTF8
    Write-Ok "done"
    Write-Color -Text "  ~/.hive/configuration.json" -Color DarkGray
}
Write-Host ""

# ============================================================
# Browser Automation (GCU) — always enabled
# ============================================================

Write-Host ""
Write-Ok "Browser automation enabled"

# Patch gcu_enabled into configuration.json
if (Test-Path $HiveConfigFile) {
    $existingConfig = Get-Content -Path $HiveConfigFile -Raw | ConvertFrom-Json
    $existingConfig | Add-Member -NotePropertyName "gcu_enabled" -NotePropertyValue $true -Force
    $existingConfig | ConvertTo-Json -Depth 4 | Set-Content -Path $HiveConfigFile -Encoding UTF8
} else {
    if (-not (Test-Path $HiveConfigDir)) {
        New-Item -ItemType Directory -Path $HiveConfigDir -Force | Out-Null
    }
    $minConfig = @{
        gcu_enabled = $true
        created_at  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    }
    $minConfig | ConvertTo-Json -Depth 4 | Set-Content -Path $HiveConfigFile -Encoding UTF8
}

Write-Host ""

# ============================================================
# Step 4: Initialize Credential Store
# ============================================================

Write-Step -Number "4" -Text "Step 4: Initializing credential store..."
Write-Color -Text "The credential store encrypts API keys and secrets for your agents." -Color DarkGray
Write-Host ""

$HiveCredDir = Join-Path (Join-Path $env:USERPROFILE ".hive") "credentials"
$HiveKeyFile = Join-Path (Join-Path $env:USERPROFILE ".hive") "secrets\credential_key"

# Check if HIVE_CREDENTIAL_KEY already exists (from env, file, or User env var)
$credKey = $env:HIVE_CREDENTIAL_KEY
$credKeySource = ""

if ($credKey) {
    $credKeySource = "environment"
} elseif (Test-Path $HiveKeyFile) {
    $credKey = (Get-Content $HiveKeyFile -Raw).Trim()
    $env:HIVE_CREDENTIAL_KEY = $credKey
    $credKeySource = "file"
}

# Backward compat: check User env var (legacy PS1 installs)
if (-not $credKey) {
    $credKey = [System.Environment]::GetEnvironmentVariable("HIVE_CREDENTIAL_KEY", "User")
    if ($credKey) {
        $env:HIVE_CREDENTIAL_KEY = $credKey
        $credKeySource = "user_env"
    }
}

if ($credKey) {
    switch ($credKeySource) {
        "environment" { Write-Ok "HIVE_CREDENTIAL_KEY already set" }
        "file"        { Write-Ok "HIVE_CREDENTIAL_KEY loaded from $HiveKeyFile" }
        "user_env"    { Write-Ok "HIVE_CREDENTIAL_KEY loaded from User environment variable" }
    }
} else {
    Write-Host "  Generating encryption key... " -NoNewline
    try {
        $generatedKey = & $UvCmd run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>$null
        if ($LASTEXITCODE -eq 0 -and $generatedKey) {
            Write-Ok "ok"
            $generatedKey = $generatedKey.Trim()

            # Save to file (matching quickstart.sh behavior)
            $secretsDir = Split-Path $HiveKeyFile -Parent
            New-Item -ItemType Directory -Path $secretsDir -Force | Out-Null
            [System.IO.File]::WriteAllText($HiveKeyFile, $generatedKey)

            # Restrict file permissions (best-effort on Windows)
            try {
                $acl = Get-Acl $HiveKeyFile
                $acl.SetAccessRuleProtection($true, $false)
                $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                    $env:USERNAME, "FullControl", "Allow")
                $acl.SetAccessRule($rule)
                Set-Acl $HiveKeyFile $acl
            } catch {
                # Non-critical; file is in user's home directory
            }

            $env:HIVE_CREDENTIAL_KEY = $generatedKey
            $credKey = $generatedKey
            Write-Ok "Encryption key saved to $HiveKeyFile"
        } else {
            Write-Warn "failed"
            Write-Warn "Credential store will not be available."
            Write-Host "  You can set HIVE_CREDENTIAL_KEY manually later."
        }
    } catch {
        Write-Warn "failed - $($_.Exception.Message)"
    }
}

if ($credKey) {
    $credCredsDir = Join-Path $HiveCredDir "credentials"
    $credMetaDir  = Join-Path $HiveCredDir "metadata"
    New-Item -ItemType Directory -Path $credCredsDir -Force | Out-Null
    New-Item -ItemType Directory -Path $credMetaDir  -Force | Out-Null

    $indexFile = Join-Path $credMetaDir "index.json"
    if (-not (Test-Path $indexFile)) {
        '{"credentials": {}, "version": "1.0"}' | Set-Content -Path $indexFile -Encoding UTF8
    }

    Write-Ok "Credential store initialized at ~/.hive/credentials/"

    Write-Host "  Verifying credential store... " -NoNewline
    $verifyOut = & $UvCmd run python -c "from framework.credentials.storage import EncryptedFileStorage; storage = EncryptedFileStorage(); print('ok')" 2>$null
    if ($verifyOut -match "ok") {
        Write-Ok "ok"
    } else {
        Write-Warn "skipped"
    }
}
Write-Host ""

# ============================================================
# Step 5: Verify Setup
# ============================================================

Write-Step -Number "5" -Text "Step 5: Verifying installation..."

$verifyErrors = 0

# Batch verification using same check_requirements script
$verifyModules = @("framework", "aden_tools")

try {
    $verifyOutput = & $UvCmd run python scripts/check_requirements.py @verifyModules 2>&1 | Out-String
    $verifyJson = $null
    
    try {
        $verifyJson = $verifyOutput | ConvertFrom-Json
    } catch {
        Write-Host "  Warning: Could not parse verification results" -ForegroundColor Yellow
        # Fall back to basic checks if JSON parsing fails
        foreach ($mod in $verifyModules) {
            Write-Host "  $([char]0x2B21) $mod... " -NoNewline
            $null = & $UvCmd run python -c "import $mod" 2>&1
            if ($LASTEXITCODE -eq 0) { Write-Ok "ok" }
            else { Write-Fail "failed"; $verifyErrors++ }
        }
    }
    
    if ($verifyJson) {
        Write-Host "  $([char]0x2B21) framework... " -NoNewline
        if ($verifyJson.framework -eq "ok") { Write-Ok "ok" }
        else { Write-Fail "failed"; $verifyErrors++ }
        
        Write-Host "  $([char]0x2B21) aden_tools... " -NoNewline
        if ($verifyJson.aden_tools -eq "ok") { Write-Ok "ok" }
        else { Write-Fail "failed"; $verifyErrors++ }
    }
} catch {
    Write-Host "  Warning: Verification check encountered an error" -ForegroundColor Yellow
}

Write-Host "  $([char]0x2B21) litellm... " -NoNewline
$null = & $UvCmd run python -c "import litellm" 2>&1
if ($LASTEXITCODE -eq 0) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host "  $([char]0x2B21) MCP config... " -NoNewline
if (Test-Path (Join-Path $ScriptDir ".mcp.json")) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host "  $([char]0x2B21) skills... " -NoNewline
$skillsDir = Join-Path (Join-Path $ScriptDir ".claude") "skills"
if (Test-Path $skillsDir) {
    $skillCount = (Get-ChildItem -Directory $skillsDir -ErrorAction SilentlyContinue).Count
    Write-Ok "$skillCount found"
} else {
    Write-Warn "skipped"
}

Write-Host "  $([char]0x2B21) codex CLI... " -NoNewline
$CodexAvailable = $false
$codexVer = ""
$codexCmd = Get-Command codex -ErrorAction SilentlyContinue
if ($codexCmd) {
    $codexVersionRaw = & codex --version 2>$null | Select-Object -First 1
    if ($codexVersionRaw -match '(\d+)\.(\d+)\.(\d+)') {
        $cMajor = [int]$Matches[1]
        $cMinor = [int]$Matches[2]
        $codexVer = "$($Matches[1]).$($Matches[2]).$($Matches[3])"
        if ($cMajor -gt 0 -or ($cMajor -eq 0 -and $cMinor -ge 101)) {
            Write-Ok $codexVer
            $CodexAvailable = $true
        } else {
            Write-Warn "$codexVer (upgrade to 0.101.0+)"
        }
    } else {
        Write-Warn "skipped"
    }
} else {
    Write-Warn "skipped"
}

Write-Host "  $([char]0x2B21) local settings... " -NoNewline
$localSettingsPath = Join-Path $ScriptDir ".claude\settings.local.json"
$localSettingsExample = Join-Path $ScriptDir ".claude\settings.local.json.example"
if (Test-Path $localSettingsPath) {
    Write-Ok "ok"
} elseif (Test-Path $localSettingsExample) {
    Copy-Item $localSettingsExample $localSettingsPath
    Write-Ok "copied from example"
} else {
    Write-Warn "skipped"
}

Write-Host "  $([char]0x2B21) credential store... " -NoNewline
$credStoreDir = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".hive") "credentials") "credentials"
if ($credKey -and (Test-Path $credStoreDir)) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host "  $([char]0x2B21) frontend... " -NoNewline
$frontendIndex = Join-Path $ScriptDir "core\frontend\dist\index.html"
if (Test-Path $frontendIndex) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host ""
if ($verifyErrors -gt 0) {
    Write-Color -Text "Setup failed with $verifyErrors error(s)." -Color Red
    Write-Host "Please check the errors above and try again."
    exit 1
}

# ============================================================
# Step 6: Install hive CLI wrapper
# ============================================================

Write-Step -Number "6" -Text "Step 6: Installing hive CLI..."

# Verify hive.ps1 wrapper exists in project root
$hivePs1Path = Join-Path $ScriptDir "hive.ps1"
if (Test-Path $hivePs1Path) {
    Write-Ok "hive.ps1 wrapper found in project root"
} else {
    Write-Fail "hive.ps1 not found -- please restore it from version control"
}

# Optionally add project dir to User PATH
$currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($currentUserPath -notlike "*$ScriptDir*") {
    $newUserPath = $currentUserPath + ";" + $ScriptDir
    [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    Write-Ok "Project directory added to User PATH"
} else {
    Write-Ok "Project directory already in PATH"
}

Write-Host ""

# ============================================================
# Success!
# ============================================================

Clear-Host
Write-Host ""
$successBanner = ""
for ($i = 0; $i -lt 13; $i++) {
    if ($i % 2 -eq 0) { $successBanner += $hex } else { $successBanner += $hexDim }
}
Write-Color -Text $successBanner -Color Green
Write-Host ""
Write-Color -Text "        ADEN HIVE - READY" -Color Green
Write-Host ""
Write-Color -Text $successBanner -Color Green
Write-Host ""
Write-Host "Your environment is configured for building AI agents."
Write-Host ""

# Show configured provider
if ($SelectedProviderId) {
    if (-not $SelectedModel) { $SelectedModel = $DefaultModels[$SelectedProviderId] }
    Write-Color -Text "Default LLM:" -Color White
    if ($SubscriptionMode -eq "claude_code") {
        Write-Ok "Claude Code Subscription -> $SelectedModel"
        Write-Color -Text "  Token auto-refresh from ~/.claude/.credentials.json" -Color DarkGray
    } elseif ($SubscriptionMode -eq "zai_code") {
        Write-Ok "ZAI Code Subscription -> $SelectedModel"
        Write-Color -Text "  API: api.z.ai (OpenAI-compatible)" -Color DarkGray
    } elseif ($SubscriptionMode -eq "minimax_code") {
        Write-Ok "MiniMax Coding Key -> $SelectedModel"
        Write-Color -Text "  API: api.minimax.io/v1 (OpenAI-compatible)" -Color DarkGray
    } elseif ($SubscriptionMode -eq "codex") {
        Write-Ok "OpenAI Codex Subscription -> $SelectedModel"
    } elseif ($SubscriptionMode -eq "antigravity") {
        Write-Ok "Antigravity Subscription -> $SelectedModel"
        Write-Color -Text "  Direct OAuth (no proxy required)" -Color DarkGray
    } elseif ($SelectedProviderId -eq "openrouter") {
        Write-Ok "OpenRouter API Key -> $SelectedModel"
        Write-Color -Text "  API: openrouter.ai/api/v1 (OpenAI-compatible)" -Color DarkGray
    } else {
        Write-Color -Text "  $SelectedProviderId" -Color Cyan -NoNewline
        Write-Host " -> " -NoNewline
        Write-Color -Text $SelectedModel -Color DarkGray
    }
    Write-Color -Text "  To use a different model for worker agents, run:" -Color DarkGray
    Write-Host "     " -NoNewline
    Write-Color -Text ".\scripts\setup_worker_model.ps1" -Color Cyan
    Write-Host ""
}

# Show credential store status
if ($credKey) {
    Write-Color -Text "Credential Store:" -Color White
    Write-Ok "~/.hive/credentials/  (encrypted)"
    Write-Host ""
}

# Show Codex instructions if available
if ($CodexAvailable) {
    Write-Color -Text "Build a New Agent (Codex):" -Color White
    Write-Host ""
    Write-Host "  Codex " -NoNewline
    Write-Color -Text $codexVer -Color Green -NoNewline
    Write-Host " is available. To use it with Hive:"
    Write-Host "  1. Restart your terminal (or open a new one)"
    Write-Host "  2. Run: " -NoNewline
    Write-Color -Text "codex" -Color Cyan
    Write-Host "  3. Type: " -NoNewline
    Write-Color -Text "use hive" -Color Cyan
    Write-Host ""
}

# Final instructions and auto-launch
Write-Host "API keys saved as User environment variables. New terminals pick them up automatically." -ForegroundColor DarkGray
Write-Host "Launch anytime with " -NoNewline -ForegroundColor DarkGray
Write-Color -Text "hive open" -Color Cyan -NoNewline
Write-Host ". Run .\quickstart.ps1 again to reconfigure." -ForegroundColor DarkGray
Write-Host ""

if ($FrontendDistReady -or $NodeAvailable) {
    if ($FrontendDistReady) {
        Write-Color -Text "Launching dashboard..." -Color White
    } else {
        Write-Color -Text "Launching dashboard (retrying frontend build via hive open)..." -Color White
    }
    Write-Host ""
    & $hivePs1Path open
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Dashboard launch failed"
        Write-Host "  Run '.\hive.ps1 open' manually to inspect the error." -ForegroundColor DarkGray
    }
} else {
    Write-Color -Text "Frontend build was skipped or failed, and no built dashboard is available." -Color Yellow -NoNewline
    Write-Host " Launch manually when ready:"
    Write-Color -Text "     .\hive.ps1 open" -Color Cyan
    Write-Host ""
}
