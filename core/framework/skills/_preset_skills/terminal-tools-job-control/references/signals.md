# Signal reference

Query `terminal_job_manage(action="capabilities")` for the server's supported actions and semantics. The table below describes POSIX signals; signal numbers can vary by platform.

On Windows only `signal_term` and `signal_kill` are implemented. Both forcefully terminate the job process tree, without running application cleanup handlers. `signal_int` is not a Windows Ctrl-C mechanism and returns `unsupported_action`. Windows exit codes do not use the POSIX `-N` convention.

| Action | Signal | Number | Purpose | Catchable? |
|---|---|---|---|---|
| `signal_int` | SIGINT | 2 | Interrupt — Ctrl-C equivalent. Most CLIs treat as "stop gracefully". | Yes |
| `signal_term` | SIGTERM | 15 | Termination request, followed by forced tree cleanup after up to 2 seconds. | Initially |
| `signal_kill` | SIGKILL | 9 | Forced kill. Process can't catch, clean up, or finalize. Use sparingly. | **No** |
| `signal_hup` | SIGHUP | 1 | Hangup. Many daemons reload config on this. | Yes |
| `signal_usr1` | SIGUSR1 | 10 | User-defined #1. Common: dump state, rotate logs (nginx, etc). | Yes |
| `signal_usr2` | SIGUSR2 | 12 | User-defined #2. Common: graceful binary upgrade (unicorn, etc). | Yes |

## POSIX escalation idiom

```
1. signal_int   (Ctrl-C — graceful)
2. wait 2-5s, check status with terminal_job_logs(wait_until_exit=True, wait_timeout_sec=3)
3. if still running: signal_term (SIGTERM, then forced cleanup after up to 2 seconds)
4. check exit status
```

Handlers may flush logs or close connections. If the program needs longer to shut down, use its documented application shutdown interface; `signal_term` has a bounded cleanup window.

## When to use SIGUSR1 / SIGUSR2

These are application-defined. Read the target's docs first. Common:
- **nginx**: SIGUSR1 → reopen log files (for log rotation)
- **unicorn / puma**: SIGUSR2 → fork a new master with the latest binary (graceful restart)
- **rsync**: SIGUSR1 → print stats so far

## Reading exit codes after a signal

On POSIX, when the directly tracked process exits via a signal, `terminal_job_logs` returns `exit_code: -N` (subprocess convention) where `abs(N)` is the signal number. A tracked shell can instead report its child's signal exit as `128 + N`.

| exit_code | Means |
|---|---|
| -2 | Killed by SIGINT |
| -9 | Killed by SIGKILL |
| -15 | Killed by SIGTERM |
