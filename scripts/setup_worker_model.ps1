#Requires -Version 5.1
<#
.SYNOPSIS
    setup_worker_model.ps1 - Configure a separate LLM model for worker agents

.DESCRIPTION
    Worker agents can use a different (e.g. cheaper/faster) model than the
    queen agent.  This script writes a "worker_llm" section to
    ~/.hive/configuration.json.  If no worker model is configured, workers
    fall back to the default (queen) model.

.NOTES
    Run from the project root: .\scripts\setup_worker_model.ps1
#>

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
$UvHelperPath = Join-Path $ScriptDir "uv-discovery.ps1"
$HiveConfigDir = Join-Path $env:USERPROFILE ".hive"
$HiveConfigFile = Join-Path $HiveConfigDir "configuration.json"

. $UvHelperPath

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

function Write-Ok {
    param([string]$Text)
    Write-Color -Text "$([char]0x2B22) $Text" -Color Green
}

function Write-Warn {
    param([string]$Text)
    Write-Color -Text "$([char]0x2B22) $Text" -Color Yellow
}

# ============================================================
# Provider / model definitions
# ============================================================

$ProviderEnvVars = @{
    "ANTHROPIC_API_KEY"  = @{ Name = "Anthropic (Claude)"; Id = "anthropic" }
    "OPENAI_API_KEY"     = @{ Name = "OpenAI (GPT)"; Id = "openai" }
    "GEMINI_API_KEY"     = @{ Name = "Google Gemini"; Id = "gemini" }
    "GROQ_API_KEY"       = @{ Name = "Groq"; Id = "groq" }
    "CEREBRAS_API_KEY"   = @{ Name = "Cerebras"; Id = "cerebras" }
    "OPENROUTER_API_KEY" = @{ Name = "OpenRouter"; Id = "openrouter" }
    "MISTRAL_API_KEY"    = @{ Name = "Mistral"; Id = "mistral" }
    "TOGETHER_API_KEY"   = @{ Name = "Together AI"; Id = "together" }
    "DEEPSEEK_API_KEY"   = @{ Name = "DeepSeek"; Id = "deepseek" }
}

$DefaultModels = @{
    "anthropic"   = "claude-haiku-4-5-20251001"
    "openai"      = "gpt-5-mini"
    "gemini"      = "gemini-3-flash-preview"
    "groq"        = "moonshotai/kimi-k2-instruct-0905"
    "cerebras"    = "zai-glm-4.7"
    "mistral"     = "mistral-large-latest"
    "together_ai" = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    "deepseek"    = "deepseek-chat"
}

$ModelChoices = @{
    "anthropic" = @(
        @{ Id = "claude-haiku-4-5-20251001";  Label = "Haiku 4.5 - Fast + cheap (recommended for workers)"; MaxTokens = 8192;  MaxContext = 180000 }
        @{ Id = "claude-sonnet-4-20250514";   Label = "Sonnet 4 - Fast + capable";                         MaxTokens = 8192;  MaxContext = 180000 }
        @{ Id = "claude-sonnet-4-5-20250929"; Label = "Sonnet 4.5 - Best balance";                         MaxTokens = 16384; MaxContext = 180000 }
        @{ Id = "claude-opus-4-6";            Label = "Opus 4.6 - Most capable";                           MaxTokens = 32768; MaxContext = 180000 }
    )
    "openai" = @(
        @{ Id = "gpt-5-mini"; Label = "GPT-5 Mini - Fast + cheap (recommended for workers)"; MaxTokens = 16384; MaxContext = 120000 }
        @{ Id = "gpt-5.2";    Label = "GPT-5.2 - Most capable";                              MaxTokens = 16384; MaxContext = 120000 }
    )
    "gemini" = @(
        @{ Id = "gemini-3-flash-preview";   Label = "Gemini 3 Flash - Fast (recommended for workers)"; MaxTokens = 8192; MaxContext = 900000 }
        @{ Id = "gemini-3.1-pro-preview";   Label = "Gemini 3.1 Pro - Best quality";                   MaxTokens = 8192; MaxContext = 900000 }
    )
    "groq" = @(
        @{ Id = "moonshotai/kimi-k2-instruct-0905"; Label = "Kimi K2 - Best quality (recommended)"; MaxTokens = 8192; MaxContext = 120000 }
        @{ Id = "openai/gpt-oss-120b";              Label = "GPT-OSS 120B - Fast reasoning";        MaxTokens = 8192; MaxContext = 120000 }
    )
    "cerebras" = @(
        @{ Id = "zai-glm-4.7";                     Label = "ZAI-GLM 4.7 - Best quality (recommended)"; MaxTokens = 8192; MaxContext = 120000 }
        @{ Id = "qwen3-235b-a22b-instruct-2507";   Label = "Qwen3 235B - Frontier reasoning";          MaxTokens = 8192; MaxContext = 120000 }
    )
}

# ============================================================
# Main
# ============================================================

$uvInfo = Find-Uv
if (-not $uvInfo) {
    Write-Color -Text "uv not found. Run quickstart.ps1 first." -Color Red
    exit 1
}
$UvCmd = $uvInfo.Path

Write-Host ""
Write-Color -Text "$([char]0x2B22) Worker Model Setup" -Color Yellow
Write-Host ""
Write-Color -Text "Configure a separate LLM model for worker agents." -Color DarkGray
Write-Color -Text "Worker agents will use this model instead of the default queen model." -Color DarkGray
Write-Host ""

# Show current configuration
if (Test-Path $HiveConfigFile) {
    try {
        Push-Location $ProjectDir
        $currentConfig = & $UvCmd run python -c "
from framework.config import get_preferred_model, get_preferred_worker_model
print(f'Queen:  {get_preferred_model()}')
wm = get_preferred_worker_model()
print(f'Worker: {wm if wm else chr(34) + \"(same as queen)\" + chr(34)}')
" 2>$null
        Pop-Location
        if ($currentConfig) {
            Write-Color -Text "Current configuration:" -Color White
            foreach ($line in $currentConfig) {
                Write-Color -Text "  $line" -Color DarkGray
            }
            Write-Host ""
        }
    } catch {
        Pop-Location
    }
}

# Detect available providers
$AvailableProviders = @()
foreach ($envVar in $ProviderEnvVars.Keys) {
    $val = [System.Environment]::GetEnvironmentVariable($envVar, "User")
    if (-not $val) { $val = [System.Environment]::GetEnvironmentVariable($envVar) }
    if ($val) {
        $AvailableProviders += @{
            EnvVar = $envVar
            Name   = $ProviderEnvVars[$envVar].Name
            Id     = $ProviderEnvVars[$envVar].Id
        }
    }
}

if ($AvailableProviders.Count -eq 0) {
    Write-Color -Text "No API keys found." -Color Red
    Write-Host "Run .\quickstart.ps1 first to set up your LLM provider."
    exit 1
}

# Pick provider
$SelectedProvider = $null
if ($AvailableProviders.Count -eq 1) {
    $SelectedProvider = $AvailableProviders[0]
    Write-Ok "Provider: $($SelectedProvider.Name)"
} else {
    Write-Color -Text "Select provider for worker agents:" -Color White
    Write-Host ""
    for ($i = 0; $i -lt $AvailableProviders.Count; $i++) {
        Write-Host "  " -NoNewline
        Write-Color -Text "$($i+1))" -Color Cyan -NoNewline
        Write-Host " $($AvailableProviders[$i].Name)"
    }
    Write-Host ""
    while ($true) {
        $choice = Read-Host "Enter choice (1-$($AvailableProviders.Count))"
        $idx = [int]$choice - 1
        if ($idx -ge 0 -and $idx -lt $AvailableProviders.Count) {
            $SelectedProvider = $AvailableProviders[$idx]
            Write-Host ""
            Write-Ok "Provider: $($SelectedProvider.Name)"
            break
        }
        Write-Color -Text "Invalid choice." -Color Red
    }
}

$SelectedProviderId = $SelectedProvider.Id
$SelectedEnvVar = $SelectedProvider.EnvVar
$SelectedModel = $DefaultModels[$SelectedProviderId]
$SelectedMaxTokens = 8192
$SelectedMaxContextTokens = 120000
$SelectedApiBase = ""

if ($SelectedProviderId -eq "openrouter") {
    $SelectedApiBase = "https://openrouter.ai/api/v1"
}

# Select model
$choices = $ModelChoices[$SelectedProviderId]
if ($choices -and $choices.Count -gt 0) {
    Write-Host ""
    Write-Color -Text "Select worker model:" -Color White
    for ($i = 0; $i -lt $choices.Count; $i++) {
        Write-Host "  " -NoNewline
        Write-Color -Text "$($i+1))" -Color Cyan -NoNewline
        Write-Host " $($choices[$i].Label)"
    }
    Write-Host ""
    while ($true) {
        $choice = Read-Host "Enter choice (1-$($choices.Count)) [1]"
        if (-not $choice) { $choice = "1" }
        $idx = [int]$choice - 1
        if ($idx -ge 0 -and $idx -lt $choices.Count) {
            $SelectedModel = $choices[$idx].Id
            $SelectedMaxTokens = $choices[$idx].MaxTokens
            $SelectedMaxContextTokens = $choices[$idx].MaxContext
            Write-Host ""
            Write-Ok "Worker model: $SelectedModel"
            break
        }
        Write-Color -Text "Invalid choice." -Color Red
    }
} else {
    Write-Host ""
    Write-Ok "Worker model: $SelectedModel"
}

# Confirm and save
Write-Host ""
$confirm = Read-Host "Save this worker model configuration? [Y/n]"
if ($confirm -and $confirm -notmatch "^[Yy]") {
    Write-Host ""
    Write-Host "Cancelled. Worker agents will continue using the default model."
    exit 0
}

Write-Host ""
Write-Host "  Saving worker model configuration... " -NoNewline

# Read existing config, add worker_llm section
if (-not (Test-Path $HiveConfigDir)) {
    New-Item -ItemType Directory -Path $HiveConfigDir -Force | Out-Null
}

try {
    if (Test-Path $HiveConfigFile) {
        $config = Get-Content -Path $HiveConfigFile -Raw | ConvertFrom-Json
    } else {
        $config = @{}
    }
} catch {
    $config = @{}
}

$workerLlm = @{
    provider           = $SelectedProviderId
    model              = $SelectedModel
    max_tokens         = $SelectedMaxTokens
    max_context_tokens = $SelectedMaxContextTokens
}

if ($SelectedEnvVar) {
    $workerLlm["api_key_env_var"] = $SelectedEnvVar
}
if ($SelectedApiBase) {
    $workerLlm["api_base"] = $SelectedApiBase
}

$config | Add-Member -NotePropertyName "worker_llm" -NotePropertyValue $workerLlm -Force
$config | ConvertTo-Json -Depth 4 | Set-Content -Path $HiveConfigFile -Encoding UTF8
Write-Ok "done"
Write-Color -Text "  ~/.hive/configuration.json (worker_llm section)" -Color DarkGray

Write-Host ""
Write-Ok "Worker model configured successfully."
Write-Color -Text "  Worker agents will now use: $SelectedProviderId/$SelectedModel" -Color DarkGray
Write-Color -Text "  Run this script again to change, or remove the worker_llm section" -Color DarkGray
Write-Color -Text "  from ~/.hive/configuration.json to revert to the default." -Color DarkGray
Write-Host ""
