#Requires -Version 5.1
<#
.SYNOPSIS
    quickstart.ps1 - Interactive onboarding for Aden Agent Framework (Windows)

.DESCRIPTION
    An interactive setup wizard that:
    1. Installs Python dependencies via uv
    2. Installs Playwright browser for web scraping
    3. Helps configure LLM API keys
    4. Verifies everything works

.NOTES
    Run from the project root: .\quickstart.ps1
    Requires: PowerShell 5.1+ and Python 3.11+
#>

# Use "Continue" so stderr from external tools (uv, python) does not
# terminate the script.  Errors are handled via $LASTEXITCODE checks.
$ErrorActionPreference = "Continue"

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
        [System.IO.Path]::GetFullPath($_)
    }
    
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
        
        # Normalize existing paths for comparison
        $existing = $existing | Where-Object { $_ } | ForEach-Object {
            [System.IO.Path]::GetFullPath($_)
        }
        
        # Normalize paths and find missing exclusions
        $missing = @()
        foreach ($path in $Paths) {
            $normalized = [System.IO.Path]::GetFullPath($path)
            
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
            $normalized = [System.IO.Path]::GetFullPath($path)
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

# Get the directory where this script lives
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

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

$PythonCmd = $null
foreach ($candidate in @("python3.13", "python3.12", "python3.11", "python3", "python")) {
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
    # Try plain "python" as final fallback (common on Windows)
    try {
        $ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Color -Text "Python $ver found but 3.11+ is required." -Color Red
        } else {
            Write-Color -Text "Python is not installed." -Color Red
        }
    } catch {
        Write-Color -Text "Python is not installed." -Color Red
    }
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

$uvCmd = Get-Command uv -ErrorAction SilentlyContinue

# If uv not in PATH, check if it exists in default location
if (-not $uvCmd) {
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
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue

        if ($uvCmd) {
            Write-Ok "uv is now in PATH"
        }
    }
}

# If still not found, install it
if (-not $uvCmd) {
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
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    } catch {
        Write-Color -Text "Error: uv installation failed" -Color Red
        Write-Host "Please install uv manually from https://astral.sh/uv/"
        exit 1
    }
    if (-not $uvCmd) {
        Write-Color -Text "Error: uv not found after installation" -Color Red
        Write-Host "Please close and reopen PowerShell, then run this script again."
        Write-Host "Or install uv manually from https://astral.sh/uv/"
        exit 1
    }
    Write-Ok "uv installed successfully"
}

$uvVersion = & uv --version
Write-Ok "uv detected: $uvVersion"
Write-Host ""

# Check for Node.js (needed for frontend dashboard)
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
            Write-Host "    Install from https://nodejs.org" -ForegroundColor DarkGray
        }
    }
} else {
    Write-Warn "Node.js not found (optional, needed for web dashboard)"
    Write-Host "    Install from https://nodejs.org" -ForegroundColor DarkGray
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

        $syncOutput = & uv sync 2>&1
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

    # Install Playwright browser
    Write-Host "  Installing Playwright browser... " -NoNewline
    $null = & uv run python -c "import playwright" 2>&1
    $importExitCode = $LASTEXITCODE
    if ($importExitCode -eq 0) {
        $null = & uv run python -m playwright install chromium 2>&1
        $playwrightExitCode = $LASTEXITCODE

        if ($playwrightExitCode -eq 0) {
            Write-Ok "ok"
        } else {
            Write-Warn "skipped (install manually: uv run python -m playwright install chromium)"
        }
    } else {

        Write-Warn "skipped"
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Ok "All packages installed"
Write-Host ""

# Build frontend (if Node.js is available)
$FrontendBuilt = $false
if ($NodeAvailable) {
    Write-Step -Number "" -Text "Building frontend dashboard..."
    Write-Host ""
    $frontendDir = Join-Path $ScriptDir "core\frontend"
    if (Test-Path (Join-Path $frontendDir "package.json")) {
        Write-Host "  Installing npm packages... " -NoNewline
        Push-Location $frontendDir
        try {
            $null = & npm install --no-fund --no-audit 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "ok"
                Write-Host "  Building frontend... " -NoNewline
                $null = & npm run build 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Ok "ok"
                    Write-Ok "Frontend built -> core/frontend/dist/"
                    $FrontendBuilt = $true
                } else {
                    Write-Warn "build failed"
                    Write-Host "    Run 'cd core\frontend && npm run build' manually to debug." -ForegroundColor DarkGray
                }
            } else {
                Write-Warn "npm install failed"
                $NodeAvailable = $false
            }
        } finally {
            Pop-Location
        }
    }
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
    @{ Module = "litellm";                          Label = "litellm";      Required = $false },
    @{ Module = "framework.mcp.agent_builder_server"; Label = "MCP server module"; Required = $true }
)

# Batch check all imports in single process (reduces subprocess spawning overhead)
$modulesToCheck = @("framework", "aden_tools", "litellm", "framework.mcp.agent_builder_server")

try {
    $checkOutput = & uv run $PythonCmd scripts/check_requirements.py @modulesToCheck 2>&1 | Out-String
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
# Step 4: Verify Claude Code Skills
# ============================================================

Write-Step -Number "4" -Text "Step 4: Verifying Claude Code skills..."

# (skills check is informational only, shown in final verification)

# ============================================================
# Provider / model data
# ============================================================

$ProviderMap = [ordered]@{
    ANTHROPIC_API_KEY = @{ Name = "Anthropic (Claude)"; Id = "anthropic" }
    OPENAI_API_KEY    = @{ Name = "OpenAI (GPT)";       Id = "openai" }
    GEMINI_API_KEY    = @{ Name = "Google Gemini";       Id = "gemini" }
    GOOGLE_API_KEY    = @{ Name = "Google AI";           Id = "google" }
    GROQ_API_KEY      = @{ Name = "Groq";               Id = "groq" }
    CEREBRAS_API_KEY  = @{ Name = "Cerebras";            Id = "cerebras" }
    MISTRAL_API_KEY   = @{ Name = "Mistral";             Id = "mistral" }
    TOGETHER_API_KEY  = @{ Name = "Together AI";         Id = "together" }
    DEEPSEEK_API_KEY  = @{ Name = "DeepSeek";            Id = "deepseek" }
}

$DefaultModels = @{
    anthropic   = "claude-opus-4-6"
    openai      = "gpt-5.2"
    gemini      = "gemini-3-flash-preview"
    groq        = "moonshotai/kimi-k2-instruct-0905"
    cerebras    = "zai-glm-4.7"
    mistral     = "mistral-large-latest"
    together_ai = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    deepseek    = "deepseek-chat"
}

# Model choices: array of hashtables per provider
$ModelChoices = @{
    anthropic = @(
        @{ Id = "claude-opus-4-6";            Label = "Opus 4.6 - Most capable (recommended)"; MaxTokens = 32768 },
        @{ Id = "claude-sonnet-4-5-20250929"; Label = "Sonnet 4.5 - Best balance";             MaxTokens = 16384 },
        @{ Id = "claude-sonnet-4-20250514";   Label = "Sonnet 4 - Fast + capable";             MaxTokens = 8192 },
        @{ Id = "claude-haiku-4-5-20251001";  Label = "Haiku 4.5 - Fast + cheap";              MaxTokens = 8192 }
    )
    openai = @(
        @{ Id = "gpt-5.2";   Label = "GPT-5.2 - Most capable (recommended)"; MaxTokens = 16384 },
        @{ Id = "gpt-5-mini"; Label = "GPT-5 Mini - Fast + cheap";            MaxTokens = 16384 }
    )
    gemini = @(
        @{ Id = "gemini-3-flash-preview"; Label = "Gemini 3 Flash - Fast (recommended)"; MaxTokens = 8192 },
        @{ Id = "gemini-3-pro-preview";   Label = "Gemini 3 Pro - Best quality";         MaxTokens = 8192 }
    )
    groq = @(
        @{ Id = "moonshotai/kimi-k2-instruct-0905"; Label = "Kimi K2 - Best quality (recommended)"; MaxTokens = 8192 },
        @{ Id = "openai/gpt-oss-120b";              Label = "GPT-OSS 120B - Fast reasoning";        MaxTokens = 8192 }
    )
    cerebras = @(
        @{ Id = "zai-glm-4.7";                    Label = "ZAI-GLM 4.7 - Best quality (recommended)"; MaxTokens = 8192 },
        @{ Id = "qwen3-235b-a22b-instruct-2507";  Label = "Qwen3 235B - Frontier reasoning";          MaxTokens = 8192 }
    )
}

function Get-ModelSelection {
    param([string]$ProviderId)

    $choices = $ModelChoices[$ProviderId]
    if (-not $choices -or $choices.Count -eq 0) {
        return @{ Model = $DefaultModels[$ProviderId]; MaxTokens = 8192 }
    }
    if ($choices.Count -eq 1) {
        return @{ Model = $choices[0].Id; MaxTokens = $choices[0].MaxTokens }
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
        $raw = Read-Host "Enter choice [1]"
        if ([string]::IsNullOrWhiteSpace($raw)) { $raw = "1" }
        if ($raw -match '^\d+$') {
            $num = [int]$raw
            if ($num -ge 1 -and $num -le $choices.Count) {
                $sel = $choices[$num - 1]
                Write-Host ""
                Write-Ok "Model: $($sel.Id)"
                return @{ Model = $sel.Id; MaxTokens = $sel.MaxTokens }
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

$SelectedProviderId = ""
$SelectedEnvVar     = ""
$SelectedModel      = ""
$SelectedMaxTokens  = 8192
$SubscriptionMode   = ""

# ── Credential detection (silent — just set flags) ───────────
$ClaudeCredDetected = $false
$claudeCredPath = Join-Path $env:USERPROFILE ".claude\.credentials.json"
if (Test-Path $claudeCredPath) { $ClaudeCredDetected = $true }

$CodexCredDetected = $false
$codexAuthPath = Join-Path $env:USERPROFILE ".codex\auth.json"
if (Test-Path $codexAuthPath) { $CodexCredDetected = $true }

$ZaiCredDetected = $false
$zaiKey = [System.Environment]::GetEnvironmentVariable("ZAI_API_KEY", "User")
if (-not $zaiKey) { $zaiKey = $env:ZAI_API_KEY }
if ($zaiKey) { $ZaiCredDetected = $true }

# Detect API key providers
$ProviderMenuEnvVars  = @("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY")
$ProviderMenuNames    = @("Anthropic (Claude) - Recommended", "OpenAI (GPT)", "Google Gemini - Free tier available", "Groq - Fast, free tier", "Cerebras - Fast, free tier")
$ProviderMenuIds      = @("anthropic", "openai", "gemini", "groq", "cerebras")
$ProviderMenuUrls     = @(
    "https://console.anthropic.com/settings/keys",
    "https://platform.openai.com/api-keys",
    "https://aistudio.google.com/apikey",
    "https://console.groq.com/keys",
    "https://cloud.cerebras.ai/"
)

# ── Show unified provider selection menu ─────────────────────
Write-Color -Text "Select your default LLM provider:" -Color White
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

Write-Host ""
Write-Color -Text "  API key providers:" -Color Cyan

# 4-8) API key providers
for ($idx = 0; $idx -lt $ProviderMenuEnvVars.Count; $idx++) {
    $num = $idx + 4
    $envVal = [System.Environment]::GetEnvironmentVariable($ProviderMenuEnvVars[$idx], "Process")
    if (-not $envVal) { $envVal = [System.Environment]::GetEnvironmentVariable($ProviderMenuEnvVars[$idx], "User") }
    Write-Host "  " -NoNewline
    Write-Color -Text "$num" -Color Cyan -NoNewline
    Write-Host ") $($ProviderMenuNames[$idx])" -NoNewline
    if ($envVal) { Write-Color -Text "  (credential detected)" -Color Green } else { Write-Host "" }
}

Write-Host "  " -NoNewline
Write-Color -Text "9" -Color Cyan -NoNewline
Write-Host ") Skip for now"
Write-Host ""

while ($true) {
    $raw = Read-Host "Enter choice (1-9)"
    if ($raw -match '^\d+$') {
        $num = [int]$raw
        if ($num -ge 1 -and $num -le 9) { break }
    }
    Write-Color -Text "Invalid choice. Please enter 1-9" -Color Red
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
        $SubscriptionMode   = "claude_code"
        $SelectedProviderId = "anthropic"
        $SelectedModel      = "claude-opus-4-6"
        $SelectedMaxTokens  = 32768
        Write-Host ""
        Write-Ok "Using Claude Code subscription"
    }
    2 {
        # ZAI Code Subscription
        $SubscriptionMode   = "zai_code"
        $SelectedProviderId = "openai"
        $SelectedEnvVar     = "ZAI_API_KEY"
        $SelectedModel      = "glm-5"
        $SelectedMaxTokens  = 32768
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
                & uv run python (Join-Path $ScriptDir "core\codex_oauth.py") 2>&1
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
            $SubscriptionMode   = "codex"
            $SelectedProviderId = "openai"
            $SelectedModel      = "gpt-5.3-codex"
            $SelectedMaxTokens  = 16384
            Write-Host ""
            Write-Ok "Using OpenAI Codex subscription"
        }
    }
    { $_ -ge 4 -and $_ -le 8 } {
        # API key providers
        $provIdx = $num - 4
        $SelectedEnvVar     = $ProviderMenuEnvVars[$provIdx]
        $SelectedProviderId = $ProviderMenuIds[$provIdx]
        $providerName       = $ProviderMenuNames[$provIdx] -replace ' - .*', ''  # strip description
        $signupUrl          = $ProviderMenuUrls[$provIdx]

        # Check if key is already set
        $existingKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "User")
        if (-not $existingKey) { $existingKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "Process") }
        if (-not $existingKey) {
            Write-Host ""
            Write-Host "Get your API key from: " -NoNewline
            Write-Color -Text $signupUrl -Color Cyan
            Write-Host ""
            $apiKey = Read-Host "Paste your $providerName API key (or press Enter to skip)"

            if ($apiKey) {
                [System.Environment]::SetEnvironmentVariable($SelectedEnvVar, $apiKey, "User")
                Set-Item -Path "Env:\$SelectedEnvVar" -Value $apiKey
                Write-Host ""
                Write-Ok "API key saved as User environment variable: $SelectedEnvVar"
                Write-Color -Text "  (Persisted for all future sessions)" -Color DarkGray
            } else {
                Write-Host ""
                Write-Warn "Skipped. Set the environment variable manually when ready:"
                Write-Host "  [System.Environment]::SetEnvironmentVariable('$SelectedEnvVar', 'your-key', 'User')"
                $SelectedEnvVar     = ""
                $SelectedProviderId = ""
            }
        }
    }
    9 {
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

# For ZAI subscription: prompt for API key if not already set
if ($SubscriptionMode -eq "zai_code") {
    $existingZai = [System.Environment]::GetEnvironmentVariable("ZAI_API_KEY", "User")
    if (-not $existingZai) { $existingZai = $env:ZAI_API_KEY }
    if (-not $existingZai) {
        Write-Host ""
        $apiKey = Read-Host "Paste your ZAI API key (or press Enter to skip)"

        if ($apiKey) {
            [System.Environment]::SetEnvironmentVariable("ZAI_API_KEY", $apiKey, "User")
            $env:ZAI_API_KEY = $apiKey
            Write-Host ""
            Write-Ok "ZAI API key saved as User environment variable"
        } else {
            Write-Host ""
            Write-Warn "Skipped. Add your ZAI API key later:"
            Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('ZAI_API_KEY', 'your-key', 'User')" -Color Cyan
            $SelectedEnvVar     = ""
            $SelectedProviderId = ""
            $SubscriptionMode   = ""
        }
    }
}

# Prompt for model if not already selected (manual provider path)
if ($SelectedProviderId -and -not $SelectedModel) {
    $modelSel = Get-ModelSelection $SelectedProviderId
    $SelectedModel     = $modelSel.Model
    $SelectedMaxTokens = $modelSel.MaxTokens
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
            provider       = $SelectedProviderId
            model          = $SelectedModel
            max_tokens     = $SelectedMaxTokens
        }
        created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    }

    if ($SubscriptionMode -eq "claude_code") {
        $config.llm["use_claude_code_subscription"] = $true
    } elseif ($SubscriptionMode -eq "codex") {
        $config.llm["use_codex_subscription"] = $true
    } elseif ($SubscriptionMode -eq "zai_code") {
        $config.llm["api_base"] = "https://api.z.ai/api/coding/paas/v4"
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    } else {
        $config.llm["api_key_env_var"] = $SelectedEnvVar
    }

    $config | ConvertTo-Json -Depth 4 | Set-Content -Path $HiveConfigFile -Encoding UTF8
    Write-Ok "done"
    Write-Color -Text "  ~/.hive/configuration.json" -Color DarkGray
}
Write-Host ""

# ============================================================
# Step 5: Initialize Credential Store
# ============================================================

Write-Step -Number "5" -Text "Step 5: Initializing credential store..."
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
        $generatedKey = & uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>$null
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
    $verifyOut = & uv run python -c "from framework.credentials.storage import EncryptedFileStorage; storage = EncryptedFileStorage(); print('ok')" 2>$null
    if ($verifyOut -match "ok") {
        Write-Ok "ok"
    } else {
        Write-Warn "skipped"
    }
}
Write-Host ""

# ============================================================
# Step 6: Verify Setup
# ============================================================

Write-Step -Number "6" -Text "Step 6: Verifying installation..."

$verifyErrors = 0

# Batch verification using same check_requirements script
$verifyModules = @("framework", "aden_tools")

try {
    $verifyOutput = & uv run $PythonCmd scripts/check_requirements.py @verifyModules 2>&1 | Out-String
    $verifyJson = $null
    
    try {
        $verifyJson = $verifyOutput | ConvertFrom-Json
    } catch {
        Write-Host "  Warning: Could not parse verification results" -ForegroundColor Yellow
        # Fall back to basic checks if JSON parsing fails
        foreach ($mod in $verifyModules) {
            Write-Host "  $([char]0x2B21) $mod... " -NoNewline
            $null = & uv run $PythonCmd -c "import $mod" 2>&1
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
$null = & uv run python -c "import litellm" 2>&1
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
# Step 7: Install hive CLI wrapper
# ============================================================

Write-Step -Number "7" -Text "Step 7: Installing hive CLI..."

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
    } elseif ($SubscriptionMode -eq "codex") {
        Write-Ok "OpenAI Codex Subscription -> $SelectedModel"
    } else {
        Write-Color -Text "  $SelectedProviderId" -Color Cyan -NoNewline
        Write-Host " -> " -NoNewline
        Write-Color -Text $SelectedModel -Color DarkGray
    }
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

# Auto-launch dashboard or show manual instructions
if ($FrontendBuilt) {
    Write-Color -Text "Launching dashboard..." -Color White
    Write-Host ""
    Write-Color -Text "  Starting server on http://localhost:8787" -Color DarkGray
    Write-Color -Text "  Press Ctrl+C to stop" -Color DarkGray
    Write-Host ""
    & (Join-Path $ScriptDir "hive.ps1") serve --open
} else {
    Write-Color -Text "═══════════════════════════════════════════════════════" -Color Yellow
    Write-Host ""
    Write-Color -Text "  IMPORTANT: Restart your terminal now!" -Color Yellow
    Write-Host ""
    Write-Color -Text "═══════════════════════════════════════════════════════" -Color Yellow
    Write-Host ""
    Write-Host 'Environment variables (uv, API keys) are now configured, but you need to'
    Write-Host 'restart your terminal for them to take effect in new sessions.'
    Write-Host ""

    Write-Color -Text "Run an Agent:" -Color White
    Write-Host ""
    Write-Host "  Launch the interactive dashboard to browse and run agents:"
    Write-Host "  You can start an example agent or an agent built by yourself:"
    Write-Color -Text "     .\hive.ps1 tui" -Color Cyan
    Write-Host ""

    if ($SelectedProviderId -or $credKey) {
        Write-Color -Text "Note:" -Color White
        Write-Host "- uv has been added to your User PATH"
        if ($SelectedProviderId -and $SelectedEnvVar) {
            Write-Host "- $SelectedEnvVar is set for LLM access"
        }
        if ($credKey) {
            Write-Host "- HIVE_CREDENTIAL_KEY is set for credential encryption"
        }
        Write-Host "- All variables will persist across reboots"
        Write-Host ""
    }

    Write-Color -Text 'Run .\quickstart.ps1 again to reconfigure.' -Color DarkGray
    Write-Host ""
}
