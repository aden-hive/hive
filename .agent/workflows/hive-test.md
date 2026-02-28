---
description: Iterative agent testing with session recovery. Generates tests from goal, executes, analyzes failures via runtime logs, fixes, and resumes from checkpoints. Use when testing an agent, debugging test failures, or verifying fixes without re-running from scratch.
when_to_use: |
  - Agent structure is complete and needs validation
  - Debugging failing tests iteratively
  - Verifying fixes without re-running expensive early nodes
  - Running final regression tests before deployment
  Loop: Generate → Execute → Analyze → Fix → Resume → Verify
---

use hive-test skill
