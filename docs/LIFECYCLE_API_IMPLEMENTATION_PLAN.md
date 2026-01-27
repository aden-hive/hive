# Lifecycle APIs for Production Deployment (Self-Hosted)

## Overview

This implementation adds standardized lifecycle management APIs to the Hive agent framework, enabling production-grade deployments in Docker/Kubernetes environments. The feature addresses a critical gap in the roadmap under **Phase 2: Expansion → Deployment (Self-Hosted)**.

### Problem Statement

Currently, Hive lacks:
- **Programmatic control**: No standardized way to start/stop/pause/resume agent execution via API
- **Health monitoring**: No endpoints for Kubernetes liveness/readiness probes
- **Graceful shutdown**: No mechanism to handle SIGTERM and finish in-flight work
- **Status visibility**: No way for orchestration systems to query agent runtime state

This prevents production deployments where agents need to:
- Respond to Kubernetes health probes (liveness/readiness)
- Handle graceful shutdowns (SIGTERM → finish work → exit)
- Support pause/resume for maintenance windows
- Provide runtime status to monitoring systems

## User Review Required

> [!IMPORTANT]
> **API Design Decision**: This implementation proposes a FastAPI-based HTTP server with RESTful endpoints. Alternative approaches include:
> - gRPC for better performance and type safety
> - WebSocket for real-time status streaming
> - Both HTTP and gRPC (dual protocol support)
>
> **Recommendation**: Start with HTTP/REST for simplicity and broad compatibility, with gRPC as a future enhancement.

> [!WARNING]
> **Breaking Change Potential**: Adding a lifecycle server may require changes to:
> - Docker container entrypoints
> - Environment variable configuration
> - Agent initialization patterns
>
> Backward compatibility will be maintained by making the lifecycle server **optional** (disabled by default).

## Proposed Changes

### Component 1: Lifecycle Server (New)

#### [NEW] `core/framework/runtime/lifecycle_server.py`

**Purpose**: FastAPI-based HTTP server exposing lifecycle and health check endpoints.

**Key Features**:
- RESTful API endpoints for lifecycle operations
- Kubernetes-compatible health probes
- Graceful shutdown handling with configurable timeout
- Async/await support for non-blocking operations
- Prometheus-compatible metrics endpoint (optional)

**API Endpoints**:

```python
# Lifecycle Operations
POST   /api/v1/lifecycle/start          # Start agent runtime
POST   /api/v1/lifecycle/stop           # Stop agent runtime (graceful)
POST   /api/v1/lifecycle/pause          # Pause execution (finish current work)
POST   /api/v1/lifecycle/resume         # Resume execution
POST   /api/v1/lifecycle/restart        # Restart runtime

# Health & Status
GET    /health/live                     # Liveness probe (is process alive?)
GET    /health/ready                    # Readiness probe (ready for work?)
GET    /api/v1/status                   # Detailed runtime status
GET    /api/v1/status/streams           # Active execution streams

# Metrics (optional)
GET    /metrics                         # Prometheus metrics
```

**Status Response Schema**:
```json
{
  "state": "running|stopped|paused|starting|stopping",
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

---

### Component 2: Runtime State Management (Modified)

#### [MODIFY] `core/framework/runtime/agent_runtime.py`

**Changes**:
1. Add `RuntimeState` enum: `STOPPED`, `STARTING`, `RUNNING`, `PAUSED`, `STOPPING`
2. Add `pause()` and `resume()` methods to `AgentRuntime`
3. Add `get_status()` method returning detailed runtime state
4. Add signal handlers for graceful shutdown (SIGTERM, SIGINT)
5. Add health check methods: `is_alive()`, `is_ready()`
6. Track execution metrics (total, failed, active streams)

**New Methods**:
```python
async def pause(self, drain_timeout: float = 30.0) -> None:
    """Pause runtime, allowing in-flight executions to complete."""
    
async def resume(self) -> None:
    """Resume paused runtime."""
    
def get_status(self) -> RuntimeStatus:
    """Get detailed runtime status for monitoring."""
    
def is_alive(self) -> bool:
    """Liveness check - is the process alive?"""
    
def is_ready(self) -> bool:
    """Readiness check - ready to accept work?"""
```

**Pause/Resume Implementation**:
- Pause: Stop accepting new executions, wait for in-flight work to complete (with timeout)
- Resume: Re-enable execution acceptance
- State transitions: `RUNNING → PAUSED → RUNNING`

---

### Component 3: Configuration & Environment (Modified)

#### [MODIFY] `core/framework/__init__.py`

**Changes**: Export new lifecycle components for public API.

```python
from framework.runtime.lifecycle_server import LifecycleServer, LifecycleConfig
from framework.runtime.agent_runtime import RuntimeState, RuntimeStatus
```

#### [NEW] `core/framework/runtime/lifecycle_config.py`

**Purpose**: Configuration for lifecycle server.

```python
@dataclass
class LifecycleConfig:
    enabled: bool = False                    # Disabled by default
    host: str = "0.0.0.0"
    port: int = 8080
    graceful_shutdown_timeout: float = 30.0  # Seconds to wait for in-flight work
    enable_metrics: bool = True
    enable_cors: bool = False
    cors_origins: list[str] = field(default_factory=list)
```

**Environment Variables**:
```bash
HIVE_LIFECYCLE_ENABLED=true
HIVE_LIFECYCLE_PORT=8080
HIVE_LIFECYCLE_HOST=0.0.0.0
HIVE_GRACEFUL_SHUTDOWN_TIMEOUT=30
```

---

### Component 4: Docker & Kubernetes Integration (New)

#### [NEW] `Dockerfile.lifecycle`

**Purpose**: Production-ready Dockerfile with lifecycle server enabled.

**Features**:
- Multi-stage build for smaller image
- Non-root user for security
- Health check configuration
- Signal handling for graceful shutdown

#### [NEW] `examples/kubernetes/deployment.yaml`

**Purpose**: Example Kubernetes deployment with probes.

**Features**:
- Liveness and readiness probes
- Graceful shutdown via preStop hook
- HorizontalPodAutoscaler for scaling
- PodDisruptionBudget for HA

---

### Component 5: CLI Integration (Modified)

#### [MODIFY] `core/framework/cli.py`

**Changes**: Add lifecycle server commands to CLI.

**New Commands**:
```bash
# Start agent with lifecycle server
python -m core serve exports/my-agent --lifecycle-port 8080

# Start lifecycle server for existing runtime
python -m core lifecycle start --port 8080 --agent exports/my-agent

# Check status
python -m core lifecycle status --endpoint http://localhost:8080
```

---

### Component 6: Documentation (New)

#### [NEW] `docs/LIFECYCLE_API.md`

**Purpose**: Complete API documentation for lifecycle endpoints.

**Contents**:
- API endpoint reference
- Request/response schemas
- Kubernetes integration guide
- Docker deployment examples
- Health check configuration
- Graceful shutdown best practices

#### [NEW] `docs/DEPLOYMENT_GUIDE.md`

**Purpose**: Production deployment guide.

**Contents**:
- Docker deployment
- Kubernetes deployment
- Health monitoring setup
- Graceful shutdown configuration
- Scaling considerations
- Troubleshooting

---

## Verification Plan

### Automated Tests

1. **Unit Tests** (`core/framework/runtime/tests/test_lifecycle_server.py`)
   - Test all API endpoints (start, stop, pause, resume)
   - Test health check responses
   - Test state transitions
   - Test graceful shutdown with in-flight work
   - Test concurrent request handling

2. **Integration Tests** (`core/framework/runtime/tests/test_lifecycle_integration.py`)
   - Test full lifecycle: start → pause → resume → stop
   - Test signal handling (SIGTERM, SIGINT)
   - Test timeout scenarios
   - Test error recovery

3. **Docker Tests**
   ```bash
   # Build image
   docker build -f Dockerfile.lifecycle -t hive-agent:test .
   
   # Test health checks
   docker run -d --name hive-test -p 8080:8080 hive-agent:test
   curl http://localhost:8080/health/live
   curl http://localhost:8080/health/ready
   
   # Test graceful shutdown
   docker stop --time=35 hive-test  # Should complete in <35s
   ```

4. **Kubernetes Tests** (using kind/minikube)
   ```bash
   # Deploy to test cluster
   kubectl apply -f examples/kubernetes/deployment.yaml
   
   # Verify probes
   kubectl describe pod hive-agent-xxx | grep -A 5 "Liveness\|Readiness"
   
   # Test rolling update (should be graceful)
   kubectl rollout restart deployment/hive-agent
   kubectl rollout status deployment/hive-agent
   ```

---

## Implementation Phases

### Phase 1: Core Runtime Enhancements (Week 1)
- [ ] Add `RuntimeState` enum and state management to `AgentRuntime`
- [ ] Implement `pause()` and `resume()` methods
- [ ] Add `get_status()` and health check methods
- [ ] Add signal handlers for graceful shutdown
- [ ] Write unit tests for runtime state management

### Phase 2: Lifecycle Server (Week 1-2)
- [ ] Create `LifecycleServer` with FastAPI
- [ ] Implement all API endpoints
- [ ] Add request validation and error handling
- [ ] Write unit tests for server endpoints
- [ ] Add integration tests

### Phase 3: Docker & Kubernetes (Week 2)
- [ ] Create `Dockerfile.lifecycle`
- [ ] Create Kubernetes deployment examples
- [ ] Test health probes in Kubernetes
- [ ] Test graceful shutdown in containers
- [ ] Document deployment patterns

### Phase 4: Documentation & Examples (Week 2-3)
- [ ] Write `LIFECYCLE_API.md`
- [ ] Write `DEPLOYMENT_GUIDE.md`
- [ ] Create example agents using lifecycle APIs
- [ ] Update main README with lifecycle features
- [ ] Create video walkthrough (optional)

### Phase 5: CLI & Developer Experience (Week 3)
- [ ] Add lifecycle commands to CLI
- [ ] Add configuration validation
- [ ] Create quickstart scripts
- [ ] Update developer documentation

---

## Success Metrics

- ✅ All API endpoints return correct responses
- ✅ Health probes work in Kubernetes
- ✅ Graceful shutdown completes in-flight work within timeout
- ✅ Pause/resume maintains execution state correctly
- ✅ Zero downtime during rolling updates in Kubernetes
- ✅ 100% test coverage for lifecycle components
- ✅ Documentation covers all deployment scenarios

---

## Future Enhancements

1. **gRPC Support**: Add gRPC endpoints for better performance
2. **WebSocket Streaming**: Real-time status updates via WebSocket
3. **Advanced Metrics**: Detailed execution metrics, latency histograms
4. **Auto-scaling**: Integration with Kubernetes HPA based on metrics
5. **Circuit Breaker**: Automatic pause on high error rates
6. **Distributed Tracing**: OpenTelemetry integration for observability
