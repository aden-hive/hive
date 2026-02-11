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

$ErrorActionPreference = "Stop"

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
if (-not $uvCmd) {
    Write-Warn "uv not found. Installing..."
    try {
        # Official uv installer for Windows
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        # Refresh PATH so we can find the newly installed uv
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
        # 1. Temporarily allow status messages without crashing
        $oldPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"

        # 2. Capture the output as a string
        $syncOutput = & uv sync 2>&1 | Out-String

        # 3. Save the actual exit code from uv
        $actualExitCode = $LASTEXITCODE

        # 4. Restore the strict setting
        $ErrorActionPreference = $oldPref
        if ($LASTEXITCODE -eq 0) {
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
    $null = & uv run $PythonCmd -c "import playwright" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $null = & uv run $PythonCmd -m playwright install chromium 2>&1
        if ($LASTEXITCODE -eq 0) {
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

foreach ($imp in $imports) {
    Write-Host "  $($imp.Label)... " -NoNewline
    $null = & uv run $PythonCmd -c "import $($imp.Module)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "ok"
    } elseif ($imp.Required) {
        Write-Fail "failed"
        $importErrors++
    } else {
        Write-Warn "issues (may be OK)"
    }
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
        @{ Id = "claude-opus-4-6";            Label = "Opus 4.6 - Most capable (recommended)"; MaxTokens = 8192 },
        @{ Id = "claude-sonnet-4-5-20250929"; Label = "Sonnet 4.5 - Best balance";             MaxTokens = 8192 },
        @{ Id = "claude-sonnet-4-20250514";   Label = "Sonnet 4 - Fast + capable";             MaxTokens = 8192 },
        @{ Id = "claude-haiku-4-5-20251001";  Label = "Haiku 4.5 - Fast + cheap";              MaxTokens = 8192 }
    )
    openai = @(
        @{ Id = "gpt-5.2";   Label = "GPT-5.2 - Most capable (recommended)"; MaxTokens = 16384 },
        @{ Id = "gpt-5-mini"; Label = "GPT-5 Mini - Fast + cheap";            MaxTokens = 16384 },
        @{ Id = "gpt-5-nano"; Label = "GPT-5 Nano - Fastest";                 MaxTokens = 16384 }
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
# Step 5 (was 3 in bash): Configure LLM API Key
# ============================================================

Write-Step -Number "5" -Text "Step 5: Configuring LLM provider..."

# Hive config paths
$HiveConfigDir  = Join-Path $env:USERPROFILE ".hive"
$HiveConfigFile = Join-Path $HiveConfigDir "configuration.json"

$SelectedProviderId = ""
$SelectedEnvVar     = ""
$SelectedModel      = ""
$SelectedMaxTokens  = 8192

# Scan for existing API keys in the current environment
$FoundProviders = @()
$FoundEnvVars   = @()

foreach ($envVar in $ProviderMap.Keys) {
    $val = [System.Environment]::GetEnvironmentVariable($envVar, "Process")
    if (-not $val) { $val = [System.Environment]::GetEnvironmentVariable($envVar, "User") }
    if ($val) {
        $FoundProviders += $ProviderMap[$envVar].Name
        $FoundEnvVars   += $envVar
    }
}

if ($FoundProviders.Count -gt 0) {
    Write-Host "Found API keys:"
    Write-Host ""
    foreach ($p in $FoundProviders) {
        Write-Ok $p
    }
    Write-Host ""

    if ($FoundProviders.Count -eq 1) {
        if (Prompt-YesNo "Use this key?") {
            $SelectedEnvVar     = $FoundEnvVars[0]
            $SelectedProviderId = $ProviderMap[$SelectedEnvVar].Id
            Write-Host ""
            Write-Ok "Using $($FoundProviders[0])"
            $modelSel = Get-ModelSelection $SelectedProviderId
            $SelectedModel     = $modelSel.Model
            $SelectedMaxTokens = $modelSel.MaxTokens
        }
    } else {
        Write-Color -Text "Select your default LLM provider:" -Color White
        Write-Host ""
        for ($i = 0; $i -lt $FoundProviders.Count; $i++) {
            Write-Color -Text "  $($i + 1)" -Color Cyan -NoNewline
            Write-Host ") $($FoundProviders[$i])"
        }
        $otherIdx = $FoundProviders.Count + 1
        Write-Color -Text "  $otherIdx" -Color Cyan -NoNewline
        Write-Host ") Other"
        Write-Host ""

        while ($true) {
            $raw = Read-Host "Enter choice (1-$otherIdx)"
            if ($raw -match '^\d+$') {
                $num = [int]$raw
                if ($num -ge 1 -and $num -le $otherIdx) {
                    if ($num -eq $otherIdx) { break }  # fall through to manual selection
                    $idx = $num - 1
                    $SelectedEnvVar     = $FoundEnvVars[$idx]
                    $SelectedProviderId = $ProviderMap[$SelectedEnvVar].Id
                    Write-Host ""
                    Write-Ok "Selected: $($FoundProviders[$idx])"
                    $modelSel = Get-ModelSelection $SelectedProviderId
                    $SelectedModel     = $modelSel.Model
                    $SelectedMaxTokens = $modelSel.MaxTokens
                    break
                }
            }
            Write-Color -Text "Invalid choice. Please enter 1-$otherIdx" -Color Red
        }
    }
}

if (-not $SelectedProviderId) {
    $providerOptions = @(
        "Anthropic (Claude) - Recommended",
        "OpenAI (GPT)",
        "Google Gemini - Free tier available",
        "Groq - Fast, free tier",
        "Cerebras - Fast, free tier",
        "Skip for now"
    )
    $choice = Prompt-Choice "Select your LLM provider:" $providerOptions

    $providerDetails = @(
        @{ EnvVar = "ANTHROPIC_API_KEY"; Id = "anthropic"; Name = "Anthropic"; Url = "https://console.anthropic.com/settings/keys" },
        @{ EnvVar = "OPENAI_API_KEY";    Id = "openai";    Name = "OpenAI";    Url = "https://platform.openai.com/api-keys" },
        @{ EnvVar = "GEMINI_API_KEY";    Id = "gemini";    Name = "Google Gemini"; Url = "https://aistudio.google.com/apikey" },
        @{ EnvVar = "GROQ_API_KEY";      Id = "groq";      Name = "Groq";      Url = "https://console.groq.com/keys" },
        @{ EnvVar = "CEREBRAS_API_KEY";  Id = "cerebras";  Name = "Cerebras";  Url = "https://cloud.cerebras.ai/" }
    )

    if ($choice -lt 5) {
        $det = $providerDetails[$choice]
        $SelectedEnvVar     = $det.EnvVar
        $SelectedProviderId = $det.Id

        # Check if key is already set
        $existingKey = [System.Environment]::GetEnvironmentVariable($SelectedEnvVar, "User")
        if (-not $existingKey) {
            Write-Host ""
            Write-Host "Get your API key from: " -NoNewline
            Write-Color -Text $det.Url -Color Cyan
            Write-Host ""
            $apiKey = Read-Host "Paste your $($det.Name) API key (or press Enter to skip)"

            if ($apiKey) {
                # Persist as a User-level environment variable (survives reboots)
                [System.Environment]::SetEnvironmentVariable($SelectedEnvVar, $apiKey, "User")
                # Also set in current session
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
    } else {
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

# Prompt for model if not already selected
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
            api_key_env_var = $SelectedEnvVar
        }
        created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    }
    $config | ConvertTo-Json -Depth 4 | Set-Content -Path $HiveConfigFile -Encoding UTF8
    Write-Ok "done"
    Write-Color -Text "  ~/.hive/configuration.json" -Color DarkGray
}
Write-Host ""

# ============================================================
# Step 6: Initialize Credential Store
# ============================================================

Write-Step -Number "6" -Text "Step 6: Initializing credential store..."
Write-Color -Text "The credential store encrypts API keys and secrets for your agents." -Color DarkGray
Write-Host ""

$HiveCredDir = Join-Path $env:USERPROFILE ".hive" "credentials"

# Check if HIVE_CREDENTIAL_KEY is already set
$credKey = [System.Environment]::GetEnvironmentVariable("HIVE_CREDENTIAL_KEY", "User")
if (-not $credKey) { $credKey = $env:HIVE_CREDENTIAL_KEY }

if ($credKey) {
    Write-Ok "HIVE_CREDENTIAL_KEY already set"
} else {
    Write-Host "  Generating encryption key... " -NoNewline
    try {
        $generatedKey = & uv run $PythonCmd -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>$null
        if ($LASTEXITCODE -eq 0 -and $generatedKey) {
            Write-Ok "ok"
            [System.Environment]::SetEnvironmentVariable("HIVE_CREDENTIAL_KEY", $generatedKey.Trim(), "User")
            $env:HIVE_CREDENTIAL_KEY = $generatedKey.Trim()
            $credKey = $generatedKey.Trim()
            Write-Ok "Encryption key saved as User environment variable"
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
        "{}" | Set-Content -Path $indexFile -Encoding UTF8
    }

    Write-Ok "Credential store initialized at ~/.hive/credentials/"

    Write-Host "  Verifying credential store... " -NoNewline
    $verifyOut = & uv run $PythonCmd -c "from framework.credentials.storage import EncryptedFileStorage; storage = EncryptedFileStorage(); print('ok')" 2>$null
    if ($verifyOut -match "ok") {
        Write-Ok "ok"
    } else {
        Write-Warn "skipped"
    }
}
Write-Host ""

# ============================================================
# Step 7: Verify Setup
# ============================================================

Write-Step -Number "7" -Text "Step 7: Verifying installation..."

$verifyErrors = 0

$verifications = @(
    @{ Cmd = "import framework";   Label = "framework" },
    @{ Cmd = "import aden_tools";  Label = "aden_tools" }
)

foreach ($v in $verifications) {
    Write-Host "  $([char]0x2B21) $($v.Label)... " -NoNewline
    $null = & uv run $PythonCmd -c $v.Cmd 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Ok "ok" }
    else { Write-Fail "failed"; $verifyErrors++ }
}

Write-Host "  $([char]0x2B21) litellm... " -NoNewline
$null = & uv run $PythonCmd -c "import litellm" 2>&1
if ($LASTEXITCODE -eq 0) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host "  $([char]0x2B21) MCP config... " -NoNewline
if (Test-Path (Join-Path $ScriptDir ".mcp.json")) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host "  $([char]0x2B21) skills... " -NoNewline
$skillsDir = Join-Path $ScriptDir ".claude" "skills"
if (Test-Path $skillsDir) {
    $skillCount = (Get-ChildItem -Directory $skillsDir -ErrorAction SilentlyContinue).Count
    Write-Ok "$skillCount found"
} else {
    Write-Warn "skipped"
}

Write-Host "  $([char]0x2B21) credential store... " -NoNewline
$credStoreDir = Join-Path $env:USERPROFILE ".hive" "credentials" "credentials"
if ($credKey -and (Test-Path $credStoreDir)) { Write-Ok "ok" } else { Write-Warn "skipped" }

Write-Host ""
if ($verifyErrors -gt 0) {
    Write-Color -Text "Setup failed with $verifyErrors error(s)." -Color Red
    Write-Host "Please check the errors above and try again."
    exit 1
}

# ============================================================
# Step 8: Install hive CLI wrapper
# ============================================================

Write-Step -Number "8" -Text "Step 8: Installing hive CLI..."

# Create a hive.ps1 wrapper in the project root that can be added to PATH
$hivePs1Path = Join-Path $ScriptDir "hive.ps1"

$hivePs1Content = @"
#!/usr/bin/env pwsh
# Wrapper script for the Hive CLI (Windows).
# Uses uv to run the hive command in the project's virtual environment.

`$ErrorActionPreference = "Stop"
`$ScriptDir = Split-Path -Parent `$MyInvocation.MyCommand.Definition

if ((Get-Location).Path -ne `$ScriptDir) {
    Write-Error "hive must be run from the project directory.``nCurrent directory: `$(Get-Location)``nExpected directory: `$ScriptDir``n``nRun: cd `$ScriptDir"
    exit 1
}

if (-not (Test-Path (Join-Path `$ScriptDir "pyproject.toml")) -or -not (Test-Path (Join-Path `$ScriptDir "core"))) {
    Write-Error "Not a valid Hive project directory: `$ScriptDir"
    exit 1
}

if (-not (Test-Path (Join-Path `$ScriptDir ".venv"))) {
    Write-Error "Virtual environment not found. Run .\quickstart.ps1 first to set up the project."
    exit 1
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed. Run .\quickstart.ps1 first."
    exit 1
}

& uv run hive @args
"@

Set-Content -Path $hivePs1Path -Value $hivePs1Content -Encoding UTF8
Write-Ok "hive.ps1 wrapper created in project root"

# Optionally add project dir to User PATH
$currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($currentUserPath -notlike "*$ScriptDir*") {
    Write-Host ""
    Write-Host "  To run 'hive' from anywhere, add this directory to your PATH:"
    Write-Color -Text "  `$env:Path += `";$ScriptDir`"" -Color Cyan
    Write-Host "  Or permanently:"
    Write-Color -Text "  [System.Environment]::SetEnvironmentVariable('Path', `$env:Path + ';$ScriptDir', 'User')" -Color Cyan
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

if ($SelectedProviderId) {
    if (-not $SelectedModel) { $SelectedModel = $DefaultModels[$SelectedProviderId] }
    Write-Color -Text "Default LLM:" -Color White
    Write-Color -Text "  $SelectedProviderId" -Color Cyan -NoNewline
    Write-Host " -> " -NoNewline
    Write-Color -Text $SelectedModel -Color DarkGray
    Write-Host ""
}

if ($credKey) {
    Write-Color -Text "Credential Store:" -Color White
    Write-Ok "~/.hive/credentials/  (encrypted)"
    Write-Color -Text "  Set up agent credentials with: /setup-credentials" -Color DarkGray
    Write-Host ""
}

Write-Color -Text "Build a New Agent:" -Color White
Write-Host ""
Write-Host "  1. Open Claude Code in this directory:"
Write-Color -Text "     claude" -Color Cyan
Write-Host ""
Write-Host "  2. Build a new agent:"
Write-Color -Text "     /hive" -Color Cyan
Write-Host ""
Write-Host "  3. Test an existing agent:"
Write-Color -Text "     /hive-test" -Color Cyan
Write-Host ""
Write-Color -Text "Run an Agent:" -Color White
Write-Host ""
Write-Host "  Launch the interactive dashboard to browse and run agents:"
Write-Host "  You can start an example agent or an agent built by yourself:"
Write-Color -Text "     .\hive.ps1 tui" -Color Cyan
Write-Host ""

if ($SelectedProviderId -or $credKey) {
    Write-Color -Text "Note:" -Color White -NoNewline
    Write-Host " Environment variables were saved at the User level."
    Write-Host "  They will be available in new PowerShell sessions automatically."
    Write-Host "  For the current session, they are already active."
    Write-Host ""
}

Write-Color -Text "Run .\quickstart.ps1 again to reconfigure." -Color DarkGray
Write-Host ""
