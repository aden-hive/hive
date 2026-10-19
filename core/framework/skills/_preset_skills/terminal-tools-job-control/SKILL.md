---
name: hive.terminal-tools-job-control
description: Use when launching anything that runs longer than a minute, anything that streams logs, anything you want to keep running while doing other work — or when terminal_exec auto-backgrounded on you and returned a job_id. Teaches the start→poll→wait pattern with terminal_job_logs offset bookkeeping, bounded blocking polls, platform-specific process control via terminal_job_manage capabilities, and the hard rule that jobs die when the terminal-tools server restarts. Read before calling terminal_job_start, or right after terminal_exec auto-backgrounded.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Background job control

Background jobs are how you do things that take time without blocking your conversation. Three tools cover the surface: `terminal_job_start`, `terminal_job_logs`, `terminal_job_manage`.

## When to use a job

- Builds, deploys, long tests
- Processes you want to monitor (streaming a log file, a dev server)
- Anything that auto-backgrounded from `terminal_exec` (you have a `job_id`; pivot to this skill's idioms)

For one-shot work expected to finish quickly, `terminal_exec` is simpler. The auto-promotion mechanic in `terminal_exec` is your safety net — start with `terminal_exec`, take over with this skill if needed.

## Lifecycle

```
terminal_job_start(command, ...)
  → { job_id, pid, started_at }

terminal_job_logs(job_id, since_offset=0, max_bytes=64000)
  → { data, offset, next_offset, status: "running"|"exited", exit_code, ... }

# Repeat with since_offset = previous next_offset until status == "exited"
# Or block once with wait_until_exit=True:
terminal_job_logs(job_id, since_offset=N, wait_until_exit=True, wait_timeout_sec=30)
  → blocks server-side until exit or timeout
```

After exit, the job is retained for inspection (`terminal_job_manage(action="list")`) until evicted by FIFO (50 most recent exits kept).

## Offset bookkeeping — the only rule that matters

The job's output lives in a 4 MB ring buffer per stream. Each call to `terminal_job_logs` returns:

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

First query the actions implemented on the server's platform:

```
terminal_job_manage(action="capabilities")
# Returns platform, supported_actions, signals (action → semantics), note.
```

On POSIX, request `signal_int`, wait and inspect the job, then use `signal_term` if needed. `signal_term` gives the process group up to 2 seconds before forced cleanup; `signal_kill` forces termination immediately. Cleanup in response to SIGINT/SIGTERM depends on the application.

On Windows, `signal_term` and `signal_kill` both forcefully terminate the job process tree. Neither invokes application cleanup handlers. `signal_int` / Ctrl-C and the other POSIX signals are unsupported and return `unsupported_action` with the supported actions. If a program has a documented shutdown command on stdin, that can be used before forced termination.

After signaling, check exit with `terminal_job_logs(job_id, wait_until_exit=True, wait_timeout_sec=2)`.

## Stdin

```
terminal_job_manage(action="stdin", job_id=..., data="some input\n")
terminal_job_manage(action="close_stdin", job_id=...)
```

For tools that read stdin to EOF, `close_stdin` after writing flushes them. For interactive tools that read line-by-line, just write each line.

## Take-over: when terminal_exec auto-backgrounds

When `terminal_exec` returned `auto_backgrounded: true, job_id: <X>`, the process is **already** in the JobManager with its output flowing into the ring buffer. Your transition is seamless:

```
# Already saw the start of output in terminal_exec's stdout/stderr.
# Pick up reading where the env left off — use the byte count of the
# initial stdout as your since_offset, OR just request tail output:
terminal_job_logs(job_id="job_xxx", tail=True, max_bytes=64000)
```

Or block until exit and grab everything:

```
terminal_job_logs(job_id="job_xxx", since_offset=0, wait_until_exit=True, wait_timeout_sec=30)
```

## Hard rules

- **Jobs die when the server restarts.** The desktop runtime restarts terminal-tools when Hive restarts. There's no re-attach. `nohup` does not escape managed process-tree cleanup; durable services need a separate service manager.
- **Server-wide hard cap on concurrent jobs** (`TERMINAL_TOOLS_MAX_JOBS`, default 32). Past the cap, `terminal_job_start` returns an error. Wait for jobs to exit or kill old ones.
- **No cross-restart output.** Output handles and ring buffers are in-memory only.

See `references/signals.md` for the full signal catalog.
