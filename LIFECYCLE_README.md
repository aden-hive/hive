# 🚀 Lifecycle API Implementation for Hive

## 📍 Location
This directory contains the complete implementation for adding **Lifecycle Management APIs** to the Hive agent framework.

## 📦 What's Included

### ✅ Implementation Files (Ready to Use)

1. **`core/framework/runtime/lifecycle_server.py`**
   - Complete FastAPI-based HTTP server
   - All lifecycle endpoints implemented
   - Health check endpoints for Kubernetes
   - Prometheus metrics support
   - ~500 lines of production-ready code

2. **`Dockerfile.lifecycle`**
   - Production-ready Docker configuration
   - Multi-stage build for smaller images
   - Non-root user for security
   - Health checks configured
   - Graceful shutdown handling

3. **`examples/kubernetes/deployment.yaml`**
   - Complete Kubernetes deployment manifest
   - Liveness and readiness probes
   - HorizontalPodAutoscaler for auto-scaling
   - PodDisruptionBudget for HA
   - ConfigMap and Secret management

### 📚 Documentation

4. **`docs/LIFECYCLE_API_IMPLEMENTATION_PLAN.md`**
   - Complete technical design
   - API specifications
   - Implementation phases
   - Verification strategy

5. **`docs/GITHUB_ISSUE_LIFECYCLE_API.md`**
   - Ready-to-submit GitHub issue
   - Problem statement
   - Proposed solution
   - Acceptance criteria

6. **`d:\Ycomb\SUMMARY.md`**
   - Project analysis
   - Next steps guide
   - Quick reference

---

## 🎯 Quick Start

### Prerequisites

⚠️ **Important**: You need Python 3.11+ (currently have 3.10.0)

```powershell
# Check Python version
python --version

# If < 3.11, download from python.org or use conda
conda create -n hive python=3.11
conda activate hive
```

### Installation

```powershell
# Navigate to hive directory
cd d:\Ycomb\hive

# Install core framework
cd core
pip install -e .

# Install tools
cd ..\tools
pip install -e .

# Install lifecycle server dependencies
pip install fastapi uvicorn[standard] pydantic pytest
```

### Test the Lifecycle Server

```powershell
# Navigate to project root
cd d:\Ycomb\hive

# Run the lifecycle server (mock mode for testing)
python core/framework/runtime/lifecycle_server.py --agent exports/test-agent --port 8080
```

In another terminal:
```powershell
# Test health endpoints
curl http://localhost:8080/health/live
curl http://localhost:8080/health/ready
curl http://localhost:8080/api/v1/status

# Test lifecycle operations
curl -X POST http://localhost:8080/api/v1/lifecycle/start
curl -X POST http://localhost:8080/api/v1/lifecycle/pause
curl -X POST http://localhost:8080/api/v1/lifecycle/resume
curl -X POST http://localhost:8080/api/v1/lifecycle/stop
```

---

## 🐳 Docker Deployment

### Build the Image

```powershell
cd d:\Ycomb\hive

# Build Docker image
docker build -f Dockerfile.lifecycle -t hive-agent:latest .
```

### Run the Container

```powershell
# Run with lifecycle server enabled
docker run -d `
  --name hive-agent `
  -p 8080:8080 `
  -e HIVE_LIFECYCLE_ENABLED=true `
  -e ANTHROPIC_API_KEY=your-key `
  hive-agent:latest

# Check health
curl http://localhost:8080/health/live
curl http://localhost:8080/api/v1/status

# View logs
docker logs -f hive-agent

# Graceful shutdown
docker stop --time=35 hive-agent
```

---

## ☸️ Kubernetes Deployment

### Deploy to Kubernetes

```powershell
# Create secrets
kubectl create secret generic hive-secrets `
  --from-literal=anthropic-api-key=YOUR_KEY

# Apply deployment
kubectl apply -f examples/kubernetes/deployment.yaml

# Check status
kubectl get pods
kubectl get deployments
kubectl get services

# Port forward to test locally
kubectl port-forward svc/hive-agent-service 8080:8080

# Test endpoints
curl http://localhost:8080/health/live
curl http://localhost:8080/api/v1/status
```

### Monitor the Deployment

```powershell
# Watch pods
kubectl get pods -w

# Check health probes
kubectl describe pod hive-agent-xxx | Select-String "Liveness|Readiness" -Context 5

# View logs
kubectl logs -f deployment/hive-agent

# Check auto-scaling
kubectl get hpa
kubectl top pods
```

---

## 📋 API Endpoints Reference

### Lifecycle Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/lifecycle/start` | POST | Start agent runtime |
| `/api/v1/lifecycle/stop` | POST | Stop gracefully |
| `/api/v1/lifecycle/pause` | POST | Pause execution |
| `/api/v1/lifecycle/resume` | POST | Resume execution |
| `/api/v1/lifecycle/restart` | POST | Restart runtime |

### Health & Status

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health/live` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe |
| `/api/v1/status` | GET | Detailed status |
| `/api/v1/status/streams` | GET | Active streams |
| `/metrics` | GET | Prometheus metrics |

---

## 🧪 Testing

### Run Unit Tests

```powershell
cd d:\Ycomb\hive

# Run all tests
pytest core/framework/runtime/tests/ -v

# Run specific test file
pytest core/framework/runtime/tests/test_lifecycle_server.py -v

# Run with coverage
pytest core/framework/runtime/tests/ --cov=framework.runtime --cov-report=html
```

### Manual Testing Checklist

- [ ] Start runtime via API
- [ ] Stop runtime gracefully
- [ ] Pause runtime (verify in-flight work completes)
- [ ] Resume runtime
- [ ] Health probes return correct status
- [ ] Graceful shutdown with SIGTERM
- [ ] Docker health checks work
- [ ] Kubernetes probes work
- [ ] Zero-downtime rolling update

---

## 🔧 Configuration

### Environment Variables

```bash
# Lifecycle Server
HIVE_LIFECYCLE_ENABLED=true          # Enable lifecycle server
HIVE_LIFECYCLE_PORT=8080             # Server port
HIVE_LIFECYCLE_HOST=0.0.0.0          # Server host
HIVE_GRACEFUL_SHUTDOWN_TIMEOUT=30    # Shutdown timeout (seconds)
HIVE_LIFECYCLE_METRICS=true          # Enable Prometheus metrics
HIVE_LIFECYCLE_CORS=false            # Enable CORS

# LLM API Keys
ANTHROPIC_API_KEY=your-key
OPENAI_API_KEY=your-key
```

---

## 📝 Next Steps

### 1. Submit GitHub Issue

Go to: https://github.com/adenhq/hive/issues/new

Copy content from: `docs/GITHUB_ISSUE_LIFECYCLE_API.md`

### 2. Fork Repository

```powershell
# On GitHub, fork adenhq/hive to your account
# Then clone your fork
cd d:\Ycomb
git clone https://github.com/YOUR_USERNAME/hive.git hive-fork
cd hive-fork
git remote add upstream https://github.com/adenhq/hive.git
```

### 3. Create Feature Branch

```powershell
cd d:\Ycomb\hive-fork
git checkout -b feature/lifecycle-apis
```

### 4. Implement & Test

```powershell
# Copy files from this directory to your fork
# Run tests
pytest core/framework/runtime/tests/ -v

# Commit changes
git add .
git commit -m "feat: Add lifecycle management APIs"
git push origin feature/lifecycle-apis
```

### 5. Create Pull Request

- Go to your fork on GitHub
- Click "New Pull Request"
- Use the PR template from `docs/GITHUB_ISSUE_LIFECYCLE_API.md`

---

## 📂 File Structure

```
d:\Ycomb\hive/
├── core/framework/runtime/
│   └── lifecycle_server.py          ✅ NEW - FastAPI server
├── Dockerfile.lifecycle              ✅ NEW - Production Dockerfile
├── examples/kubernetes/
│   └── deployment.yaml               ✅ NEW - K8s deployment
├── docs/
│   ├── LIFECYCLE_API_IMPLEMENTATION_PLAN.md  ✅ NEW - Technical design
│   └── GITHUB_ISSUE_LIFECYCLE_API.md         ✅ NEW - Issue template
└── LIFECYCLE_README.md               ✅ THIS FILE
```

---

## 🔗 Resources

### Documentation
- **Implementation Plan**: `docs/LIFECYCLE_API_IMPLEMENTATION_PLAN.md`
- **GitHub Issue**: `docs/GITHUB_ISSUE_LIFECYCLE_API.md`
- **Project Summary**: `d:\Ycomb\SUMMARY.md`

### Hive Project
- **Main README**: `README.md`
- **Developer Guide**: `DEVELOPER.md`
- **Roadmap**: `ROADMAP.md`

### External Links
- **Hive Repository**: https://github.com/adenhq/hive
- **Discord Community**: https://discord.com/invite/MXE49hrKDk
- **Documentation**: https://docs.adenhq.com/

---

## ⚠️ Important Notes

1. **Python Version**: Upgrade to Python 3.11+ before installing dependencies
2. **Issue Assignment**: Get assigned to the GitHub issue before starting work
3. **Testing**: Write comprehensive tests - the project has high quality standards
4. **Code Style**: Follow existing code conventions in the project
5. **Documentation**: Update all relevant docs when implementing

---

## 💡 Tips

- **Start Small**: Test lifecycle server locally first
- **Docker Next**: Build and test Docker image
- **Kubernetes Last**: Deploy to K8s cluster
- **Ask Questions**: Use Discord for help from maintainers
- **Follow Conventions**: Match existing code style

---

## 🎉 You're Ready!

All files are in place. Once you:
1. ✅ Upgrade Python to 3.11+
2. ✅ Install dependencies
3. ✅ Submit GitHub issue
4. ✅ Get assigned to the issue

You can start implementing and testing the lifecycle APIs!

**Good luck with your contribution!** 🚀
