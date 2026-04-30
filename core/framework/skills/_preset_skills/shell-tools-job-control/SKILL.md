---
name: hive.shell-tools-job-control
description: Use when launching anything that runs longer than a minute, anything that streams logs, anything you want to keep running while doing other work — or when shell_exec auto-backgrounded on you and returned a job_id. Teaches the start→poll→wait pattern with shell_job_logs offset bookkeeping, the `wait_until_exit=True` blocking-poll idiom, the truncated_bytes_dropped resumption signal, the merge_stderr decision, the SIGINT→SIGTERM→SIGKILL escalation ladder via shell_job_manage, and the hard rule that jobs die when the shell-tools server restarts. Read before calling shell_job_start, or right after shell_exec auto-backgrounded.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Background job control

Background jobs are how you do things that take time without blocking your conversation. Three tools cover the surface: `shell_job_start`, `shell_job_logs`, `shell_job_manage`.

## When to use a job

- Builds, deploys, long tests
- Processes you want to monitor (streaming a log file, a dev server)
- Anything that auto-backgrounded from `shell_exec` (you have a `job_id`; pivot to this skill's idioms)

For one-shot work expected to finish quickly, `shell_exec` is simpler. The auto-promotion mechanic in `shell_exec` is your safety net — start with `shell_exec`, take over with this skill if needed.

## Lifecycle

```
shell_job_start(command, ...)
  → { job_id, pid, started_at }

shell_job_logs(job_id, since_offset=0, max_bytes=64000)
  → { data, offset, next_offset, status: "running"|"exited", exit_code, ... }

# Repeat with since_offset = previous next_offset until status == "exited"
# Or block once with wait_until_exit=True:
shell_job_logs(job_id, since_offset=N, wait_until_exit=True, wait_timeout_sec=60)
  → blocks server-side until exit or timeout
```

After exit, the job is retained for inspection (`shell_job_manage(action="list")`) until evicted by FIFO (50 most recent exits kept).

## Offset bookkeeping — the only rule that matters

The job's output lives in a 4 MB ring buffer per stream. Each call to `shell_job_logs` returns:

- `data` — bytes between `since_offset` and `next_offset`
- `next_offset` — pass this as `since_offset` on your next call
- `truncated_bytes_dropped` — non-zero when your `since_offset` was older than the ring's floor (you fell behind)

**Always carry `next_offset` forward.** Don't replay from 0 — that's an offset reset, you'll see the same data twice and miss the part that fell off.

When `truncated_bytes_dropped > 0`, the buffer evicted N bytes between your last call and now. Treat it as a signal that the job is producing output faster than you're consuming. Either poll more often or accept the gap and read from `next_offset` going forward.

## merge_stderr — interleaved or separate

```
merge_stderr=False  → two streams, request "stdout" or "stderr" by name
merge_stderr=True   → one stream ("merged"), order preserved
```

Pick `merge_stderr=True` when:
- The job's logs are designed to be read together (most servers, build tools)
- You don't need to distinguish "this was stderr"

Pick `merge_stderr=False` when:
- stderr is genuinely error-only and stdout is data
- You'll process them differently

## Signal escalation

```
shell_job_manage(action="signal_int",  job_id=...)   # graceful (Ctrl-C-equivalent)
shell_job_manage(action="signal_term", job_id=...)   # polite kill (SIGTERM)
shell_job_manage(action="signal_kill", job_id=...)   # forced kill (SIGKILL, uncatchable)
```

The idiom: `signal_int` → wait 2-5s → `signal_term` → wait 2-5s → `signal_kill`. Most well-behaved processes handle SIGINT (graceful) and SIGTERM (cleanup, then exit). SIGKILL bypasses cleanup — use only when the process is truly unresponsive.

After signaling, check exit with `shell_job_logs(job_id, wait_until_exit=True, wait_timeout_sec=2)`.

## Stdin

```
shell_job_manage(action="stdin", job_id=..., data="some input\n")
shell_job_manage(action="close_stdin", job_id=...)
```

For tools that read stdin to EOF, `close_stdin` after writing flushes them. For interactive tools that read line-by-line, just write each line.

## Take-over: when shell_exec auto-backgrounds

When `shell_exec` returned `auto_backgrounded: true, job_id: <X>`, the process is **already** in the JobManager with its output flowing into the ring buffer. Your transition is seamless:

```
# Already saw the start of output in shell_exec's stdout/stderr.
# Pick up reading where the env left off — use the byte count of the
# initial stdout as your since_offset, OR just request tail output:
shell_job_logs(job_id="job_xxx", tail=True, max_bytes=64000)
```

Or block until exit and grab everything:

```
shell_job_logs(job_id="job_xxx", since_offset=0, wait_until_exit=True, wait_timeout_sec=120)
```

## Hard rules

- **Jobs die when the server restarts.** The desktop runtime restarts shell-tools when Hive restarts. There's no re-attach. If you need durability, use `nohup` + `shell_exec` to detach into the system's process tree and track the PID yourself.
- **Server-wide hard cap on concurrent jobs** (`SHELL_TOOLS_MAX_JOBS`, default 32). Past the cap, `shell_job_start` returns an error. Wait for jobs to exit or kill old ones.
- **No cross-restart output.** Output handles and ring buffers are in-memory only.

See `references/signals.md` for the full signal catalog.
