# Building Production AI Agents: From Prototype to Deployment

*A practical guide to taking AI agents from demo to production*

---

Getting an AI agent working in a demo is easy. Getting it to work reliably in production is hard. This guide covers the critical differences and how to bridge the gap.

---

## Demo vs Production

| Aspect | Demo | Production |
|--------|------|------------|
| Traffic | You testing it | Hundreds/thousands of users |
| Uptime | "It worked when I tried" | 99.9% required |
| Errors | "Let me restart it" | Must handle gracefully |
| Cost | "It's just a demo" | Every dollar matters |
| Security | None | Critical |
| Monitoring | Print statements | Full observability |
| Recovery | Manual restart | Automatic healing |

---

## The Production Readiness Checklist

### 1. Reliability

- [ ] Retry logic with exponential backoff
- [ ] Circuit breakers for failing services
- [ ] Graceful degradation (fallbacks)
- [ ] Health check endpoints
- [ ] Automatic recovery from crashes

### 2. Scalability

- [ ] Horizontal scaling capability
- [ ] Stateless design (or managed state)
- [ ] Queue-based processing for bursts
- [ ] Database connection pooling
- [ ] Caching layer

### 3. Observability

- [ ] Structured logging
- [ ] Metrics collection
- [ ] Distributed tracing
- [ ] Alerting rules
- [ ] Dashboard for monitoring

### 4. Security

- [ ] API authentication
- [ ] Input validation
- [ ] Output sanitization
- [ ] Secrets management
- [ ] Audit logging

### 5. Cost Control

- [ ] Budget limits
- [ ] Usage tracking
- [ ] Model degradation policies
- [ ] Anomaly detection

### 6. Human Oversight

- [ ] HITL checkpoints
- [ ] Escalation policies
- [ ] Audit trails
- [ ] Manual override capability

---

## Architecture Patterns

### Pattern 1: Simple Agent Service

```
┌──────────────────────────────────────────┐
│               Agent Service              │
│  ┌────────────────────────────────────┐ │
│  │  Request Handler                    │ │
│  │  ┌──────┐  ┌──────┐  ┌──────┐     │ │
│  │  │Validate│→│Agent │→│Format │     │ │
│  │  │ Input │ │Execute│ │Output│     │ │
│  │  └──────┘  └──────┘  └──────┘     │ │
│  └────────────────────────────────────┘ │
│                    │                     │
│  ┌─────────────────────────────────────┐│
│  │  Dependencies                       ││
│  │  • LLM API  • Tools  • Database    ││
│  └─────────────────────────────────────┘│
└──────────────────────────────────────────┘
```

**Best for:** Simple use cases, low volume

### Pattern 2: Queue-Based Processing

```
┌───────┐    ┌───────┐    ┌───────────────┐
│Request│───▶│ Queue │───▶│ Agent Workers │
│  API  │    │       │    │   (N copies)  │
└───────┘    └───────┘    └───────────────┘
                               │
                               ▼
                          ┌─────────┐
                          │ Results │
                          │   DB    │
                          └─────────┘
```

**Best for:** High volume, async processing

### Pattern 3: Event-Driven Agents

```
┌─────────────┐
│ Event Source│─────┐
└─────────────┘     │
                    ▼
┌─────────────┐ ┌─────────┐ ┌─────────────┐
│ Event Source│─▶│  Event  │─▶│   Agent     │
└─────────────┘ │   Bus   │ │ Processors  │
                └─────────┘ └─────────────┘
┌─────────────┐     │
│ Event Source│─────┘
└─────────────┘
```

**Best for:** Reactive systems, integrations

### Pattern 4: Full Platform (Aden)

```
┌────────────────────────────────────────────────────────┐
│                    Aden Platform                       │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ Coding Agent │  │Worker Agents │  │  Dashboard  │ │
│  │  (Generate)  │  │  (Execute)   │  │  (Monitor)  │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
│         │                │                  │         │
│         ▼                ▼                  ▼         │
│  ┌────────────────────────────────────────────────┐  │
│  │            Control Plane                       │  │
│  │  • Budget  • Policies  • Metrics  • HITL     │  │
│  └────────────────────────────────────────────────┘  │
│                         │                            │
│  ┌────────────────────────────────────────────────┐  │
│  │            Storage Layer                       │  │
│  │  • Events  • Policies  • Config              │  │
│  └────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

**Best for:** Complex systems, self-improving agents

---

## Implementing Reliability

### Retry Logic
```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1, max_delay=60):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except (RateLimitError, TimeoutError) as e:
                    retries += 1
                    if retries > max_retries:
                        raise

                    delay = min(base_delay * (2 ** retries), max_delay)
                    logger.warning(f"Retry {retries}/{max_retries} after {delay}s: {e}")
                    await asyncio.sleep(delay)
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3)
async def call_llm(prompt):
    return await llm_client.complete(prompt)
```

### Circuit Breaker
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_time=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open

    async def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_time:
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            raise
```

### Graceful Degradation
```python
async def process_with_fallback(task):
    try:
        # Try primary approach
        return await primary_agent.execute(task)
    except AgentError:
        try:
            # Fall back to simpler approach
            return await fallback_agent.execute(task)
        except AgentError:
            # Last resort: static response
            return create_static_response(task)
```

---

## Implementing Observability

### Structured Logging
```python
import structlog

logger = structlog.get_logger()

async def execute_agent(task):
    logger.info("agent_execution_started",
                task_id=task.id,
                agent_id=agent.id,
                input_tokens=count_tokens(task.input))

    try:
        result = await agent.run(task)
        logger.info("agent_execution_completed",
                    task_id=task.id,
                    duration_ms=duration,
                    output_tokens=count_tokens(result),
                    cost_usd=calculate_cost(result))
        return result
    except Exception as e:
        logger.error("agent_execution_failed",
                     task_id=task.id,
                     error=str(e),
                     error_type=type(e).__name__)
        raise
```

### Metrics Collection
```python
from prometheus_client import Counter, Histogram, Gauge

# Counters
agent_requests_total = Counter(
    'agent_requests_total',
    'Total agent requests',
    ['agent_id', 'status']
)

# Histograms
agent_duration_seconds = Histogram(
    'agent_duration_seconds',
    'Agent execution duration',
    ['agent_id']
)

# Gauges
agent_active_tasks = Gauge(
    'agent_active_tasks',
    'Currently running agent tasks',
    ['agent_id']
)

async def execute_with_metrics(agent, task):
    agent_active_tasks.labels(agent_id=agent.id).inc()
    start = time.time()

    try:
        result = await agent.run(task)
        agent_requests_total.labels(agent_id=agent.id, status='success').inc()
        return result
    except Exception:
        agent_requests_total.labels(agent_id=agent.id, status='error').inc()
        raise
    finally:
        duration = time.time() - start
        agent_duration_seconds.labels(agent_id=agent.id).observe(duration)
        agent_active_tasks.labels(agent_id=agent.id).dec()
```

### Distributed Tracing
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def execute_with_tracing(agent, task):
    with tracer.start_as_current_span("agent_execution") as span:
        span.set_attribute("agent.id", agent.id)
        span.set_attribute("task.id", task.id)

        # LLM call
        with tracer.start_as_current_span("llm_call") as llm_span:
            llm_span.set_attribute("model", agent.model)
            result = await call_llm(task.prompt)
            llm_span.set_attribute("tokens", result.usage.total_tokens)

        # Tool execution
        with tracer.start_as_current_span("tool_execution") as tool_span:
            tool_span.set_attribute("tool", tool.name)
            tool_result = await execute_tool(tool, result)

        return tool_result
```

---

## Security Best Practices

### Input Validation
```python
from pydantic import BaseModel, validator

class AgentRequest(BaseModel):
    task: str
    context: dict = {}
    max_tokens: int = 1000

    @validator('task')
    def validate_task(cls, v):
        if len(v) > 10000:
            raise ValueError('Task too long')
        if contains_injection_attempt(v):
            raise ValueError('Invalid input detected')
        return v

    @validator('max_tokens')
    def validate_max_tokens(cls, v):
        if v > 4000:
            raise ValueError('max_tokens too high')
        return v
```

### Output Sanitization
> **Note:** The following snippet is illustrative and shows a simplified example
> of output sanitization logic. Actual implementations may differ.
```python
def sanitize_output(result):
    # Remove any leaked secrets
    result = mask_patterns(result, SECRET_PATTERNS)

    # Validate structure
    if not is_valid_response(result):
        raise OutputValidationError("Invalid response structure")

    # Check for harmful content
    if contains_harmful_content(result):
        raise ContentPolicyError("Response violates content policy")

    return result
```

### Audit Logging
```python
async def audit_log(event):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event.type,
        "agent_id": event.agent_id,
        "user_id": event.user_id,
        "action": event.action,
        "input_hash": hash_content(event.input),  # Don't log full input
        "output_hash": hash_content(event.output),
        "metadata": event.metadata
    }
    await audit_db.insert(log_entry)
```

---

## Deployment Strategies

### Blue-Green Deployment
```
                    Load Balancer
                          │
              ┌───────────┴───────────┐
              │                       │
        ┌─────▼─────┐          ┌─────▼─────┐
        │   Blue    │          │   Green   │
        │ (Current) │          │   (New)   │
        └───────────┘          └───────────┘

1. Deploy new version to Green
2. Test Green environment
3. Switch traffic Blue → Green
4. Keep Blue for rollback
```

### Canary Deployment
```
                    Load Balancer
                          │
              ┌───────────┴───────────┐
              │ 95%                5% │
        ┌─────▼─────┐          ┌─────▼─────┐
        │  Stable   │          │  Canary   │
        │ (v1.0)    │          │  (v1.1)   │
        └───────────┘          └───────────┘

1. Deploy new version as Canary
2. Route 5% traffic to Canary
3. Monitor metrics
4. Gradually increase or rollback
```

### Feature Flags
```python
async def execute_agent(task, user):
    if feature_flags.is_enabled("new_agent_v2", user.id):
        return await agent_v2.execute(task)
    else:
        return await agent_v1.execute(task)
```

---

## Framework Comparison: Production Readiness

| Feature | DIY | LangChain | CrewAI | Aden |
|---------|-----|-----------|--------|------|
| Retry logic | Build | Partial | Basic | Built-in |
| Circuit breakers | Build | No | No | Built-in |
| Health checks | Build | No | No | Built-in |
| Monitoring | Build | LangSmith | Build | Built-in |
| Cost control | Build | No | No | Built-in |
| HITL | Build | Build | Basic | Native |
| Self-healing | Build | No | No | Native |
| Dashboard | Build | LangSmith | No | Built-in |

---

## Testing for Production

### Unit Tests
```python
def test_agent_handles_rate_limit():
    with mock.patch('llm.complete', side_effect=RateLimitError()):
        result = agent.execute(task)
        assert result.status == "retried"

def test_agent_validates_input():
    with pytest.raises(ValidationError):
        agent.execute({"task": "x" * 100000})  # Too long
```

### Integration Tests
```python
async def test_full_agent_flow():
    # Create test task
    task = create_test_task()

    # Execute agent
    result = await agent.execute(task)

    # Verify result
    assert result.success
    assert result.output is not None

    # Verify monitoring
    assert metrics.request_count > 0
    assert metrics.last_cost < 1.0
```

### Load Tests
```python
async def load_test_agent():
    tasks = [create_test_task() for _ in range(100)]

    start = time.time()
    results = await asyncio.gather(*[
        agent.execute(task) for task in tasks
    ])
    duration = time.time() - start

    success_rate = sum(1 for r in results if r.success) / len(results)
    avg_latency = duration / len(tasks)

    assert success_rate > 0.95
    assert avg_latency < 5.0  # seconds
```

### Chaos Tests
```python
async def test_agent_survives_llm_outage():
    with mock.patch('llm.complete', side_effect=ConnectionError()):
        # Should use fallback or degrade gracefully
        result = await agent.execute(task)
        assert result.status in ["fallback", "degraded"]

async def test_agent_survives_high_load():
    # Simulate burst traffic
    tasks = [create_test_task() for _ in range(1000)]
    results = await asyncio.gather(*[
        agent.execute(task) for task in tasks
    ], return_exceptions=True)

    # Should not crash, may throttle
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) / len(results) < 0.1  # <10% error rate
```

---

## Conclusion

Production AI agents require:

1. **Reliability**: Retries, circuit breakers, fallbacks
2. **Observability**: Logs, metrics, traces, dashboards
3. **Security**: Validation, sanitization, auditing
4. **Cost Control**: Budgets, tracking, degradation
5. **Human Oversight**: HITL, escalation, override

Frameworks like Aden provide many of these out of the box. For other frameworks, you'll need to build this infrastructure yourself.

The gap between demo and production is significant—plan for it from the start.

---

*Last updated: January 2025*
