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

## Two ways to state an outcome

**In conversation.** With the built-in Queens, your message *is* the goal. The Queen turns it into a [task plan](./coordination.md#the-task-plan) you can see and edit, asks when something is ambiguous, and, once the work becomes a colony, defines "done" concretely as the columns of the colony's [tracker](./coordination.md#the-tracker): one row per unit of work, checked with SQL before she reports back. You stay the judge of the result.

**As a structured `Goal`.** Agents loaded from an agent definition (`framework/loader/agent_loader.py`) can declare a `Goal` object (`framework/schemas/goal.py`) instead of a sentence. Its success criteria become the agent's judge check, and its criteria, constraints, and context are written into the agent's prompt. The built-in Queens and workers carry an empty `Goal` and rely on the conversation, the plan, and the tracker instead.

## Goals as First-Class Citizens

A structured `Goal` is not a string description. It has three components:

### Success Criteria

Each goal has weighted success criteria that define what "done" looks like.

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

Each criterion names a metric (`output_contains`, `output_equals`, `llm_judge`, or `custom`) and a weight, so you can say what matters most — a perfectly compliant message that isn't personalized still falls short.

### Constraints

Constraints define what must **not** happen. They're the guardrails.

```python
constraints=[
    Constraint(
        id="no_spam",
        description="Never send more than 3 messages to the same person per week",
        constraint_type="hard",    # written into the prompt as MUST
        category="safety"
    ),
    Constraint(
        id="tone",
        description="Keep messages under 120 words",
        constraint_type="soft",    # written into the prompt as SHOULD
        category="quality"
    ),
]
```

Hard constraints are the lines the agent must not cross; soft constraints are preferences it should respect but can bend when necessary. Both are written into the agent's prompt (as MUST and SHOULD), so they're guidance the model reasons with rather than a runtime enforcement layer. For hard limits on spend or reach, use the tools themselves: tool allowlists, tool-call budgets, and the credentials you grant. Constraint categories include `time`, `cost`, `safety`, `scope`, and `quality`.

### Context

Goals carry context — domain knowledge, preferences, background information that the agent needs to make good decisions. It's written into the agent's prompt alongside the criteria and constraints, so the agent is always reasoning with the full picture.

## Why This Matters

Whether the outcome comes from a conversation or a structured `Goal`, stating it as a result rather than a procedure pays off three ways:

1. **The agent can self-correct.** It's always reasoning against what "done" means. Within [the loop](./the_loop.md), a judge can use declared criteria to accept the output, retry with feedback, or escalate; in a colony, the Queen checks the tracker rows against what you asked for before she reports back.

2. **Improvement has a target.** When an agent falls short, the gap is concrete: a missed criterion, an empty tracker column. That signal is what drives [how a colony improves](./improvement.md) — the feedback the judge injects, the notes a Queen reflects into memory, and the skill she writes once the pilot works.

3. **Humans stay in control.** You define the boundaries. The agent has freedom to find creative solutions within them, and the Queen asks you when a decision is yours.

## Learn more

- [The Colony](./colony.md) — what you point a goal at.
- [The Queen](./queen.md) — who takes the goal and grows a colony around it.
- [The Loop](./the_loop.md) — how the judge evaluates output against your success criteria.
- [How a Colony Improves](./improvement.md) — how missed criteria drive improvement.
