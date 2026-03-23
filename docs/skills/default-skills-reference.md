# Default Skills Reference (Phase 4)

Hive ships with six built-in operational skills that provide runtime resilience.

These default skills are always loaded (unless disabled) and appear in the agent’s system
prompt as “Operational Protocols”.

## The six default skills

| Skill | Purpose | Typical trigger | Main tuning knobs |
|-------|---------|------------------|-------------------|
| `hive.note-taking` | Structured working notes in shared memory | Multi-step tasks with intermediate findings | verbosity, section format, checkpoint cadence |
| `hive.batch-ledger` | Track per-item status in batch operations | Processing a list of items (files, tickets, rows) | batch size, retry policy, completion threshold |
| `hive.context-preservation` | Save context before context window pruning | Long sessions near context pressure | snapshot frequency, summary depth |
| `hive.quality-monitor` | Self-assess output quality periodically | Deliverables requiring quality bars | check interval, strictness, stop-on-fail |
| `hive.error-recovery` | Structured error classification and recovery | Tool failures and runtime exceptions | max retries, fallback policy |
| `hive.task-decomposition` | Break complex tasks into subtasks | Broad or ambiguous requests | decomposition depth, merge policy |

## Shared memory expectations (high level)

Each default skill follows a shared memory convention and stores its intermediate results so the
agent can keep working even when context needs pruning.

If you disable a default skill, its intermediate state will not be produced.

