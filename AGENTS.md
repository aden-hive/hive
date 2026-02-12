# Hive Agent Instructions (Codex)

Use skills from `.agents/skills`:
- hive
- hive-create
- hive-concepts
- hive-patterns
- hive-test
- hive-credentials

Rules:
- Prefer MCP tools from `agent-builder` and `tools`.
- Before assuming tool availability, list MCP tools first.
- Reuse existing Hive skill workflows; do not invent alternative flows unless required.

Shortcut Handling:
- Treat `hive`, `hive-create`, `hive-concepts`, `hive-patterns`, `hive-test`, and `hive-credentials` as workflow invocation phrases.
- Users do not need to type skill file paths when using these phrases.
