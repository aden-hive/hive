# 🚀 Quick Start: Web Dashboard

## 30-Second Setup

### Terminal 1: Start Backend

```bash
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
npm install  # First time only
npm start
# Output: 🚀 Hive Dashboard Backend running on http://localhost:5000
```

### Terminal 2: Start Frontend

```bash
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\frontend
npm install  # First time only
npm run dev
# Output: Local: http://localhost:5173/
```

### Terminal 3: Set API Key (Important!)

```bash
# PowerShell
$env:ANTHROPIC_API_KEY="api-key-here"

# Then restart backend (Ctrl+C and npm start again)
```

---

## 🎉 You're Done!

Open browser: **http://localhost:5173**

Click on **"🤖 Agent Runner"** tab and start chatting!

---

## What You Can Do

### Example Queries:

- "I forgot my password"
- "How much does Product X cost?"
- "What's in my shopping cart?"
- "Where is my order?"

### Control Buttons:

- **Send** - Execute agent
- **Pause** - Pause execution
- **Resume** - Continue paused
- **Stop** - Cancel execution
- **History** - View previous sessions

---

## Troubleshooting

| Problem             | Solution                                                                  |
| ------------------- | ------------------------------------------------------------------------- |
| Backend won't start | Check port 5000 is free: `netstat -ano \| findstr 5000`                   |
| Frontend won't load | Check port 5173 is free, try different port: `npm run dev -- --port 5174` |
| Agent times out     | Agent runs for up to 10 minutes                                           |
| No response         | Check ANTHROPIC_API_KEY is set before starting backend                    |
| History is empty    | Create a new session by sending a query                                   |

---

## Architecture

```
Browser (http://localhost:5173)
    ↓ HTTP requests
Express Backend (http://localhost:5000/api/hive/*)
    ↓ Spawns Python subprocess
Python Agent (framework run customer_service_agent)
    ↓ Processes through 6 nodes
Returns response to frontend
```

---

## Next Steps

1. ✅ **Basic Testing** - Try example queries above
2. 📖 **Full Documentation** - See `WEB_INTEGRATION_GUIDE.md`
3. 🔧 **Customization** - Modify `AgentRunner.jsx` styling
4. 🚀 **Deployment** - Deploy to production (see guide)
5. 📊 **Analytics** - Add usage tracking (future)

---

## File Changes Made

```
✨ New/Updated Files:

Backend:
  - src/services/agentWebService.js         (NEW)
  - src/routes/hiveRoutes.js                (UPDATED)

Frontend:
  - src/components/AgentRunner.jsx          (UPDATED)
  - src/components/AgentRunner.css          (UPDATED)

Documentation:
  - WEB_INTEGRATION_GUIDE.md               (NEW)
  - WEB_QUICK_START.md                     (NEW - this file)
```

---

## API Endpoints

```
POST   /api/hive/run              Execute agent
GET    /api/hive/state            Get execution state
GET    /api/hive/history          Get session history
POST   /api/hive/pause            Pause execution
POST   /api/hive/resume           Resume execution
POST   /api/hive/stop             Stop execution
POST   /api/hive/clear-history    Clear history
GET    /api/hive/agents           List agents
GET    /api/hive/agents/:name     Get agent info
```

Test with curl:

```bash
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"input":"I forgot my password"}'
```

---

**Ready to go!** 🎉
