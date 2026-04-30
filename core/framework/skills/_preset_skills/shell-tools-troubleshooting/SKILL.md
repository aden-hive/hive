---
name: hive.shell-tools-troubleshooting
description: Read when a shell-tools call returned something surprising — empty stdout despite no error, exit_code is null, output_handle came back expired, "too many jobs" / "session busy" / "too many PTYs", warning was set unexpectedly, semantic_status disagrees with exit_code. Diagnostic recipes only — load on demand. Don't preload; the foundational skill covers the happy path.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Troubleshooting shell-tools

Recipes for surprising results. Match the symptom to the section.

## Empty `stdout` despite the command "should have" produced output

Possible causes:
1. Output went to **stderr** instead. Check `stderr` in the envelope (or use `merge_stderr=True` for jobs).
2. Output was **fully truncated** because `max_output_kb` is too small. Check `stdout_truncated_bytes > 0`. Bump `max_output_kb` or paginate via `output_handle`.
3. Command produced no output (correct, just unexpected — `silent` flags, no matches).
4. Pipeline issue: the last stage of a pipe ran but stdout went elsewhere (`> /dev/null`, redirected via `2>&1`).
5. Process is buffering its output and didn't flush before exit. Add `stdbuf -oL` (line-buffered) or `unbuffer` to the command.

## `exit_code: null`

| Cause | Other field |
|---|---|
| Auto-backgrounded | `auto_backgrounded: true, job_id: <X>` |
| Hard timeout, process killed | `timed_out: true` |
| Pre-spawn failure (command not found) | `error: ...` set, `pid: null` |
| Still running (in `shell_job_logs`) | `status: "running"` |

## `output_handle` returned `expired: true`

5-minute TTL. Either (a) you waited too long, or (b) the store evicted it under memory pressure (64 MB total cap, LRU eviction). Re-run the command.

To reduce risk: paginate the handle as soon as you receive it, or use `shell_job_*` for huge outputs (4 MB ring buffer with offsets — no expiry).

## "too many jobs" / `JobLimitExceeded`

`SHELL_TOOLS_MAX_JOBS` (default 32) hit. Either:
- Wait for jobs to exit (poll with `shell_job_logs(wait_until_exit=True)`)
- Kill old jobs: `shell_job_manage(action="list")` to see what's running, then `signal_term` the abandoned ones
- Raise the cap via env (rare)

## "session busy"

A `shell_pty_run` was issued while another `_run` is in flight on the same session. PTY sessions are single-threaded conversations. Wait for the prior call to return, or open a second session.

## "PTY cap reached"

`SHELL_TOOLS_MAX_PTY` (default 8) hit. Close idle sessions (`shell_pty_close`). Idle reaping is lazy; force it by opening — no, actually, opening throws when the cap is hit. Just close manually.

## `warning` is set, the command worked

Informational only. The pattern matched (e.g. `rm -rf` literally appears, or `git push --force` was used). The command ran. The warning is your "did I mean to do that?" prompt — verify the side effect was intended before continuing.

## `semantic_status: "ok"` but `exit_code: 1`

Working as designed. Some commands use exit 1 for legitimate non-error states:
- `grep` / `rg` exit 1 when **no matches** found
- `find` exit 1 when **some directories were unreadable** (typical on `/proc`, etc.)
- `diff` exit 1 when **files differ**
- `test` / `[` exit 1 when **condition is false**

The `semantic_message` field explains. Trust `semantic_status`, not raw `exit_code`.

## `semantic_status: "error"` but `exit_code: 0`

Shouldn't happen. If it does, file a bug.

## `truncated_bytes_dropped > 0` in `shell_job_logs`

Your `since_offset` was older than the ring buffer's floor — bytes evicted before you could read them. Either:
- Poll faster (lower latency between calls)
- Use `merge_stderr=True` (single 4 MB ring instead of 4 MB × 2)
- Accept the gap and move forward from `next_offset`

## `shell_pty_open` succeeds but the first `_run` times out

The session may not have produced its first prompt sentinel within the 2-second startup window. Try:
- A `shell_pty_run(sid, read_only=True, timeout_sec=2)` to drain whatever's accumulated
- A noop command (`shell_pty_run(sid, command="true")`) to force a prompt cycle

Could also indicate the bash process died at startup — `shell_pty_run(sid, ...)` would then return `"session has exited"`.

## `shell="/bin/zsh"` returned an error

By design. shell-tools is bash-only on POSIX. Use `shell=True` (default `/bin/bash`) or omit `shell=` to exec directly.

## A command in `shell=True` is interpreted differently than expected

Bash, not zsh, semantics. `**/*` doesn't recurse without `shopt -s globstar`; `=cmd` expansion doesn't work; arrays use `arr[idx]` not `${arr[idx]}` differently than zsh. When in doubt, the foundational skill's "bash, not zsh" section is the canonical statement.
