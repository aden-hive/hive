# WARNING: Destructive. Only run after revoking rotated secrets.
# Requires git-filter-repo installed and on PATH (https://github.com/newren/git-filter-repo)

param(
    [string]$RepoUrl = "https://github.com/waqasm86/hive.git",
    [string]$TempDir = "$env:TEMP\hive-filter-repo"
)

if (-Not (Get-Command git-filter-repo -ErrorAction SilentlyContinue)) {
    Write-Error "git-filter-repo not found. Install via 'pip install git-filter-repo' or follow docs."
    exit 1
}

if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }

Write-Output "Cloning mirror into $TempDir"
git clone --mirror $RepoUrl $TempDir

Set-Location $TempDir

Write-Output "Running git-filter-repo to remove .env"
# This removes the path .env from all commits
git filter-repo --invert-paths --paths ".env"

Write-Output "Force-pushing cleaned refs back to origin"
# Make sure remote URL is correct in the mirror; this will overwrite history
git remote set-url origin $RepoUrl

git push --force --all

Write-Output "Done. Instruct collaborators to re-clone and verify."
