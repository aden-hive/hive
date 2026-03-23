# Tuning Default Skills (Phase 4)

You can tune default skills to adapt behavior to workload while keeping the resilience
benefits they provide.

## Disable vs. configure

Prefer tuning/configure when:

- You only need less verbosity or lower frequency.
- You want guardrails, but for narrower scopes.

Disable when:

- A skill introduces measurable noise for a specific agent profile.
- A policy or environment constraint makes the default behavior invalid.

## How to disable default skills

Example (disable a specific default skill):

```python
default_skills = {
    "hive.quality-monitor": {"enabled": False},
}
```

Example (disable all defaults):

```python
default_skills = {
    "_all": {"enabled": False},
}
```

## Suggested tuning workflow

1. Keep all defaults enabled for baseline runs.
2. Measure latency, output quality, and retry behavior on representative tasks.
3. Reduce the noisiest skill settings first (do not change everything at once).
4. Re-run the same workload and compare deltas.
5. Disable only if regressions are not recoverable by tuning.

> TODO(#6369): Add concrete examples for command-based diagnostics once CLI behavior is finalized.

