---
name: hive.shell-tools-fs-search
description: Use shell_rg / shell_find when you need raw filesystem search outside the project tree — system configs, /var/log, /etc, archive contents — or when files-tools.search_files is too project-scoped. Teaches the rg vs find vs shell_exec("ls/du/tree") split, common rg flag combos for code/logs/configs, find predicates for mtime/size/type queries, and the rule that for tree views or single-file stat info you should just use shell_exec instead of inventing a tool. Read before reaching for raw shell to grep or find anything.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Filesystem search

shell-tools provides two structured search tools: `shell_rg` (ripgrep for content) and `shell_find` (find for predicates). Everything else (tree, stat, du) is just `shell_exec`.

## When to use what

| Task | Tool |
|---|---|
| Find code/text matching a pattern in your **project** | `files-tools.search_files` (project-aware, ranks by relevance) |
| Find code/text matching a pattern in `/var/log`, `/etc`, archives, system dirs | `shell_rg` |
| Find files matching name/glob/predicate | `shell_find` |
| List a directory | `shell_exec("ls -la /path")` |
| Tree view | `shell_exec("tree -L 2 /path")` |
| Single-path stat | `shell_exec("stat /path")` |
| Disk usage | `shell_exec("du -sh /path")` or `shell_exec("du -h --max-depth=2 /")` |
| Count matches across files | `shell_rg(pattern, count=True via extra_args=["-c"])` |

## `shell_rg` — content search

ripgrep is fast, gitignore-aware, and has a deep flag surface. The structured wrapper exposes the most useful flags directly; `extra_args` covers the rest.

### Common patterns

```
# All Python files containing "TODO"
shell_rg(pattern="TODO", path=".", type_filter="py")

# Case-insensitive, with context
shell_rg(pattern="error", path="/var/log", ignore_case=True, context=2)

# Search hidden files (rg ignores them by default)
shell_rg(pattern="api_key", path="~", hidden=True)

# Don't respect .gitignore (find files git would ignore)
shell_rg(pattern="generated", path=".", no_ignore=True)

# Multi-line pattern (e.g., function definitions spanning lines)
shell_rg(pattern=r"def\s+\w+\(.*\n.*\n", path="src", extra_args=["--multiline"])

# Specific filename glob
shell_rg(pattern="version", path=".", glob="*.toml")
```

### rg flag idioms

| Flag | Effect |
|---|---|
| `-tpy` (`type_filter="py"`) | Only Python files |
| `-uu` | Don't respect any ignores (incl. `.git/`) |
| `--multiline` (`extra_args`) | Allow regex spanning lines |
| `--max-count` (`max_count`) | Stop after N matches per file |
| `--max-depth` (`max_depth`) | Limit recursion |
| `-w` (`extra_args`) | Whole word match |
| `-F` (`extra_args`) | Fixed string (no regex) |

See `references/ripgrep_cheatsheet.md` for the long form.

## `shell_find` — predicate search

`find` excels at "files matching N criteria". The wrapper surfaces the most common predicates; combine via the structured arguments.

```
# All .log files modified in the last 7 days, larger than 1MB
shell_find(path="/var/log", iname="*.log", mtime_days=7, size_kb_min=1024)

# All directories named ".git" (find Git repos under a tree)
shell_find(path="~/projects", name=".git", type_filter="d")

# Only the top three levels
shell_find(path="/etc", max_depth=3, type_filter="f")

# Symlinks
shell_find(path=".", type_filter="l")
```

See `references/find_predicates.md` for combinations not directly exposed.

## Output truncation

Both tools return `truncated: true` when their output exceeded the inline cap. For `shell_rg`, this means matches were dropped (refine the pattern or narrow the path); for `shell_find`, results past `max_results` (default 1000) are dropped. Tighten predicates rather than raising the cap.

## Anti-patterns

- **Don't `shell_rg` your project tree** — `files-tools.search_files` is project-aware and ranks results.
- **Don't reach for `shell_find` to list one directory** — `shell_exec("ls -la /path")` is shorter.
- **Don't use `shell_exec("grep ...")`** when `shell_rg` exists — rg is faster, gitignore-aware, and returns structured matches.
- **Don't use `shell_exec("find ...")`** to invent your own predicate combinations — use `shell_find` and report missing capabilities.
