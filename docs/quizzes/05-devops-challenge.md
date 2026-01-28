# 🔧 DevOps Challenge

Master the deployment and operations of AI agent infrastructure! This challenge is for DevOps and Platform engineers who want to ensure Aden runs reliably at scale.

**Difficulty:** Advanced
**Time:** 2-3 hours
**Prerequisites:** Complete [Getting Started](./01-getting-started.md), Docker, Linux, CI/CD experience

---

## Part 1: Infrastructure Analysis (20 points)

### Task 1.1: Docker Deep Dive 🐳
Analyze the Aden Docker setup:

1. What Dockerfile exists in the repository and what does it build?
2. How would you containerize the MCP tools server?
3. How is hot reload enabled for development?
4. What would need to be mounted as volumes for persistence?
5. What networking considerations exist for the MCP server?

### Task 1.2: Service Dependencies 🔗
Map the service dependencies:

1. Create a dependency diagram showing which services depend on which
2. What's the startup order? Does it matter?
3. What happens if MongoDB is unavailable?
4. What happens if Redis is unavailable?
5. Which services are stateless vs stateful?

### Task 1.3: Configuration Management ⚙️
Analyze how configuration works:

1. How does `config.yaml` get generated?
2. What environment variables are required?
3. How are secrets managed? (API keys, database passwords)
4. What's the difference between dev and prod configs?

---

## Part 2: Deployment Scenarios (25 points)

### Task 2.1: Production Deployment Plan 📋
Design a production deployment for a company with:
- 100 active agents
- 10,000 LLM requests/day
- 99.9% uptime requirement
- Multi-region support needed

Provide:
1. **Infrastructure diagram** (cloud provider of your choice)
2. **Service sizing** (CPU, memory for each component)
3. **Database setup** (primary/replica, backups)
4. **Load balancing strategy**
5. **Estimated monthly cost**

### Task 2.2: Kubernetes Migration 🚢
Convert the Docker Compose setup to Kubernetes:

1. Create a Kubernetes deployment manifest for the Hive backend
2. Create a Service and Ingress for external access
3. Design a ConfigMap for configuration
4. Create a Secret for sensitive data
5. Set up a HorizontalPodAutoscaler

```yaml
# Provide your manifests here
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hive-backend
spec:
  # Your implementation
```

### Task 2.3: High Availability Design 🔄
Design for high availability:

1. How would you handle backend service failures?
2. How would you handle database failover?
3. What's your strategy for zero-downtime deployments?
4. How would you handle WebSocket connections during rolling updates?
5. Design a disaster recovery plan

---

## Part 3: CI/CD Pipeline (25 points)

### Task 3.1: GitHub Actions Pipeline 🔄
Create a complete CI/CD pipeline:

```yaml
# .github/workflows/ci-cd.yml
name: Aden CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  # Your implementation should include:
  # - Linting
  # - Type checking
  # - Unit tests
  # - Integration tests
  # - Build Docker images
  # - Push to registry
  # - Deploy to staging (on develop)
  # - Deploy to production (on main, with approval)
```

Include:
1. Separate jobs for frontend and backend
2. Matrix testing for multiple Node versions
3. Docker layer caching
4. Deployment gates/approvals
5. Rollback strategy

### Task 3.2: Testing Strategy 🧪
Design the testing infrastructure:

1. **Unit Tests:** What to test? How to mock LLM calls?
2. **Integration Tests:** How to test with real databases?
3. **E2E Tests:** What user flows to test?
4. **Load Tests:** How to simulate agent traffic?
5. **Chaos Tests:** What failures to simulate?

Provide example test configurations for each type.

### Task 3.3: Environment Management 🌍
Design environment strategy:

| Environment | Purpose | Data | Who Can Access |
|-------------|---------|------|----------------|
| Local | Development | Mock | Developers |
| Dev | Integration | Sanitized | Engineering |
| Staging | Pre-prod | Copy of prod | Engineering + QA |
| Production | Live | Real | Restricted |

For each environment, specify:
1. How it's provisioned
2. How data is managed
3. How deployments happen
4. Access control

---

## Part 4: Observability & Operations (30 points)

### Task 4.1: Monitoring Stack 📊
Design a comprehensive monitoring solution:

1. **Metrics:** What to collect? (list at least 10 key metrics)
2. **Logs:** Logging strategy and aggregation
3. **Traces:** Distributed tracing for agent flows
4. **Dashboards:** Design 3 key dashboards

```yaml
# Provide a docker-compose addition for monitoring
services:
  prometheus:
    # Your config
  grafana:
    # Your config
  # Add more as needed
```

### Task 4.2: Alerting Rules 🚨
Create alerting rules for critical scenarios:

```yaml
# Prometheus alerting rules
groups:
  - name: aden-critical
    rules:
      - alert: HighErrorRate
        expr: # Your expression
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: # Your description

      # Add more alerts for:
      # - Service down
      # - High latency
      # - Budget exceeded
      # - Database connection issues
      # - Memory pressure
```

Create at least 8 alert rules covering different failure modes.

### Task 4.3: Incident Response 🆘
Create an incident response runbook:

**Scenario:** Agent response times spike to 30 seconds (normal: 2 seconds)

Provide:
1. **Detection:** How was this discovered?
2. **Triage:** Initial investigation steps
3. **Diagnosis:** Decision tree for root causes
4. **Resolution:** Steps for each root cause
5. **Post-mortem:** Template for incident review

```markdown
# Runbook: High Agent Latency

## Symptoms
- Agent response times > 10s
- Dashboard showing degraded status

## Initial Triage
1. Check [ ] Is this affecting all agents or specific ones?
2. Check [ ] Is the backend healthy? (health endpoint)
3. Check [ ] Are databases responsive?
...

## Diagnostic Steps
...

## Resolution Steps
### If LLM Provider Issue:
...

### If Database Issue:
...
```

---

## Part 5: Security Hardening (Bonus - 20 points)

### Task 5.1: Security Audit 🔒
Perform a security analysis:

1. **Network:** What ports are exposed? Are they necessary?
2. **Secrets:** How are secrets currently handled? Improvements?
3. **Authentication:** How is API auth implemented?
4. **Container Security:** What image scanning would you add?
5. **Database Security:** What hardening is needed?

### Task 5.2: Compliance Checklist ✅
For SOC 2 compliance, what changes are needed?

1. Access control improvements
2. Audit logging requirements
3. Encryption requirements
4. Data retention policies
5. Incident response requirements

---

## Submission Checklist

- [ ] Part 1 infrastructure analysis
- [ ] Part 2 deployment designs and manifests
- [ ] Part 3 CI/CD pipeline YAML
- [ ] Part 4 monitoring and alerting configs
- [ ] (Bonus) Part 5 security analysis

### How to Submit

1. Create a GitHub Gist with your answers
2. Name it `aden-devops-YOURNAME.md`
3. Include all YAML/configuration files
4. Include any diagrams (use Mermaid, ASCII, or image links)
5. Email to `careers@adenhq.com`
   - Subject: `[DevOps Challenge] Your Name`

---

## Scoring

| Section | Points |
|---------|--------|
| Part 1: Infrastructure | 20 |
| Part 2: Deployment | 25 |
| Part 3: CI/CD | 25 |
| Part 4: Observability | 30 |
| Part 5: Security (Bonus) | +20 |
| **Total** | **100 (+20)** |

**Passing score:** 75+ points

---

## Bonus Points (+15)

- **+5:** Set up a working local Kubernetes cluster with Aden
- **+5:** Create a Terraform module for cloud deployment
- **+5:** Submit a PR improving deployment documentation

---

## Resources

- [Docker Documentation](https://docs.docker.com)
- [Kubernetes Documentation](https://kubernetes.io/docs)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Prometheus](https://prometheus.io/docs)
- [Grafana](https://grafana.com/docs)

---

Good luck! We're looking for engineers who keep systems running smoothly! 🔧✨
