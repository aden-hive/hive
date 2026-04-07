function Get-WorkingUvInfo {
    <#
    .SYNOPSIS
        Find a runnable uv executable, not just a PATH entry named "uv"
    .OUTPUTS
        Hashtable with Path and Version, or $null if no working uv is found
    #>
    # pyenv-win can expose a uv shim that exists on PATH but fails at runtime.
    # Verify each candidate with `uv --version` before trusting it.
    $candidates = @()

    $commands = @(Get-Command uv -All -ErrorAction SilentlyContinue)
    foreach ($cmd in $commands) {
        if ($cmd.Source) {
            $candidates += $cmd.Source
        } elseif ($cmd.Definition) {
            $candidates += $cmd.Definition
        } elseif ($cmd.Name) {
            $candidates += $cmd.Name
        }
    }

    $defaultUvExe = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $defaultUvExe) {
        $candidates += $defaultUvExe
    }

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        try {
            $versionOutput = & $candidate --version 2>$null
            $version = ($versionOutput | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($version)) {
                return @{
                    Path = $candidate
                    Version = $version
                }
            }
        } catch {
            # Try the next candidate.
        }
    }

    return $null
}
