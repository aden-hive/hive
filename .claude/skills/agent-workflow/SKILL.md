---
name: agent-workflow
description: Complete workflow for building, implementing, and testing goal-driven agents. Orchestrates building-agents-* and testing-agent skills. Use when starting a new agent project, unsure which skill to use, or need end-to-end guidance.
license: Apache-2.0
metadata:
  author: hive
  version: "2.0"
  type: workflow-orchestrator
  orchestrates:
    - building-agents-core
    - building-agents-construction
    - building-agents-patterns
    - testing-agent
---

# Agent Development Workflow

Complete Standard Operating Procedure (SOP) for building production-ready goal-driven agents.

## Overview

This workflow orchestrates specialized skills to take you from initial concept to production-ready agent:

1. **Understand Concepts** (5-10 min) → `/building-agents-core` (optional)
2. **Build Structure** (15-30 min) → `/building-agents-construction`
3. **Optimize Design** (10-15 min) → `/building-agents-patterns` (optional)
4. **Test & Validate** (20-40 min) → `/testing-agent`

## When to Use This Workflow

Use this meta-skill when:
- Starting a new agent from scratch
- Unclear which skill to use first
- Need end-to-end guidance for agent development
- Want consistent, repeatable agent builds

**Skip this workflow** if:
- You only need to test an existing agent → use `/testing-agent` directly
- You know exactly which phase you're in → use specific skill directly

## Quick Decision Tree

```
"Need to understand agent concepts" → building-agents-core
"Build a new agent" → building-agents-construction
"Optimize my agent design" → building-agents-patterns
"Test my agent" → testing-agent
"Not sure what I need" → Read phases below, then decide
"Agent has structure but needs implementation" → See agent directory STATUS.md
```

## Phase 0: Understand Concepts (Optional)

**Duration**: 5-10 minutes
**Skill**: `/building-agents-core`
**Input**: Questions about agent architecture

### When to Use

- First time building an agent
- Need to understand node types, edges, goals
- Want to validate tool availability
- Learning about pause/resume architecture

### What This Phase Provides

- Architecture overview (Python packages, not JSON)
- Core concepts (Goal, Node, Edge, Pause/Resume)
- Tool discovery and validation procedures
- Workflow overview

**Skip this phase** if you already understand agent fundamentals.

## Phase 1: Build Agent Structure

**Duration**: 15-30 minutes
**Skill**: `/building-agents-construction`
**Input**: User requirements ("Build an agent that...")

### What This Phase Does

Creates the complete agent architecture:
- Package structure (`exports/agent_name/`)
- Goal with success criteria and constraints
- Workflow graph (nodes and edges)
- Node specifications
- CLI interface
- Documentation

### Process

1. **Create package** - Directory structure with skeleton files
2. **Define goal** - Success criteria and constraints written to agent.py
3. **Design nodes** - Each node approved and written incrementally
4. **Connect edges** - Workflow graph with conditional routing
5. **Finalize** - Agent class, exports, and documentation

### Outputs

- ✅ `exports/agent_name/` package created
- ✅ Goal defined in agent.py
- ✅ 3-5 success criteria defined
- ✅ 1-5 constraints defined
- ✅ 5-10 nodes specified in nodes/__init__.py
- ✅ 8-15 edges connecting workflow
- ✅ Validated structure (passes `python -m agent_name validate`)
- ✅ README.md with usage instructions
- ✅ CLI commands (info, validate, run, shell)

### Success Criteria

You're ready for Phase 2 when:
- Agent structure validates without errors
- All nodes and edges are defined
- CLI commands work (info, validate)
- You see: "Agent complete: exports/agent_name/"

### Common Outputs

The building-agents-construction skill produces:
```
exports/agent_name/
├── __init__.py          (package exports)
├── __main__.py          (CLI interface)
├── agent.py             (goal, graph, agent class)
├── nodes/__init__.py    (node specifications)
├── config.py            (configuration)
├── implementations.py   (may be created for Python functions)
└── README.md            (documentation)
```

### Next Steps

**If structure complete and validated:**
→ Check `exports/agent_name/STATUS.md` or `IMPLEMENTATION_GUIDE.md`
→ These files explain implementation options
→ You may need to add Python functions or MCP tools (not covered by current skills)

**If want to optimize design:**
→ Proceed to Phase 1.5 (building-agents-patterns)

**If ready to test:**
→ Proceed to Phase 2

## Phase 1.5: Optimize Design (Optional)

**Duration**: 10-15 minutes
**Skill**: `/building-agents-patterns`
**Input**: Completed agent structure

### When to Use

- Want to add pause/resume functionality
- Need error handling patterns
- Want to optimize performance
- Need examples of complex routing
- Want best practices guidance

### What This Phase Provides

- Practical examples and patterns
- Pause/resume architecture
- Error handling strategies
- Anti-patterns to avoid
- Performance optimization techniques

**Skip this phase** if your agent design is straightforward.

## Phase 2: Test & Validate

**Duration**: 20-40 minutes
**Skill**: `/testing-agent`
**Input**: Working agent from Phase 1

### What This Phase Does

Creates comprehensive test suite:
- Constraint tests (verify hard requirements)
- Success criteria tests (measure goal achievement)
- Edge case tests (handle failures gracefully)
- Integration tests (end-to-end workflows)

### Process

1. **Analyze agent** - Read goal, constraints, success criteria
2. **Generate tests** - Create pytest files in `exports/agent_name/tests/`
3. **User approval** - Review and approve each test
4. **Run evaluation** - Execute tests and collect results
5. **Debug failures** - Identify and fix issues
6. **Iterate** - Repeat until all tests pass

### Outputs

- ✅ Test files in `exports/agent_name/tests/`
- ✅ Test report with pass/fail metrics
- ✅ Coverage of all success criteria
- ✅ Coverage of all constraints
- ✅ Edge case handling verified

### Success Criteria

You're done when:
- All tests pass
- All success criteria validated
- All constraints verified
- Agent handles edge cases
- Test coverage is comprehensive

### Next Steps

**Agent ready for:**
- Production deployment
- Integration into larger systems
- Documentation and handoff
- Continuous monitoring

## Phase Transitions

### From Phase 1 to Phase 2

**Trigger signals:**
- "Agent complete: exports/..."
- Structure validation passes
- README indicates implementation complete

**Before proceeding:**
- Verify agent can be imported: `from exports.agent_name import default_agent`
- Check if implementation is needed (see STATUS.md or IMPLEMENTATION_GUIDE.md)
- Confirm agent executes without import errors

### Skipping Phases

**When to skip Phase 1:**
- Agent structure already exists
- Only need to add tests
- Modifying existing agent

**When to skip Phase 2:**
- Prototyping or exploring
- Agent not production-bound
- Manual testing sufficient

## Common Patterns

### Pattern 1: Complete New Build (Simple)

```
User: "Build an agent that monitors files"
→ Use /building-agents-construction
→ Agent structure created
→ Use /testing-agent
→ Tests created and passing
→ Done: Production-ready agent
```

### Pattern 1b: Complete New Build (With Learning)

```
User: "Build an agent (first time)"
→ Use /building-agents-core (understand concepts)
→ Use /building-agents-construction (build structure)
→ Use /building-agents-patterns (optimize design)
→ Use /testing-agent (validate)
→ Done: Production-ready agent
```

### Pattern 2: Test Existing Agent

```
User: "Test my agent at exports/my_agent"
→ Skip Phase 1
→ Use /testing-agent directly
→ Tests created
→ Done: Validated agent
```

### Pattern 3: Iterative Development

```
User: "Build an agent"
→ Use /building-agents-construction (Phase 1)
→ Implementation needed (see STATUS.md)
→ [User implements functions]
→ Use /testing-agent (Phase 2)
→ Tests reveal bugs
→ [Fix bugs manually]
→ Re-run tests
→ Done: Working agent
```

### Pattern 4: Complex Agent with Patterns

```
User: "Build an agent with multi-turn conversations"
→ Use /building-agents-core (learn pause/resume)
→ Use /building-agents-construction (build structure)
→ Use /building-agents-patterns (implement pause/resume pattern)
→ Use /testing-agent (validate conversation flows)
→ Done: Complex conversational agent
```

## Skill Dependencies

```
agent-workflow (meta-skill)
    │
    ├── building-agents-core (foundational)
    │   ├── Architecture concepts
    │   ├── Node/Edge/Goal definitions
    │   ├── Tool discovery procedures
    │   └── Workflow overview
    │
    ├── building-agents-construction (procedural)
    │   ├── Creates package structure
    │   ├── Defines goal
    │   ├── Adds nodes incrementally
    │   ├── Connects edges
    │   ├── Finalizes agent class
    │   └── Requires: building-agents-core
    │
    ├── building-agents-patterns (reference)
    │   ├── Best practices
    │   ├── Pause/resume patterns
    │   ├── Error handling
    │   ├── Anti-patterns
    │   └── Performance optimization
    │
    └── testing-agent
        ├── Reads agent goal
        ├── Generates tests
        ├── Runs evaluation
        └── Reports results
```

## Troubleshooting

### "Agent structure won't validate"

- Check node IDs match between nodes/__init__.py and agent.py
- Verify all edges reference valid node IDs
- Ensure entry_node exists in nodes list
- Run: `PYTHONPATH=core:exports python -m agent_name validate`

### "Agent has structure but won't run"

- Check for STATUS.md or IMPLEMENTATION_GUIDE.md in agent directory
- Implementation may be needed (Python functions or MCP tools)
- This is expected - building-agents-construction creates structure, not implementation
- See implementation guide for completion options

### "Tests are failing"

- Review test output for specific failures
- Check agent goal and success criteria
- Verify constraints are met
- Use `/testing-agent` to debug and iterate
- Fix agent code and re-run tests

### "Not sure which phase I'm in"

Run these checks:

```bash
# Check if agent structure exists
ls exports/my_agent/agent.py

# Check if it validates
PYTHONPATH=core:exports python -m my_agent validate

# Check if tests exist
ls exports/my_agent/tests/

# If structure exists and validates → Phase 2 (testing)
# If structure doesn't exist → Phase 1 (building)
# If tests exist but failing → Debug phase
```

## Best Practices

### For Phase 1 (Building)

1. **Start with clear requirements** - Know what the agent should do
2. **Define success criteria early** - Measurable goals drive design
3. **Keep nodes focused** - One responsibility per node
4. **Use descriptive names** - Node IDs should explain purpose
5. **Validate incrementally** - Check structure after each major addition

### For Phase 2 (Testing)

1. **Test constraints first** - Hard requirements must pass
2. **Mock external dependencies** - Use mock mode for LLMs/APIs
3. **Cover edge cases** - Test failures, not just success paths
4. **Iterate quickly** - Fix one test at a time
5. **Document test patterns** - Future tests follow same structure

### General Workflow

1. **Use version control** - Git commit after each phase
2. **Document decisions** - Update README with changes
3. **Keep iterations small** - Build → Test → Fix → Repeat
4. **Preserve working states** - Tag successful iterations
5. **Learn from failures** - Failed tests reveal design issues

## Exit Criteria

You're done with the workflow when:

✅ Agent structure validates
✅ All tests pass
✅ Success criteria met
✅ Constraints verified
✅ Documentation complete
✅ Agent ready for deployment

## Additional Resources

- **building-agents-core**: See `.claude/skills/building-agents-core/SKILL.md`
- **building-agents-construction**: See `.claude/skills/building-agents-construction/SKILL.md`
- **building-agents-patterns**: See `.claude/skills/building-agents-patterns/SKILL.md`
- **testing-agent**: See `.claude/skills/testing-agent/SKILL.md`
- **Agent framework docs**: See `core/README.md`
- **Example agents**: See `exports/` directory

## Summary

This workflow provides a proven path from concept to production-ready agent:

1. **Learn** with `/building-agents-core` → Understand fundamentals (optional)
2. **Build** with `/building-agents-construction` → Get validated structure
3. **Optimize** with `/building-agents-patterns` → Apply best practices (optional)
4. **Test** with `/testing-agent` → Get verified functionality

The workflow is **flexible** - skip phases as needed, iterate freely, and adapt to your specific requirements. The goal is **production-ready agents** built with **consistent, repeatable processes**.

## Skill Selection Guide

**Choose building-agents-core when:**
- First time building agents
- Need to understand architecture
- Validating tool availability
- Learning about node types and edges

**Choose building-agents-construction when:**
- Actually building an agent
- Have clear requirements
- Ready to write code
- Want step-by-step guidance

**Choose building-agents-patterns when:**
- Agent structure complete
- Need advanced patterns
- Implementing pause/resume
- Optimizing performance
- Want best practices

**Choose testing-agent when:**
- Agent structure complete
- Ready to validate functionality
- Need comprehensive test coverage
- Debugging agent behavior
