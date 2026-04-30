# find predicate reference

The `shell_find` wrapper exposes name/iname, type, mtime_days, size bounds, max_depth, max_results. For combinations beyond that, drop to `shell_exec("find ...")`.

## Time predicates

| Need | find predicate |
|---|---|
| Modified within N days | `-mtime -N` (wrapper: `mtime_days=N`) |
| Modified more than N days ago | `-mtime +N` |
| Modified exactly N days ago | `-mtime N` |
| Accessed within N days | `-atime -N` |
| Inode changed within N days | `-ctime -N` |
| Modified in last N minutes | `-mmin -N` |
| Newer than reference file | `-newer ref` |

## Size predicates

| Need | find predicate |
|---|---|
| Bigger than N kilobytes | `-size +Nk` (wrapper: `size_kb_min`) |
| Smaller than N kilobytes | `-size -Nk` (wrapper: `size_kb_max`) |
| Exactly N kilobytes | `-size Nk` |
| Bigger than N megabytes | `-size +NM` |
| Empty files | `-empty` |

## Type predicates

| Need | find predicate |
|---|---|
| Regular file | `-type f` (wrapper: `type_filter="f"`) |
| Directory | `-type d` (wrapper: `type_filter="d"`) |
| Symlink | `-type l` (wrapper: `type_filter="l"`) |
| Block device | `-type b` |
| Character device | `-type c` |
| FIFO | `-type p` |
| Socket | `-type s` |

## Permission predicates

| Need | find predicate |
|---|---|
| Owned by user | `-user alice` |
| Owned by group | `-group dev` |
| Permission bits exact | `-perm 644` |
| Has any of these bits | `-perm /u+x` |
| Has all of these bits | `-perm -u+x` |
| Readable by current user | `-readable` |
| Writable | `-writable` |
| Executable | `-executable` |

## Composing

`find` evaluates predicates left-to-right with implicit AND. For OR, use `\(`...\` or .

```
# .log OR .txt (drop to shell_exec for OR)
shell_exec(r"find /path \( -name '*.log' -o -name '*.txt' \) -type f", shell=True)

# NOT in a directory called node_modules
shell_exec("find . -path '*/node_modules' -prune -o -name '*.js' -print", shell=True)
```

## Actions

| Need | predicate |
|---|---|
| Print path (default) | (implicit `-print`) |
| Print null-separated | `-print0` (for piping to xargs -0) |
| Delete | `-delete` (DANGEROUS — use shell_exec with explicit confirmation) |
| Run command per match | `-exec cmd {} \;` (drop to shell_exec) |
| Run command, batched | `-exec cmd {} +` |

## When NOT to use find

- **One directory listing**: `shell_exec("ls -la /path")`
- **Recursive grep**: `shell_rg`
- **Count files**: `shell_exec("find /path -type f | wc -l")`
