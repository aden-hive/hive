---
name: hive.shell-tools-foundations
description: Required reading whenever any shell_* tool is available. Teaches the foreground/background dichotomy (shell_exec auto-promotes past 30s, returns a job_id you poll with shell_job_logs), the standard envelope shape (exit_code, stdout, stdout_truncated_bytes, output_handle, semantic_status, warning, auto_backgrounded, job_id), output handle pagination via shell_output_get, when to read semantic_status instead of raw exit_code (grep/rg/find/diff/test exit 1 is NOT an error), the destructive-warning surface (rm -rf, git push --force, DROP TABLE), tool preference (use files-tools / gcu-tools / hive_tools before raw shell), and the bash-only-on-macOS policy. Skipping this leads to "tool returned no output" surprises, orphaned jobs, and panic over benign grep exit codes.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# shell-tools — foundations

These tools give you a real terminal: foreground exec with smart envelopes, background jobs with offset-based log streaming, persistent PTY shells, and filesystem search. Bash-only on POSIX.

## Tool preference (read first)

Before reaching for shell-tools, check whether a higher-level tool already covers the task. Shell is for system operations the other servers don't reach.

- **Reading files** → `files-tools.read_file` (handles size, paging, line-numbered output) — NOT `shell_exec("cat ...")`
- **Editing files** → `files-tools.edit_file` (atomic patch with diff verification) — NOT `shell_exec("sed -i ...")`
- **Writing files** → `files-tools.write_file` — NOT `shell_exec("echo > ...")`
- **In-project search** → `files-tools.search_files` (project-scoped, code-aware) — use `shell_rg` only for raw paths outside the project (`/var/log`, `/etc`)
- **Browser / web pages** → `gcu-tools.browser_*` for rendered pages — NOT `shell_exec("curl ...")`
- **Web search** → `hive_tools.web_search` — NOT scraping
- **System operations** (process exec, jobs, PTYs, raw fs search) → shell-tools. This is its territory.

## The standard envelope

Every spawn-style call (`shell_exec`, the auto-promoted job state) returns this shape:

```jsonc
{
  "exit_code": 0,                    // null when auto-backgrounded or pre-spawn error
  "stdout": "...",                   // decoded, truncated to max_output_kb (default 256 KB)
  "stderr": "...",
  "stdout_truncated_bytes": 0,       // > 0 means more is in output_handle
  "stderr_truncated_bytes": 0,
  "runtime_ms": 42,
  "pid": 12345,
  "output_handle": null,             // "out_<hex>" when truncated — paginate with shell_output_get
  "timed_out": false,
  "semantic_status": "ok",           // "ok" | "signal" | "error" — read THIS, not just exit_code
  "semantic_message": null,          // e.g. "No matches found" for grep exit 1
  "warning": null,                   // e.g. "may force-remove files" for rm -rf
  "auto_backgrounded": false,
  "job_id": null                     // set when auto_backgrounded=true
}
```

## Auto-promotion (the core mental model)

`shell_exec` runs commands in the foreground until the **auto-background budget** (default 30s) elapses. Past that point, the process is silently transferred to a background job and the call returns immediately with:

```jsonc
{ "auto_backgrounded": true, "exit_code": null, "job_id": "job_<hex>", ... }
```

When you see `auto_backgrounded: true`, **pivot to polling**. The job is still running:

```
shell_job_logs(job_id, since_offset=0, wait_until_exit=true, wait_timeout_sec=60)
  → blocks server-side until the job exits or the timeout, returns logs + status
```

You're not failing — you're freed up to do other work while the long task runs.

To force pure-foreground (kill on `timeout_sec`), pass `auto_background_after_sec=0`. Use this when you genuinely don't want a background job (small commands where promotion would surprise you).

## Semantic exit codes — read `semantic_status`, not raw `exit_code`

Several common commands use exit 1 for legitimate non-error states:

| Command | exit 0 | exit 1 |
|---|---|---|
| `grep` / `rg` | matches found | **no matches** (not an error) |
| `find` | success | **some dirs unreadable** (informational) |
| `diff` | identical | **files differ** (informational) |
| `test` / `[` | true | **false** (informational) |

For these, `semantic_status` will be `"ok"` even when `exit_code == 1`, with `semantic_message` describing why ("No matches found"). For everything else, `semantic_status` defaults to `"ok"` on 0 and `"error"` on nonzero.

**Rule**: always check `semantic_status` first. Only fall back to `exit_code` when you need the exact number (e.g. distinguishing `make` errors).

## Destructive warnings — re-read your command

The envelope's `warning` field is set when the command matches a known destructive pattern (`rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE`, `kubectl delete`, `terraform destroy`, etc.). The command **still ran** — the warning is informational. Use it as a "did I mean to do that?" prompt before trusting subsequent steps that depend on the side effect.

If a `warning` appears unexpectedly, stop and verify: was the destructive action intended, or did a path/glob slip in?

## Output handles — never lose output

When `stdout_truncated_bytes > 0` or `stderr_truncated_bytes > 0`, the inline output was capped at `max_output_kb` (default 256 KB). The full bytes are stashed under `output_handle` for **5 minutes**. Paginate with:

```
shell_output_get(output_handle, since_offset=0, max_kb=64)
  → { data, offset, next_offset, eof, expired }
```

Track `next_offset` across calls. If `expired: true`, re-run the command (the handle's TTL has lapsed).

The store has a 64 MB cap with LRU eviction. For huge outputs, prefer `shell_job_start` + `shell_job_logs` polling (4 MB ring buffer per stream, infinite total throughput).

## Bash, not zsh — even on macOS

`shell_exec` and `shell_pty_open` always invoke `/bin/bash`. The user's `$SHELL` is ignored. Explicit `shell="/bin/zsh"` is **rejected** with a clear error. This is a deliberate security stance, not aesthetic — zsh has command/builtin classes (`zmodload`, `=cmd` expansion, `zpty`, `ztcp`, `zf_*`) that bypass bash-shaped checks. The `shell-tools-pty-sessions` skill explains the implications for PTY sessions specifically.

`ZDOTDIR` and `ZSH_*` env vars are stripped before exec to prevent zsh dotfiles leaking in. Bash dotfiles still apply when invoked interactively (e.g. PTY sessions use `bash --norc --noprofile` to keep things predictable).

## Pipelines and complex commands

For pipes, redirects, globs, and bash builtins, set `shell=True`:

```
shell_exec("find . -type f -name '*.log' | xargs grep -l ERROR | head", shell=True)
```

For simple `argv` commands, `shell=False` (the default) is faster and avoids quoting hazards. Naive whitespace splitting is fine for the common case; use `shell=True` when arguments contain spaces or quotes.

## When to use what (cheat sheet)

| Need | Tool |
|---|---|
| One-shot command, ≤30s | `shell_exec` |
| One-shot command, might be longer | `shell_exec` (auto-promotes) |
| Long-running job from the start | `shell_job_start` |
| State across calls (cd, env, REPL) | `shell_pty_open` + `shell_pty_run` |
| Search file contents (raw paths) | `shell_rg` |
| Find files by predicate | `shell_find` |
| Retrieve truncated output | `shell_output_get` |
| Tree / stat / du | `shell_exec("ls -la"/"stat foo"/"du -sh path")` |
| HTTP / DNS / ping / archives | `shell_exec("curl ..."/"dig ..."/"tar xzf ...")` |

See `references/exit_codes.md` for the full POSIX + signal-induced + semantic catalog.
