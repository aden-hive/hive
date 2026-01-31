# Memory Tooling Example (STM + LTM)

This example demonstrates how to model **Short-Term Memory (STM)** and **Long-Term Memory (LTM)** workflows using Aden Hive's plan execution system.

> **Why this exists**
>
> The repo includes STM/LTM concepts, but new contributors may not see a clear end-to-end usage pattern.
> This folder provides a minimal, beginner-friendly workflow example without changing any core framework logic.

---

## What this example shows

### STM (Short-Term Memory)
STM is represented as the **current execution context**: values produced by one step that are referenced by later steps.

In this repo, STM-style passing of values is achieved via **step outputs** and `$variable` references, e.g.:

- `$step_1_capture_user_message.stm_user_message`

This is validated by the plan validator (see `validate_plan()` in the MCP agent builder server).

---

### LTM (Long-Term Memory)
LTM is represented as a **durable memory store** accessed via tool calls (typically through an MCP tool server).

This example includes steps that:
- write a stable user profile into LTM
- read it back later
- generate a personalized answer using both STM + LTM

---

## Files

- `example_plan.json`  
  A plan that demonstrates a realistic memory workflow (capture → extract → store → recall → respond).

- `example_agent.json`  
  A graph-style agent representation of the same idea.

- `instructions.md`  
  Step-by-step instructions for validating and simulating the plan using the MCP Agent Builder.

---

## How to validate the plan

The MCP Agent Builder provides a `validate_plan()` tool that checks:

- required step fields exist
- step dependencies reference valid step IDs
- `$variable` references resolve to outputs of previous steps

This prevents a common issue where a step references memory/context that was never produced.

---

## How to simulate the plan execution

The MCP Agent Builder also provides `simulate_plan_execution()` which prints a step-by-step trace:

- step order (dependency-driven)
- expected outputs per step
- a simulated execution context

This is useful for quickly understanding how STM values flow forward and how LTM operations fit into the workflow.

---

## Expected outcome

After running the plan:

1. The user’s initial message is captured in STM.
2. Stable preferences are extracted (name, style, location, etc).
3. Those preferences are written to LTM.
4. A later user question is answered using both:
   - STM (latest question)
   - LTM (saved preferences)

Result: the agent responds in a personalized way, even if the new question doesn’t repeat user preferences.
