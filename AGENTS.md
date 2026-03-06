# Repository Guidelines

Shared agent instructions for this workspace.

## Deprecations

- **TUI is deprecated.** The terminal UI (`hive tui`) is no longer maintained. Use the browser-based interface (`hive open`) instead.

## Coding Agent Notes

- 
- When working on a GitHub Issue or PR, print the full URL at the end of the task.
- When answering questions, respond with high-confidence answers only: verify in code; do not guess.
- Do not update dependencies casually. Version bumps, patched dependencies, overrides, or vendored dependency changes require explicit approval.
- Add brief comments for tricky logic. Keep files reasonably small when practical; split or refactor large files instead of growing them indefinitely.
- If shared guardrails are available locally, review them; otherwise follow this repo's guidance.
- Use `uv` for Python execution and package management. Do not use `python` or `python3` directly unless the user explicitly asks for it.
- Prefer `uv run` for scripts and tests, and `uv pip` for package operations.


## Multi-Agent Safety

- Do not create, apply, or drop `git stash` entries unless explicitly requested.
- Do not create, remove, or modify `git worktree` checkouts unless explicitly requested.
- Do not switch branches or check out a different branch unless explicitly requested.
- When the user says `push`, you may `git pull --rebase` to integrate latest changes, but never discard other in-progress work.
- When the user says `commit`, commit only your changes. When the user says `commit all`, commit everything in grouped chunks.
- When you see unrecognized files or unrelated changes, keep going and focus on your scoped changes.

## Change Hygiene

- If staged and unstaged diffs are formatting-only, resolve them without asking.
- If a commit or push was already requested, include formatting-only follow-up changes in that same commit when practical.
- Only stop to ask for confirmation when changes are semantic and may alter behavior.
