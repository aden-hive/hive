# Quick Win Issue - Windows Setup Documentation

## Title:
```
[Docs] Add Windows PowerShell setup instructions - breaks onboarding for 75% of developers
```

## Body:
```markdown
## Problem

`ENVIRONMENT_SETUP.md` only has Unix/Mac commands. Windows developers (75% market share) cannot set up without trial and error.

### What's Missing:

**1. Virtual Environment Activation:**
- Unix has: `source .venv/bin/activate`  
- Windows needs: `.venv\Scripts\Activate.ps1`

**2. Environment Variables:**
- Unix has: `export ANTHROPIC_API_KEY="..."`
- Windows needs: `$env:ANTHROPIC_API_KEY="..."`

**3. PYTHONPATH:**
- Unix: `PYTHONPATH=core:exports`
- Windows: `$env:PYTHONPATH="core;exports"` (semicolon, not colon!)

**4. Path Separators:**
- Unix uses: `/`
- Windows uses: `\`

## Impact

- High abandonment rate during setup
- Lost contributors
- Poor first impression
- Slower community growth

## Solution Implemented

Added Windows-specific instructions throughout ENVIRONMENT_SETUP.md:
- ✅ PowerShell commands
- ✅ CMD commands where applicable
- ✅ Path separator notes
- ✅ Side-by-side Unix/Windows examples

## Files Modified

- `ENVIRONMENT_SETUP.md` - Added Windows sections

## Why This Matters

As someone who just went through Windows setup, I experienced this firsthand. Clear OS-specific docs = faster onboarding.

---

**Already implemented. Ready for review.**
```
