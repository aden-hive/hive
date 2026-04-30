---
name: hive.shell-tools-pty-sessions
description: Use when you need state across calls — building env vars, navigating with cd, driving REPLs (python -i, mysql, psql, node), or responding to interactive prompts (sudo password, ssh host-key confirmation, mysql connection). Teaches the prompt-sentinel exec pattern (default mode), raw I/O for REPLs (raw_send=True then read_only=True), the one-in-flight-per-session rule, and the close-or-leak-against-the-cap discipline. Bash on macOS — never zsh; explicit shell=/bin/zsh is rejected. Read before calling shell_pty_open.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Persistent PTY sessions

PTY sessions are how you talk to interactive programs — programs that detect a terminal (`isatty()`) and behave differently when they don't see one. Use a session when:

- You need state to persist across calls (`cd`, env vars, sourced scripts)
- You're driving a REPL (`python -i`, `mysql`, `psql`, `node`, `irb`)
- A program demands an interactive prompt (`sudo`, `ssh`, `npm login`, `gh auth login`)

For everything else, `shell_exec` is simpler. Sessions cost more (per-session bash process, ring buffer, idle-reaping bookkeeping) and have a hard cap (`SHELL_TOOLS_MAX_PTY`, default 8).

## Why PTY (and not subprocess pipes)

Subprocess pipes break on every interactive program. The moment a program calls `isatty()` and sees False, it disables prompts, color, line-editing, password masking, progress bars — sometimes refuses to start. PTY makes us look like a real terminal so these programs work the same as in your shell.

The cost: PTY output includes terminal escape codes (cursor moves, color codes). The session captures them as-is; if you need clean text, strip ANSI escapes in your processing layer.

## Bash on macOS — by deliberate policy

`shell_pty_open` always invokes `/bin/bash`, regardless of the user's `$SHELL`. macOS users: yes, even when zsh is your interactive default. This is the **shell-tools-foundations** policy applied to PTYs.

Reasons:
- zsh has command/builtin classes (`zmodload`, `=cmd` expansion, `zpty`, `ztcp`) that bypass bash-shaped security checks
- One shell behavior across platforms eliminates "works on Linux, breaks on macOS" surprises
- Bash is universal: any shell you've used will accept the bash subset

The bash invocation uses `--norc --noprofile` so user dotfiles don't leak in. PS1 is set to a unique sentinel for prompt detection. PS2 is empty. PROMPT_COMMAND is empty.

## Three modes of `shell_pty_run`

### 1. Default: send command, wait for prompt sentinel

```
shell_pty_run(session_id, command="ls -la")
  → { output, prompt_after: True, ... }
```

The session writes `ls -la\n`, waits for the sentinel that its custom PS1 emits, returns the slice between submission and prompt. **One in-flight call per session** — a concurrent call returns a `"session busy"` error.

### 2. raw_send: send raw input, no waiting

```
shell_pty_run(session_id, command="print('hi')\n", raw_send=True)
  → { bytes_sent: 12 }
```

For REPLs, vim keystrokes, password prompts. The session writes the bytes and returns immediately — it doesn't wait for a prompt (REPLs don't print bash's prompt; they print their own).

After a `raw_send`, you typically follow with:

### 3. read_only: drain currently-buffered output

```
shell_pty_run(session_id, read_only=True, timeout_sec=2)
  → { output: "hi\n", more: False, ... }
```

Reads whatever the session has accumulated since the last drain, with a brief settle window. Use after raw_send to capture the REPL's response.

## Custom prompt detection (`expect`)

When the command launches a program with its own prompt (Python REPL's `>>> `, mysql's `mysql> `, sudo's password prompt), the bash sentinel won't appear until the program exits. Override:

```
shell_pty_run(session_id, command="python3", expect=r">>>\s*$", timeout_sec=10)
  → output up to and including ">>>", then control returns
```

For sudo:

```
shell_pty_run(session_id, command="sudo -k && sudo whoami", expect=r"[Pp]assword:")
shell_pty_run(session_id, command="<password>", raw_send=True, command="<password>\n")
shell_pty_run(session_id, read_only=True, timeout_sec=5)
```

(Treat passwords carefully — they end up in the ring buffer.)

## Always close

```
shell_pty_close(session_id)
```

Leaked sessions count against `SHELL_TOOLS_MAX_PTY` (default 8). Idle reaping happens lazily on every `_open` call (sessions inactive longer than `idle_timeout_sec`, default 1800s, are dropped) — but don't rely on it. Close when you're done.

For unresponsive sessions, `force=True` skips the graceful "exit" attempt and goes straight to SIGTERM/SIGKILL.

## Common patterns

### Stateful navigation

```
sid = shell_pty_open(cwd="/")
shell_pty_run(sid, command="cd /var/log")
shell_pty_run(sid, command="ls -la *.log | head")
shell_pty_close(sid)
```

### Python REPL

```
sid = shell_pty_open()
shell_pty_run(sid, command="python3", expect=r">>>\s*$")
shell_pty_run(sid, command="x = 42", raw_send=True)
shell_pty_run(sid, command="print(x*x)\n", raw_send=True)
result = shell_pty_run(sid, read_only=True)  # → "1764\n>>> "
shell_pty_run(sid, command="exit()", raw_send=True)
shell_pty_close(sid)
```

### ssh with host-key prompt

```
sid = shell_pty_open()
shell_pty_run(sid, command="ssh user@new-host", expect=r"\(yes/no.*\)\?")
shell_pty_run(sid, command="yes\n", raw_send=True)
shell_pty_run(sid, read_only=True, timeout_sec=10)  # password prompt or login
```
