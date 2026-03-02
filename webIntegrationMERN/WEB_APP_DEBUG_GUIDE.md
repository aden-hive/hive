# Web App Fix - Debug Logging & Testing Guide

## Changes Made

### 1. Backend Debug Logging (agentWebService.js)

**startAgent() method:**

```javascript
// Now logs:
[Agent] Using Python: python
[Agent] Working directory: C:\Users\yokas\Desktop\m\hive\hive-web-dashboard\hive
[Agent] Shell: bash
[Agent Output] stdout: {...output...}
[Agent Output] stderr: {...errors...}
[Agent] Process closed with code: 0
[Agent] Total output length: 1234 bytes
[Agent] Session stored with ID: session-1707...

// On errors:
[Agent] CRITICAL Process spawn error: {error details}
[Agent] Error code: -4058
[Agent] Error syscall: spawn bash
```

**listAgents() method:**

```javascript
// Now logs:
[ListAgents] Using Python: python
[ListAgents] Working directory: C:\Users\yokas\Desktop\m\hive
[ListAgents] Shell: bash
[ListAgents] stdout: {...}
[ListAgents] Process closed with code: 0
[ListAgents] Agents output length: 523
```

### 2. Backend Route Logging (hiveRoutes.js)

```javascript
// POST /api/hive/run logs:
[Route] POST /api/hive/run received
[Route] Input: "I forgot my password"
[Route] Current execution state: idle
[Route] Request payload: {...}
[Route] Agent execution completed successfully
[Route] Result status: success
[Route] Output length: 1234
[Route] Session ID: session-1707...

// GET /api/hive/state logs:
[Route] GET /api/hive/state
[Route] Current state: {"executionState":"idle","lastMessage":null,"sessionCount":0}

// GET /api/hive/agents logs:
[Route] GET /api/hive/agents
[Route] Agents retrieved: customer_service_agent...
```

### 3. Frontend Debug Logging (AgentRunner.jsx)

```javascript
// handleRunAgent() logs:
[Web] ========== AGENT RUN START ==========
[Web] Input: "I forgot my password"
[Web] Input length: 20
[Web] Execution state: idle
[Web] Request payload: {"input":"I forgot my password"}
[Web] ========== AGENT RUN SUCCESS ==========
[Web] Response received: {...response object...}
[Web] Result status: success
[Web] Output length: 1234
[Web] Session ID: session-1707...

// On errors:
[Web] ========== AGENT RUN FAILED ==========
[Web] Error status: 500
[Web] Error data: {"error":"...error message..."}
[Web] Final error message: Agent failed to execute
```

### 4. Frontend Dashboard Logging (Dashboard.jsx)

```javascript
// fetchDashboardData() logs:
[Dashboard] Fetching dashboard data...
[Dashboard] Agents response: {...}
[Dashboard] Health response: {...}
[Dashboard] Agent count: 5
[Dashboard] Data fetch successful

// On errors:
[Dashboard] Error fetching data: Network error
[Dashboard] Error status: 500
```

### 5. Frontend Status Logging (Status.jsx)

```javascript
// fetchStatus() logs:
[Status] Fetching status...
[Status] Health response: {...}
[Status] Hive response: {...}
[Status] Status fetch successful

// On errors:
[Status] Error fetching status: ECONNREFUSED
```

## Testing Instructions

### Option 1: Use Test Script

```bash
cd hive-web-dashboard/backend

# Run all tests
bash scripts/test-api-bash.sh test-all

# Test individual endpoints
bash scripts/test-api-bash.sh health
bash scripts/test-api-bash.sh agents
bash scripts/test-api-bash.sh run-api "I forgot my password"
bash scripts/test-api-bash.sh run-direct "Can I reset my password?"
bash scripts/test-api-bash.sh history 10
```

### Option 2: Manual curl Testing

```bash
# Health check
curl http://localhost:5000/api/health

# List agents
curl http://localhost:5000/api/hive/agents

# Run agent
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"input": "I forgot my password"}'

# Check state
curl http://localhost:5000/api/hive/state
```

### Option 3: Web UI with Console Monitoring

1. **Start Backend:**

   ```bash
   cd hive-web-dashboard/backend
   npm run dev
   ```

   Watch for logs prefixed with `[Agent]`, `[Route]`, `[ListAgents]`

2. **Start Frontend:**

   ```bash
   cd hive-web-dashboard/frontend
   npm run dev
   ```

   Open http://localhost:5173

3. **Open Browser Console:**
   Press `F12` → Console tab → Filter for `[Web]`, `[Dashboard]`, `[Status]`

4. **Submit Agent Query:**
   Enter text in AgentRunner component
   Watch both frontend and backend logs in parallel

## Key Changes Summary

| Component          | Change                                                               | Purpose                              |
| ------------------ | -------------------------------------------------------------------- | ------------------------------------ |
| agentWebService.js | Added detailed logging to startAgent(), listAgents(), getAgentInfo() | Track Python process execution       |
| agentWebService.js | Improved error handling with specific error codes                    | Debug subprocess failures            |
| hiveRoutes.js      | Added request/response logging to all endpoints                      | Track API flow                       |
| AgentRunner.jsx    | Added comprehensive handleRunAgent() logging                         | Debug frontend-backend communication |
| Dashboard.jsx      | Added fetchDashboardData() logging                                   | Monitor dashboard data fetching      |
| Status.jsx         | Added fetchStatus() logging                                          | Monitor health checks                |
| test-api-bash.sh   | Created comprehensive API testing script                             | Manual endpoint testing              |

## How to Read the Logs

### When Everything Works

**Backend terminal shows:**

```
[Agent] Using Python: python
[Agent] Working directory: C:\Users\yokas\...
[Agent] Shell: bash
[Agent Output] stdout: I can help you reset your password...
[Agent] Process closed with code: 0
[Agent] Session stored with ID: session-1707482...
```

**Browser console shows:**

```
[Web] Input: "I forgot my password"
[Web] ========== AGENT RUN SUCCESS ==========
[Web] Output length: 523
[Web] Session ID: session-1707482...
```

### When Something Fails

**Backend terminal shows:**

```
[Agent] CRITICAL Process spawn error: Error: spawn bash ENOENT
[Agent] Error code: -4058
[Agent] Error syscall: spawn bash
```

**Browser console shows:**

```
[Web] ========== AGENT RUN FAILED ==========
[Web] Error status: 500
[Web] Error data: {"error":"spawn bash ENOENT"}
```

## Debugging Checklist

- [ ] Backend starts without errors: `npm run dev` shows "🚀 Hive Dashboard Backend running"
- [ ] Frontend starts without errors: `npm run dev` shows Vite dev server ready
- [ ] Browser console shows no critical errors (RED text)
- [ ] Backend logs appear when frontend makes requests
- [ ] Backend logs include `[Agent]`, `[Route]`, `[ListAgents]` prefixes
- [ ] Frontend logs include `[Web]`, `[Dashboard]`, `[Status]` prefixes
- [ ] Python command works in Git Bash: `python --version` shows version
- [ ] Bash is available: `bash --version` shows bash version
- [ ] Test script runs: `bash scripts/test-api-bash.sh health` succeeds

## Tech Stack Notes

The current architecture uses:

- **Node.js + Express** for web API
- **React + Vite** for frontend
- **Python subprocess** for agent execution
- **Bash shell** for subprocess communication (Git Bash compatible)

This is a valid architecture but has the challenge of cross-language subprocess communication. If you want to avoid these issues entirely, consider:

1. **FastAPI + React:** Native Python web framework - no subprocess needed
2. **Flask + React:** Lightweight Python alternative
3. **Python only:** Pure Python solution using FastAPI/Flask + frontend framework

These would eliminate the subprocess/PATH complexity while keeping the same modular design.
