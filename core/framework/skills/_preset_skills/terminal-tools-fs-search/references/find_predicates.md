# find predicate reference

Plain name/glob file lookups go to `terminal_glob`. For predicate queries — mtime, size, type, depth, permissions, or any combination — there is no structured wrapper; drive `find` directly via `terminal_exec("find ...")` using the predicates below.

## Time predicates

| Need | find predicate |
|---|---|
| Modified within N days | `-mtime -N` |
| Modified more than N days ago | `-mtime +N` |
| Modified exactly N days ago | `-mtime N` |
| Accessed within N days | `-atime -N` |
| Inode changed within N days | `-ctime -N` |
| Modified in last N minutes | `-mmin -N` |
| Newer than reference file | `-newer ref` |

## Size predicates

| Need | find predicate |
|---|---|
| Bigger than N kilobytes | `-size +Nk` |
| Smaller than N kilobytes | `-size -Nk` |
| Exactly N kilobytes | `-size Nk` |
| Bigger than N megabytes | `-size +NM` |
| Empty files | `-empty` |

## Type predicates

| Need | find predicate |
|---|---|
| Regular file | `-type f` |
| Directory | `-type d` |
| Symlink | `-type l` |
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
# .log OR .txt (drop to terminal_exec for OR)
terminal_exec(r"find /path \( -name '*.log' -o -name '*.txt' \) -type f", shell=True)

# NOT in a directory called node_modules
terminal_exec("find . -path '*/node_modules' -prune -o -name '*.js' -print", shell=True)
```

## Actions

| Need | predicate |
|---|---|
| Print path (default) | (implicit `-print`) |
| Print null-separated | `-print0` (for piping to xargs -0) |
| Delete | `-delete` (DANGEROUS — use terminal_exec with explicit confirmation) |
| Run command per match | `-exec cmd {} \;` (drop to terminal_exec) |
| Run command, batched | `-exec cmd {} +` |

## When NOT to use find

- **One directory listing**: `terminal_exec("ls -la /path")`
- **Recursive grep**: `terminal_rg`
- **Count files**: `terminal_exec("find /path -type f | wc -l")`
