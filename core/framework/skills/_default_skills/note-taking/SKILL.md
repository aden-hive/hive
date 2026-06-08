---
name: hive.note-taking
description: Maintain a free-form scratchpad of decisions, extracted values, and open questions so context pruning doesn't lose anything you still need.
metadata:
  author: hive
  type: default-skill
  visibility: [worker]
---

## Operational Protocol: Structured Note-Taking

Maintain free-form working notes in shared buffer key `_working_notes` for data that *you* need to remember but that isn't captured by the colony task queue.

**Do not duplicate the queue in here.** Per-task goal, ordered steps, and SOP gates live in `progress.db` — use `hive.colony-progress-tracker` for those. These notes are for things the DB schema doesn't cover.

Update at these checkpoints:

- After receiving new information that changes how you plan to approach the current step
- Before any tool call that will produce substantial output you'll need to reference later
- When you make a non-obvious decision whose *why* would be lost if the tool call history gets pruned

Structure:

### Key Decisions — decisions made and WHY
### Working Data — intermediate results, extracted values (URLs, IDs, key snippets — not full pages)
### Open Questions — uncertainties you plan to verify
### Blockers — anything preventing progress that isn't already captured in `tasks.last_error`

Update incrementally — do not rewrite from scratch each time.
