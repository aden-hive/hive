---
name: hive.quality-monitor
description: Periodically self-assess output quality to catch degradation before the judge does.
metadata:
  author: hive
  type: default-skill
  visibility: [worker]
---

## Operational Protocol: Quality Self-Assessment

Every {{assessment_interval}} iterations, self-assess:

1. On-task? Still working toward the stated objective?
2. Thorough? Cutting corners compared to earlier?
3. Non-repetitive? Producing new value or rehashing?
4. Consistent? Latest output contradict earlier decisions?
5. Complete? Tracking all items, or silently dropped some?

If degrading: write assessment to `_quality_log`, re-read `_working_notes`,
change approach explicitly. If acceptable: brief note in `_quality_log`.
