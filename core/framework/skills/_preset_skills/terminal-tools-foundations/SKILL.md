---
name: hive.terminal-tools-foundations
description: Required when terminal_* tools are available. Explains foreground execution, outer collect_result handles, promoted job IDs and their retrieval/cancellation, deadlines, output retention, platform shell selection, and structured editing when enabled.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# terminal-tools — foundations

These tools provide command execution, background jobs, log streaming, filesystem search, and optional PTY sessions. POSIX uses bash for shell commands; Windows selects Git Bash, PowerShell, then cmd. Inspect `shell_kind` in results.

## Tool preference (read first)

Use `search_tools(query="inventory")` before describing capabilities. It reports this session's loaded, searchable, disabled, and configured-but-unavailable tools. Load searchable tools by exact name. An absent schema alone does not prove a capability is missing; configuration does not prove credentials or connectivity work. Terminal tools and coding file tools default to the injected session workdir; an explicit absolute path overrides it.

- **Reading files** → use `read_file` before `edit_file` when the coding tools are enabled; it records file state for the stale-edit guard. Otherwise use a command appropriate to `shell_kind`.
- **Editing files** → prefer `edit_file` when enabled. Replacement mode requires a unique match unless `replace_all=true`; patch mode validates all operations before writing. Inspect its changed-file summary and diff. Re-read files after external changes. Terminal editing remains available when coding tools are disabled.
- **Writing files** → heredoc: `terminal_exec("cat > PATH <<'EOF' ... EOF")`
- **Searching** → `terminal_rg` (content / regex grep) and `terminal_glob` (find files by name)
- **Browser / web pages** → call `browser_setup`, read the browser skill, then run `hive-browser <command> --json` through `terminal_exec`.
- **Web search** → check the inventory for `web_search` and load it if available; verify required credentials. Do not invent a callable tool name.
- **System operations** (process exec, jobs, PTYs) → terminal-tools. This is its territory.

## The standard envelope

Every spawn-style call (`terminal_exec`, the auto-promoted job state) returns this shape:

```jsonc
{
  "exit_code": 0,                    // null when auto-backgrounded or pre-spawn error
  "stdout": "...",                   // decoded, truncated to max_output_kb (default 256 KB)
  "stderr": "...",
  "stdout_truncated_bytes": 0,       // > 0 means more is in output_handle
  "stderr_truncated_bytes": 0,
  "runtime_ms": 42,
  "pid": 12345,
  "output_handle": null,             // "out_<hex>" when truncated — paginate with terminal_output_get
  "timed_out": false,
  "semantic_status": "ok",           // "ok" | "signal" | "error" — read THIS, not just exit_code
  "semantic_message": null,          // e.g. "No matches found" for grep exit 1
  "warning": null,                   // e.g. "may force-remove files" for rm -rf
  "auto_backgrounded": false,
  "job_id": null,                    // set when auto_backgrounded=true
  "shell_kind": "bash"               // interpreter that ran it: "bash" | "powershell" | "cmd" | "direct"
}
```

## Auto-promotion (the core mental model)

The agent loop first waits up to five seconds for `terminal_exec`. A slower call returns a `bg_*` handle; redeem it with `collect_result`. The terminal's own **promotion threshold** defaults to 30 seconds. Past that threshold it transfers the process to its job manager and returns:

```jsonc
{ "auto_backgrounded": true, "exit_code": null, "job_id": "job_<hex>", ... }
```

When you see `auto_backgrounded: true`, **pivot to polling**. The job is still running:

```
terminal_job_logs(job_id, since_offset=0, wait_until_exit=true, wait_timeout_sec=30)
  → blocks server-side until the job exits or the timeout, returns logs + status
```

You're not failing — you're freed up to do other work while the long task runs.

`collect_result` does not redeem `job_id`: after collecting a promoted call, use `terminal_job_logs` until status is `exited`. Track separate stdout/stderr offsets; use `terminal_job_manage(action="signal_term", job_id=...)` to cancel. Poll waits are capped at 45 seconds and do not extend execution deadlines. Job retrieval/management ship with basic exec; explicit job creation and PTYs require the advanced category.

`timeout_sec` defaults to 60 seconds **from command start**, including time after promotion. Expiry terminates the owned process tree; final logs report `timed_out=true`. A deadline at or before promotion kills inline. Set `timeout_sec=0` for unlimited execution with promotion enabled. To keep execution foreground, set `auto_background_after_sec=0` and a finite timeout of at most 220 seconds (or less if the caller has a smaller budget). Use managed jobs for longer waits. Jobs belong to the terminal server and do not survive its restart.

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

## Output handles and retention

When `stdout_truncated_bytes > 0` or `stderr_truncated_bytes > 0`, retained output exceeded the inline cap (default 256 KiB per stream). An `output_handle` retrieves the retained bytes for **5 minutes**, subject to earlier eviction. Paginate with:

```
terminal_output_get(output_handle, since_offset=0, max_kb=64)
  → { data, offset, next_offset, eof, expired }
```

Track `next_offset` across calls. If `expired: true`, inspect saved log files first. Repeat a command only if replaying its side effects is appropriate.

The store has a 64 MiB cap with LRU eviction. Process output passes through a 4 MiB ring per stream; old bytes can be overwritten. Poll job logs promptly and check `truncated_bytes_dropped`. For complete build logs, redirect output to a file and inspect that file as well as the exit status.

## Bash, not zsh — even on macOS

On POSIX, `terminal_exec` uses direct argv execution for simple commands and `/bin/bash` for shell syntax or `shell=True`. The user's `$SHELL` does not select the interpreter. zsh is refused by the shell resolver. PTY sessions are POSIX-only.

Foreground commands and explicit background jobs inherit ordinary environment variables, with `ZDOTDIR` and `ZSH_*` removed from the inherited base even when `env` is omitted. Explicit `env` values are then merged and take precedence; framework-injected identity wins over an agent-supplied identity. Noninteractive shell configuration may differ from the user's interactive terminal.

## Windows — check `shell_kind` before assuming bash

On Windows the shell is resolved in priority order: **Git Bash → PowerShell → cmd**. Which one ran your command is reported in the envelope's `shell_kind` field. Bash is only available if Git for Windows is installed; otherwise you land in PowerShell (or cmd as the floor). **Read `shell_kind` and adapt** — bash idioms silently break in the others:

| You wrote | `bash` | `powershell` | `cmd` |
|---|---|---|---|
| `cat` / `ls` | ✓ | ✓ (aliases) | ✗ (`type` / `dir`) |
| `grep` / `sed` / GNU `find` | ✓ | ✗ | ✗ |
| `a && b` | ✓ | ✗ in PS 5.1 (use `;`) | ✓ |
| `2>/dev/null` | ✓ | `2>$null` | `2>nul` |
| single-quoted `'args'` | ✓ | ✓ | ✗ (use `"..."`) |

Practical rule: if `shell_kind != "bash"`, prefer commands that are portable (a bare program name + args, e.g. `node x.js`, `python -m pip install ...`) or write the PowerShell/cmd-native form. Don't assume coreutils. PTY sessions (`terminal_pty_*`) are POSIX-only and return an "unsupported on Windows" error.

**Paths under `shell_kind: "bash"` on Windows (Git Bash):** backslashes are escape characters, so a Windows path passed verbatim gets mangled (`cat C:\Users\me\x` → bash reads `C:Usersmex`). Use forward slashes (`C:/Users/me/x`, which Git Bash accepts) or the MSYS form (`/c/Users/me/x`). Quoting a backslash path in single quotes also preserves it (`cat 'C:\Users\me\x'`).

## Pipelines and complex commands

Pipes (`|`), redirects (`>`, `<`, `>>`), conditionals (`&&`, `||`, `;`), and globs (`*`, `?`, `[`) are detected automatically. You can pass them with the default `shell=False` and the runtime will transparently route through `/bin/bash -c` and surface `auto_shell: true` in the envelope:

```
terminal_exec("ps aux | sort -k3 -rn | head -40")
  → { exit_code: 0, stdout: "...", auto_shell: true, ... }
```

For simple argv commands (no metacharacters) `shell=False` is faster and direct-execs the binary. For commands with shell features but no metacharacters that the detector catches (rare — exotic bash builtins, here-strings), pass `shell=True` explicitly:

```
terminal_exec("set -e; complicated bash logic", shell=True)
```

Quoted strings work either way — the detector uses `shlex.split` which handles `"quoted args with spaces"` correctly.

## When to use what (cheat sheet)

| Need | Tool |
|---|---|
| One-shot command, ≤30s | `terminal_exec` |
| One-shot command, might be longer | `terminal_exec` (auto-promotes) |
| Long-running job from the start | `terminal_job_start` |
| State across calls (cd, env, REPL) | `terminal_pty_open` + `terminal_pty_run` |
| Search file contents (any path) | `terminal_rg` |
| Find files by name/glob (any path) | `terminal_glob` |
| Retrieve truncated output | `terminal_output_get` |
| Tree / stat / du | `terminal_exec("ls -la"/"stat foo"/"du -sh path")` |
| HTTP / DNS / ping / archives | `terminal_exec("curl ..."/"dig ..."/"tar xzf ...")` |

See `references/exit_codes.md` for the full POSIX + signal-induced + semantic catalog.
