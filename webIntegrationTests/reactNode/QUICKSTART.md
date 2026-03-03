# 🚀 Quick Start Guide

Get the Hive Web Dashboard running in 5 minutes!

## 5-Minute Setup

### Step 1: Install Dependencies (2 minutes)

**Backend:**

```bash
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard\backend
npm install
```

**Frontend:**

```bash
cd ..\frontend
npm install
```

### Step 2: Configure Environment (1 minute)

Edit `backend/.env`:

```bash
PORT=5000
HIVE_HOME=/c/Users/yokas/Desktop/m/hive/hive
NODE_ENV=development
```

### Step 3: Start Servers (1 minute)

**Terminal 1 - Backend:**

```bash
cd backend
npm run dev
```

You should see:

```
🚀 Hive Dashboard Backend running on http://localhost:5000
📦 Integrations API available at /api/integrations
```

**Terminal 2 - Frontend:**

```bash
cd frontend
npm run dev
```

You should see:

```
VITE v5.0.8  ready in 245 ms
➜  Local:   http://localhost:5173/
```

### Step 4: Open Dashboard (1 minute)

Open your browser: `http://localhost:5173`

Done! 🎉

---

## First Steps in Dashboard

### 1. Check Status (30 seconds)

- Click **📊 Status** tab
- See Backend and Hive health
- Both should show ✓ Online

### 2. List Agents (30 seconds)

- Click **🤖 Agents** tab
- See all exported Hive agents
- If empty, you don't have agents exported yet

### 3. Run an Agent (1 minute)

- Click **▶️ Run Agent** tab
- Enter an agent name
- Paste JSON input: `{"key": "value"}`
- Click **▶️ Run Agent**
- See results instantly

### 4. Configure Integration (2 minutes)

- Click **🔌 Integrations** tab
- Select an integration (e.g., Slack)
- Enter credentials
- Click **💾 Save Configuration**
- Click **🧪 Test Connection**

### 5. View Dashboard (1 minute)

- Click **📈 Dashboard** tab
- See statistics and charts
- Watch real-time updates

---

## Troubleshooting Quick Fixes

### Backend Won't Start

```bash
cd backend
npm install
npm run dev
```

### Can't Find Hive Command

```bash
# Add Hive to PATH
export PATH="/c/Users/yokas/Desktop/m/hive/hive:$PATH"
```

### Frontend Won't Connect

- Check backend is running (http://localhost:5000/api/health)
- Check browser console (F12) for errors
- Verify CORS is enabled

### Port Already in Use

```bash
# Change port in vite.config.js
server: {
  port: 5174,  // Change to different port
}
```

---

## Next Steps

### Learn More

1. Read **PROJECT_SUMMARY.md** - Full overview
2. Read **SETUP.md** - Detailed setup guide
3. Read **INTEGRATION_GUIDE.md** - Add integrations

### Try It Out

1. ✅ List your Hive agents
2. ✅ Run an agent from dashboard
3. ✅ Configure Slack integration
4. ✅ Test integration connection

### Deploy to Production

1. Follow **SETUP.md** - Production section
2. Use Docker or PM2
3. Configure nginx reverse proxy
4. Set up SSL/TLS

---

## Command Reference

### Backend Commands

```bash
npm run dev        # Start development server
npm start          # Start production server
npm install        # Install dependencies
```

### Frontend Commands

```bash
npm run dev        # Start dev server
npm run build      # Build for production
npm run preview    # Preview build
npm install        # Install dependencies
```

### Hive Commands

```bash
hive --help        # Show help
hive list          # List agents
hive run exports/agent_name --input '{...}'  # Run agent
hive tui           # Interactive dashboard
```

---

## File Locations

| What         | Where                                        |
| ------------ | -------------------------------------------- |
| Backend      | `hive-web-dashboard/backend/`                |
| Frontend     | `hive-web-dashboard/frontend/`               |
| Docs         | `hive-web-dashboard/*.md`                    |
| Components   | `frontend/src/components/`                   |
| API Routes   | `backend/src/routes/`                        |
| Integrations | `backend/src/services/integrationService.js` |

---

## What Each Tab Does

| Tab              | Purpose        | Actions                  |
| ---------------- | -------------- | ------------------------ |
| **Status**       | Check health   | See backend/Hive status  |
| **Agents**       | List agents    | View all exported agents |
| **Run**          | Execute agents | Run with JSON input      |
| **Integrations** | Manage APIs    | Configure credentials    |
| **Dashboard**    | Stats & charts | View metrics             |

---

## URLs Reference

| Service      | URL                                    |
| ------------ | -------------------------------------- |
| Dashboard    | http://localhost:5173                  |
| Backend API  | http://localhost:5000                  |
| Health Check | http://localhost:5000/api/health       |
| Integrations | http://localhost:5000/api/integrations |

---

## Environment Variables

Set in `backend/.env`:

```env
# Server
PORT=5000                    # API port
NODE_ENV=development         # Environment

# Hive
HIVE_HOME=/path/to/hive     # Hive installation

# Optional
LOG_LEVEL=debug             # Logging level
CORS_ORIGIN=http://localhost:5173  # CORS
```

---

## API Quick Reference

### Check if Backend Works

```bash
curl http://localhost:5000/api/health
```

### List Agents

```bash
curl http://localhost:5000/api/hive/agents
```

### List Integrations

```bash
curl http://localhost:5000/api/integrations
```

### Run Agent

```bash
curl -X POST http://localhost:5000/api/hive/run \
  -H "Content-Type: application/json" \
  -d '{"agentName":"my_agent","input":{}}'
```

---

## Common Issues & Fixes

### Issue: Backend Can't Find Hive

**Fix:** Ensure Hive is in PATH

```bash
which hive          # Check if installed
hive --help         # Test if works
```

### Issue: Port Already in Use

**Fix:** Kill process or change port

```bash
# Find process on port 5000
lsof -i :5000
# Kill it
kill -9 <PID>
```

### Issue: Frontend Can't Reach Backend

**Fix:** Check backend is running

```bash
curl http://localhost:5000/api/health
```

### Issue: Permissions Denied

**Fix:** For Windows, use WSL or Git Bash

```bash
# Install WSL 2 or use Git Bash
bash  # Start bash
```

---

## Useful Resources

### Documentation

- **PROJECT_SUMMARY.md** - Full overview
- **SETUP.md** - Setup & deployment
- **INTEGRATION_GUIDE.md** - Build integrations
- **README.md** - Main project docs
- **FILE_MANIFEST.md** - File reference

### External Links

- Hive Docs: https://docs.adenhq.com
- GitHub: https://github.com/adenhq/hive
- Node.js: https://nodejs.org
- React: https://react.dev
- Vite: https://vitejs.dev

---

## Support

**Having Issues?**

1. Check troubleshooting section above
2. Read SETUP.md for detailed info
3. Check backend/frontend console logs
4. Open GitHub issue
5. Join Discord community

---

## Success Checklist

- [ ] Installed Node.js 16+
- [ ] Installed npm 7+
- [ ] Hive CLI is installed
- [ ] Cloned/navigated to project
- [ ] Installed backend dependencies
- [ ] Installed frontend dependencies
- [ ] Created backend/.env
- [ ] Started backend server
- [ ] Started frontend server
- [ ] Opened dashboard at localhost:5173
- [ ] Checked Status tab
- [ ] Listed agents
- [ ] Can see dashboard

**If all checked: You're ready to go! 🚀**

---

## Next Level

### Deploy to Production

Follow **SETUP.md** → Production Deployment section

### Add Custom Integration

Follow **INTEGRATION_GUIDE.md** → Building Custom Integrations

### Extend Dashboard

Add new components to `frontend/src/components/`

---

**You're all set! Enjoy the Hive Dashboard! 🐝**
