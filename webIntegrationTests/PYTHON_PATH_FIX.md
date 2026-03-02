# 🔧 Python PATH Fix - Backend Error Resolution

## Problem

```
Error: spawn python ENOENT
code: 'ENOENT'
syscall: 'spawn python'
```

**Root Cause**: Node.js backend cannot find Python executable in system PATH when spawning child process.

---

## Quick Fix (30 seconds)

### Option 1: PowerShell (Recommended)

Run the backend from **PowerShell** instead of Git Bash/CMD:

```powershell
# In PowerShell
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
npm start
```

**Why**: PowerShell has better Python integration on Windows.

---

### Option 2: Restart Command Prompt

Sometimes PATH isn't updated. Restart your terminal:

```cmd
# Close all terminals, then in NEW Command Prompt:
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
npm start
```

---

### Option 3: Add Python to PATH Permanently

#### For Windows 10/11:

1. **Find Python location**:

   ```powershell
   where python
   # Should output: C:\Users\yokas\AppData\Local\Programs\Python\Python312\python.exe
   ```

2. **If `where python` fails**:
   - Open **System Properties** → **Environment Variables**
   - Under "System variables", find or create `PATH`
   - Add your Python directory (e.g., `C:\Users\yokas\AppData\Local\Programs\Python\Python312`)
   - Click OK and restart terminal

3. **Verify**:
   ```powershell
   python --version
   # Should output: Python 3.x.x
   ```

---

## Verification Steps

### Step 1: Verify Python Installation

```powershell
python --version
python -m pip list
python -m framework version
```

All three should work without errors.

### Step 2: Start Backend with Debugging

```powershell
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
$env:DEBUG=* npm start
```

Look for this output:

```
🚀 Hive Dashboard Backend running on http://localhost:5000
```

### Step 3: Test API Endpoint

```powershell
# In another PowerShell window
Invoke-WebRequest http://localhost:5000/api/health -UseBasicParsing
```

Should return:

```json
{
  "status": "Backend is running",
  "version": "1.1.0",
  "features": ["hive-agents", "integrations", "credentials"],
  "timestamp": "2026-02-12T..."
}
```

### Step 4: Run Agent

```powershell
# Backend should be running (port 5000)
# Frontend running (port 5173)
# Test in browser console or curl:

curl -X POST http://localhost:5000/api/hive/run `
  -H "Content-Type: application/json" `
  -d '{\"input\": \"I forgot my password\"}'
```

---

## Terminal Compatibility Matrix

| Terminal                      | Python | Agent Works | Recommendation    |
| ----------------------------- | ------ | ----------- | ----------------- |
| PowerShell                    | ✅     | ✅          | **BEST**          |
| Command Prompt (cmd)          | ✅     | ✅          | Good              |
| Git Bash                      | ⚠️     | ❌          | Avoid for backend |
| Windows Terminal (PowerShell) | ✅     | ✅          | **BEST**          |

**Use PowerShell or Windows Terminal** for running the Node.js backend.

---

## Full Setup Checklist

- [ ] Python installed: `python --version`
- [ ] Python in PATH: `where python`
- [ ] Framework installed: `python -m framework version`
- [ ] Tools installed: `python -m pip list | grep aden`
- [ ] API Key set: `echo $env:ANTHROPIC_API_KEY` (should show key)
- [ ] Backend starts: `npm start` from backend folder
- [ ] Frontend starts: `npm run dev` from frontend folder
- [ ] Health check passes: `curl http://localhost:5000/api/health`
- [ ] Can run agent: POST to `/api/hive/run`

---

## Common Issues

### Issue: `python: command not found`

**Solution**:

```powershell
# Install Python from https://www.python.org/downloads/
# Choose "Add Python to PATH" during installation
# Restart terminal
```

### Issue: `ENOENT` after PATH update

**Solution**:

```powershell
# Close ALL terminals and command prompts
# Open NEW PowerShell window
# Test: python --version
```

### Issue: Module not found: `framework`

**Solution**:

```powershell
cd c:\Users\yokas\Desktop\m\hive
python -m pip install -e ./core
```

### Issue: ANTHROPIC_API_KEY not recognized

**Solution**:

```powershell
# Set for current session:
$env:ANTHROPIC_API_KEY="sk-ant-..."

# Verify:
echo $env:ANTHROPIC_API_KEY
```

---

## Debug Commands

Run these in sequence if you still have issues:

```powershell
# 1. Check Python
python --version
where python

# 2. Check Framework
python -m framework version

# 3. Check Tools
python -c "from framework import Agent; print('Framework OK')"

# 4. Check Node
node --version
npm --version

# 5. Start Backend with verbose logging
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
$env:NODE_DEBUG=* npm start

# 6. In another terminal, test endpoint
curl http://localhost:5000/api/health
```

---

## Still Not Working?

1. **Share these outputs**:

   ```powershell
   python --version
   where python
   echo $env:ANTHROPIC_API_KEY
   node -e "console.log(process.env.PATH)"
   ```

2. **Check backend error logs** - look for the exact error message in console

3. **Verify hive installation**:
   ```powershell
   cd c:\Users\yokas\Desktop\m\hive
   python -m framework list
   ```

---

## Success Indicators

✅ You'll see this when backend works:

```
🚀 Hive Dashboard Backend running on http://localhost:5000
📦 Integrations API available at /api/integrations
```

✅ Frontend will show no connection errors

✅ You can submit queries and get responses

---

**Last Updated**: February 12, 2026
**Status**: Ready to use
