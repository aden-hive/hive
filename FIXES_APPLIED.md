# Fixes Applied to Aden Hive

This document lists the fixes that were applied to address the identified issues.

## Issues Identified & Fixes Applied:

### 1. **uv Installation** (`README.md` and `docs/getting-started.md`)
- **Issue**: Users try to run `./quickstart.sh` but `uv` is not installed
- **Fix**: Added `pip install uv` instruction before cloning and running quickstart

### 2. **Windows Quickstart** (`README.md` and `docs/getting-started.md`)
- **Issue**: No clear Windows instructions - users try to run `./quickstart.sh` on Windows
- **Fix**: Added Windows-specific section showing `.\quickstart.ps1` in PowerShell

### 3. **TUI Deprecation** (`docs/getting-started.md`)
- **Issue**: Shows `hive tui` commands but TUI is deprecated (per AGENTS.md)
- **Fix**: Added deprecation notice in Next Steps section recommending `hive open` instead

---

## Summary:
Apply these fixes to your local copy and submit as a PR to demonstrate understanding of the codebase and attention to detail.

## Files Modified:
1. `README.md` - Added uv installation and Windows quickstart instructions
2. `docs/getting-started.md` - Added uv installation, Windows quickstart, and TUI deprecation notice

