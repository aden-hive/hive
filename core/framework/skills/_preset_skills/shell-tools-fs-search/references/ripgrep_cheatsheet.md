# ripgrep cheatsheet

For when the structured `shell_rg` flags don't cover the case. Pass via `extra_args=[...]`.

## Filtering

| Need | Flag |
|---|---|
| Whole word | `-w` |
| Fixed string (no regex) | `-F` |
| Match files only (paths, not lines) | `-l` |
| Count matches per file | `-c` |
| Print only filenames with no matches | `--files-without-match` |
| Exclude binary files | (default) |
| Include binaries | `--binary` |
| Search archives transparently | (rg doesn't — extract first) |

## Output shape

| Need | Flag |
|---|---|
| Show only matched part | `-o` |
| Show byte offset of match | `-b` |
| No filename prefix | `-N` (or pipe through awk) |
| Color always (for piping into a colorizer) | `--color=always` |
| JSON output | (the wrapper already uses `--json` internally) |

## Boundaries

| Need | Flag |
|---|---|
| Line-by-line (default) | (default) |
| Multi-line regex | `--multiline` (or `-U`) |
| Multi-line dotall (`.` matches `\n`) | `--multiline-dotall` |
| Crlf line endings | `--crlf` |

## Path control

| Need | Flag |
|---|---|
| Follow symlinks | `-L` |
| Don't follow | (default) |
| Search hidden | `-.` (also expressed as `hidden=True`) |
| Don't respect any ignores | `-uuu` |
| Glob include | `-g 'pattern'` (also `glob="..."`) |
| Glob exclude | `-g '!pattern'` |

## Performance

| Need | Flag |
|---|---|
| One thread | `-j 1` |
| Smaller mmap chunks | `--mmap` (default behavior usually fine) |
| Per-file match cap | `-m N` (also `max_count=N`) |

## Common composed queries

```
# Find unused imports in Python
shell_rg(pattern=r"^import\s+\w+$", path="src", type_filter="py")

# All TODO/FIXME/XXX with file:line
shell_rg(pattern=r"\b(TODO|FIXME|XXX)\b", path=".", extra_args=["-n"])

# Functions defined at module top-level
shell_rg(pattern=r"^def\s+\w+", path=".", type_filter="py")

# Lines that DON'T match a pattern (filtered through awk)
# rg can't invert at line level; use shell_exec with grep -v
```
