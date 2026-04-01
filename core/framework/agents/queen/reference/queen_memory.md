# Queen Memory — File System Structure

```
~/.hive/
├── queen/
│   ├── MEMORY.md                          ← Semantic memory
│   ├── memories/
│   │   ├── MEMORY-2026-03-09.md           ← Episodic memory (today)
│   │   ├── MEMORY-2026-03-08.md
│   │   └── ...
│   └── session/
│       └── {session_id}/                  ← One dir per session (or resumed-from session)
│           ├── conversations/
│           │   ├── parts/
│           │   │   ├── 00001.json         ← One file per message (role, content, tool_calls)
│           │   │   ├── 00002.json
│           │   │   └── ...
│           │   └── spillover/
│           │       ├── conversation_1.md  ← Compacted old conversation segments
│           │       ├── conversation_2.md
│           │       └── ...
│           └── data/
│               ├── web_search_1.txt      ← Spillover: large tool results
│               ├── web_search_2.txt
│               └── ...
```

---

## The two memory tiers

| File | Tier | Written by | Read at |
|---|---|---|---|
| `MEMORY.md` | Semantic | Consolidation LLM (auto, post-session) | Session start (injected into system prompt) |
| `memories/MEMORY-YYYY-MM-DD.md` | Episodic | Queen via `write_to_diary` tool + consolidation LLM | Session start (today's file injected) |

---

## Session directory naming

The session directory name is **`queen_resume_from`** when a cold-restore resumes an existing
session, otherwise the new **`session_id`**. This means resumed sessions accumulate all messages
in the original directory rather than fragmenting across multiple folders.

---

## Consolidation

`consolidate_queen_memory()` runs every **5 minutes** in the background and once more at session
end. It reads:

1. `conversations/parts/*.json` — full message history (user + assistant turns; tool results skipped)

It then makes two LLM writes:

- Rewrites `MEMORY.md` in place (semantic memory — queen never touches this herself)
- Appends a timestamped prose entry to today's `memories/MEMORY-YYYY-MM-DD.md`

If the combined transcript exceeds ~200 K characters it is recursively binary-compacted via the
LLM before being sent to the consolidation model (mirrors `EventLoopNode._llm_compact`).
