# Quick Reference: Web App Debugging & Testing

## 🚀 Start Everything

```bash
# Terminal 1: Backend
cd hive-web-dashboard/backend
npm run dev

# Terminal 2: Frontend
cd hive-web-dashboard/frontend
npm run dev

# Then open: http://localhost:5173
```

## 📊 Monitor Logs

### Backend Logs (Terminal 1)

Look for these prefixes:

```
[Agent] ...           - Agent execution logs
[Route] ...          - API request logs
[ListAgents] ...     - Agent listing logs
[Python] ...         - Python path detection
```

### Frontend Logs (Browser F12 → Console)

Look for these prefixes:

```
[Web] ...            - AgentRunner component
[Dashboard] ...      - Dashboard component
[Status] ...         - Status component
```

## ✅ Quick Testing

### Test 1: API Health Check

```bash
curl http://localhost:5000/api/health
```

### Test 2: List Agents

```bash
curl http://localhost:5000/api/hive/agents
```

### Test 3: Run Agent

```bash
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"input": "I forgot my password"}'
```

### Test 4: Using Script

```bash
cd hive-web-dashboard/backend
bash scripts/test-api-bash.sh test-all
```

## 🔍 Debugging Checklist

- [ ] Backend running? Check terminal 1 for "🚀 Hive Dashboard Backend running"
- [ ] Frontend running? Check terminal 2 for "VITE v5.4.21 ready"
- [ ] Browser console clear? Press F12, check console tab
- [ ] Logs appearing? Submit form and watch both terminals
- [ ] Python found? Check backend logs for "[Python] Using direct 'python' command"
- [ ] Bash available? Backend should use "bash" shell

## 📝 Common Log Patterns

### Success Pattern

```
Backend:
[Agent] Using Python: python
[Agent] Working directory: C:\Users\yokas\...
[Agent] Shell: bash
[Agent Output] stdout: I can help you...
[Agent] Process closed with code: 0

Frontend:
[Web] ========== AGENT RUN SUCCESS ==========
[Web] Output length: 523
```

### Failure Pattern

```
Backend:
[Agent] CRITICAL Process spawn error: Error: spawn bash ENOENT
[Agent] Error code: -4058

Frontend:
[Web] ========== AGENT RUN FAILED ==========
[Web] Error status: 500
```

## 🛠️ Quick Fixes

### Backend won't start

```bash
cd hive-web-dashboard/backend
npm install
npm run dev
```

### Frontend won't start

```bash
cd hive-web-dashboard/frontend
npm install
npm run dev
```

### Python not found

```bash
# Check Python
python --version

# If not found, install from https://www.python.org/downloads/
```

### Bash not found

```bash
# Check bash
bash --version

# If not found, install Git Bash from https://git-scm.com/
```

### Agent execution fails

```bash
# Test directly
cd hive-web-dashboard/hive
python -m framework run customer_service_agent --input "test"
```

## 📁 Key Files

| File                                      | Purpose                     |
| ----------------------------------------- | --------------------------- |
| `backend/src/services/agentWebService.js` | Python subprocess execution |
| `backend/src/routes/hiveRoutes.js`        | API endpoints               |
| `frontend/src/components/AgentRunner.jsx` | Agent input form            |
| `frontend/src/components/Dashboard.jsx`   | Statistics display          |
| `backend/scripts/test-api-bash.sh`        | API testing script          |

## 🌐 URLs

| Service     | URL                                     |
| ----------- | --------------------------------------- |
| Frontend    | http://localhost:5173                   |
| Backend API | http://localhost:5000                   |
| API Health  | http://localhost:5000/api/health        |
| Agents List | http://localhost:5000/api/hive/agents   |
| Agent Run   | POST http://localhost:5000/api/hive/run |

## 📖 Documentation

- `WEB_APP_DEBUG_GUIDE.md` - Detailed logging and testing guide
- `GIT_BASH_INTEGRATION_GUIDE.md` - Git Bash/Windows integration details
- `TECH_STACK_EVALUATION.md` - Tech stack comparison and recommendations
- `PYTHON_PATH_FIX.md` - Python path detection troubleshooting

## 💡 Pro Tips

1. **Keep logs visible:** Use `| tee` to save logs to file

   ```bash
   npm run dev | tee backend.log
   ```

2. **Filter logs:** Use `grep` to find specific logs

   ```bash
   grep "\[Agent\]" backend.log
   ```

3. **Monitor in real-time:** Open new terminal and `tail`

   ```bash
   tail -f backend.log
   ```

4. **Test without UI:** Use the bash script

   ```bash
   bash scripts/test-api-bash.sh run-api "your input"
   ```

5. **Browser DevTools:**
   - F12 → Console: See frontend logs
   - F12 → Network: See API requests/responses
   - F12 → Application: See stored data

## 🎯 Next Steps

1. Start both backend and frontend
2. Open browser console (F12)
3. Submit a test query in AgentRunner
4. Check both:
   - Backend terminal logs
   - Browser console logs
5. If error, read the detailed logs and check:
   - Is Python available?
   - Is Bash available?
   - Are there permission issues?
   - Is the Hive framework installed?

## 📞 Getting Help

1. **Read the logs carefully** - They now include detailed context
2. **Use the test script** - `bash scripts/test-api-bash.sh test-all`
3. **Check the guides:**
   - For subprocess issues → `GIT_BASH_INTEGRATION_GUIDE.md`
   - For tech stack questions → `TECH_STACK_EVALUATION.md`
   - For Python path problems → `PYTHON_PATH_FIX.md`
4. **Isolate the problem:**
   - Test Python directly
   - Test API with curl
   - Test UI in browser

---

**Last updated:** February 13, 2026
**Status:** Web app debugging and testing infrastructure complete ✅
