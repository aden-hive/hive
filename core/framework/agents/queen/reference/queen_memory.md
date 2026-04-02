# Queen Memory v2 — File-Per-Memory Architecture

```
~/.hive/
├── queen/
│   ├── memories/
│   │   ├── .cursor.json                     ← Cursor: last processed message seq
│   │   ├── .reflection_error.txt            ← Last reflection error traceback
│   │   ├── .legacy/                         ← Archived v1 MEMORY.md files
│   │   ├── user-prefers-tests.md            ← Individual memory files
│   │   ├── project-api-patterns.md
│   │   └── ...
│   └── session/
│       └── {session_id}/
│           ├── conversations/
│           │   ├── parts/
│           │   │   ├── 0000000001.json
│           │   │   └── ...
│           │   └── spillover/
│           │       └── ...
│           └── data/
│               └── ...
```

---

## How it works

Queen memory has two subsystems: **Reflect** (writing) and **Recall** (reading).

### Reflect — incremental memory extraction

After each queen turn, a lightweight background agent inspects the new messages and extracts learnings into individual `.md` files.

- **Short reflection** — every queen turn. Reads messages since the last cursor position, passes them to a mini LLM loop (max 5 turns) with restricted tools that can list/read/write/delete memory files. Advances the cursor on success.
- **Long reflection** — every 5 short reflections, on context compaction, and at session end. Reads all memory files holistically to organize, deduplicate, and trim noise.

Both run under an `asyncio.Lock` — if a trigger fires while a reflection is active, it's skipped (messages will be reconsidered next time).

### Recall — pre-turn memory selection

Before each turn, a single structured-output LLM call picks up to 5 relevant memories from the file index. The selected files are read, prepended with staleness warnings for files older than 1 day, and injected into the system prompt via `phase_state._cached_recall_block`.

Recall runs as a background task after each `LLM_TURN_COMPLETE` and caches the result. This means memories are technically one turn behind — acceptable because the user's next query isn't known yet when the prompt is composed.

---

## Memory file format

Each file uses YAML frontmatter (convention enforced by prompt, not code):

```markdown
---
name: {{memory name}}
description: {{one-line description — used to decide relevance in future conversations}}
type: {{goal, environment, technique, reference}}
---

{{memory content}}
```

Parsing is **lenient**: broken or missing frontmatter degrades gracefully. Files show up in scans with `None` description and no type. Nothing rejects or repairs malformed files.

---

## Limits

| Setting | Value |
|---------|-------|
| Max memory files | 200 |
| Max file size | 4 KB |
| Max recall selections per turn | 5 |
| Reflection loop max turns | 5 |
| Long reflection interval | Every 5 short reflections |

---

## Cursor-based incremental processing

The cursor (`.cursor.json`) stores the last processed message sequence number. On each short reflection:

1. Read all `parts/*.json` files where `seq > cursor`
2. **Compaction fallback**: if no files match (cursor evicted by compaction), read all visible parts instead
3. Pass new messages to reflection LLM
4. Advance cursor to the new max seq

---

## Debugging

Enable debug logging to see reflect and recall activity:

```bash
# With hive serve
hive serve --debug

# With hive run
hive run --debug path/to/agent
```

This sets the log level to DEBUG, which shows:

| Logger prefix | What you see |
|---|---|
| `reflect: short` | Message count, cursor range, "no new messages" |
| `reflect: long` | File count being organized |
| `reflect: loop` | Turn-by-turn progress, tool call names |
| `reflect: tool` | Individual tool results (write/delete/list) |
| `reflect: turn complete` | Short count progress (e.g. `3/5`) |
| `recall:` | File scan count, selected filenames, injection block count |
| `recall: cache` | Cache update/skip with truncated query |

For tests:

```bash
uv run pytest core/tests/test_queen_memory.py -v --log-cli-level=DEBUG
```

---

## Migration from v1

On first run, `init_memory_dir()` calls `migrate_legacy_memories()` which:

1. Reads old `MEMORY.md` and recent `MEMORY-YYYY-MM-DD.md` files
2. Converts each section/entry into an individual memory file
3. Archives originals to `~/.hive/queen/memories/.legacy/`
