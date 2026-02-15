#!/usr/bin/env pwsh
# Wrapper script for the Hive CLI (Windows).
# Modified by AthanasEdigerMartin - Adding enhanced error logging and regional comments.
#
# On Windows, User-level environment variables (set via quickstart.ps1) are
# stored in the registry but may not be loaded into the current terminal.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# ── Validate project directory ──────────────────────────────────────
# Hakikisha upo kwenye folder sahihi la Hive kabla ya kuanza.

if ((Get-Location).Path -ne $ScriptDir) {
    Write-Host "Checking directory status..." -ForegroundColor Cyan
    Write-Error "hive must be run from the project directory.`nCurrent directory: $(Get-Location)`nExpected directory: $ScriptDir`n`nRun: cd $ScriptDir"
    exit 1
}

if (-not (Test-Path (Join-Path $ScriptDir "pyproject.toml")) -or -not (Test-Path (Join-Path $ScriptDir "core"))) {
    Write-Error "Not a valid Hive project directory: $ScriptDir. Please check if core files exist."
    exit 1
}

if (-not (Test-Path (Join-Path $ScriptDir ".venv"))) {
    Write-Host "Virtual environment is missing! (Mazingira ya venv hayajapatikana)" -ForegroundColor Yellow
    Write-Error "Virtual environment not found. Run .\quickstart.ps1 first to set up the project."
    exit 1
}

# ── Ensure uv is available ──────────────────────────────────────────
# 'uv' ni muhimu kwa ajili ya kuendesha agent.

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $uvExe = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $uvExe) {
        $env:Path = (Split-Path $uvExe) + ";" + $env:Path
    } else {
        Write-Host "UV tool not found. Please install it to proceed." -ForegroundColor Red
        Write-Error "uv is not installed. Run .\quickstart.ps1 first."
        exit 1
    }
}

# ── Load environment variables from Windows Registry ────────────────
# Tunapakia API Keys kutoka kwenye Windows Registry ili agent afanye kazi.

$configPath = Join-Path (Join-Path $env:USERPROFILE ".hive") "configuration.json"
if (Test-Path $configPath) {
    try {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        $envVarName = $config.llm.api_key_env_var
        if ($envVarName) {
            $val = [System.Environment]::GetEnvironmentVariable($envVarName, "User")
            if ($val -and -not (Test-Path "Env:\$envVarName" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:\$envVarName" -Value $val
                Write-Host "Successfully loaded API Key: $envVarName" -ForegroundColor Green
            }
        }
    } catch {
        Write-Host "Warning: Could not load some environment variables from Registry." -ForegroundColor Gray
    }
}

# Load HIVE_CREDENTIAL_KEY for encrypted credential store
$credKey = [System.Environment]::GetEnvironmentVariable("HIVE_CREDENTIAL_KEY", "User")
if ($credKey -and -not $env:HIVE_CREDENTIAL_KEY) {
    $env:HIVE_CREDENTIAL_KEY = $credKey
}

# ── Run the Hive CLI ────────────────────────────────────────────────
Write-Host "Launching Hive Agent..." -ForegroundColor Magenta
& uv run hive @args