# 🧠 Architecture Deep Dive Challenge

Test your understanding of Aden's architecture and backend systems. This challenge is perfect for backend engineers who want to contribute to the core framework.

**Difficulty:** Intermediate
**Time:** 1-2 hours
**Prerequisites:** Complete [Getting Started](./01-getting-started.md), familiarity with Node.js/TypeScript

---

## Part 1: System Architecture (20 points)

### Task 1.1: Component Mapping 🗺️
Study the Aden architecture and answer:

1. Describe the data flow from when a user defines a goal to when worker agents execute. Include all major components.

2. Explain the "self-improvement loop" - what happens when an agent fails?

3. What's the difference between:
   - Coding Agent vs Worker Agent
   - STM (Short-Term Memory) vs LTM (Long-Term Memory)
   - Hot storage vs Cold storage for events

### Task 1.2: Database Design 💾
Aden uses three databases. For each, explain:

1. **TimescaleDB:** What type of data is stored? Why TimescaleDB specifically?
2. **MongoDB:** What is stored here? Why a document database?
3. **PostgreSQL:** What is its primary purpose?

### Task 1.3: Real-time Communication 📡
Answer these about the real-time systems:

1. What protocol connects the SDK to the Hive backend for policy updates?
2. How does the dashboard receive live agent metrics?
3. What is the heartbeat interval for SDK health checks?

---

## Part 2: Code Analysis (25 points)

### Task 2.1: API Routes 🛣️
Explore the backend code and document:

1. List all the main API route prefixes (e.g., `/user`, `/v1/control`, etc.)
2. For the `/v1/control` routes, what are the main endpoints and their purposes?
3. What authentication method is used for API requests?

### Task 2.2: MCP Tools Deep Dive 🔧
The MCP server provides 19 tools. Categorize them and answer:

1. List all **Budget tools** (tools with "budget" in the name)
2. List all **Analytics tools**
3. List all **Policy tools**
4. Pick ONE tool and explain:
   - What parameters does it accept?
   - What does it return?
   - When would the Coding Agent use it?

### Task 2.3: Event Specification 📊
Find and analyze the SDK event specification:

1. What are the four event types that can be sent from SDK to server?
2. For a `MetricEvent`, list at least 5 fields that are captured
3. What is "Layer 0 content capture" and when is it used?

---

## Part 3: Design Questions (25 points)

### Task 3.1: Scaling Scenario 📈
Imagine Aden needs to handle 1000 concurrent agents across 50 teams:

1. Which components would be the bottleneck? Why?
2. How would you horizontally scale the system?
3. What database optimizations would you recommend?
4. How would you ensure team data isolation at scale?

### Task 3.2: New Feature Design 🆕
Design a new feature: **Agent Collaboration Logs**

Requirements:
- Track when agents communicate with each other
- Store the message content and metadata
- Support querying by time range, agent, or conversation thread
- Real-time streaming to the dashboard

Provide:
1. Database schema design (which DB and table structure)
2. API endpoint design (routes and payloads)
3. How would this integrate with existing event batching?

### Task 3.3: Failure Handling ⚠️
The self-healing loop is core to Aden. Design the detailed flow:

1. How should failures be categorized (types of failures)?
2. What data should be captured for the Coding Agent to improve?
3. How do you prevent infinite failure loops?
4. When should the system escalate to human intervention?

---

## Part 4: Practical Implementation (30 points)

### Task 4.1: Write a New MCP Tool 🛠️
Create a new MCP tool called `hive_agent_performance_report`:

**Requirements:**
- Returns performance metrics for a specific agent over a time period
- Includes: total requests, success rate, avg latency, total cost
- Accepts parameters: `agent_id`, `start_time`, `end_time`

Provide:
1. Tool definition (name, description, input schema)
2. Implementation pseudocode or actual TypeScript
3. Example request and response

### Task 4.2: Budget Enforcement Algorithm 💰
Implement the logic for budget enforcement:

```typescript
interface BudgetCheck {
  action: 'allow' | 'block' | 'throttle' | 'degrade';
  reason: string;
  degradedModel?: string;
  delayMs?: number;
}

function checkBudget(
  currentSpend: number,
  budgetLimit: number,
  requestedModel: string,
  estimatedCost: number
): BudgetCheck {
  // Your implementation here
}
```

Requirements:
- Block if budget would be exceeded
- Throttle (2000ms delay) if ≥95% used
- Degrade to cheaper model if ≥80% used
- Allow otherwise

### Task 4.3: Event Aggregation Query 📈
Write a SQL query for TimescaleDB that:

1. Aggregates metrics by hour for the last 24 hours
2. Groups by model and provider
3. Calculates: total tokens, total cost, avg latency, request count
4. Orders by total cost descending

---

## Submission Checklist

- [ ] All Part 1 architecture answers
- [ ] All Part 2 code analysis answers
- [ ] All Part 3 design documents
- [ ] All Part 4 implementations

### How to Submit

1. Create a GitHub Gist with your answers
2. Name it `aden-architecture-YOURNAME.md`
3. Include any code files as separate files in the Gist
4. Email to `careers@adenhq.com`
   - Subject: `[Architecture Challenge] Your Name`

---

## Scoring

| Section | Points |
|---------|--------|
| Part 1: System Architecture | 20 |
| Part 2: Code Analysis | 25 |
| Part 3: Design Questions | 25 |
| Part 4: Implementation | 30 |
| **Total** | **100** |

**Passing score:** 75+ points

---

## Bonus Points (+20)

- Identify a bug or improvement in the actual codebase and open an issue
- Submit a PR fixing a documentation issue
- Create a diagram of your design using Mermaid or similar

---

Good luck! We're looking for engineers who can think systematically about distributed systems! 🏗️
