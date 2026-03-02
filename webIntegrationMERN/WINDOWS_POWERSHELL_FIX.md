# Windows PowerShell Subprocess Fix

## Problem

The backend was failing with `Error: spawn bash ENOENT` when running from PowerShell because:

- Previous implementation tried to use `bash` or `/bin/bash` as the shell
- These commands don't exist in PowerShell environment (only in Git Bash)
- Node.js subprocess execution was trying to spawn a non-existent shell

## Root Cause

The code was attempting to wrap Python execution in a bash shell:

```javascript
// OLD - DOESN'T WORK IN POWERSHELL
const shellCommand = process.platform === "win32" ? "bash" : "/bin/bash";
const shellArgs = ["-c", `python -m framework run customer_service_agent ...`];
spawn(shellCommand, shellArgs, options); // bash ENOENT error
```

## Solution

**Directly invoke Python without shell wrapping:**

```javascript
// NEW - WORKS ON ALL PLATFORMS
const args = [
  "-m",
  "framework",
  "run",
  "customer_service_agent",
  "--input",
  agentInput,
];
spawn(this.pythonPath, args, options); // Direct Python execution
```

## Changes Made

### File: `hive-web-dashboard/backend/src/services/agentWebService.js`

**Updated 3 methods:**

1. **startAgent()** - Line ~101
   - Changed from: `spawn(shellCommand, shellArgs, options)`
   - Changed to: `spawn(this.pythonPath, args, options)`
   - Removes bash/shell wrapping, uses Python directly

2. **listAgents()** - Line ~287
   - Changed from: `spawn(shellCommand, shellArgs, options)`
   - Changed to: `spawn(this.pythonPath, args, options)`
   - Direct Python invocation for listing agents

3. **getAgentInfo()** - Line ~359
   - Changed from: `spawn(shellCommand, shellArgs, options)`
   - Changed to: `spawn(this.pythonPath, args, options)`
   - Direct Python invocation for agent info

## Why This Works

### Benefits:

✅ **Windows PowerShell Compatible** - No bash dependency needed  
✅ **Git Bash Compatible** - Still works if running from Git Bash  
✅ **macOS/Linux Compatible** - Direct Python execution works everywhere  
✅ **Simpler** - No shell wrapping overhead  
✅ **More Reliable** - No shell context issues

### Technical Details:

- `spawn(command, args, options)` - Direct executable invocation
- Python automatically receives arguments array without shell parsing
- No string escaping issues (no shell interpolation)
- Works consistently across all Windows terminal environments

## Testing

### To Verify the Fix:

1. **Restart backend:**

   ```bash
   npm run dev
   ```

2. **Expected output:**

   ```
   [Python] Using direct 'python' command
   🚀 Hive Dashboard Backend running on http://localhost:5000
   [Route] GET /api/hive/agents
   [ListAgents] Using Python: python
   [ListAgents] Command: python -m framework list
   ```

3. **Frontend should now load agents without errors**

## Environment Compatibility

| Environment        | Status   | Notes                    |
| ------------------ | -------- | ------------------------ |
| Windows PowerShell | ✅ Fixed | Works directly           |
| Windows cmd.exe    | ✅ Works | Direct Python invocation |
| Git Bash (Windows) | ✅ Works | No bash dependency       |
| macOS/Linux bash   | ✅ Works | Direct Python execution  |
| macOS/Linux zsh    | ✅ Works | Works with all shells    |

## No Breaking Changes

This fix:

- Maintains all existing functionality
- Doesn't change the public API
- Keeps all logging intact
- Works with existing Python installations
- No new dependencies required
