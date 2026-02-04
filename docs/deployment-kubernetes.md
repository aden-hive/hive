# Agent Lifecycle & Kubernetes Deployment Guide

This guide covers deploying Hive agents to Kubernetes with proper lifecycle management, health probes, and graceful shutdown.

## Overview

The Hive framework provides production-ready lifecycle management:

- **AgentState** - Lifecycle state machine (INITIALIZING → READY → RUNNING → STOPPED)
- **HealthChecker** - Kubernetes-compatible liveness/readiness probes
- **HealthServer** - HTTP server for health endpoints
- **Signal Handlers** - Graceful shutdown on SIGTERM/SIGINT

## Quick Start

```python
from framework.runtime.agent_runtime import AgentRuntime, AgentState
from framework.runtime.health import HealthChecker
from framework.runtime.health_server import HealthServer

# Create and configure runtime
runtime = AgentRuntime(
    graph=my_graph,
    goal=my_goal,
    storage_path="./storage",
    llm=llm_provider,
)

# Register entry points
runtime.register_entry_point(...)

# Start with health server
async with HealthServer(runtime, port=8080):
    await runtime.start()
    
    # Runtime handles SIGTERM automatically
    # Or manually control lifecycle:
    # await runtime.pause()
    # await runtime.resume()
    # await runtime.graceful_shutdown()
```

## Agent Lifecycle States

```
INITIALIZING → READY → RUNNING ↔ PAUSED
                   ↓
              DRAINING → STOPPED
                   ↓
                 ERROR
```

| State | Description | Accepts Work? |
|-------|-------------|---------------|
| `INITIALIZING` | Starting up, loading config | No |
| `READY` | Fully started, waiting for triggers | Yes |
| `RUNNING` | Actively executing goals | Yes |
| `PAUSED` | Temporarily suspended | No |
| `DRAINING` | Finishing current work | No |
| `STOPPED` | Fully stopped | No |
| `ERROR` | Unrecoverable error | No |

## Health Endpoints

The `HealthServer` provides three endpoints:

| Endpoint | Purpose | Success | Failure |
|----------|---------|---------|---------|
| `GET /health` | Full status | JSON with details | JSON with error |
| `GET /health/live` | Liveness probe | `200 OK` | `503` |
| `GET /health/ready` | Readiness probe | `200 OK` | `503` |

### Liveness Probe

Returns `200` unless the agent is in `ERROR` state.

**Kubernetes behavior:** Failed liveness → Pod restart

### Readiness Probe

Returns `200` only when agent is `READY` or `RUNNING`.

**Kubernetes behavior:** Failed readiness → Remove from load balancer

## Kubernetes Deployment

### Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hive-agent
  labels:
    app: hive-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: hive-agent
  template:
    metadata:
      labels:
        app: hive-agent
    spec:
      terminationGracePeriodSeconds: 60  # Allow time for drain
      containers:
      - name: agent
        image: your-registry/hive-agent:latest
        ports:
        - containerPort: 8080
          name: health
        - containerPort: 8000
          name: api
        
        # Environment
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: agent-secrets
              key: anthropic-api-key
        - name: HEALTH_PORT
          value: "8080"
        
        # Resource limits
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        
        # Health probes
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 15
          timeoutSeconds: 5
          failureThreshold: 3
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
        
        # Startup probe for slow-starting agents
        startupProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
          failureThreshold: 30  # 30 * 5 = 150s max startup time
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: hive-agent
spec:
  selector:
    app: hive-agent
  ports:
  - name: api
    port: 8000
    targetPort: 8000
  - name: health
    port: 8080
    targetPort: 8080
```

### Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: agent-secrets
type: Opaque
stringData:
  anthropic-api-key: "sk-ant-..."
```

## Docker Compose

```yaml
version: '3.8'

services:
  agent:
    build: .
    ports:
      - "8000:8000"
      - "8080:8080"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - HEALTH_PORT=8080
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health/live"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    stop_grace_period: 60s  # Allow graceful shutdown
```

## Graceful Shutdown

When Kubernetes sends SIGTERM:

1. **Agent receives SIGTERM** → Signal handler triggered
2. **Readiness probe fails** → Removed from load balancer
3. **Drain phase begins** → Finish in-flight work
4. **Drain timeout** → Force stop if needed
5. **Agent stops** → Container exits

### Code Flow

```python
# This happens automatically when SIGTERM is received:
async def _handle_sigterm(self):
    logger.info("SIGTERM received, initiating graceful shutdown")
    
    # Stop accepting new work
    await self.drain(timeout_seconds=30)
    
    # Stop the runtime
    await self.stop()
```

### Tuning Shutdown

```yaml
# Kubernetes
terminationGracePeriodSeconds: 60  # Total time allowed

# In code
await runtime.graceful_shutdown(timeout_seconds=30)
```

## Monitoring

### Health Status Response

```json
{
  "status": "healthy",
  "state": "running",
  "uptime_seconds": 3600.5,
  "active_executions": 2,
  "started_at": "2026-01-31T10:00:00Z",
  "dependencies": [
    {"name": "storage", "healthy": true, "message": "Storage active"},
    {"name": "event_bus", "healthy": true, "message": "5 subscriptions"},
    {"name": "llm_provider", "healthy": true, "message": "LLM provider ready (claude-3)"}
  ],
  "details": {
    "entry_points": 2,
    "paused": false,
    "draining": false
  }
}
```

### Prometheus Metrics (Future)

```
# HELP hive_agent_state Current agent state
# TYPE hive_agent_state gauge
hive_agent_state{state="running"} 1

# HELP hive_agent_uptime_seconds Agent uptime
# TYPE hive_agent_uptime_seconds counter
hive_agent_uptime_seconds 3600.5

# HELP hive_agent_executions_active Current active executions
# TYPE hive_agent_executions_active gauge
hive_agent_executions_active 2
```

## Best Practices

### 1. Always Use Health Server

```python
# ✅ Good - health server running
async with HealthServer(runtime, port=8080):
    await runtime.start()
    await asyncio.Event().wait()  # Run forever

# ❌ Bad - no health visibility
await runtime.start()
```

### 2. Set Appropriate Timeouts

```python
# Production: longer timeouts
await runtime.graceful_shutdown(timeout_seconds=60)

# Development: faster iteration
await runtime.graceful_shutdown(timeout_seconds=5)
```

### 3. Handle Pausing for Maintenance

```python
# Maintenance mode
await runtime.pause()
# ... perform maintenance ...
await runtime.resume()
```

### 4. Monitor Drain Progress

```python
# Check active executions during drain
stats = runtime.get_stats()
print(f"Active: {stats['active_executions']}, Draining: {stats['draining']}")
```

## Troubleshooting

### Agent Not Becoming Ready

1. Check `GET /health` for detailed status
2. Look at dependency health
3. Check logs for initialization errors

```bash
kubectl logs -f deployment/hive-agent
kubectl exec -it deploy/hive-agent -- curl localhost:8080/health
```

### Slow Shutdown

1. Increase `terminationGracePeriodSeconds`
2. Check for stuck executions
3. Consider reducing drain timeout

### Health Server Not Responding

1. Verify port binding (0.0.0.0 vs localhost)
2. Check for port conflicts
3. Ensure runtime is started

```python
# Bind to all interfaces for Kubernetes
server = HealthServer(runtime, host="0.0.0.0", port=8080)
```
