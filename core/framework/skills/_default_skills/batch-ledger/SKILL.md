---
name: hive.batch-ledger
description: Track per-item status when processing collections to prevent skipped or duplicated items.
metadata:
  author: hive
  type: default-skill
---

## Operational Protocol: Batch Progress Ledger

When processing a collection of items, maintain a batch ledger in `_batch_ledger`.

Initialize when you identify the batch:
- `_batch_total`: total item count
- `_batch_ledger`: JSON with per-item status

Per-item statuses: pending → in_progress → completed|failed|skipped

- Set `in_progress` BEFORE processing
- Set final status AFTER processing with 1-line result_summary
- Include error reason for failed/skipped items
- Update aggregate counts after each item
- NEVER remove items from the ledger
- If resuming, skip items already marked completed
