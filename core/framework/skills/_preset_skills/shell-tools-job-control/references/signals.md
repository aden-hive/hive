# Signal reference

shell_job_manage exposes six signals via the action name.

| Action | Signal | Number | Purpose | Catchable? |
|---|---|---|---|---|
| `signal_int` | SIGINT | 2 | Interrupt — Ctrl-C equivalent. Most CLIs treat as "stop gracefully". | Yes |
| `signal_term` | SIGTERM | 15 | Polite termination request. Default for `kill`. | Yes |
| `signal_kill` | SIGKILL | 9 | Forced kill. Process can't catch, clean up, or finalize. Use sparingly. | **No** |
| `signal_hup` | SIGHUP | 1 | Hangup. Many daemons reload config on this. | Yes |
| `signal_usr1` | SIGUSR1 | 10 | User-defined #1. Common: dump state, rotate logs (nginx, etc). | Yes |
| `signal_usr2` | SIGUSR2 | 12 | User-defined #2. Common: graceful binary upgrade (unicorn, etc). | Yes |

## Escalation idiom

```
1. signal_int   (Ctrl-C — graceful)
2. wait 2-5s, check status with shell_job_logs(wait_until_exit=True, wait_timeout_sec=3)
3. if still running: signal_term (cleanup-then-exit)
4. wait 2-5s
5. if still running: signal_kill (forced)
```

The waits matter: SIGTERM handlers do real work (flush logs, close DBs, release locks) and need time. Skipping straight to SIGKILL leaks resources.

## When to use SIGUSR1 / SIGUSR2

These are application-defined. Read the target's docs first. Common:
- **nginx**: SIGUSR1 → reopen log files (for log rotation)
- **unicorn / puma**: SIGUSR2 → fork a new master with the latest binary (graceful restart)
- **rsync**: SIGUSR1 → print stats so far

## Reading exit codes after a signal

When a job exits via signal, `shell_job_logs` returns `exit_code: -N` (subprocess convention) where `abs(N)` is the signal number. The shell convention `128 + N` doesn't apply to the JobManager — that's for shell-spawned children.

| exit_code | Means |
|---|---|
| -2 | Killed by SIGINT |
| -9 | Killed by SIGKILL |
| -15 | Killed by SIGTERM |
