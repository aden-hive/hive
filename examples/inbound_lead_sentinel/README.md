# Inbound Lead Sentinel Agent

The **Inbound Lead Sentinel Agent** is a goal-driven autonomous agent built with Hive to prevent lead leakage and protect revenue by qualifying inbound demo requests before routing them to sales systems like Salesforce.

This agent demonstrates how Hive can orchestrate multiple enterprise tools in a resilient, adaptive, production-grade workflow.

---

## 🧠 Problem Statement

High-growth B2B companies often struggle with:

- Lead leakage from inbound demo requests
- Slow response times from sales teams
- Incomplete or low-quality lead data
- Brittle hardcoded workflows that fail when logic changes

This agent solves these problems using Hive’s adaptive multi-node agent architecture.

---

## 🚀 What This Agent Does

The Inbound Lead Sentinel agent:

1. **Triggers on new inbound demo requests**
2. **Enriches lead data using Apollo.io**
3. **Scores leads using Queen Bee ICP scoring**
4. **Routes high-value leads to Salesforce as Opportunities**
5. **Blocks or queues low-quality leads to protect sales margin**
6. **Implements a circuit breaker to prevent runaway API calls**
7. **Logs failures and supports adaptive self-improvement**

---

## 🏗 Architecture Overview

### Multi-Node Graph Design

| Node | Purpose |
|------|---------|
| Trigger Node | Detect inbound lead events |
| Enrichment Node | Fetch company & persona data from Apollo |
| Scoring Node | Evaluate ICP fit using Queen Bee |
| Routing Node | Push qualified leads to Salesforce |
| Guardrail Node | Rate limiting & circuit breaker |
| Observability Node | Logs and telemetry |

---

## ⚙️ Installation

```bash
# Clone Hive
git clone https://github.com/adenhq/hive.git
cd hive

# Run quickstart setup
./quickstart.sh

## ▶️ Run the Example

From the example directory:

```bash
cd hive/examples/inbound_lead_sentinel
python -c "from agent import inbound_lead_pipeline; print(inbound_lead_pipeline({'name':'John','email':'john@startup.com'}))"
```

Expected output:

```json
{"status": "sent_to_salesforce", "lead": {"name": "John", "email": "john@startup.com", "company_size": 250, "industry": "SaaS"}}
```

## ✅ Run Tests

Tests are provided under `tests/`. If `pytest` is installed:

```bash
pytest -q tests
```

If `pytest` is not available, you can still validate behavior using the command in “Run the Example”.
