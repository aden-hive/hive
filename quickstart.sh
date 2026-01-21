#!/bin/bash
#
# quickstart.sh - Install/overwrite building-agents and testing-agent skills
#
# This script copies the skills from this repo to your Claude Code configuration.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Claude Code skills directory
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"

echo ""
echo "================================================"
echo "  Hive Agent Framework - Skill Installation"
echo "================================================"
echo ""

# Check if .claude/skills exists in this repo
if [ ! -d "$SCRIPT_DIR/.claude/skills" ]; then
    echo -e "${RED}Error: Skills directory not found at $SCRIPT_DIR/.claude/skills${NC}"
    exit 1
fi

# Create Claude skills directory if it doesn't exist
if [ ! -d "$CLAUDE_SKILLS_DIR" ]; then
    echo -e "${YELLOW}Creating Claude skills directory: $CLAUDE_SKILLS_DIR${NC}"
    mkdir -p "$CLAUDE_SKILLS_DIR"
fi

# Function to install a skill
install_skill() {
    local skill_name=$1
    local source_dir="$SCRIPT_DIR/.claude/skills/$skill_name"
    local target_dir="$CLAUDE_SKILLS_DIR/$skill_name"

    if [ ! -d "$source_dir" ]; then
        echo -e "${RED}✗ Skill not found: $skill_name${NC}"
        return 1
    fi

    # Check if skill already exists
    if [ -d "$target_dir" ]; then
        echo -e "${YELLOW}  Overwriting existing skill: $skill_name${NC}"
        rm -rf "$target_dir"
    else
        echo -e "${GREEN}  Installing new skill: $skill_name${NC}"
    fi

    # Copy the skill
    cp -r "$source_dir" "$target_dir"

    echo -e "${GREEN}✓ Installed: $skill_name${NC}"
    echo "  Location: $target_dir"
    echo ""
}

# Install skills
echo "Installing skills to: $CLAUDE_SKILLS_DIR"
echo ""

install_skill "building-agents"
install_skill "testing-agent"

echo "================================================"
echo -e "${GREEN}✓ Installation complete!${NC}"
echo "================================================"
echo ""
echo "Skills installed:"
echo "  - /building-agents - Build goal-driven agents as Python packages"
echo "  - /testing-agent   - Run goal-based evaluation tests for agents"
echo ""
echo "Usage:"
echo "  1. Open Claude Code (CLI or VS Code extension)"
echo "  2. Type /building-agents to build a new agent"
echo "  3. Type /testing-agent to test an existing agent"
echo ""
echo "Documentation:"
echo "  - Building: $CLAUDE_SKILLS_DIR/building-agents/SKILL.md"
echo "  - Testing:  $CLAUDE_SKILLS_DIR/testing-agent/SKILL.md"
echo ""
echo "Example agent:"
echo "  - exports/outbound_sales_agent/ - Full working example"
echo ""
