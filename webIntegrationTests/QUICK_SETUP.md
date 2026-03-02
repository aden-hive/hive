# ⚡ Quick Backend Setup - 5 Minutes

## The Issue

Node.js backend can't find Python when running from non-PowerShell terminals.

## The Fix

### Use PowerShell (Not Git Bash!)

```powershell
# Terminal 1: Start Backend
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
npm start

# Terminal 2: Start Frontend
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\frontend
npm run dev
```

### Verify It Works

- Backend: http://localhost:5000/api/health
- Frontend: http://localhost:5173
- Test: Submit "I forgot my password" in web UI

## If Still Broken

**Check Python PATH**:

```powershell
python --version           # Should work
where python              # Should show path
echo $env:ANTHROPIC_API_KEY  # Should show API key
```

**If Python not found**:

1. Install from https://www.python.org (check "Add to PATH")
2. Restart PowerShell
3. Try again

## Success Signs

- Backend console shows: `🚀 Hive Dashboard Backend running on http://localhost:5000`
- Frontend loads at http://localhost:5173
- No 500 errors in browser console
- Agent responses appear in UI

---

**Full guide**: `PYTHON_PATH_FIX.md`
