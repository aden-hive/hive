---
name: hive.terminal-tools-fs-search
description: Use terminal_rg / terminal_glob for all filesystem search — your project tree as well as system configs, /var/log, /etc, archive contents. Teaches the rg vs glob vs terminal_exec("find/ls/du/tree") split, common rg flag combos for code/logs/configs, glob patterns for finding files by name, the rule that mtime/size/type predicate queries drop to terminal_exec("find ..."), and that for tree views or single-file stat info you should just use terminal_exec instead of inventing a tool. Read before reaching for raw shell to grep or find anything.
metadata:
  author: hive
  type: preset-skill
  version: "1.0"
---

# Filesystem search

terminal-tools provides two structured search tools: `terminal_rg` (ripgrep for content) and `terminal_glob` (find files by name/glob). Predicate queries (mtime/size/type) and everything else (tree, stat, du) are just `terminal_exec`.

## When to use what

| Task | Tool |
|---|---|
| Find code/text matching a pattern (project tree or any path) | `terminal_rg` (gitignore-aware; defaults to your session workdir) |
| Find files by name/glob (any path) | `terminal_glob` |
| Find files by mtime/size/type predicate | `terminal_exec("find ...")` (see references/find_predicates.md) |
| List a directory | `terminal_exec("ls -la /path")` |
| Tree view | `terminal_exec("tree -L 2 /path")` |
| Single-path stat | `terminal_exec("stat /path")` |
| Disk usage | `terminal_exec("du -sh /path")` or `terminal_exec("du -h --max-depth=2 /")` |
| Count matching lines in returned results | `terminal_rg(...).total` (check `truncated` before treating it as complete) |

## `terminal_rg` — content search

ripgrep is fast, gitignore-aware, and has a deep flag surface. The structured wrapper exposes common search flags directly; `extra_args` accepts additional flags compatible with JSON output. Output modes such as `--count` and `--files-with-matches` are not compatible with this structured interface; use the CLI when that output is needed.

Quickstart installs and verifies ripgrep. Existing installations can be repaired with `uv run scripts/ensure_ripgrep.py --install` from the repository root. The runtime also checks Windows package-manager locations and current registry PATH entries; `HIVE_RIPGREP_PATH` can select an absolute executable path. Startup logs report the executable and version, or instructions to fix the missing dependency.

If ripgrep is unavailable, `terminal_rg` returns `code="ripgrep_required"` without searching by default. For an approximate search, explicitly set `allow_fallback=True`: this uses Python regex, a limited filetype table, and basename globs, and does **not** honor `.gitignore`. Even with opt-in, context, `extra_args`, unknown filetypes and complex globs require ripgrep and return an error. Inspect `fallback_limitations`; do not treat approximate results as a gitignore-aware inventory.

With `context=N`, surrounding lines are returned in `context`, separate from `matches`. Both contain `path`, `line`, and `text`; `total` counts only match entries.

### Common patterns

```
# All Python files containing "TODO"
terminal_rg(pattern="TODO", path=".", type_filter="py")

# Case-insensitive, with context
terminal_rg(pattern="error", path="/var/log", ignore_case=True, context=2)

# Search hidden files (rg ignores them by default)
terminal_rg(pattern="api_key", path="~", hidden=True)

# Don't respect .gitignore (find files git would ignore)
terminal_rg(pattern="generated", path=".", no_ignore=True)

# Multi-line pattern (e.g., function definitions spanning lines)
terminal_rg(pattern=r"def\s+\w+\(.*\n.*\n", path="src", extra_args=["--multiline"])

# Specific filename glob
terminal_rg(pattern="version", path=".", glob="*.toml")
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

## `terminal_glob` — find files by name

Lists files matching a glob, gitignore-aware (backed by `rg --files`). The pattern is widened for you so a bare stem Just Works — the actual glob run is returned as `expanded_pattern`:

- `lk_scan_post_reactors` → matched as `**/*lk_scan_post_reactors*` (recursive substring)
- `*.py` → matched as `**/*.py` (recursive by default)
- `src/**/*.py` → used verbatim

If `rg` is unavailable, filename search retains a best-effort walk with `fallback="python-walk"` and a note that `.gitignore` is not honored.

```
# Find a file by stem anywhere under a tree
terminal_glob(pattern="lk_scan_post_reactors", path="core/framework/skills")

# All YAML configs under /etc
terminal_glob(pattern="*.yaml", path="/etc")

# Include .gitignored / hidden / build-cache files
terminal_glob(pattern="*.log", path=".", include_ignored=True)
```

For **predicate** queries (modified in last N days, larger than N MB, only dirs/symlinks), `terminal_glob` is the wrong tool — drop to `terminal_exec("find ...")`. See `references/find_predicates.md`.

## Output truncation

Both tools return `truncated: true` when output exceeded the inline cap. For `terminal_rg`, matches were dropped (refine the pattern or narrow the path); for `terminal_glob`, results past `max_results` (default 1000) were dropped — the search stops early at the cap, so narrow the pattern rather than raising it. `terminal_glob` also returns `timed_out: true` (with the partial results it gathered) when the walk exceeded its deadline.

## Anti-patterns

- **`terminal_rg` is the project search tool** — gitignore-aware and returns structured matches; use it for in-project search as well as raw paths.
- **Don't reach for `terminal_glob` to list one directory** — `terminal_exec("ls -la /path")` is shorter.
- **Don't use `terminal_exec("grep ...")`** when `terminal_rg` exists — rg is faster, gitignore-aware, and returns structured matches.
- **Don't hand-roll `terminal_exec("find ... -name ...")`** for a plain name search — use `terminal_glob`. Reserve `terminal_exec("find ...")` for mtime/size/type predicates.
