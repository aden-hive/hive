import os
import sys
import json

def setup_opencode():
    print("✨ Setting up Opencode integration...")

    # 1. Define paths
    base_dir = os.getcwd()
    opencode_dir = os.path.join(base_dir, ".opencode")
    agents_dir = os.path.join(opencode_dir, "agents")
    
    # Create directories
    if not os.path.exists(agents_dir):
        os.makedirs(agents_dir)
        print(f"   Created directory: {agents_dir}")

    # 2. Determine Path Separator (Windows uses ';' others use ':')
    # We force ';' if on Windows to be safe
    path_sep = ";" if os.name == 'nt' else ":"
    print(f"   Detected OS: {os.name} (using separator '{path_sep}')")

    # 3. Create mcp.json
    mcp_config = {
        "mcpServers": {
            "agent-builder": {
                "command": "python",
                "args": ["-m", "framework.mcp.agent_builder_server"],
                "cwd": "core",
                "env": {
                    "PYTHONPATH": f"../tools/src{path_sep}."
                }
            },
            "tools": {
                "command": "python",
                "args": ["mcp_server.py", "--stdio"],
                "cwd": "tools",
                "env": {
                    "PYTHONPATH": f"src{path_sep}../core"
                }
            }
        }
    }
    
    mcp_path = os.path.join(opencode_dir, "mcp.json")
    with open(mcp_path, "w") as f:
        json.dump(mcp_config, f, indent=2)
    print(f"✅ Created {mcp_path}")

    # 4. Create Hive Agent
    agent_content = """---
name: hive
description: Hive Agent Builder & Manager
mode: primary
model: anthropic/claude-3-5-sonnet-20241022
tools:
  agent-builder: true
  tools: true
---

# Hive Agent
You are the Hive Agent Builder. Your goal is to help the user construct, configure, and deploy AI agents using the Hive framework.

## Capabilities
1. **Scaffold Agents:** Create new agent directories/configs.
2. **Manage Tools:** Add/remove tools via MCP.
3. **Debug:** Analyze agent workflows.

## Context & Skills
- You have access to all skills in `.claude/skills/`.
- Always use the `agent-builder` MCP server for filesystem operations.
"""
    
    agent_path = os.path.join(agents_dir, "hive.md")
    with open(agent_path, "w", encoding="utf-8") as f:
        f.write(agent_content)
    
    print(f"✅ Created {agent_path}")
    print("\n🎉 Setup Complete! Restart Opencode and type '/hive' to begin.")

if __name__ == "__main__":
    setup_opencode()