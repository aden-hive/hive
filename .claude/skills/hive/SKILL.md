---
name: hive
description: Complete workflow for building, implementing, and testing goal-driven agents. Orchestrates hive-* skills. Use when starting a new agent project, unsure which skill to use, or need end-to-end guidance.
license: Apache-2.0
metadata:
  author: hive
  version: "2.0"
  type: workflow-orchestrator
  orchestrates:
    - hive-concepts
    - hive-create
    - hive-patterns
    - hive-test
    - hive-credentials
    - hive-debugger
---

# Agent Development Workflow

**THIS IS AN EXECUTABLE WORKFLOW. DO NOT explore the codebase or read source files. ROUTE to the correct skill IMMEDIATELY.**

When this skill is loaded, **ALWAYS use the AskUserQuestion tool** to present options:

```
Use AskUserQuestion with these options:
- "Build a new agent" → Then invoke /hive-create
- "Test an existing agent" → Then invoke /hive-test
- "Learn agent concepts" → Then invoke /hive-concepts
- "Optimize agent design" → Then invoke /hive-patterns
- "Set up credentials" → Then invoke /hive-credentials
- "Debug a failing agent" → Then invoke /hive-debugger
- "Other" (please describe what you want to achieve)
```

**DO NOT:** Read source files, explore the codebase, search for code, or do any investigation before routing. The sub-skills handle all of that.

---

Complete Standard Operating Procedure (SOP) for building production-ready goal-driven agents.

## Overview

This workflow orchestrates specialized skills to take you from initial concept to production-ready agent:

1. **Understand Concepts** → `/hive-concepts` (optional)
2. **Build Structure** → `/hive-create`
3. **Optimize Design** → `/hive-patterns` (optional)
4. **Setup Credentials** → `/hive-credentials` (if agent uses tools requiring API keys)
5. **Test & Validate** → `/hive-test`
6. **Debug Issues** → `/hive-debugger` (if agent fails at runtime)

## When to Use This Workflow

Use this meta-skill when:
- Starting a new agent from scratch
- Unclear which skill to use first
- Need end-to-end guidance for agent development

**Skip this workflow** if you know which phase you're in → use the specific skill directly.

## Quick Decision Tree

```
"Need to understand agent concepts"      → /hive-concepts
"Build a new agent"                       → /hive-create
"Optimize my agent design"                → /hive-patterns
"Need client-facing nodes or feedback"    → /hive-patterns
"Set up API keys for my agent"            → /hive-credentials
"Test my agent"                           → /hive-test
"My agent is failing/stuck/has errors"    → /hive-debugger
"Not sure what I need"                    → Stay here, use the menu above
"Agent has structure but needs impl"      → See agent directory STATUS.md
```

## Phase Reference

Each phase is fully documented in its own skill. This section is a quick summary — see the linked skill for full instructions.

| Phase | Skill | What It Does | When to Use |
|-------|-------|-------------|-------------|
| 0 | `/hive-concepts` | Architecture, node types, edges, judges, tool discovery | First time building; need fundamentals |
| 1 | `/hive-create` | 6-step interactive builder → Python package in `exports/` | Building a new agent (scratch or template) |
| 1.5 | `/hive-patterns` | Client-facing nodes, feedback loops, judges, fan-out, context mgmt | Optimizing an existing agent design |
| 2 | `/hive-credentials` | Detect missing creds, Aden OAuth or direct API key, encrypted store | Before running/testing agent |
| 3 | `/hive-test` | Generate → Execute → Analyze → Fix → Resume → Verify | Validating agent against goal |
| 4 | `/hive-debugger` | L1/L2/L3 log analysis → fix templates → checkpoint recovery | Agent failing at runtime |

### Phase Transitions

**Phase 1 → Phase 3 (Build → Test):**
- Agent structure validates: `PYTHONPATH=exports uv run python -m agent_name validate`
- Agent can be imported: `from exports.agent_name import default_agent`
- Check `STATUS.md` or `IMPLEMENTATION_GUIDE.md` for any remaining implementation work

**Phase 3 → Phase 4 (Test → Debug):**
- Tests reveal runtime failures (not just assertion errors)
- Agent is stuck in retry loops or producing no output
- Tool calls are failing with auth or timeout errors

## Common Patterns

### Pattern 1: Complete New Build
```
/hive-create → Structure created → /hive-test → Tests passing → Done
```

### Pattern 2: Build with Learning
```
/hive-concepts → /hive-create → /hive-patterns → /hive-test → Done
```

### Pattern 3: Test Existing Agent
```
/hive-test directly → Tests created → Debug failures → Done
```

### Pattern 4: Iterative Development
```
/hive-create → Structure created → [User implements functions]
→ /hive-test → Tests reveal bugs → [Fix bugs] → Re-run → Done
```

### Pattern 5: Agent with HITL
```
/hive-concepts → /hive-create (with feedback edges)
→ /hive-patterns (client-facing + feedback) → /hive-test → Done
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Agent structure won't validate | Check node IDs match between `nodes/__init__.py` and `agent.py`; verify edges reference valid node IDs |
| Agent has structure but won't run | Check `STATUS.md` — implementation may be needed; `hive-create` creates structure, not implementation |
| Tests are failing | Use `/hive-test` to debug; review test output, check goal and success criteria |
| Agent is failing at runtime | Use `/hive-debugger` to analyze L1/L2/L3 logs and get fix recommendations |
| Not sure which phase I'm in | Run: `ls exports/my_agent/agent.py` (exists → Phase 3+), `ls exports/my_agent/tests/` (exists → debug phase) |

## Skill Dependencies

```
hive (meta-skill / router)
    ├── hive-concepts   → Foundational reference
    ├── hive-create     → Procedural builder (requires: hive-concepts)
    ├── hive-patterns   → Design patterns reference
    ├── hive-credentials → Auth/secret setup
    ├── hive-test       → Iterative test loop
    └── hive-debugger   → Runtime debugging (requires: hive-concepts)
```

