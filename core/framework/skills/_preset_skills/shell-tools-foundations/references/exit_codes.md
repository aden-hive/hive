# Exit code reference

## POSIX conventions

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error / catchall |
| 2 | Misuse of shell builtins, syntax error |
| 126 | Command found but not executable |
| 127 | Command not found |
| 128 | Invalid argument to `exit` |
| 128 + N | Killed by signal N |
| 130 | Killed by SIGINT (Ctrl-C) |
| 137 | Killed by SIGKILL |
| 143 | Killed by SIGTERM |
| 255 | Exit status out of range |

When `exit_code < 0` in the envelope, the process was killed by a signal: `abs(exit_code)` is the signal number (subprocess uses negative codes for signaled exits, separate from the `128 + N` shell convention).

## Semantic exits — when exit 1 is NOT an error

shell-tools encodes these in `semantic_status`. The agent should read `semantic_status` first.

| Command | Code 0 | Code 1 | Code ≥2 |
|---|---|---|---|
| `grep` / `rg` / `ripgrep` | matches found | **no matches** (ok) | error |
| `find` | success | **some dirs unreadable** (ok) | error |
| `diff` | files identical | **files differ** (ok) | error |
| `test` / `[` | condition true | **condition false** (ok) | error |

For any command not in this table, the default convention applies (0 = ok, nonzero = error).

## When `exit_code` is `null`

- `auto_backgrounded: true` — the process is still running under a `job_id`. Poll with `shell_job_logs`.
- Pre-spawn error (command not found, exec failed) — see `error` field in the envelope.
- `timed_out: true` and the process refused to die — extremely rare; the kernel has the answer.

## Common signal-induced exits

| Signal | Number | Subprocess exit | Shell exit | Meaning |
|---|---|---|---|---|
| SIGHUP | 1 | -1 | 129 | Terminal hangup |
| SIGINT | 2 | -2 | 130 | Interrupt (Ctrl-C) |
| SIGQUIT | 3 | -3 | 131 | Quit (Ctrl-\\) |
| SIGKILL | 9 | -9 | 137 | Forced kill (uncatchable) |
| SIGTERM | 15 | -15 | 143 | Polite termination |
| SIGSEGV | 11 | -11 | 139 | Segmentation fault |
| SIGABRT | 6 | -6 | 134 | Abort (assertion failed, etc.) |
