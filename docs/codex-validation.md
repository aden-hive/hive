# Codex Validation Notes

Date: 2026-02-12

## Environment checks

- `codex --version`: `codex-cli 0.99.0`
- Project Codex config present: `.codex/config.toml`
- Skill links present: `.agents/skills/{hive,hive-create,hive-concepts,hive-patterns,hive-test,hive-credentials}`
- `AGENTS.md` present at repo root

## Quickstart verification

Validated via `./quickstart.sh`:

- `codex CLI` detected
- `AGENTS.md` check passed
- `Codex MCP config` check passed
- `Codex skills` check passed

## MCP registration verification

Command:

```bash
codex mcp list
```

Result:

- `agent-builder` -> `enabled`
- `tools` -> `enabled`

## Previous non-interactive smoke test attempt (environment-dependent)

Command:

```bash
codex exec --cd . --skip-git-repo-check --json "List connected MCP servers and tools. If available, confirm agent-builder and tools."
```

Result:

- One attempt failed due network/backend stream disconnection:
  `stream disconnected before completion: error sending request for url (https://chatgpt.com/backend-api/codex/responses)`

## Status

- Codex integration files are configured and validated.
- MCP servers are registered and enabled in Codex.
- Remaining E2E work: run full Codex chat workflow (`hive-create` then `hive-test`) and capture outputs.
