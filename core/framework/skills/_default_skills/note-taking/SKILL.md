---
name: hive.note-taking
description: Maintain structured working notes throughout execution to prevent information loss during context pruning.
metadata:
  author: hive
  type: default-skill
---

## Operational Protocol: Structured Note-Taking

Maintain structured working notes in shared buffer key `_working_notes`.
Update at these checkpoints:

- After completing each discrete subtask or batch item
- After receiving new information that changes your plan
- Before any tool call that will produce substantial output

Structure:

### Objective — restate the goal
### Current Plan — numbered steps, mark completed with ✓
### Key Decisions — decisions made and WHY
### Working Data — intermediate results, extracted values
### Open Questions — uncertainties to verify
### Blockers — anything preventing progress

Update incrementally — do not rewrite from scratch each time.
