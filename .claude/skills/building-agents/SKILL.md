---
name: building-agents
description: DEPRECATED - Split into building-agents-core, building-agents-construction, and building-agents-patterns. Use agent-workflow for complete guidance.
license: Apache-2.0
metadata:
  author: hive
  version: "1.0"
  status: deprecated
  replaced_by:
    - building-agents-core
    - building-agents-construction
    - building-agents-patterns
---

# DEPRECATED: Building Agents Skill

**This skill has been split into three focused skills for better organization.**

## Use These Instead

### 1. `/building-agents-core` - Foundational Concepts
- Architecture overview (Python packages)
- Core concepts (Goal, Node, Edge, Pause/Resume)
- Tool discovery and validation procedures
- When to use: Learning fundamentals, first-time agent builders

### 2. `/building-agents-construction` - Building Process
- Step-by-step agent construction
- Package structure, goal definition, nodes, edges
- CLI interface and finalization
- When to use: Actually building an agent

### 3. `/building-agents-patterns` - Best Practices
- Design patterns and examples
- Pause/resume architecture
- Error handling and performance
- Anti-patterns to avoid
- When to use: Optimizing design, advanced features

## Complete Workflow

Use **`/agent-workflow`** meta-skill for end-to-end guidance:

```
Phase 0: Understand → /building-agents-core (optional)
Phase 1: Build → /building-agents-construction
Phase 1.5: Optimize → /building-agents-patterns (optional)
Phase 2: Test → /testing-agent
```

## Why Split?

- **Reduced context** - Each skill under 650 lines (vs 939 lines)
- **Better organization** - Clear separation of concerns
- **Faster loading** - Load only what you need
- **Easier maintenance** - Update one aspect independently

## Quick Decision Guide

**"I'm new to agents"** → Start with `/building-agents-core`

**"Build an agent now"** → Use `/building-agents-construction`

**"Optimize my design"** → Use `/building-agents-patterns`

**"Complete workflow"** → Use `/agent-workflow`

**"Test my agent"** → Use `/testing-agent`

## Migration

All functionality from the original building-agents skill is preserved across the three new skills. The content has been reorganized, not removed.

**Original file**: Available as `SKILL.md.bak` for reference

**See also**: [DEPRECATED.md](./DEPRECATED.md) for detailed migration guide

---

**Deprecated**: 2026-01-21
**Replaced by**: building-agents-core, building-agents-construction, building-agents-patterns
**Orchestrator**: agent-workflow
