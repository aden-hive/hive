# [Feature Request] Lifecycle APIs for Production Deployment (Self-Hosted)

## 📋 Issue Type
- [x] Feature Request
- [ ] Bug Report
- [ ] Documentation

## 🎯 Roadmap Reference
This addresses the roadmap item under **Phase 2: Expansion → Deployment (Self-Hosted)**:
- [ ] Basic lifecycle APIs (Start, Stop, Pause, Resume)

## 🔍 Problem Statement

Currently, there is no standardized way to:
- ✗ Programmatically start/stop/pause/resume agent execution
- ✗ Check if an agent runtime is healthy (for Kubernetes probes)
- ✗ Gracefully shut down agents with in-flight work
- ✗ Query agent status from external orchestration systems

This is **critical for production deployments** where agents run in Docker/Kubernetes and need:

### Required Capabilities
1. **Liveness probes** - Is the agent process alive?
2. **Readiness probes** - Is the agent ready to accept work?
3. **Graceful shutdown** - SIGTERM → finish current work → exit
4. **Pause/resume** - Support for maintenance windows
5. **Status monitoring** - Query runtime state from orchestration systems

## 💡 Proposed Solution

Implement a **FastAPI-based HTTP server** that exposes lifecycle and health check endpoints, integrated with the existing `AgentRuntime` class.

### API Design

#### Lifecycle Operations
```http
POST   /api/v1/lifecycle/start          # Start agent runtime
POST   /api/v1/lifecycle/stop           # Stop agent runtime (graceful)
POST   /api/v1/lifecycle/pause          # Pause execution
POST   /api/v1/lifecycle/resume         # Resume execution
POST   /api/v1/lifecycle/restart        # Restart runtime
```

#### Health & Status
```http
GET    /health/live                     # Liveness probe (Kubernetes)
GET    /health/ready                    # Readiness probe (Kubernetes)
GET    /api/v1/status                   # Detailed runtime status
GET    /api/v1/status/streams           # Active execution streams
```

#### Example Status Response
```json
{
  "state": "running",
  "uptime_seconds": 3600,
  "active_streams": 3,
  "total_executions": 150,
  "failed_executions": 2,
  "entry_points": ["main", "webhook", "scheduled"],
  "health": {
    "storage": "healthy",
    "llm": "healthy",
    "tools": "healthy"
  }
}
```

## 🏗️ Technical Requirements

### 1. Runtime State Management
Enhance `AgentRuntime` (`core/framework/runtime/agent_runtime.py`) with:
- `RuntimeState` enum: `STOPPED`, `STARTING`, `RUNNING`, `PAUSED`, `STOPPING`
- `pause()` and `resume()` methods
- `get_status()` method for monitoring
- `is_alive()` and `is_ready()` health checks
- Signal handlers for graceful shutdown (SIGTERM, SIGINT)

### 2. Lifecycle Server
New component: `core/framework/runtime/lifecycle_server.py`
- FastAPI-based HTTP server
- Async/await support
- Request validation with Pydantic
- Error handling and logging
- Optional Prometheus metrics endpoint

### 3. Docker Integration
- Production-ready Dockerfile with health checks
- Graceful shutdown handling (STOPSIGNAL SIGTERM)
- Non-root user for security
- Multi-stage build for smaller images

### 4. Kubernetes Integration
- Example deployment manifests
- Liveness and readiness probe configuration
- PreStop hook for graceful shutdown
- Rolling update strategy

### 5. Configuration
Environment variables:
```bash
HIVE_LIFECYCLE_ENABLED=true
HIVE_LIFECYCLE_PORT=8080
HIVE_LIFECYCLE_HOST=0.0.0.0
HIVE_GRACEFUL_SHUTDOWN_TIMEOUT=30
```

## ✅ Acceptance Criteria

- [ ] All lifecycle endpoints (start, stop, pause, resume) work correctly
- [ ] Health endpoints (`/health/live`, `/health/ready`) return accurate status
- [ ] Graceful shutdown completes in-flight executions within timeout
- [ ] Pause operation waits for current work to complete
- [ ] Resume operation restores runtime to working state
- [ ] Kubernetes liveness/readiness probes work correctly
- [ ] Docker container handles SIGTERM gracefully
- [ ] Zero downtime during Kubernetes rolling updates
- [ ] Comprehensive unit and integration tests (>90% coverage)
- [ ] Complete API documentation
- [ ] Deployment guide for Docker and Kubernetes

## 📦 Deliverables

### Code Components
1. `core/framework/runtime/lifecycle_server.py` - FastAPI server
2. `core/framework/runtime/lifecycle_config.py` - Configuration
3. Enhanced `core/framework/runtime/agent_runtime.py` - State management
4. `Dockerfile.lifecycle` - Production Docker image
5. `examples/kubernetes/deployment.yaml` - K8s deployment example

### Documentation
1. `docs/LIFECYCLE_API.md` - API reference
2. `docs/DEPLOYMENT_GUIDE.md` - Production deployment guide
3. Updated `README.md` - Feature announcement

### Tests
1. `core/framework/runtime/tests/test_lifecycle_server.py` - Unit tests
2. `core/framework/runtime/tests/test_lifecycle_integration.py` - Integration tests
3. Docker and Kubernetes test scripts

## 🔄 Implementation Phases

### Phase 1: Core Runtime (Week 1)
- [ ] Add state management to `AgentRuntime`
- [ ] Implement `pause()` and `resume()` methods
- [ ] Add health check methods
- [ ] Signal handler for graceful shutdown
- [ ] Unit tests

### Phase 2: Lifecycle Server (Week 1-2)
- [ ] Create FastAPI server
- [ ] Implement all endpoints
- [ ] Request validation
- [ ] Integration tests

### Phase 3: Docker & Kubernetes (Week 2)
- [ ] Create Dockerfile
- [ ] Kubernetes manifests
- [ ] Test health probes
- [ ] Test graceful shutdown

### Phase 4: Documentation (Week 2-3)
- [ ] API documentation
- [ ] Deployment guide
- [ ] Examples and tutorials

## 🎨 Design Decisions

### Why FastAPI?
- **Async/await** support for non-blocking operations
- **Automatic OpenAPI** documentation
- **Pydantic validation** for type safety
- **Wide adoption** in Python ecosystem
- **Easy testing** with TestClient

### Why HTTP/REST?
- **Broad compatibility** with monitoring tools
- **Simple integration** with Kubernetes probes
- **Easy debugging** with curl/httpie
- **Future-proof** - can add gRPC later

### Backward Compatibility
- Lifecycle server is **disabled by default**
- Existing agents work without changes
- Opt-in via environment variable or config

## 🔗 Related Issues
- Roadmap: Phase 2 → Deployment (Self-Hosted)
- Related to: Docker container standardization
- Related to: Headless backend execution

## 🙋 Questions for Maintainers

1. **API versioning**: Should we start with `/api/v1/` or just `/api/`?
2. **Metrics**: Should Prometheus metrics be included in v1 or separate PR?
3. **Authentication**: Should lifecycle endpoints require auth? (e.g., API key)
4. **Port conflict**: Default port 8080 OK, or prefer different port?
5. **CLI integration**: Should we add `python -m core serve` command?

## 📚 References

- [Kubernetes Liveness/Readiness Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Docker Health Checks](https://docs.docker.com/engine/reference/builder/#healthcheck)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Graceful Shutdown in Python](https://docs.python.org/3/library/signal.html)

## 🤝 I Can Help!

I'm interested in implementing this feature and can:
- [ ] Write the implementation
- [ ] Write comprehensive tests
- [ ] Write documentation
- [ ] Review PRs from others

**Estimated effort**: 2-3 weeks for complete implementation

---

**Note**: I've created a detailed implementation plan in a separate document. Happy to discuss the approach before starting work!
