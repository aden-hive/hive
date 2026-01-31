## Summary

Add Cursor IDE support for existing Claude Code skills and MCP servers.

## Changes

- Created `.cursor/skills/` directory with symlinks to all 5 existing skills:
  - `agent-workflow`
  - `building-agents-core`
  - `building-agents-construction`
  - `building-agents-patterns`
  - `testing-agent`
- Added `.cursor/mcp.json` with MCP server configuration (same as `.mcp.json`)

## Why symlinks for skills?

- Single source of truth - updates to `.claude/skills/` are reflected in both IDEs
- No duplication or sync issues
- Cursor automatically loads skills from `.cursor/skills/`, `.claude/skills/`, and `.codex/skills/`

## MCP Configuration

Cursor requires `.cursor/mcp.json` for project-level MCP servers. This enables:
- `agent-builder` - Agent building MCP server
- `tools` - Hive tools MCP server

## Setup in Cursor

1. **Enable MCP**: Open Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`) and run `MCP: Enable`
2. **Restart Cursor** to load the MCP servers from `.cursor/mcp.json`
3. **Skills**: Type `/` in Agent chat and search for the skill name
