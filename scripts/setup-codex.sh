    #!/bin/bash
#
# setup-codex.sh - Configure Codex CLI for Hive agent building
#
# This script:
# 1. Creates .codex/ directory with MCP configuration
# 2. Generates instructions.md for Codex
# 3. Sets up the same MCP servers used by Claude Code
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo ""
echo "=================================================="
echo "  Hive Agent Framework - Codex CLI Setup"
echo "=================================================="
echo ""

# ============================================================
# Step 1: Check Prerequisites
# ============================================================

echo -e "${BLUE}Step 1: Checking prerequisites...${NC}"
echo ""

# Check if codex is installed
if command -v codex &> /dev/null; then
    CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
    echo -e "${GREEN}  ✓ Codex CLI found: $CODEX_VERSION${NC}"
else
    echo -e "${YELLOW}  ⚠ Codex CLI not found${NC}"
    echo "    Install it from: https://developers.openai.com/codex/cli/"
    echo "    Continuing with configuration anyway..."
fi

# Check Python
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python is not installed.${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ Python found${NC}"

echo ""

# ============================================================
# Step 2: Create .codex Directory
# ============================================================

echo -e "${BLUE}Step 2: Creating Codex configuration...${NC}"
echo ""

CODEX_DIR="$PROJECT_ROOT/.codex"
mkdir -p "$CODEX_DIR"

# ============================================================
# Step 3: Generate config.toml
# ============================================================

cat > "$CODEX_DIR/config.toml" << EOF
# Hive Agent Builder - Codex CLI MCP Configuration
#
# This configures Codex to use the same MCP servers as Claude Code.
# The agent-builder server provides tools for building AI agents.
# The hive-tools server provides runtime tools (web search, file ops, etc.)

[mcp_servers.agent-builder]
command = "python"
args = ["-m", "framework.mcp.agent_builder_server"]
cwd = "$PROJECT_ROOT/core"
env = { PYTHONPATH = "$PROJECT_ROOT/tools/src" }

[mcp_servers.hive-tools]
command = "python"
args = ["mcp_server.py", "--stdio"]
cwd = "$PROJECT_ROOT/tools"
env = { PYTHONPATH = "src" }
EOF

echo -e "${GREEN}  ✓ Created config.toml${NC}"

# ============================================================
# Step 4: Generate instructions.md
# ============================================================

cat > "$CODEX_DIR/instructions.md" << 'EOF'
# Hive Agent Builder Instructions

You have access to MCP tools for building goal-driven AI agents.

## Available MCP Servers

1. **agent-builder** - Tools for creating agent graphs
2. **hive-tools** - Runtime tools (web search, file operations, etc.)

## Agent Building Workflow

### Step 1: Create a Session
```
mcp.agent-builder.create_session(name="my-agent")
```

### Step 2: Register Tools Server
Before adding nodes that use tools, register the hive-tools server:
```
mcp.agent-builder.add_mcp_server(
    name="hive-tools",
    transport="stdio",
    command="python",
    args='["mcp_server.py", "--stdio"]',
    cwd="tools",
    description="Hive tools for web search, file operations"
)
```

### Step 3: Define the Goal
```
mcp.agent-builder.set_goal(
    goal_id="research-goal",
    name="Research a Topic",
    description="Search the web and create a summary",
    success_criteria='[{"id": "sc1", "description": "Found 3+ sources", "metric": "source_count", "target": ">=3"}]'
)
```

### Step 4: Add Nodes
Node types:
- `llm_generate`: Pure LLM text/JSON generation (no tools)
- `llm_tool_use`: LLM with tool access
- `router`: Conditional branching
- `function`: Python function execution

Example:
```
mcp.agent-builder.add_node(
    node_id="search-web",
    name="Search the Web",
    description="Searches for information on the topic",
    node_type="llm_tool_use",
    input_keys='["topic"]',
    output_keys='["search_results"]',
    system_prompt="Search for information about the given topic...",
    tools='["web_search"]'
)
```

### Step 5: Connect Nodes with Edges
```
mcp.agent-builder.add_edge(
    edge_id="e1",
    source="search-web",
    target="summarize",
    condition="on_success"
)
```

### Step 6: Validate and Export
```
mcp.agent-builder.validate_graph()
mcp.agent-builder.export_graph(output_dir="exports/my_agent")
```

## Available Tools (from hive-tools)

When adding `llm_tool_use` nodes, you can use these tools:
- `web_search` - Search the web using Brave Search API
- `web_scrape` - Scrape content from a webpage
- `pdf_read` - Read and extract text from PDFs
- `view_file` - Read file contents
- `write_to_file` - Write content to a file
- `list_dir` - List directory contents
- `grep_search` - Search for patterns in files
- `execute_command_tool` - Run shell commands

## Important Rules

1. **Always register hive-tools FIRST** before adding nodes that use tools
2. **Only use tools that exist** - check with `mcp.agent-builder.list_mcp_tools()`
3. **entry_points format**: Always use `{"start": "first-node-id"}`
4. **Validate before export** - catches errors early

## Example: Research Agent

```
# 1. Create session
mcp.agent-builder.create_session(name="research-agent")

# 2. Register tools
mcp.agent-builder.add_mcp_server(name="hive-tools", transport="stdio", command="python", args='["mcp_server.py", "--stdio"]', cwd="tools")

# 3. Set goal
mcp.agent-builder.set_goal(goal_id="research", name="Research Topic", description="...", success_criteria='[...]')

# 4. Add nodes
mcp.agent-builder.add_node(node_id="search", name="Search", node_type="llm_tool_use", ...)
mcp.agent-builder.add_node(node_id="summarize", name="Summarize", node_type="llm_generate", ...)

# 5. Add edges
mcp.agent-builder.add_edge(edge_id="e1", source="search", target="summarize")

# 6. Export
mcp.agent-builder.validate_graph()
mcp.agent-builder.export_graph(output_dir="exports/research_agent")
```

For more details, see:
- `.claude/skills/building-agents-construction/SKILL.md`
- `.claude/skills/building-agents-core/SKILL.md`
- `core/MCP_SERVER_GUIDE.md`
EOF

echo -e "${GREEN}  ✓ Created instructions.md${NC}"

echo ""

# ============================================================
# Step 5: Verify Python Packages
# ============================================================

echo -e "${BLUE}Step 3: Verifying Python packages...${NC}"
echo ""

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Check if framework is importable
if $PYTHON_CMD -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ framework package OK${NC}"
else
    echo -e "${YELLOW}  ⚠ framework not installed - run ./scripts/setup-python.sh first${NC}"
fi

# Check if aden_tools is importable
if $PYTHON_CMD -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ aden_tools package OK${NC}"
else
    echo -e "${YELLOW}  ⚠ aden_tools not installed - run ./scripts/setup-python.sh first${NC}"
fi

echo ""

# ============================================================
# Step 6: Success
# ============================================================

echo "=================================================="
echo -e "${GREEN}  ✓ Codex CLI Setup Complete!${NC}"
echo "=================================================="
echo ""
echo "Configuration created at:"
echo "  $CODEX_DIR/config.toml"
echo "  $CODEX_DIR/instructions.md"
echo ""
echo "Usage:"
echo "  1. Navigate to the project:"
echo "     ${BLUE}cd $PROJECT_ROOT${NC}"
echo ""
echo "  2. Start Codex:"
echo "     ${BLUE}codex${NC}"
echo ""
echo "  3. Ask Codex to build an agent:"
echo "     ${BLUE}\"Build me a research agent that searches the web and writes a summary\"${NC}"
echo ""
echo "MCP tools available:"
echo "  • mcp.agent-builder.create_session"
echo "  • mcp.agent-builder.set_goal"
echo "  • mcp.agent-builder.add_node"
echo "  • mcp.agent-builder.add_edge"
echo "  • mcp.agent-builder.validate_graph"
echo "  • mcp.agent-builder.export_graph"
echo "  • mcp.hive-tools.web_search"
echo "  • mcp.hive-tools.web_scrape"
echo "  • ... and more"
echo ""
