# <#
# quickstart.ps1 - Interactive onboarding for Aden Agent Framework (Windows)
# 
# 1. Installs Python dependencies
# 2. Helps configure LLM API keys
# 3. Verifies imports
# #>

$ErrorActionPreference = "Stop"

# Helper function for prompts
function Prompt-YesNo {
    param([string]$prompt, [string]$default = "y")
    $fullPrompt = if ($default -eq "y") { "$prompt [Y/n] " } else { "$prompt [y/N] " }
    $response = Read-Host -Prompt $fullPrompt
    if ([string]::IsNullOrWhiteSpace($response)) { $response = $default }
    return ($response -like "y*")
}

function Prompt-Choice {
    param([string]$prompt, [string[]]$options)
    Write-Host "`n$prompt" -ForegroundColor White
    for ($i = 0; $i -lt $options.Length; $i++) {
        Write-Host "  $($i + 1)) $($options[$i])" -ForegroundColor Cyan
    }
    Write-Host ""
    while ($true) {
        $choice = Read-Host -Prompt "Enter choice (1-$($options.Length))"
        if ($choice -as [int] -and ($choice -ge 1 -and $choice -le $options.Length)) {
            return ($choice - 1)
        }
        Write-Host "Invalid choice. Please enter 1-$($options.Length)" -ForegroundColor Red
    }
}

Clear-Host
Write-Host "**************************************************" -ForegroundColor Yellow
Write-Host "          A D E N   H I V E (Windows)" -ForegroundColor Yellow
Write-Host "**************************************************" -ForegroundColor Yellow
Write-Host "     Goal-driven AI agent framework" -ForegroundColor Gray
Write-Host ""

if (-not (Prompt-YesNo "Ready to begin?")) {
    Write-Host "No problem! Run this script again when you're ready."
    exit
}

# Step 1: Python
Write-Host "`n* Step 1: Checking Python..." -ForegroundColor Blue
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Please install Python 3.11+." -ForegroundColor Red
    exit 1
}
$pythonVersion = python --version
Write-Host "* Found $pythonVersion" -ForegroundColor Green

# Step 2: uv
Write-Host "`n* Step 2: Checking uv..." -ForegroundColor Blue
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "  uv not found. Installing..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Write-Host "Error: uv installation failed" -ForegroundColor Red
        exit 1
    }
}
$uvVersion = uv --version
Write-Host "  OK: $uvVersion" -ForegroundColor Green

# Step 3: Packages
Write-Host "`n* Step 3: Installing packages..." -ForegroundColor Blue
if (-not (Test-Path "pyproject.toml")) {
    Write-Host "failed (no pyproject.toml found)" -ForegroundColor Red
    exit 1
}
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "  X workspace installation failed" -ForegroundColor Red
    exit 1
}
Write-Host "  OK: packages installed" -ForegroundColor Green

# Step 4: LLM
Write-Host "`n* Step 4: Configuring LLM provider..." -ForegroundColor Blue
$hiveConfigDir = "$HOME\.hive"
$hiveConfigFile = "$hiveConfigDir\configuration.json"
New-Item -ItemType Directory -Force -Path $hiveConfigDir | Out-Null

$providers = @(
    @{ Name = "Anthropic (Claude)"; EnvVar = "ANTHROPIC_API_KEY"; ID = "anthropic"; Model = "claude-3-5-sonnet-latest"; URL = "https://console.anthropic.com/settings/keys" },
    @{ Name = "OpenAI (GPT)"; EnvVar = "OPENAI_API_KEY"; ID = "openai"; Model = "gpt-4o"; URL = "https://platform.openai.com/api-keys" },
    @{ Name = "Google Gemini"; EnvVar = "GEMINI_API_KEY"; ID = "gemini"; Model = "gemini-1.5-pro"; URL = "https://aistudio.google.com/apikey" }
)

$choiceIdx = Prompt-Choice "Select your default LLM provider:" ($providers | ForEach-Object { $_.Name })
$selected = $providers[$choiceIdx]

# Dynamic check
$envVarName = $selected.EnvVar
$existingKey = Get-ChildItem "Env:$envVarName" -ErrorAction SilentlyContinue

if (-not $existingKey) {
    Write-Host "`nGet your API key from: $($selected.URL)" -ForegroundColor Cyan
    $apiKey = Read-Host -Prompt "Paste your $($selected.Name) API key (or Enter to skip)"
    if ($apiKey) {
        Set-Content "Env:$envVarName" $apiKey
        [System.Environment]::SetEnvironmentVariable($envVarName, $apiKey, "User")
        Write-Host "* API key saved." -ForegroundColor Green
    }
}
else {
    Write-Host "* Found existing API key for $($selected.Name)." -ForegroundColor Green
}

$config = @{
    llm        = @{
        provider        = $selected.ID
        model           = $selected.Model
        api_key_env_var = $selected.EnvVar
    }
    created_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
}
$config | ConvertTo-Json | Out-File $hiveConfigFile -Encoding utf8
Write-Host "* Configuration saved to $hiveConfigFile" -ForegroundColor Green

# Step 5: Credentials
Write-Host "`n* Step 5: Initializing credential store..." -ForegroundColor Blue
if (-not $env:HIVE_CREDENTIAL_KEY) {
    Write-Host "  Generating encryption key... " -NoNewline
    $genKey = uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    if ($LASTEXITCODE -eq 0) {
        $env:HIVE_CREDENTIAL_KEY = $genKey
        [System.Environment]::SetEnvironmentVariable("HIVE_CREDENTIAL_KEY", $genKey, "User")
        Write-Host "OK" -ForegroundColor Green
    }
    else {
        Write-Host "FAILED" -ForegroundColor Red
    }
}
else {
    Write-Host "* Encryption key exists." -ForegroundColor Green
}

$hiveCredDir = "$hiveConfigDir\credentials"
New-Item -ItemType Directory -Force -Path "$hiveCredDir\credentials" | Out-Null
New-Item -ItemType Directory -Force -Path "$hiveCredDir\metadata" | Out-Null
if (-not (Test-Path "$hiveCredDir\metadata\index.json")) {
    "{}" | Out-File "$hiveCredDir\metadata\index.json" -Encoding ascii
}
Write-Host "* Credential store initialized." -ForegroundColor Green

# Step 6: Verify
Write-Host "`n* Step 6: Verifying final imports..." -ForegroundColor Blue
$importErrors = 0
function Test-Module {
    param([string]$module)
    Write-Host "  . $module... " -NoNewline
    uv run python -c "import $module" 2>$null
    if ($LASTEXITCODE -eq 0) { 
        Write-Host "OK" -ForegroundColor Green
        return 0
    }
    else {
        Write-Host "FAILED" -ForegroundColor Red
        return 1
    }
}
$importErrors += Test-Module "framework"
$importErrors += Test-Module "aden_tools"

if ($importErrors -eq 0) {
    Clear-Host
    Write-Host "**************************************************" -ForegroundColor Green
    Write-Host "          ADEN HIVE - READY FOR WINDOWS" -ForegroundColor Green
    Write-Host "**************************************************" -ForegroundColor Green
    Write-Host "Your environment is ready!"
    Write-Host "LLM: $($selected.ID)"
    Write-Host "Next: Run 'hive tui'"
}
else {
    Write-Host "Final verification failed." -ForegroundColor Red
}
