# 🎯 Web App & MCP Integration - Complete Guide

## Quick Navigation

### 🚀 Getting Started

- **[QUICK_WEB_REFERENCE.md](QUICK_WEB_REFERENCE.md)** - Start here for quick commands
- **[SESSION_SUMMARY.md](SESSION_SUMMARY.md)** - Overview of all fixes made

### 🔧 Implementation Details

- **[WEB_APP_DEBUG_GUIDE.md](WEB_APP_DEBUG_GUIDE.md)** - Comprehensive debugging & testing (850 lines)
- **[MCP_PATH_RESOLUTION_FIX.md](MCP_PATH_RESOLUTION_FIX.md)** - MCP server path fix (200 lines)
- **[GIT_BASH_INTEGRATION_GUIDE.md](GIT_BASH_INTEGRATION_GUIDE.md)** - Windows/Git Bash details

### 📊 Architecture & Analysis

- **[TECH_STACK_EVALUATION.md](TECH_STACK_EVALUATION.md)** - Tech stack comparison & recommendations
- **[PYTHON_PATH_FIX.md](PYTHON_PATH_FIX.md)** - Python path detection details

## What Was Fixed ✅

### Problem 1: Web App Agent Execution Failed

```
Error: spawn C:\WINDOWS\system32\cmd.exe ENOENT
```

**Solution:** Updated Node.js backend to use bash shell instead of cmd.exe
**Files Modified:**

- `hive-web-dashboard/backend/src/services/agentWebService.js`
- `hive-web-dashboard/backend/src/routes/hiveRoutes.js`

### Problem 2: TUI Agent Selection Failed

```
Failed to register MCP server: [WinError 267] The directory name is invalid
```

**Solution:** Fixed MCP config path resolution to use absolute paths
**Files Modified:**

- `hive/core/framework/runner/tool_registry.py`
- All `mcp_servers.json` files in templates

## How to Test

### Test 1: Web App (Recommended First)

```bash
# Terminal 1: Backend
cd hive-web-dashboard/backend
npm run dev

# Terminal 2: Frontend
cd hive-web-dashboard/frontend
npm run dev

# Browser: Open http://localhost:5173
# Test: Type a question in AgentRunner component
# Watch: Terminal 1 for [Agent] logs, Browser F12 for [Web] logs
```

### Test 2: API Directly

```bash
cd hive-web-dashboard/backend

# Run all tests
bash scripts/test-api-bash.sh test-all

# Or test individual endpoints
bash scripts/test-api-bash.sh health
bash scripts/test-api-bash.sh agents
bash scripts/test-api-bash.sh run-api "I forgot my password"
```

### Test 3: TUI Agent Selection

```bash
cd hive
python -m framework

# Select an agent
# Should connect to MCP server successfully ✅
```

## Key Features Added

### 1. Comprehensive Debug Logging

Every component now logs with prefixed messages:

- Backend: `[Agent]`, `[Route]`, `[ListAgents]`, `[Python]`
- Frontend: `[Web]`, `[Dashboard]`, `[Status]`
- Easy to filter in browser console and terminal

### 2. API Testing Script

**File:** `hive-web-dashboard/backend/scripts/test-api-bash.sh`

Commands:

```bash
bash test-api-bash.sh health          # Test backend health
bash test-api-bash.sh agents          # List available agents
bash test-api-bash.sh run-api "input" # Run agent via API
bash test-api-bash.sh run-direct "input" # Run agent directly
bash test-api-bash.sh history 10      # Get execution history
bash test-api-bash.sh test-all        # Run all tests
```

### 3. Automatic Path Resolution

MCP server configuration now uses `{HIVE_ROOT}` placeholder:

```json
{
  "hive-tools": {
    "cwd": "{HIVE_ROOT}/tools"
  }
}
```

- Automatically detects Hive root directory
- Works from any execution context
- Cross-platform compatible

## Documentation Overview

| Document                          | Content                    | Audience                           |
| --------------------------------- | -------------------------- | ---------------------------------- |
| **QUICK_WEB_REFERENCE.md**        | Quick commands & checklist | Developers (5 min read)            |
| **SESSION_SUMMARY.md**            | Complete session overview  | Project managers (10 min read)     |
| **WEB_APP_DEBUG_GUIDE.md**        | Detailed debugging guide   | Developers (20 min read)           |
| **MCP_PATH_RESOLUTION_FIX.md**    | MCP fix details            | Backend developers (15 min read)   |
| **TECH_STACK_EVALUATION.md**      | Architecture analysis      | Architects (30 min read)           |
| **GIT_BASH_INTEGRATION_GUIDE.md** | Windows integration        | DevOps/Windows users (15 min read) |

## Log Examples

### Success Case

```
Backend (Terminal 1):
[Agent] Using Python: python
[Agent] Working directory: C:\Users\yokas\...
[Agent] Shell: bash
[Agent Output] stdout: I can help you reset your password...
[Agent] Process closed with code: 0
[Agent] Session stored with ID: session-1707...

Frontend (Browser Console F12):
[Web] ========== AGENT RUN START ==========
[Web] Input: "I forgot my password"
[Web] Request payload: {"input":"I forgot my password"}
[Web] ========== AGENT RUN SUCCESS ==========
[Web] Response received: {...}
[Web] Output length: 523
```

### Failure Case - How to Debug

```
Backend shows:
[Agent] CRITICAL Process spawn error: Error: spawn bash ENOENT

This means: Bash not found. Check GIT_BASH_INTEGRATION_GUIDE.md

Frontend shows:
[Web] ========== AGENT RUN FAILED ==========
[Web] Error status: 500
[Web] Error data: {"error":"spawn bash ENOENT"}

Browser → Network tab shows: POST /api/hive/run 500 response

Solution: Install Git Bash or ensure bash is in PATH
```

## Architecture Flow

```
User Input (Browser)
       ↓
AgentRunner Component (React)
       ↓ [Web] logs
POST /api/hive/run
       ↓
Express Backend
       ↓ [Route] logs
hiveController.startAgent()
       ↓
agentWebService.startAgent()
       ↓ [Agent] logs
spawn bash -c "python -m framework run ..."
       ↓
Bash Shell (Git Bash on Windows, /bin/bash on Unix)
       ↓
Python Agent (Hive Framework)
       ↓
Claude API
       ↓
Agent Response
       ↓ [Agent Output] logs
Node.js collects stdout/stderr
       ↓
Response JSON sent to frontend
       ↓ [Web] logs
React displays result
```

## Common Issues & Solutions

### Issue: "bash ENOENT"

**Cause:** Bash shell not found
**Solution:** Install Git Bash from https://git-scm.com/

### Issue: "python command not found"

**Cause:** Python not in PATH
**Solution:** Install Python from https://www.python.org/
OR add Python to PATH

### Issue: "framework list command failed"

**Cause:** Hive framework not installed
**Solution:**

```bash
cd hive
pip install -e .
```

### Issue: "backend won't start"

**Cause:** Dependencies missing
**Solution:**

```bash
cd hive-web-dashboard/backend
npm install
npm run dev
```

### Issue: "frontend won't start"

**Cause:** Dependencies missing
**Solution:**

```bash
cd hive-web-dashboard/frontend
npm install
npm run dev
```

## Tech Stack Details

| Layer    | Technology                  | Purpose             |
| -------- | --------------------------- | ------------------- |
| Frontend | React 18 + Vite 5.4         | Web UI & components |
| Backend  | Node.js 22.14 + Express.js  | REST API            |
| Agent    | Python 3.x + Hive Framework | AI agent logic      |
| Shell    | Bash (Git Bash on Windows)  | Python subprocess   |
| LLM      | Anthropic Claude API        | AI responses        |

**Alternative Tech Stacks** (See TECH_STACK_EVALUATION.md):

- FastAPI + React (recommended alternative)
- Flask + React (simpler)
- Django + React (batteries included)

## Performance Baseline

Expected timings:

- Web UI request: 2-5 seconds (including agent execution)
- Agent response time: 1-3 seconds (depends on Claude latency)
- API health check: <100ms
- List agents: <200ms

## Deployment Checklist

Before deploying to production:

- [ ] Test web app locally with debug logging enabled
- [ ] Test API endpoints with test script
- [ ] Test TUI agent selection
- [ ] Verify Python is installed on deployment server
- [ ] Verify Bash is available (use sh as fallback)
- [ ] Set ANTHROPIC_API_KEY environment variable
- [ ] Configure logging aggregation
- [ ] Setup process monitoring (PM2 recommended)
- [ ] Load test with multiple concurrent requests

## Support Resources

### Documentation

- 📖 **WEB_APP_DEBUG_GUIDE.md** - Detailed troubleshooting
- 🔧 **TECH_STACK_EVALUATION.md** - Architecture decisions
- 🚀 **QUICK_WEB_REFERENCE.md** - Quick commands

### Scripts

- 🧪 **test-api-bash.sh** - API testing

### External Links

- [Hive Framework Docs](hive/README.md)
- [React Documentation](https://react.dev)
- [Express.js Guide](https://expressjs.com)
- [Vite Guide](https://vitejs.dev)

## Summary of Changes

### Code Changes

- ✅ Fixed Windows subprocess execution
- ✅ Fixed MCP path resolution
- ✅ Added comprehensive debug logging
- ✅ Created API testing script

### Documentation Created

- ✅ 2,700+ lines of new documentation
- ✅ 5 comprehensive guides
- ✅ Architecture diagrams & examples
- ✅ Troubleshooting guides

### Testing Infrastructure

- ✅ Bash-based API testing script
- ✅ Multiple test scenarios
- ✅ Manual testing instructions
- ✅ Log filtering examples

## Next Steps

1. **Read QUICK_WEB_REFERENCE.md** (5 minutes)
2. **Start backend & frontend** (5 minutes)
3. **Open browser to http://localhost:5173** (1 minute)
4. **Test with a sample query** (2 minutes)
5. **Monitor logs in both terminals** (ongoing)
6. **Use test script for API testing** (as needed)
7. **Reference WEB_APP_DEBUG_GUIDE.md for issues** (as needed)

---

**Session Completed:** February 13, 2026
**Status:** All fixes implemented & documented ✅
**Ready for Testing:** Yes
**Ready for Deployment:** After testing

For detailed information, see **SESSION_SUMMARY.md** and **WEB_APP_DEBUG_GUIDE.md**.
