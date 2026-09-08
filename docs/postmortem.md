# Run Post-Mortem (`hive postmortem`)

Every run writes three levels of runtime logs (see
[`framework/tracker/runtime_log_schemas.py`](../core/framework/tracker/runtime_log_schemas.py)):
a summary, per-node details, and per-step tool logs. `hive postmortem` reads
those logs back and tells you what went wrong, instead of leaving you to scroll
a JSONL file.

It is read-only. It never touches a live runtime, so it is safe to point at a
run that is still in progress or at one that crashed before `end_run()`.

## Usage

```bash
hive postmortem                    # analyse the most recent run under ~/.hive
hive postmortem session_2026...    # a unique prefix or substring is enough
hive postmortem --list             # what runs are on disk
```

Common flags:

| Flag | Purpose |
| --- | --- |
| `--path DIR` | Search root (default `~/.hive`). Point at one agent's storage dir to narrow the scan. |
| `--format {text,markdown,json}` | `markdown` for pasting into an issue, `json` for tooling. |
| `--output FILE` | Write the report to a file instead of stdout. |
| `--model ID` | Price tokens against a specific model instead of the configured one. |
| `--fail-on SEVERITY` | Exit `1` when a finding at that severity or worse exists. |

Exit codes: `0` clean, `1` findings at/above `--fail-on`, `2` no readable run.

## What it reports

**Vitals** — status, duration, nodes/steps, tool calls and error rate, token
totals, and an estimated cost from the curated model catalog. The report always
names the model and where that model came from, so an estimate is never mistaken
for a billed amount.

One vital is worth calling out: **re-sent context**. Every step of an event loop
re-sends the whole conversation, so only the single largest send is unavoidable.
Everything beyond it is prefix the provider has already seen — the number to
watch when deciding whether prompt caching or in-node compaction is worth it.

**Findings** — ranked worst-first, each with evidence and a suggested fix:

| Code | What it catches |
| --- | --- |
| `node_failed` | A node reported failure. Start here. |
| `bad_exit_status` | Node exited `stalled`, `escalated`, `failure`, or `guard_failure`. |
| `step_errors` | Steps that raised or ended partial — tokens spent for no result. |
| `retry_storm` / `escalation_loop` | The judge kept sending work back. |
| `node_reexecuted` | A node ran more than one attempt. |
| `tool_thrash` | The same tool called repeatedly with byte-identical arguments. |
| `repeated_output` | Consecutive steps emitting identical assistant text. |
| `failing_tool` | A tool erroring often enough to be the real bottleneck. |
| `slow_tools` | Individual calls slow enough to dominate wall-clock time. |
| `oversized_tool_result` | Results large enough to crowd out the context window. |
| `context_growth` | A node's prompt ballooning across its steps. |
| `resend_overhead` | Most input tokens are re-sent prefix. |

Thresholds are deliberately conservative: a clean run reports nothing, so
anything printed is worth a look.

## In CI

Fail a nightly agent run when it degrades:

```bash
hive postmortem --fail-on high --format markdown -o postmortem.md
```

## As a library

```python
from framework.postmortem import analyze, load_run, resolve_run

location = resolve_run(None)               # most recent run
report = analyze(load_run(location))
for finding in report.sorted_findings():
    print(finding.severity, finding.code, finding.title)
```

`Thresholds` is a plain dataclass — pass a modified copy to `analyze()` to tune
any detector. Adding a detector means writing one function over
`(nodes, steps, thresholds) -> list[Finding]` and appending it to `DETECTORS` in
[`framework/postmortem/detectors.py`](../core/framework/postmortem/detectors.py).
