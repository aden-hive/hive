# Complete Setup & Deployment Guide

Complete step-by-step guide to set up and deploy the Hive Web Dashboard locally and to production.

## Table of Contents

1. [Local Development Setup](#local-development-setup)
2. [Project Structure](#project-structure)
3. [Configuration](#configuration)
4. [Running the Application](#running-the-application)
5. [Docker Deployment](#docker-deployment)
6. [Production Deployment](#production-deployment)
7. [Troubleshooting](#troubleshooting)

---

## Local Development Setup

### Prerequisites

- **Node.js 16+** and **npm 7+**
- **Python 3.11+** (for Hive agents)
- **Hive CLI installed** and in your PATH
- **Git**
- **Windows users:** Use WSL 2 or Git Bash for terminal

### Step 1: Clone Repository

```bash
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard
```

### Step 2: Install Backend Dependencies

```bash
cd backend
npm install
```

### Step 3: Install Frontend Dependencies

```bash
cd ../frontend
npm install
```

### Step 4: Configure Environment

#### Backend Configuration

```bash
cd backend
cp .env.example .env
```

Edit `.env`:

```env
PORT=5000
HIVE_HOME=/c/Users/yokas/Desktop/m/hive/hive
NODE_ENV=development
```

#### Frontend Configuration

Frontend automatically proxies to `http://localhost:5000` (configured in `vite.config.js`)

### Step 5: Start Development Servers

**Terminal 1 - Backend:**

```bash
cd backend
npm run dev
```

Expected output:

```
🚀 Hive Dashboard Backend running on http://localhost:5000
📦 Integrations API available at /api/integrations
```

**Terminal 2 - Frontend:**

```bash
cd frontend
npm run dev
```

Expected output:

```
VITE v5.0.8  ready in 245 ms

➜  Local:   http://localhost:5173/
➜  press h to show help
```

### Step 6: Access Dashboard

Open your browser and navigate to:

```
http://localhost:5173
```

You should see the Hive Dashboard with:

- ✅ Status tab showing backend and Hive status
- ✅ Agents tab listing available agents
- ✅ Run Agent tab to execute agents
- ✅ Integrations tab for API configuration
- ✅ Dashboard tab with stats and charts

---

## Project Structure

```
hive-web-dashboard/
├── backend/
│   ├── src/
│   │   ├── server.js                    # Express app entry point
│   │   ├── controllers/
│   │   │   ├── hiveController.js       # Hive agent handlers
│   │   │   └── integrationController.js # Integration handlers
│   │   ├── services/
│   │   │   ├── hiveService.js          # Hive CLI wrapper
│   │   │   └── integrationService.js   # Integration logic
│   │   └── routes/
│   │       ├── hiveRoutes.js           # Hive endpoints
│   │       └── integrationRoutes.js    # Integration endpoints
│   ├── package.json
│   ├── .env.example
│   └── README.md
│
├── frontend/
│   ├── src/
│   │   ├── main.jsx                     # React entry
│   │   ├── App.jsx                      # Main app component
│   │   ├── App.css                      # App styles
│   │   ├── index.css                    # Global styles
│   │   └── components/
│   │       ├── Status.jsx               # Backend/Hive status
│   │       ├── AgentList.jsx            # Agent list view
│   │       ├── AgentRunner.jsx          # Run agents UI
│   │       ├── Integrations.jsx         # Manage integrations
│   │       ├── Dashboard.jsx            # Stats & charts
│   │       └── [component].css          # Component styles
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── README.md
│
├── INTEGRATION_GUIDE.md                 # Integration development guide
├── SETUP.md                             # This file
├── README.md                            # Project overview
└── .gitignore
```

---

## Configuration

### Backend Environment Variables

Create `backend/.env`:

```env
# Server
PORT=5000
NODE_ENV=development

# Hive
HIVE_HOME=/c/Users/yokas/Desktop/m/hive/hive
HIVE_PATH=/hive

# Security (for production)
JWT_SECRET=your-secret-key-here
CORS_ORIGIN=http://localhost:5173

# Logging
LOG_LEVEL=debug
```

### Frontend Environment Variables

Create `frontend/.env` (if needed):

```env
VITE_API_BASE_URL=http://localhost:5000/api
VITE_APP_NAME=Hive Dashboard
```

### Vite Configuration

`frontend/vite.config.js` includes API proxy:

```javascript
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: 'http://localhost:5000',
      changeOrigin: true,
    },
  },
}
```

---

## Running the Application

### Development Mode

```bash
# Terminal 1: Backend
cd backend
npm run dev

# Terminal 2: Frontend
cd frontend
npm run dev
```

Both servers hot-reload on file changes.

### Production Mode

```bash
# Build frontend
cd frontend
npm run build

# Start backend (production)
cd ../backend
NODE_ENV=production npm start
```

Frontend build output is in `frontend/dist/` - serve with:

```bash
npx serve frontend/dist
```

---

## Docker Deployment

### Docker Setup

Create `Dockerfile` in project root:

```dockerfile
# Multi-stage build
FROM node:18-alpine AS backend
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm ci --only=production
COPY backend/src ./src

FROM node:18-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM node:18-alpine
WORKDIR /app

# Copy backend
COPY --from=backend /app/backend ./backend

# Copy frontend dist
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Install Hive (requires Python setup)
RUN apk add --no-cache python3 py3-pip

EXPOSE 5000 3000
CMD ["node", "backend/src/server.js"]
```

### Build & Run Docker

```bash
# Build image
docker build -t hive-dashboard:latest .

# Run container
docker run -p 5000:5000 -p 3000:3000 \
  -e HIVE_HOME=/hive \
  hive-dashboard:latest
```

---

## Production Deployment

### Environment Setup

1. **Server Requirements:**
   - Ubuntu 20.04+ or similar
   - Node.js 18+ installed
   - Python 3.11+ installed
   - Hive CLI configured

2. **Security:**
   - Use HTTPS (SSL/TLS certificate)
   - Set strong JWT_SECRET
   - Configure firewall rules
   - Use environment variables for secrets

### Deployment Steps

1. **Clone repository:**

```bash
git clone https://github.com/adenhq/hive.git
cd hive-web-dashboard
```

2. **Install dependencies:**

```bash
cd backend && npm ci
cd ../frontend && npm ci
```

3. **Build frontend:**

```bash
cd frontend
npm run build
```

4. **Configure environment:**

```bash
cd backend
cp .env.example .env
# Edit .env with production values
```

5. **Start application:**

**Option A - Direct (for testing):**

```bash
cd backend
NODE_ENV=production npm start
```

**Option B - PM2 (recommended for production):**

```bash
npm install -g pm2

# Create ecosystem.config.js
cat > ecosystem.config.js << EOF
module.exports = {
  apps: [{
    name: 'hive-dashboard',
    script: './backend/src/server.js',
    instances: 'max',
    exec_mode: 'cluster',
    env: {
      NODE_ENV: 'production',
      PORT: 5000
    }
  }]
};
EOF

pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

**Option C - Docker (recommended for scalability):**

```bash
docker build -t hive-dashboard:prod .
docker run -d \
  -p 5000:5000 \
  -e NODE_ENV=production \
  --restart always \
  --name hive-dashboard \
  hive-dashboard:prod
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name api.hive.example.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}

server {
    listen 80;
    server_name dashboard.hive.example.com;

    location / {
        root /var/www/hive-dashboard/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://localhost:5000;
    }
}
```

### SSL/TLS Setup (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot certonly --nginx -d api.hive.example.com
sudo certbot certonly --nginx -d dashboard.hive.example.com

# Auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

---

## Troubleshooting

### Backend Won't Start

**Error:** `Cannot find module 'express'`

**Solution:**

```bash
cd backend
npm install
```

**Error:** `EADDRINUSE: address already in use :::5000`

**Solution:**

```bash
# Find process using port 5000
lsof -i :5000
# Kill it
kill -9 <PID>
```

### Frontend Can't Connect to Backend

**Error:** `Cannot GET /api/health`

**Solutions:**

1. Verify backend is running on port 5000
2. Check CORS in `backend/src/server.js`
3. Verify proxy configuration in `vite.config.js`
4. Check browser console for detailed error

### Hive Command Not Found

**Error:** `bash: hive: command not found`

**Solutions:**

1. Add Hive to PATH:

```bash
export PATH="/c/Users/yokas/Desktop/m/hive/hive:$PATH"
```

2. Verify installation:

```bash
hive --help
```

3. For Windows, use WSL or Git Bash

### Agent Execution Fails

**Error:** `Error running agent: command failed`

**Solutions:**

1. Verify agent exists: `hive list`
2. Check agent name is correct
3. Verify JSON input is valid
4. Check Hive logs for details

### Port Conflicts

**Error:** `Port 5173 already in use`

**Solution:** Change port in `vite.config.js`:

```javascript
server: {
  port: 5174,  // Change this
}
```

---

## Performance Optimization

### Frontend Optimization

1. **Lazy Loading:**

```javascript
const Dashboard = lazy(() => import("./components/Dashboard"));
```

2. **Build Optimization:**

```bash
cd frontend
npm run build  # Creates optimized dist/
```

3. **Caching:**

```bash
# Enable HTTP caching in nginx
expires 1d;
cache-control: public;
```

### Backend Optimization

1. **Connection Pooling:**

```javascript
const pool = new Pool({
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 2000,
});
```

2. **Request Compression:**

```javascript
const compression = require("compression");
app.use(compression());
```

3. **Rate Limiting:**

```javascript
const rateLimit = require("express-rate-limit");
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
});
app.use(limiter);
```

---

## Monitoring & Logging

### Application Logs

**Backend logs:**

```bash
# Direct output
npm run dev

# File logging (add to backend)
const fs = require('fs');
const logStream = fs.createWriteStream('app.log');
```

**Frontend logs:**

- Browser Console (F12)
- Network tab for API calls

### Health Checks

```bash
# Check backend
curl http://localhost:5000/api/health

# Check Hive
curl http://localhost:5000/api/hive/status
```

### Monitoring Tools

- **PM2 Monitoring:** `pm2 web` (http://localhost:9615)
- **Docker Stats:** `docker stats hive-dashboard`
- **Nginx Metrics:** Use Prometheus exporter

---

## Security Checklist

- [ ] Change default passwords
- [ ] Use strong JWT_SECRET
- [ ] Enable HTTPS/SSL
- [ ] Set CORS whitelist
- [ ] Validate all user inputs
- [ ] Store credentials securely
- [ ] Use environment variables for secrets
- [ ] Regular security updates
- [ ] Monitor access logs
- [ ] Implement rate limiting

---

## Next Steps

1. **Configure Integrations:** See `INTEGRATION_GUIDE.md`
2. **Deploy to Production:** Follow "Production Deployment" section
3. **Monitor Performance:** Set up logging and monitoring
4. **Scale Application:** Use Docker/Kubernetes for scalability

---

## Support

- **Issues:** https://github.com/adenhq/hive/issues
- **Discussions:** https://github.com/adenhq/hive/discussions
- **Documentation:** https://docs.adenhq.com

---

**Happy deploying! 🚀**
