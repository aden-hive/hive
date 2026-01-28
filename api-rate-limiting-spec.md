# API Rate Limiting Feature Specification

## Problem Statement
Hive currently has no built-in rate limiting for LLM API calls across the 100+ providers supported through LiteLLM integration. This creates several critical issues:

### Cost Control
- Agents can exhaust API budgets rapidly through unconstrained parallel or sequential calls
- A single runaway agent or infinite loop could rack up thousands of dollars in charges before being noticed
- No safeguards against cost overruns during development, testing, or production

### API Quota Management
- Many LLM providers enforce strict rate limits (e.g., OpenAI: 10,000 TPM for free tier, 90,000 TPM for tier 1)
- Exceeding these limits results in 429 errors, failed workflows, and degraded user experience
- Batch operations or multi-agent systems can easily hit these limits without throttling

### Account Suspension Risk
- Aggressive API usage patterns can trigger provider anti-abuse systems
- Accounts may be flagged, throttled, or suspended for appearing to abuse the service
- No way to enforce "good citizen" behavior across agent deployments

### User Frustrations
- A test agent gets stuck in a loop and burns through entire monthly OpenAI budget in 20 minutes
- Production agents fail with 429 errors during peak usage because there's no intelligent backoff or queuing
- Manual monitoring of API usage dashboards instead of framework-level controls
- Each developer implements their own rate limiting logic, leading to inconsistent and error-prone solutions

## Proposed Solution
Implement a comprehensive, provider-aware rate limiting system that works seamlessly with LiteLLM integration.

### Core Features

#### 1. Configurable Rate Limits
```yaml
# In agent configuration or environment
rate_limiting:
  enabled: true
  
  # Global defaults
  global:
    requests_per_minute: 60
    tokens_per_minute: 90000
    concurrent_requests: 10
    
  # Provider-specific overrides
  providers:
    openai:
      gpt-4:
        requests_per_minute: 500
        tokens_per_minute: 150000
      gpt-3.5-turbo:
        requests_per_minute: 3500
        tokens_per_minute: 90000
        
    anthropic:
      claude-sonnet-4:
        requests_per_minute: 50
        tokens_per_minute: 40000
        
  # Per-agent limits
  agents:
    my_production_agent:
      max_cost_per_hour: 10.00  # Dollar amount
      max_requests_per_run: 100
```

#### 2. Intelligent Backoff and Queuing
- Automatically detect 429 (rate limit) errors from providers
- Implement exponential backoff with jitter
- Queue excess requests instead of failing immediately
- Respect provider Retry-After headers

#### 3. Budget Controls
```python
# Set spending limits
rate_limiter.set_budget(
    max_hourly_spend=25.00,
    max_daily_spend=100.00,
    max_monthly_spend=1000.00,
    currency="USD"
)

# Get current usage
usage = rate_limiter.get_usage_stats()
# {
#   "requests_today": 1234,
#   "tokens_today": 450000,
#   "cost_today": 45.67,
#   "remaining_budget": 54.33
# }
```

#### 4. Multi-Level Limiting
- Global level: Across all agents and providers
- Provider level: Per LLM provider (OpenAI, Anthropic, etc.)
- Model level: Per specific model (GPT-4 vs GPT-3.5)
- Agent level: Per individual agent instance
- User/Team level: For multi-tenant deployments

#### 5. Runtime Warnings and Circuit Breakers
```python
# Warning thresholds
if usage.cost_today > 0.8 * budget.max_daily_spend:
    logger.warning("80% of daily budget consumed")
    
# Circuit breaker - stop all requests
if usage.cost_today >= budget.max_daily_spend:
    raise BudgetExceededError("Daily spending limit reached")
```

## Alternatives Considered

### 1. External API Gateway
Use a separate service like Kong, Tyk, or AWS API Gateway for rate limiting.

**Pros:**
- Industry-standard solutions
- Centralized management
- Works across multiple services

**Cons:**
- Adds infrastructure complexity
- Requires running additional services
- Doesn't integrate with Hive's agent-level controls
- Harder to configure per-agent or per-model
- Not feasible for standalone/self-hosted deployments

### 2. Provider-Level Solutions Only
Rely on each LLM provider's built-in rate limiting.

**Pros:**
- No additional code needed
- Providers already enforce their limits

**Cons:**
- No proactive control - you only know limits when you hit them
- Can't set custom budgets below provider limits
- No cost control mechanisms
- Poor user experience (failures instead of queuing)
- Doesn't protect against runaway costs

### 3. Application-Level Manual Implementation
Let each developer implement their own rate limiting in their agents.

**Pros:**
- Maximum flexibility
- Custom logic per use case

**Cons:**
- Duplicated effort across every agent
- Inconsistent implementations
- Error-prone
- No framework-level visibility or control
- Doesn't align with Hive's SDK-wrapped nodes philosophy

### 4. LiteLLM's Built-in Features
Use LiteLLM's existing rate limiting capabilities (if any).

**Analysis:**
- LiteLLM focuses on provider abstraction, not rate limiting
- May have basic retry logic but not comprehensive budget/quota management
- Should still be leveraged as foundation, but needs Hive-specific enhancements

### 5. Simple Token Bucket Algorithm
Implement basic token bucket without provider awareness.

**Pros:**
- Simple to implement
- Low overhead

**Cons:**
- Doesn't account for different provider limits
- No cost tracking
- Treats all requests equally (ignores model differences)
- Not production-grade

## Additional Context

### Current State Analysis

**What Hive Currently Has:**
- ✅ LiteLLM integration supporting 100+ providers
- ✅ Cost tracking and analytics (via TimescaleDB)
- ✅ Real-time monitoring and observability

**What's Missing:**
- ❌ Proactive rate limiting
- ❌ Request queuing and backoff
- ❌ Per-provider/model/agent limits
- ❌ Budget enforcement mechanisms
- ❌ Cost circuit breakers

### Real-World Scenarios

**Scenario 1: Development Accident**
```
Developer tests agent with infinite loop bug
- Without rate limiting: $847 in charges before noticed (2 hours)
- With rate limiting: $10 max (hourly budget), auto-stopped after 30 min
```

**Scenario 2: Production Spike**
```
Marketing agent processes 10,000 customer requests simultaneously
- Without rate limiting: 429 errors, 60% failure rate, poor UX
- With rate limiting: Queued requests, 100% success rate, 2-5 min delay
```

**Scenario 3: Multi-Model Optimization**
```
Agent uses GPT-4 for complex tasks, GPT-3.5 for simple ones
- Without rate limiting: GPT-4 quota exhausted quickly
- With rate limiting: Intelligent allocation, GPT-4 reserved for high-value tasks
```

### Provider Rate Limit Examples

| Provider | Model | Tier | RPM | TPM | Cost Impact |
|----------|-------|------|-----|-----|-------------|
| OpenAI | GPT-4 | Free | 3 | 200K | $10-30/hr if exceeded |
| OpenAI | GPT-4 | Tier 1 | 500 | 300K | $30-100/hr if exceeded |
| OpenAI | GPT-3.5 | Tier 1 | 3,500 | 160K | $2-10/hr if exceeded |
| Anthropic | Claude Sonnet 4 | - | 50 | 40K | $15-50/hr if exceeded |
| Google | Gemini Pro | - | 60 | 32K | $5-20/hr if exceeded |

*Source: Provider documentation as of January 2025*

### Monitoring Dashboard Mockup
```
┌─────────────────────────────────────────────┐
│ Rate Limit Status                           │
├─────────────────────────────────────────────┤
│ OpenAI GPT-4                                │
│ ████████████░░░░░░░░ 450/500 RPM (90%)     │
│ ████████░░░░░░░░░░░░ 240K/300K TPM (80%)   │
│                                             │
│ Anthropic Claude Sonnet                     │
│ ████████████████░░░░ 42/50 RPM (84%)       │
│ ████████████████░░░░ 34K/40K TPM (85%)     │
│                                             │
│ Budget (Today)                              │
│ ████████████████████ $87.34/$100 (87%)     │
│ ⚠️  WARNING: Approaching daily limit        │
└─────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 1: Core Rate Limiter (Week 1-2)
1. Implement TokenBucket class with refill logic
2. Create RateLimiter with request/token/concurrent limits
3. Add CostTracker for budget monitoring
4. Unit tests for core functionality

### Phase 2: LiteLLM Integration (Week 2-3)
1. Enhance LiteLLMProvider with rate limiting
2. Add retry logic with exponential backoff
3. Implement provider-specific configurations
4. Integration tests with real providers

### Phase 3: Configuration & Monitoring (Week 3-4)
1. YAML configuration schema
2. Provider defaults for major LLMs
3. Metrics and observability hooks
4. Dashboard UI components

### Phase 4: Advanced Features (Week 4-5)
1. Multi-level limiting (agent, user, team)
2. Dynamic budget adjustment
3. Priority queuing
4. Load balancing across API keys

### Phase 5: Documentation & Rollout (Week 5-6)
1. API documentation
2. Migration guide
3. Best practices guide
4. Gradual rollout to production

## Success Metrics
- **Cost Reduction**: 50% reduction in unexpected API cost overruns
- **Reliability**: 99% reduction in 429 error rates
- **Developer Productivity**: 80% reduction in manual rate limit management
- **User Satisfaction**: Positive feedback on budget controls and monitoring

## Testing Strategy
- Unit tests for all core components (>90% coverage)
- Integration tests with mock LLM providers
- Load testing with concurrent requests
- Chaos testing with simulated rate limit errors
- Budget enforcement validation
- Backoff algorithm verification

## Security Considerations
- Never log or expose API tokens
- Secure storage of cost tracking data
- Rate limit bypass prevention
- Audit logging for budget changes

## Documentation Requirements
- API reference for RateLimiter classes
- Configuration examples for common scenarios
- Migration guide from manual implementations
- Troubleshooting guide for rate limit issues
- Best practices for production deployments
