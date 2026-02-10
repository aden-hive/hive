# Windows Setup Script for Aden Hive
$ErrorActionPreference = "Stop"

Write-Host "==> Checking for 'uv' package manager..." -ForegroundColor Cyan
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Host "uv is already installed." -ForegroundColor Green
} else {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$HOME\.local\bin;$env:Path"
}

Write-Host "`n==> Setting up Python 3.12..." -ForegroundColor Cyan
# This tells uv to fetch Python 3.12 and use it for this project
uv python install 3.12
uv python pin 3.12

Write-Host "`n==> Syncing dependencies..." -ForegroundColor Cyan
uv sync --all-extras

if ($?) {
    Write-Host "Dependencies installed successfully." -ForegroundColor Green
} else {
    Write-Host "Failed to sync dependencies." -ForegroundColor Red
    exit 1
}

Write-Host "`n==> Configuring environment..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env file from template." -ForegroundColor Green
    } else {
        # Create a blank .env if example is missing
        New-Item -Path ".env" -ItemType File -Force
        Write-Host "Created new .env file." -ForegroundColor Yellow
    }
} else {
    Write-Host ".env file already exists." -ForegroundColor Green
}

Write-Host "`n------------------------------------------------"
Write-Host "SETUP COMPLETE! 🚀" -ForegroundColor Green
Write-Host "To run the Hive dashboard, type:"
Write-Host "   uv run hive tui"
Write-Host "------------------------------------------------"