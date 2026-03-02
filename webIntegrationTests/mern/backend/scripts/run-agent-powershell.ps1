# Script to manually run the Hive customer service agent via PowerShell
# This allows direct testing from PowerShell without the web frontend

$HiveDir = (Resolve-Path "$PSScriptRoot\..\..\..\..\hive").Path
$AgentInput = if ($args.Count -gt 0) { $args[0] } else { "I forgot my password" }

Write-Host "[Hive Agent] Starting agent execution via PowerShell..." -ForegroundColor Cyan
Write-Host "[Hive Agent] Hive directory: $HiveDir" -ForegroundColor Cyan
Write-Host "[Hive Agent] User input: '$AgentInput'" -ForegroundColor Cyan

Set-Location $HiveDir

# Set Python environment variable
$env:PYTHONUNBUFFERED = 1

# Run the agent
& python -m framework run customer_service_agent --input $AgentInput
