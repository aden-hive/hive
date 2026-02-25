#Requires -Version 5.1
<#
.SYNOPSIS
    Benchmark script to measure import check performance

.DESCRIPTION
    Measures the time taken for import checks using both the old
    (individual subprocess) and new (batched) approaches.

.EXAMPLE
    .\scripts\benchmark_quickstart.ps1
#>

$ErrorActionPreference = "Stop"

# Get the directory where this script lives
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "=== Import Check Performance Benchmark ===" -ForegroundColor Cyan
Write-Host ""

# Find Python
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
    Write-Host "Python 3.11+ not found. Please install Python and try again." -ForegroundColor Red
    exit 1
}

Write-Host "Using Python: $PythonCmd" -ForegroundColor Green
Write-Host ""

# Define modules to check
$modules = @("framework", "aden_tools", "litellm", "framework.mcp.agent_builder_server")

# Benchmark old approach (individual subprocess calls)
Write-Host "Testing OLD approach (individual subprocess calls)..." -ForegroundColor Yellow
$oldTimes = @()

for ($i = 0; $i -lt 3; $i++) {
    $elapsed = Measure-Command {
        foreach ($module in $modules) {
            # Use 'python' instead of the detected command for uv run on Windows
            $null = & uv run python -c "import $module" 2>&1
            if ($LASTEXITCODE -ne 0) { 
                Write-Error "Installation failed: Could not import $module"
                exit 1 
            }
        }
    }
    $oldTimes += $elapsed.TotalMilliseconds
    Write-Host "  Run $($i + 1): $([math]::Round($elapsed.TotalMilliseconds, 2)) ms"
}

$oldAvg = ($oldTimes | Measure-Object -Average).Average
Write-Host ""
Write-Host "OLD approach average: $([math]::Round($oldAvg, 2)) ms" -ForegroundColor Cyan
Write-Host ""

# Benchmark new approach (batched)
Write-Host "Testing NEW approach (batched import checker)..." -ForegroundColor Yellow
$newTimes = @()

for ($i = 0; $i -lt 3; $i++) {
    $elapsed = Measure-Command {
        # Use 'python' for uv run on Windows
        $null = & uv run python scripts/check_requirements.py @modules 2>&1
    }
    $newTimes += $elapsed.TotalMilliseconds
    Write-Host "  Run $($i + 1): $([math]::Round($elapsed.TotalMilliseconds, 2)) ms"
}

$newAvg = ($newTimes | Measure-Object -Average).Average
Write-Host ""
Write-Host "NEW approach average: $([math]::Round($newAvg, 2)) ms" -ForegroundColor Cyan
Write-Host ""

# Calculate improvement
$improvement = $oldAvg - $newAvg
$improvementPercent = ($improvement / $oldAvg) * 100

Write-Host "=== Results ===" -ForegroundColor Green
Write-Host "Time saved: $([math]::Round($improvement, 2)) ms ($([math]::Round($improvementPercent, 1))% faster)" -ForegroundColor Green
Write-Host ""
