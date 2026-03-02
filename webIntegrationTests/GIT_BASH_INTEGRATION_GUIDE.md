# Git Bash Integration Guide - Hive Dashboard

## Overview

The Hive Dashboard web application runs Node.js in a Git Bash/WSL environment. This guide explains the current integration setup and provides manual linking scripts for testing the agent outside the web interface.

## Current Status

### ✅ What's Working

- **Web Dashboard Backend**: Running on `http://localhost:5000`
- **Frontend Interface**: Running on `http://localhost:5173`
- **Python Detection**: Correctly identifies `python` command in Git Bash PATH
- **API Endpoints**: All routes registered (`/api/hive/*`)

### ⚠️ Current Limitation

- **Subprocess Execution**: Git Bash environment uses `bash` as the shell, not `cmd.exe`
- **Shell Detection**: Must use `bash -c` for all subprocess calls in Git Bash

### 🔧 Solution Implemented

Updated `agentWebService.js` to use `bash` shell on all Windows systems when running through Node.js:

```javascript
const shellCommand = process.platform === "win32" ? "bash" : "/bin/bash";
const shellArgs = [
  "-c",
  `${pythonCmd} -m framework run customer_service_agent --input "${inputArg}"`,
];
spawn(shellCommand, shellArgs, options);
```

This approach:

1. ✅ Works in Git Bash environments
2. ✅ Works in WSL (Windows Subsystem for Linux)
3. ✅ Works on native Unix/Linux systems
4. ✅ Properly resolves `python` from PATH
5. ✅ Captures stdout/stderr correctly

## Manual Integration - Direct Bash Execution

If you want to test the agent directly in Git Bash without the web interface:

### Via Bash Script

```bash
# Make the script executable
chmod +x backend/scripts/run-agent-bash.sh

# Run with default prompt
./backend/scripts/run-agent-bash.sh

# Run with custom input
./backend/scripts/run-agent-bash.sh "What is your refund policy?"
```

### Via PowerShell

```powershell
# Run directly
.\backend\scripts\run-agent-powershell.ps1

# Run with custom input
.\backend\scripts\run-agent-powershell.ps1 "I need technical support"
```

### Via Git Bash Terminal (Direct)

```bash
# Navigate to hive directory
cd hive

# Set Python environment
export PYTHONUNBUFFERED=1

# Run agent with input
python -m framework run customer_service_agent --input "I forgot my password"
```

### Via PowerShell Terminal (Direct)

```powershell
# Navigate to hive directory
cd hive

# Set Python environment
$env:PYTHONUNBUFFERED = 1

# Run agent with input
python -m framework run customer_service_agent --input "I forgot my password"
```

## Testing the Web Integration

### 1. Start the Backend

```bash
cd hive-web-dashboard/backend
npm run dev
```

Expected output:

```
🚀 Hive Dashboard Backend running on http://localhost:5000
📦 Integrations API available at /api/integrations
[Python] Using direct 'python' command
```

### 2. Start the Frontend

In a new terminal:

```bash
cd hive-web-dashboard/frontend
npm run dev
```

Expected output:

```
VITE v5.4.21  ready in 1506 ms
  ➜  Local:   http://localhost:5173/
```

### 3. Test via Web Interface

1. Open `http://localhost:5173` in your browser
2. Type a message in the "Agent Input" text area
3. Click "Run Agent"
4. Wait for the response (may take 10-30 seconds)

### 4. Monitor Backend Logs

Watch the backend terminal for execution messages:

```
[Agent] Executing with input: "Your question here"
[Agent] Using Python: python
[Agent] Working directory: C:\Users\yokas\Desktop\m\hive\hive-web-dashboard\hive
[Agent] Shell: bash
```

Success:

```
[Agent Output]: <agent response>
```

Failure (would show):

```
[Agent Error]: Error message here
```

## Troubleshooting

### Issue: "spawn bash ENOENT"

**Cause**: Git Bash not installed or not in PATH
**Solution**:

```bash
# Check if bash is available
which bash

# If not found, install Git Bash from:
# https://git-scm.com/download/win
```

### Issue: "Python: command not found"

**Cause**: Python not in Git Bash PATH
**Solution**:

```bash
# Verify Python is installed
python --version

# Add Python to PATH if needed:
# 1. Find Python location
which python

# 2. Add to bashrc (if needed)
echo 'export PATH="/c/Users/yokas/AppData/Local/Programs/Python/Python314:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Issue: Agent runs but returns no output

**Cause**: Framework module not found or agent not configured
**Solution**:

```bash
# Verify Hive framework is set up
cd hive
python -m framework list

# If that fails:
pip install -e .

# Then test again
python -m framework run customer_service_agent --input "test"
```

### Issue: Backend not connecting to frontend

**Cause**: CORS configuration or proxy issue
**Solution**:

1. Check backend is running on port 5000
2. Check frontend vite proxy config in `vite.config.js`
3. Verify both services are on localhost (not 127.0.0.1)

## API Endpoints (for manual testing)

### Run Agent

```bash
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"input": "I forgot my password"}'
```

### List Agents

```bash
curl http://localhost:5000/api/hive/agents
```

### Get Agent Info

```bash
curl http://localhost:5000/api/hive/agents/customer_service_agent
```

### Get Execution State

```bash
curl http://localhost:5000/api/hive/state
```

### Get History

```bash
curl "http://localhost:5000/api/hive/history?limit=5"
```

## Architecture Notes

### Why Bash Instead of cmd.exe?

- Git Bash environment doesn't support `cmd.exe` natively
- `bash` is universally available across:
  - Git Bash on Windows
  - WSL (Windows Subsystem for Linux)
  - Native Linux/macOS systems
- Shell string execution (`bash -c "command"`) works identically across all platforms

### Process Execution Flow

1. **Web Request**: `POST /api/hive/run` with user input
2. **Backend Route**: Routes request to `agentWebService.startAgent(input)`
3. **Python Detection**: `findPython()` detects `"python"` in Git Bash PATH
4. **Shell Spawning**: `spawn("bash", ["-c", "python -m framework run ..."])`
5. **Agent Execution**: Python subprocess runs the Hive agent
6. **Output Capture**: stdout/stderr captured and returned to frontend
7. **Frontend Display**: Response shown in web dashboard

### Environment Variables

Set automatically by backend:

- `PYTHONUNBUFFERED=1` - Ensures unbuffered Python output
- `PATH` - Inherited from Git Bash environment
- `PYTHONHOME` - Not set (uses system default)

## Next Steps

If you want pure native Windows support (cmd.exe only):

1. Run Node.js from native Windows PowerShell (not Git Bash)
2. Use full path to Python: `C:\Users\yokas\AppData\Local\Python\bin\python.exe`
3. Modify `agentWebService.js` to use `cmd.exe` and full paths
4. Note: This breaks WSL and Git Bash compatibility

## Resources

- [Git Bash Documentation](https://git-scm.com/docs/bash)
- [Node.js child_process](https://nodejs.org/api/child_process.html)
- [Hive Framework Docs](../hive/docs/)
- [Backend API Routes](./hive-web-dashboard/backend/src/routes/hiveRoutes.js)

---

**Created**: February 12, 2026  
**Last Updated**: February 12, 2026  
**Status**: Integration compatible with Git Bash/WSL environments
