---
description: Interactive debugging companion for Hive agents — identifies runtime failures, retry loops, tool errors, and stalled execution through L1/L2/L3 log analysis. Use when an agent is failing, stuck, or producing unexpected results.
when_to_use: |
  - Agent is failing at runtime or producing unexpected results
  - Seeing repeated retry loops or escalations in logs
  - Tool calls are failing (auth, timeout, rate limit errors)
  - Agent execution is stalled or taking too long
  - Need root cause analysis before fixing a specific node
  Stages: Setup → Mode → Triage → Diagnosis → Root Cause → Fix → Verify
---

use hive-debugger skill
