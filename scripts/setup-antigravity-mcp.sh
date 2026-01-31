#!/usr/bin/env bash
#
# setup-antigravity-mcp.sh - Write Antigravity/Claude MCP config with auto-detected paths
#
# Run from anywhere inside the hive repo. Writes ~/.gemini/mcp.json (and optionally
# ~/.claude/mcp.json) with absolute cwd paths so the IDE can connect to agent-builder
# and tools MCP servers without manual path editing.
#
set -e

# Find repo root
REPO_ROOT=""
if git rev-parse --show-toplevel &>/dev/null; then
  REPO_ROOT="$(git rev-parse --show-toplevel)"
elif [ -f ".antigravity/mcp_config.json" ]; then
  REPO_ROOT="$(pwd)"
else
  d="$(pwd)"
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    [ -f "$d/.antigravity/mcp_config.json" ] && REPO_ROOT="$d" && break
    d="$(dirname "$d")"
  done
fi

if [ -z "$REPO_ROOT" ] || [ ! -d "$REPO_ROOT/core" ] || [ ! -d "$REPO_ROOT/tools" ]; then
  echo "Error: Run this script from inside the hive repo (could not find repo root with core/ and tools/)." >&2
  exit 1
fi

CORE_DIR="$(cd "$REPO_ROOT/core" && pwd)"
TOOLS_DIR="$(cd "$REPO_ROOT/tools" && pwd)"

PYTHON_CMD="python3"
command -v python3 &>/dev/null || PYTHON_CMD="python"

mkdir -p "$HOME/.gemini"

# Build config with absolute paths (no merge; script is for initial setup)
cat > "$HOME/.gemini/mcp.json" << EOF
{
  "mcpServers": {
    "agent-builder": {
      "command": "$PYTHON_CMD",
      "args": ["-m", "framework.mcp.agent_builder_server"],
      "cwd": "$CORE_DIR",
      "env": {
        "PYTHONPATH": "../tools/src"
      }
    },
    "tools": {
      "command": "$PYTHON_CMD",
      "args": ["mcp_server.py", "--stdio"],
      "cwd": "$TOOLS_DIR",
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
EOF

echo "Wrote $HOME/.gemini/mcp.json (cwd: $CORE_DIR, $TOOLS_DIR)"

if [ "$1" = "--claude" ]; then
  mkdir -p "$HOME/.claude"
  cp "$HOME/.gemini/mcp.json" "$HOME/.claude/mcp.json"
  echo "Wrote $HOME/.claude/mcp.json"
fi

echo ""
echo "Next: Restart Antigravity IDE so it loads the MCP config. Then open this repo; agent-builder and tools should appear."
echo "For Claude Code, run: $0 --claude"
