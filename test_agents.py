#!/usr/bin/env python
"""Test script to verify agent discovery works."""
from framework.tui.screens.agent_picker import discover_agents

groups = discover_agents()
print(f"\n✅ Agent Discovery Working!")
print(f"Total categories: {len(groups)}\n")

for category, entries in groups.items():
    print(f"📁 {category}: {len(entries)} agents")
    for entry in entries:
        print(f"   • {entry.name}")
        print(f"     Path: {entry.path}")
        print(f"     Nodes: {entry.node_count}, Tools: {entry.tool_count}")
    print()
