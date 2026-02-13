# ADR-006: Goal-driven graph generation vs manual definition

## Status: Accepted

## Context

Hive emphasizes outcome-driven development: users express goals, success criteria,
and constraints. The framework already supports manual graph definitions, but
manual wiring is slower and less aligned with the goal-driven model.

## Decision

Default to goal-driven graph generation via the coding agent. Manual graph
definition remains available for advanced or specialized use cases.

## Consequences

- Accelerates agent creation and encourages standardized goal definitions.
- Keeps a fallback path for power users and legacy workflows.
- Requires validation tooling to ensure generated graphs remain correct and safe.

