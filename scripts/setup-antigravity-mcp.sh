#!/usr/bin/env bash
#
# setup-antigravity-mcp.sh - Write Antigravity/Claude MCP config with auto-detected paths
#
# Run from anywhere inside the hive repo. Generates ~/.gemini/antigravity/mcp_config.json
# based on .agent/mcp_config.json template, with absolute paths so the IDE can
# connect to agent-builder and tools MCP servers without manual path editing.
#
set -e

# Find repo root
REPO_ROOT=""
if git rev-parse --show-toplevel &>/dev/null; then
  REPO_ROOT="$(git rev-parse --show-toplevel)"
elif [ -f ".agent/mcp_config.json" ]; then
  REPO_ROOT="$(pwd)"
else
  d="$(pwd)"
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    [ -f "$d/.agent/mcp_config.json" ] && REPO_ROOT="$d" && break
    d="$(dirname "$d")"
  done
fi

if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/core" ] || [ ! -d "$REPO_ROOT/tools" ]; then
  echo "Error: Run this script from inside the hive repo (could not find repo root with core/ and tools/)." >&2
  exit 1
fi

TEMPLATE="$REPO_ROOT/.agent/mcp_config.json"
if [ ! -f "$TEMPLATE" ]; then
  echo "Error: Template not found at $TEMPLATE" >&2
  exit 1
fi

CORE_DIR="$(cd "$REPO_ROOT/core" && pwd)"
TOOLS_DIR="$(cd "$REPO_ROOT/tools" && pwd)"

mkdir -p "$HOME/.gemini/antigravity"

# Generate config from template with absolute paths
# Replace relative "core" and "tools" with absolute paths in --directory args
sed -e "s|\"--directory\", \"core\"|\"--directory\", \"$CORE_DIR\"|g" \
    -e "s|\"--directory\", \"tools\"|\"--directory\", \"$TOOLS_DIR\"|g" \
    "$TEMPLATE" > "$HOME/.gemini/antigravity/mcp_config.json"

echo "Wrote $HOME/.gemini/antigravity/mcp_config.json (from $TEMPLATE)"
echo "  core  -> $CORE_DIR"
echo "  tools -> $TOOLS_DIR"

if [ "$1" = "--claude" ]; then
  mkdir -p "$HOME/.claude"
  cp "$HOME/.gemini/antigravity/mcp_config.json" "$HOME/.claude/mcp.json"
  echo "Wrote $HOME/.claude/mcp.json"
fi

echo ""
echo "Next: Restart Antigravity IDE so it loads the MCP config."
echo "      Then open this repo; agent-builder and tools should appear."
echo ""
echo "For Claude Code, run: $0 --claude"
