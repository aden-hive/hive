<#
.SYNOPSIS
    Interactive onboarding for Aden Agent Framework on Windows.

.DESCRIPTION
    An interactive setup wizard that:
    1. Installs/Checks Python dependencies
    2. Installs uv package manager if missing
    3. Installs Playwright browser
    4. Helps configure LLM API keys
    5. Verifies everything works
#>

$ErrorActionPreference = "Stop"

# Colors for output (Standard ANSI)
$RED = "$([char]27)[0;31m"
$GREEN = "$([char]27)[0;32m"
$YELLOW = "$([char]27)[1;33m"
$BLUE = "$([char]27)[0;34m"
$CYAN = "$([char]27)[0;36m"
$BOLD = "$([char]27)[1m"
$DIM = "$([char]27)[2m"
$NC = "$([char]27)[0m" # No Color

function Prompt-YesNo {
    param(
        [string]$Question,
        [string]$Default = "y"
    )
    if ($Default -eq "y") {
        $prompt = "$Question [Y/n] "
    }
    else {
        $prompt = "$Question [y/N] "
    }
    
    $response = Read-Host -Prompt $prompt
    if ([string]::IsNullOrWhiteSpace($response)) {
        $response = $Default
    }
    
    return $response -match "^[Yy]"
}

function Prompt-Choice {
    param(
        [string]$Question,
        [string[]]$Options
    )
    
    Write-Host ""
    Write-Host -Object "${BOLD}$Question${NC}"
    
    for ($i = 0; $i -lt $Options.Count; $i++) {
        Write-Host -Object "  ${CYAN}$($i+1))${NC} $($Options[$i])"
    }
    Write-Host ""
    
    while ($true) {
        $choice = Read-Host -Prompt "Enter choice (1-$($Options.Count))"
        if ($choice -match "^\d+$" -and [int]$choice -ge 1 -and [int]$choice -le $Options.Count) {
            return [int]$choice - 1
        }
        Write-Host -Object "${RED}Invalid choice. Please enter 1-$($Options.Count)${NC}"
    }
}

function Run-PythonScript {
    param([string]$ScriptContent)
    
    $tempFile = [System.IO.Path]::GetTempFileName() + ".py"
    try {
        Set-Content -Path $tempFile -Value $ScriptContent
        $output = (uv run python $tempFile)
        return $output
    }
    finally {
        if (Test-Path $tempFile) { Remove-Item $tempFile }
    }
}

Clear-Host
Write-Host ""
Write-Host -Object "${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}"
Write-Host ""
Write-Host -Object "${BOLD}          A D E N   H I V E${NC}"
Write-Host ""
Write-Host -Object "${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}${DIM}-${NC}${YELLOW}*${NC}"
Write-Host ""
Write-Host -Object "${DIM}     Goal-driven AI agent framework${NC}"
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

Write-Host -Object "${YELLOW}*${NC} ${BLUE}${BOLD}Step 1: Checking Python...${NC}"
Write-Host ""

# Check for Python
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host -Object "${RED}Python is not installed.${NC}"
    Write-Host ""
    Write-Host "Please install Python 3.11+ from https://python.org"
    Write-Host "Then run this script again."
    exit 1
}

# Check version
try {
    $pyVerObj = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $pyMajor = python -c "import sys; print(sys.version_info.major)"
    $pyMinor = python -c "import sys; print(sys.version_info.minor)"
}
catch {
    Write-Host -Object "${RED}Failed to check Python version.${NC}"
    exit 1
}

if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 11)) {
    Write-Host -Object "${RED}Python 3.11+ is required (found $pyVerObj)${NC}"
    Write-Host ""
    Write-Host "Please upgrade your Python installation and run this script again."
    exit 1
}

Write-Host -Object "${GREEN}*${NC} Python $pyVerObj"
Write-Host ""

# Check for uv
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host -Object "${YELLOW}  uv not found. Installing...${NC}"
    
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    }
    catch {
        Write-Host -Object "${RED}Error: uv installation failed${NC}"
        Write-Host "Please install uv manually from https://astral.sh/uv/"
        exit 1
    }
    
    # Reload env to get new path
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Write-Host -Object "${RED}Error: uv installed but not found in PATH${NC}"
        Write-Host "Please restart your terminal and try again."
        exit 1
    }
    Write-Host -Object "${GREEN}  OK uv installed successfully${NC}"
}

$uvVer = uv --version
Write-Host -Object "${GREEN}  OK uv detected: $uvVer${NC}"
Write-Host ""


# ============================================================
# Step 2: Install Python Packages
# ============================================================

Write-Host -Object "${YELLOW}*${NC} ${BLUE}${BOLD}Step 2: Installing packages...${NC}"
Write-Host ""

Write-Host -Object "${DIM}This may take a minute...${NC}"
Write-Host ""

Write-Host -NoNewline "  Installing workspace packages... "

if (Test-Path "pyproject.toml") {
    try {
        uv sync > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host -Object "${GREEN}  OK workspace packages installed${NC}"
        }
        else {
            throw "uv sync failed"
        }
    }
    catch {
        Write-Host -Object "${RED}  FAIL workspace installation failed${NC}"
        exit 1
    }
}
else {
    Write-Host -Object "${RED}failed (no root pyproject.toml)${NC}"
    exit 1
}

# Install Playwright browser
Write-Host -NoNewline "  Installing Playwright browser... "
try {
    uv run python -c "import playwright" > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        uv run python -m playwright install chromium > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host -Object "${GREEN}ok${NC}"
        }
        else {
            Write-Host -Object "${YELLOW}SKIP${NC}"
        }
    }
    else {
        Write-Host -Object "${YELLOW}SKIP${NC}"
    }
}
catch {
    Write-Host -Object "${YELLOW}SKIP${NC}"
}

Write-Host ""
Write-Host -Object "${GREEN}*${NC} All packages installed"
Write-Host ""


# ============================================================
# Step 3: Configure LLM API Key
# ============================================================

Write-Host -Object "${YELLOW}*${NC} ${BLUE}${BOLD}Step 3: Configuring LLM provider...${NC}"
Write-Host ""

# Step 3b: Verify imports
Write-Host -Object "${BLUE}Step 3b: Verifying Python imports...${NC}"
Write-Host ""

$importErrors = 0

function Check-Import {
    param([string]$Module, [string]$Name)
    try {
        uv run python -c "import $Module" > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host -Object "${GREEN}  OK $Name imports OK${NC}"
            return $true
        }
    }
    catch {}
    
    Write-Host -Object "${RED}  FAIL $Name import failed${NC}"
    return $false
}

if (-not (Check-Import "framework" "framework")) { $importErrors++ }
if (-not (Check-Import "aden_tools" "aden_tools")) { $importErrors++ }

try {
    uv run python -c "import litellm" > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host -Object "${GREEN}  OK litellm imports OK${NC}"
    }
    else {
        Write-Host -Object "${YELLOW}  WARN litellm import issues (may be OK)${NC}"
    }
}
catch {}

try {
    uv run python -c "from framework.mcp import agent_builder_server" > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host -Object "${GREEN}  OK MCP server module OK${NC}"
    }
    else {
        Write-Host -Object "${RED}  FAIL MCP server module failed${NC}"
        $importErrors++
    }
}
catch {}

if ($importErrors -gt 0) {
    Write-Host ""
    Write-Host -Object "${RED}Error: $importErrors import(s) failed. Please check the errors above.${NC}"
    exit 1
}

Write-Host ""

# ============================================================
# Step 4: Configure LLM Provider
# ============================================================

Write-Host -Object "${BLUE}Step 4: Configuring LLM provider...${NC}"
Write-Host ""

$providers = @(
    @{ Id = "anthropic"; Name = "Anthropic (Claude)"; EnvVar = "ANTHROPIC_API_KEY"; DefaultModel = "claude-sonnet-4-5-20250929"; Signup = "https://console.anthropic.com/settings/keys" },
    @{ Id = "openai"; Name = "OpenAI (GPT)"; EnvVar = "OPENAI_API_KEY"; DefaultModel = "gpt-4o"; Signup = "https://platform.openai.com/api-keys" },
    @{ Id = "gemini"; Name = "Google Gemini"; EnvVar = "GEMINI_API_KEY"; DefaultModel = "gemini-3.0-flash-preview"; Signup = "https://aistudio.google.com/apikey" },
    @{ Id = "groq"; Name = "Groq"; EnvVar = "GROQ_API_KEY"; DefaultModel = "moonshotai/kimi-k2-instruct-0905"; Signup = "https://console.groq.com/keys" },
    @{ Id = "cerebras"; Name = "Cerebras"; EnvVar = "CEREBRAS_API_KEY"; DefaultModel = "zai-glm-4.7"; Signup = "https://cloud.cerebras.ai/" }
)

# Load existing .env
$envContent = @{}
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match "^([^#=]+)=(.*)") {
            $envContent[$matches[1]] = $matches[2]
            [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
    }
}
if (Test-Path "$HOME/.env") {
    Get-Content "$HOME/.env" | ForEach-Object {
        if ($_ -match "^([^#=]+)=(.*)") {
            $key = $matches[1]
            if (-not $envContent.ContainsKey($key)) {
                $envContent[$key] = $matches[2]
                [System.Environment]::SetEnvironmentVariable($key, $matches[2], "Process")
            }
        }
    }
}

$foundProviders = @()
foreach ($p in $providers) {
    if ([System.Environment]::GetEnvironmentVariable($p.EnvVar)) {
        $foundProviders += $p
    }
}

$selectedProvider = $null

if ($foundProviders.Count -gt 0) {
    Write-Host "Found API keys:"
    Write-Host ""
    foreach ($p in $foundProviders) {
        Write-Host -Object "  ${GREEN}*${NC} $($p.Name)"
    }
    Write-Host ""
    
    if ($foundProviders.Count -eq 1) {
        if (Prompt-YesNo "Use this key?") {
            $selectedProvider = $foundProviders[0]
            Write-Host ""
            Write-Host -Object "${GREEN}*${NC} Using $($selectedProvider.Name)"
        }
    }
    else {
        Write-Host -Object "${BOLD}Select your default LLM provider:${NC}"
        $choices = $foundProviders | ForEach-Object { $_.Name }
        $idx = Prompt-Choice "Select provider:" $choices
        $selectedProvider = $foundProviders[$idx]
        Write-Host ""
        Write-Host -Object "${GREEN}*${NC} Selected: $($selectedProvider.Name)"
    }
}

if ($null -eq $selectedProvider) {
    Write-Host "No API keys found. Let's configure one."
    Write-Host ""
    
    $providerOptions = @($providers.Name) + "Skip for now"
    $choiceIdx = Prompt-Choice "Select your LLM provider:" $providerOptions
    
    if ($choiceIdx -lt $providers.Count) {
        $selectedProvider = $providers[$choiceIdx]
        
        Write-Host ""
        Write-Host -Object "Get your API key from: ${CYAN}$($selectedProvider.Signup)${NC}"
        Write-Host ""
        
        $apiKey = Read-Host -Prompt "Paste your $($selectedProvider.Name) API key (or press Enter to skip)"
        
        if (-not [string]::IsNullOrWhiteSpace($apiKey)) {
            Add-Content -Path ".env" -Value ""
            Add-Content -Path ".env" -Value "$($selectedProvider.EnvVar)=$apiKey"
            [System.Environment]::SetEnvironmentVariable($selectedProvider.EnvVar, $apiKey, "Process")
            
            Write-Host ""
            Write-Host -Object "${GREEN}*${NC} API key saved to .env"
        }
        else {
            Write-Host ""
            Write-Host -Object "${YELLOW}Skipped.${NC} Add your API key to .env when ready."
            $selectedProvider = $null
        }
    }
    else {
        Write-Host ""
        Write-Host -Object "${YELLOW}Skipped.${NC}"
        Write-Host -Object "Add your API key later to .env"
    }
}

if ($selectedProvider) {
    Write-Host ""
    Write-Host -NoNewline "  Saving configuration... "
    
    $configDir = "$HOME/.hive"
    if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Path $configDir -Force | Out-Null }
    
    $configFile = "$configDir/configuration.json"
    $configData = @{
        llm        = @{
            provider        = $selectedProvider.Id
            model           = $selectedProvider.DefaultModel
            api_key_env_var = $selectedProvider.EnvVar
        }
        created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00")
    }
    
    $configJson = $configData | ConvertTo-Json -Depth 3
    Set-Content -Path $configFile -Value $configJson
    
    Write-Host -Object "${GREEN}*${NC}"
    Write-Host -Object "  ${DIM}~/.hive/configuration.json${NC}"
}

Write-Host ""

# ============================================================
# Step 5: Initialize Credential Store
# ============================================================

Write-Host -Object "${YELLOW}*${NC} ${BLUE}${BOLD}Step 5: Initializing credential store...${NC}"
Write-Host ""
Write-Host -Object "${DIM}The credential store encrypts API keys and secrets for your agents.${NC}"
Write-Host ""

$credKey = [System.Environment]::GetEnvironmentVariable("HIVE_CREDENTIAL_KEY")

if ($credKey) {
    Write-Host -Object "${GREEN}  OK HIVE_CREDENTIAL_KEY already set${NC}"
}

if (-not $credKey) {
    Write-Host -NoNewline "  Generating encryption key... "
    $genKey = $null
    
    try {
        $genKey = Run-PythonScript "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    }
    catch {
        Write-Host -Object "${RED}failed (uv error)${NC}"
    }

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($genKey)) {
        if (-not $genKey) { Write-Host -Object "${RED}failed${NC}" }
        Write-Host -Object "${YELLOW}  WARN Credential store will not be available.${NC}"
    }
    else {
        Write-Host -Object "${GREEN}ok${NC}"
        
        if (-not (Test-Path ".env")) { New-Item ".env" -ItemType File | Out-Null }
        Add-Content -Path ".env" -Value ""
        Add-Content -Path ".env" -Value "# Encryption key for Hive credential store (~/.hive/credentials)"
        Add-Content -Path ".env" -Value "HIVE_CREDENTIAL_KEY=$genKey"
        [System.Environment]::SetEnvironmentVariable("HIVE_CREDENTIAL_KEY", $genKey, "Process")
        
        Write-Host -Object "${GREEN}  OK Encryption key saved to .env${NC}"
        $credKey = $genKey
    }
}

if ($credKey) {
    $hiveCredDir = "$HOME/.hive/credentials"
    if (-not (Test-Path "$hiveCredDir/credentials")) { New-Item -ItemType Directory -Path "$hiveCredDir/credentials" -Force | Out-Null }
    if (-not (Test-Path "$hiveCredDir/metadata")) { New-Item -ItemType Directory -Path "$hiveCredDir/metadata" -Force | Out-Null }
    
    if (-not (Test-Path "$hiveCredDir/metadata/index.json")) {
        Set-Content -Path "$hiveCredDir/metadata/index.json" -Value "{}"
    }
    
    Write-Host -Object "${GREEN}  OK Credential store initialized at ~/.hive/credentials/${NC}"
    
    Write-Host -NoNewline "  Verifying credential store... "
    try {
        $check = Run-PythonScript "from framework.credentials.storage import EncryptedFileStorage; storage = EncryptedFileStorage(); print('ok')"
        if ($check -match "ok") {
            Write-Host -Object "${GREEN}ok${NC}"
        }
        else {
            Write-Host -Object "${YELLOW}--${NC}"
        }
    }
    catch {
        Write-Host -Object "${YELLOW}--${NC}"
    }
}

Write-Host ""

# ============================================================
# Step 6: Verify Setup
# ============================================================

Write-Host -Object "${YELLOW}*${NC} ${BLUE}${BOLD}Step 6: Verifying installation...${NC}"
Write-Host ""

$verifyErrors = 0

Write-Host -NoNewline "  - framework... "
if (Check-Import "framework" "") {
    # Check-Import prints ok/fail
}
else {
    $verifyErrors++
}


Write-Host -NoNewline "  - aden_tools... "
if (Check-Import "aden_tools" "") {
}
else {
    $verifyErrors++
}

Write-Host -NoNewline "  - litellm... "
try {
    uv run python -c "import litellm" > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host -Object "${GREEN}ok${NC}"
    }
    else {
        Write-Host -Object "${YELLOW}--${NC}"
    }
}
catch {
    Write-Host -Object "${YELLOW}--${NC}"
}

Write-Host ""

if ($verifyErrors -gt 0) {
    Write-Host -Object "${RED}Setup failed with $verifyErrors error(s).${NC}"
    Write-Host "Please check the errors above and try again."
    exit 1
}

# ============================================================
# Success!
# ============================================================

Clear-Host
Write-Host ""
Write-Host -Object "${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}"
Write-Host ""
Write-Host -Object "${GREEN}${BOLD}        ADEN HIVE - READY${NC}"
Write-Host ""
Write-Host -Object "${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}${DIM}-${NC}${GREEN}*${NC}"
Write-Host ""
Write-Host "Your environment is configured for building AI agents."
Write-Host ""

if ($selectedProvider) {
    Write-Host -Object "${BOLD}Default LLM:${NC}"
    Write-Host -Object "  ${CYAN}$($selectedProvider.Id)${NC} -> ${DIM}$($selectedProvider.DefaultModel)${NC}"
    Write-Host ""
}

if ($credKey) {
    Write-Host -Object "${BOLD}Credential Store:${NC}"
    Write-Host -Object "  ${GREEN}*${NC} ${DIM}~/.hive/credentials/${NC}  (encrypted)"
    Write-Host -Object "  ${DIM}Set up agent credentials with:${NC} ${CYAN}/setup-credentials${NC}"
    Write-Host ""
}

Write-Host -Object "${BOLD}Quick Start:${NC}"
Write-Host ""
Write-Host "  1. Open Claude Code in this directory:"
Write-Host -Object "     ${CYAN}claude${NC}"
Write-Host ""
Write-Host "  2. Build a new agent:"
Write-Host -Object "     ${CYAN}/agent-workflow${NC}"
Write-Host ""
Write-Host "  3. Test an existing agent:"
Write-Host -Object "     ${CYAN}/testing-agent${NC}"
Write-Host ""
Write-Host -Object "${BOLD}Examples:${NC} ${CYAN}exports/${NC}"
Write-Host ""
Write-Host -Object "${DIM}Run ./quickstart.ps1 again to reconfigure.${NC}"
Write-Host ""
