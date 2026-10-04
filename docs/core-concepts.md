# Core Concepts

This page explains the core ideas behind Hive — what it is, how it works, and why it is different — before diving into setup or CLI usage.

## What is Hive?

Hive is a goal-driven agent platform that turns natural-language objectives into executable, adaptive agent graphs for running real business processes.

Instead of manually defining workflows step by step, users describe *what they want to achieve*. Hive handles translating that intent into coordinated agent behavior.

## From Goal → Graph

In Hive, goals are first-class inputs.

A user provides a goal in plain language (for example, improving a business process or resolving an operational task). Hive translates this goal into an executable graph:

- Nodes represent agent actions, decisions, or human approval steps  
- Edges represent control flow and data flow between actions  

This graph-based representation allows Hive to reason about execution paths, dependencies, and intervention points without requiring users to design workflows upfront.

## The Adaptation Loop

Hive is designed for continuous improvement, not one-shot execution.

After agents execute a graph:
- Outcomes are observed
- Feedback is collected
- Future executions are adjusted based on what worked and what did not

This adaptation loop allows Hive agents to improve over time as conditions, data, or goals change — making them suitable for long-running, real-world business processes.

## Human-in-the-Loop (HITL)

Human-in-the-loop nodes are a core part of Hive’s design, not an afterthought.

HITL nodes allow humans to:
- Approve or reject critical actions  
- Correct agent decisions when context is missing  
- Intervene when safety, compliance, or judgment is required  

By explicitly modeling human oversight in the agent graph, Hive balances autonomy with trust and control.

## Observability & Cost Controls

Hive treats observability and cost controls as control surfaces for decision-makers, not just implementation details.

Teams can understand:
- What agents are doing
- Why certain actions were taken
- How much execution is costing over time  

This visibility helps PMs and architects operate agents confidently, with clear guardrails around behavior and budget.

## Why Hive is Different

Hive is not a traditional workflow engine and not just an LLM chaining framework.

- Unlike static workflow tools, Hive adapts based on execution feedback  
- Unlike simple agent frameworks, Hive models long-running processes with observability and HITL built in  
- Hive is designed for real business operations, not just demos or experiments  

This makes Hive suitable for teams evaluating autonomous agents as part of core operational systems.
