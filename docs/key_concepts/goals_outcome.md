# Goals & Outcome-Driven Development

## The Core Idea

Business processes are outcome-driven. A sales team doesn't follow a rigid script — they adapt their approach until the deal closes. A support agent doesn't execute a flowchart — they resolve the customer's issue. The outcome is what matters, not the specific steps taken to get there.

Hive is built on this principle. Instead of hardcoding agent workflows step by step, you define the outcome you want, and the framework figures out how to get there. We call this **Outcome-Driven Development (ODD)**.

## Task-Driven vs Goal-Driven vs Outcome-Driven

These three paradigms represent different levels of abstraction for building agents:

**Task-Driven Development (TDD)** asks: *"Is the code correct?"*

You define explicit steps. The agent follows them. Success means the steps ran without errors. The problem: an agent can execute every step perfectly and still produce a useless result. The steps become the goal, not the actual outcome.

**Goal-Driven Development (GDD)** asks: *"Are we solving the right problem?"*

You define what you want to achieve. The agent plans and executes toward that goal. Better than TDD because it captures intent. But goals can be vague — "improve customer satisfaction" doesn't tell you when you're done.

**Outcome-Driven Development (ODD)** asks: *"Did the system produce the desired result?"*

You define measurable success criteria, hard constraints, and the context the agent needs. The agent is evaluated against the actual outcome, not whether it followed the right steps or aimed at the right goal. This is what Hive implements.

## Goals as First-Class Citizens

In Hive, a `Goal` is not a string description. It's a structured object with three components:

### Success Criteria

Each goal has weighted success criteria that define what "done" looks like. These aren't binary pass/fail checks — they're multi-dimensional measures of quality.

```python
Goal(
    id="deep-research",
    name="Deep Research Report",
    success_criteria=[
        SuccessCriterion(
            id="comprehensive",
            description="Report covers all major aspects of the research topic",
            metric="llm_judge",
            weight=0.4
        ),
        SuccessCriterion(
            id="cited",
            description="All claims are backed by cited sources",
            metric="llm_judge",
            weight=0.3
        ),
        SuccessCriterion(
            id="structured",
            description="Report has clear sections with headings and a summary",
            metric="output_contains",
            target="## Summary",
            weight=0.3
        ),
    ],
    ...
)
```

Metrics can be `output_contains`, `output_equals`, `llm_judge`, or `custom`. Weights let you express what matters most — a perfectly compliant message that isn't personalized still falls short.

### Constraints

Constraints define what must **not** happen. They're the guardrails.

```python
constraints=[
    Constraint(
        id="no_spam",
        description="Never send more than 3 messages to the same person per week",
        constraint_type="hard",    # Violation = immediate escalation
        category="safety"
    ),
    Constraint(
        id="budget_limit",
        description="Total LLM cost must not exceed $5 per run",
        constraint_type="soft",    # Violation = warning, not a hard stop
        category="cost"
    ),
]
```

Hard constraints are non-negotiable — violating one triggers escalation or failure. Soft constraints are preferences that the agent should respect but can bend when necessary. Constraint categories include `time`, `cost`, `safety`, `scope`, and `quality`.

### Context

Goals carry context — domain knowledge, preferences, background information that the agent needs to make good decisions. This context is injected into every LLM call the agent makes, so the agent is always reasoning with the full picture.

## Why This Matters

When you define goals with weighted criteria and constraints, three things happen:

1. **The agent can self-correct.** Goals are injected into every LLM call, so the agent is always reasoning against its success criteria. Within a [graph execution](./graph.md), nodes use these criteria to decide whether to accept their output, retry, or escalate — self-correction in real time.

2. **Evolution has a target.** When an agent fails, the framework knows *which criteria* it fell short on, which gives the coding agent specific information to improve the next generation (see [Evolution](./evolution.md)).

3. **Humans stay in control.** Constraints define the boundaries. The agent has freedom to find creative solutions within those boundaries, but it can't cross the lines you've drawn.

The goal lifecycle flows through `DRAFT → READY → ACTIVE → COMPLETED / FAILED / SUSPENDED`, giving you visibility into where each objective stands at any point during execution.
