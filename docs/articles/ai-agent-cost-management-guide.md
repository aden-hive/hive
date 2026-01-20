# AI Agent Cost Management: A Complete Guide

*Control spending, optimize efficiency, and prevent budget disasters*

---

AI agents can burn through budgets faster than you expect. A single runaway agent loop can cost thousands of dollars in minutes. This guide covers strategies, tools, and best practices for managing AI agent costs.

---

## The Cost Problem

### Why AI Agents Are Expensive

| Factor | Impact |
|--------|--------|
| LLM API calls | $0.01 - $0.10+ per call |
| Token usage | Input + output tokens |
| Agent loops | Multiple calls per task |
| Retries | Failed calls still cost money |
| Verbose prompts | More tokens = more cost |
| Tool usage | Additional API calls |

### Real-World Example
```
Simple customer support agent:
- 5 LLM calls per interaction
- 2000 tokens average per call
- GPT-4: ~$0.06 per call
- 100 interactions/day = $30/day

Complex research agent:
- 50+ LLM calls per task
- 10000 tokens average per call
- GPT-4: ~$0.30 per call
- 10 tasks/day = $150/day

Runaway agent loop:
- 1000 calls in 10 minutes
- $300+ before detection
```

---

## Cost Control Strategies

### Strategy 1: Budget Limits

Set hard limits on spending per:
- Time period (daily, weekly, monthly)
- Agent
- Task
- Team
- User

```python
budget_config = {
    "daily_limit": 100.00,
    "per_task_limit": 5.00,
    "per_agent_limit": 50.00,
    "alert_at_percentage": 80,
    "action_on_limit": "block"  # or "degrade", "alert"
}
```

### Strategy 2: Model Degradation

Automatically switch to cheaper models as budget is consumed:

```
Budget usage:
  0-70%  → Use GPT-4 (best quality)
 70-90%  → Use GPT-3.5-turbo (good quality)
 90-100% → Use GPT-3.5-turbo with shorter prompts
  100%+  → Block or queue requests
```

### Strategy 3: Request Throttling

Limit request rate to control burn rate:

```python
throttle_config = {
    "requests_per_minute": 10,
    "requests_per_hour": 200,
    "backoff_multiplier": 2,
    "max_backoff_seconds": 60
}
```

### Strategy 4: Token Optimization

Reduce tokens per request:

| Technique | Savings |
|-----------|---------|
| Shorter system prompts | 20-40% |
| Compressed context | 30-50% |
| Response length limits | 20-30% |
| Remove unnecessary examples | 10-20% |

### Strategy 5: Caching

Cache common requests and responses:

```python
# Before: Every request hits the API
result = llm.complete(prompt)  # Costs money

# After: Cache frequent patterns
cached = cache.get(prompt_hash)
if cached:
    result = cached  # Free
else:
    result = llm.complete(prompt)
    cache.set(prompt_hash, result)
```

---

## Framework Comparison: Cost Features

| Framework | Budget Limits | Degradation | Tracking | Alerts |
|-----------|--------------|-------------|----------|--------|
| LangChain | Third-party | Manual | LangSmith | Manual |
| CrewAI | Not built-in | Manual | Basic | Manual |
| AutoGen | Not built-in | Manual | Manual | Manual |
| **Aden** | **Native** | **Automatic** | **Built-in** | **Native** |

### Aden's Cost Controls
Aden includes comprehensive cost management:

```python
# Budget configuration in Aden
budget_rules = {
    "budget_id": "team_engineering",
    "limits": {
        "daily": 500.00,
        "monthly": 10000.00,
        "per_agent": 100.00
    },
    "degradation": {
        "80_percent": "switch_to_gpt35",
        "95_percent": "throttle",
        "100_percent": "block"
    },
    "alerts": {
        "channels": ["slack", "email"],
        "thresholds": [50, 80, 95, 100]
    }
}
```

---

## Implementing Cost Tracking

### Basic Tracking
```python
class CostTracker:
    def __init__(self):
        self.total_cost = 0
        self.cost_by_agent = {}
        self.cost_by_model = {}

    def track(self, request, response, model):
        input_tokens = count_tokens(request)
        output_tokens = count_tokens(response)

        cost = self.calculate_cost(model, input_tokens, output_tokens)

        self.total_cost += cost
        self.cost_by_agent[request.agent_id] = \
            self.cost_by_agent.get(request.agent_id, 0) + cost
        self.cost_by_model[model] = \
            self.cost_by_model.get(model, 0) + cost

        return cost

    def calculate_cost(self, model, input_tokens, output_tokens):
        rates = {
            "gpt-4": {"input": 0.03, "output": 0.06},  # per 1K tokens
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        }
        rate = rates.get(model, rates["gpt-3.5-turbo"])
        return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1000
```

### Advanced Tracking with Attribution
```python
cost_record = {
    "timestamp": "2025-01-15T10:30:00Z",
    "request_id": "req_123",
    "agent_id": "support_agent_1",
    "task_id": "task_456",
    "team_id": "customer_success",
    "model": "gpt-4",
    "input_tokens": 1500,
    "output_tokens": 500,
    "cost_usd": 0.075,
    "cached": False,
    "degraded": False
}
```

---

## Alert Configuration

### Threshold Alerts
```yaml
alerts:
  - name: "Budget Warning"
    condition: "daily_spend > daily_budget * 0.8"
    channels: ["slack"]
    message: "80% of daily budget consumed"

  - name: "Budget Critical"
    condition: "daily_spend > daily_budget * 0.95"
    channels: ["slack", "pagerduty"]
    message: "95% of daily budget - taking action"
    action: "degrade_models"

  - name: "Runaway Agent"
    condition: "requests_per_minute > 100"
    channels: ["pagerduty"]
    message: "Possible runaway agent detected"
    action: "pause_agent"
```

### Anomaly Detection
```python
def detect_anomalies(recent_costs, historical_average):
    """Alert if costs significantly exceed historical patterns"""
    threshold = historical_average * 3  # 3x normal

    if recent_costs > threshold:
        alert(
            level="critical",
            message=f"Cost anomaly: ${recent_costs:.2f} vs avg ${historical_average:.2f}",
            action="investigate"
        )
```

---

## Model Selection Strategies

### Cost vs Quality Matrix

| Model | Cost (per 1K tokens) | Quality | Best For |
|-------|---------------------|---------|----------|
| GPT-4 | $0.03-0.06 | Highest | Complex reasoning |
| GPT-4-turbo | $0.01-0.03 | High | Balance cost/quality |
| GPT-3.5-turbo | $0.0005-0.0015 | Good | High volume, simple |
| Claude 3 Opus | $0.015-0.075 | Highest | Long context |
| Claude 3 Sonnet | $0.003-0.015 | High | Good balance |
| Claude 3 Haiku | $0.00025-0.00125 | Good | Fast, cheap |

### Dynamic Model Selection
```python
def select_model(task_complexity, budget_remaining, daily_limit):
    budget_percentage = (daily_limit - budget_remaining) / daily_limit

    if task_complexity == "simple":
        return "gpt-3.5-turbo"  # Always cheap for simple
    elif budget_percentage < 0.5:
        return "gpt-4"  # Best model when budget healthy
    elif budget_percentage < 0.8:
        return "gpt-4-turbo"  # Balanced
    else:
        return "gpt-3.5-turbo"  # Preserve budget
```

---

## Optimization Techniques

### 1. Prompt Engineering for Cost
```python
# Expensive: Long system prompt
system_prompt = """
You are a helpful assistant that specializes in customer support.
You should always be polite, professional, and helpful.
When answering questions, provide detailed explanations.
Always consider the customer's perspective.
Remember to be empathetic and understanding.
[... 500 more tokens ...]
"""

# Cheaper: Concise system prompt
system_prompt = """
Customer support agent. Be helpful, polite, concise.
Resolve issues efficiently.
"""
# Savings: ~400 tokens × 1000 requests = $12/day
```

### 2. Context Window Management
```python
def manage_context(messages, max_tokens=4000):
    """Keep context within budget by summarizing old messages"""
    current_tokens = count_tokens(messages)

    if current_tokens > max_tokens:
        # Summarize older messages
        old_messages = messages[:-5]  # Keep recent
        summary = summarize(old_messages)

        return [{"role": "system", "content": f"Previous context: {summary}"}] + messages[-5:]

    return messages
```

### 3. Batch Processing
```python
# Expensive: Individual requests
for item in items:
    result = llm.complete(f"Process: {item}")

# Cheaper: Batch when possible
batch_prompt = "Process these items:\n" + "\n".join(items)
results = llm.complete(batch_prompt)
```

### 4. Response Length Control
```python
# Add to system prompt
system_prompt += "\nKeep responses under 200 words."

# Or use max_tokens parameter
response = llm.complete(
    prompt,
    max_tokens=300  # Hard limit
)
```

---

## Runaway Agent Prevention

### Detection Mechanisms
```python
class RunawayDetector:
    def __init__(self):
        self.request_times = []
        self.max_requests_per_minute = 50
        self.max_cost_per_minute = 10.00

    def check(self, cost):
        now = time.time()
        self.request_times.append((now, cost))

        # Clean old entries
        self.request_times = [
            (t, c) for t, c in self.request_times
            if now - t < 60
        ]

        # Check thresholds
        requests_per_minute = len(self.request_times)
        cost_per_minute = sum(c for _, c in self.request_times)

        if requests_per_minute > self.max_requests_per_minute:
            return "RUNAWAY_REQUESTS"
        if cost_per_minute > self.max_cost_per_minute:
            return "RUNAWAY_COST"

        return "OK"
```

### Circuit Breakers
```python
class CostCircuitBreaker:
    def __init__(self, threshold, window_seconds=60):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.costs = []
        self.is_open = False

    def record_cost(self, cost):
        now = time.time()
        self.costs.append((now, cost))
        self._cleanup()

        total_cost = sum(c for _, c in self.costs)
        if total_cost > self.threshold:
            self.is_open = True
            alert("Circuit breaker opened - costs exceeded threshold")

    def allow_request(self):
        if self.is_open:
            # Check if we should reset
            if time.time() - self.costs[-1][0] > self.window_seconds:
                self.is_open = False
                self.costs = []
                return True
            return False
        return True
```

---

## Dashboard Metrics

### Essential Cost Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Hourly spend | Cost in last hour | > 2x average |
| Daily spend | Cost today | > 80% budget |
| Cost per task | Average task cost | > expected |
| Token efficiency | Output/input ratio | < 0.3 |
| Cache hit rate | Cached vs new requests | < 50% |
| Model distribution | % by model | Unexpected shifts |

### Aden Dashboard
Aden provides built-in cost visualization:
- Real-time cost tracking
- Budget gauges with alerts
- Cost by agent/model breakdown
- Historical trends
- Anomaly detection

---

## Best Practices Summary

### Do's
1. ✅ Set budget limits before deployment
2. ✅ Implement automatic degradation
3. ✅ Monitor costs in real-time
4. ✅ Alert on anomalies
5. ✅ Optimize prompts for token efficiency
6. ✅ Cache common requests
7. ✅ Use appropriate models for task complexity
8. ✅ Review costs regularly

### Don'ts
1. ❌ Deploy without budget limits
2. ❌ Use GPT-4 for everything
3. ❌ Ignore cost metrics
4. ❌ Allow unlimited retries
5. ❌ Store full context forever
6. ❌ Skip testing cost scenarios
7. ❌ Forget about tool API costs

---

## Conclusion

AI agent cost management requires:

1. **Prevention**: Budget limits, degradation policies
2. **Detection**: Real-time tracking, anomaly alerts
3. **Optimization**: Smart model selection, token efficiency
4. **Protection**: Circuit breakers, runaway detection

Frameworks like Aden with built-in cost controls make this easier, but the principles apply to any agent system. Start with conservative limits and adjust based on real usage patterns.

---

*Last updated: January 2025*
