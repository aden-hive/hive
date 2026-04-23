# Issue #4927: DSA Mentor Agent - Implementation Plan & Validation Strategy

## 🎯 Overview

This document outlines the step-by-step implementation process with continuous validation checkpoints to ensure we're building the DSA Mentor Agent correctly.

---

## 📋 Implementation Workflow

### Phase 1: Foundation Setup (30 minutes)
**Goal**: Create the basic structure and verify it works

#### Step 1.1: Create Directory Structure
```bash
# Create the template directory
mkdir -p examples/templates/dsa_mentor/nodes

# Verify structure
tree examples/templates/dsa_mentor/
```

**✅ Validation Checkpoint 1.1:**
- [ ] Directory structure exists
- [ ] Matches pattern from `marketing_agent/`

#### Step 1.2: Create Minimal Files
Create these files with minimal content to test imports:

**File: `examples/templates/dsa_mentor/__init__.py`**
```python
"""DSA Mentor Agent — template example."""

# Placeholder - will fill in later
__all__ = []
```

**File: `examples/templates/dsa_mentor/config.py`**
```python
"""Runtime configuration for DSA Mentor Agent."""

from dataclasses import dataclass, field

@dataclass
class RuntimeConfig:
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 2048
    storage_path: str = "~/.hive/storage"
    mock_mode: bool = False

@dataclass
class AgentMetadata:
    name: str = "dsa_mentor"
    version: str = "0.1.0"
    description: str = "DSA Mentor Agent for algorithm learning"
    author: str = ""
    tags: list[str] = field(
        default_factory=lambda: ["education", "dsa", "algorithms", "mentor", "template"]
    )

default_config = RuntimeConfig()
metadata = AgentMetadata()
```

**File: `examples/templates/dsa_mentor/nodes/__init__.py`**
```python
"""Node definitions for DSA Mentor Agent."""

from framework.graph import NodeSpec

# Placeholder - will add nodes later
all_nodes = []
```

**✅ Validation Checkpoint 1.2:**
```bash
# Test imports work
cd /Users/Ishaan/Downloads/hive-fresh
uv run python -c "from examples.templates.dsa_mentor.config import default_config; print('✓ Config imports')"
uv run python -c "from examples.templates.dsa_mentor.nodes import all_nodes; print('✓ Nodes import')"
```
- [ ] No import errors
- [ ] Files are syntactically correct

---

### Phase 2: Core Agent Structure (1 hour)
**Goal**: Build the agent.py skeleton with goal, edges, and agent class

#### Step 2.1: Create Goal Definition
**File: `examples/templates/dsa_mentor/agent.py`** (partial)

Start with just the goal definition:

```python
"""DSA Mentor Agent — goal, edges, graph spec, and agent class."""

from pathlib import Path
from framework.graph import Goal, SuccessCriterion, Constraint

# Goal definition
goal = Goal(
    id="dsa-mentor",
    name="DSA Mentor Agent",
    description=(
        "Act as an AI coding mentor that provides guided hints, reviews code quality, "
        "identifies weak DSA areas, and suggests personalized practice plans."
    ),
    success_criteria=[
        SuccessCriterion(
            id="hint-quality",
            description="Provides progressive hints without revealing full solutions",
            metric="llm_judge",
            target="Hints are helpful but not complete solutions",
            weight=0.3,
        ),
        # Add other 3 criteria...
    ],
    constraints=[
        Constraint(
            id="no-direct-solutions",
            description="Never provide complete solutions - only hints and guidance",
            constraint_type="hard",
            category="educational",
        ),
        # Add other constraints...
    ],
    input_schema={
        "problem_statement": {"type": "string"},
        "user_code": {"type": "string", "optional": True},
        "user_question": {"type": "string", "optional": True},
        "difficulty_level": {"type": "string", "optional": True},
    },
    output_schema={
        "hint": {"type": "string"},
        "code_review": {"type": "object", "optional": True},
        "weak_areas": {"type": "array", "optional": True},
        "practice_plan": {"type": "array", "optional": True},
    },
)
```

**✅ Validation Checkpoint 2.1:**
```bash
# Test goal definition
uv run python -c "from examples.templates.dsa_mentor.agent import goal; print(f'✓ Goal: {goal.name}')"
```
- [ ] Goal object creates successfully
- [ ] All success criteria defined
- [ ] All constraints defined
- [ ] Schemas are valid

#### Step 2.2: Create Minimal Agent Class
Add the agent class skeleton:

```python
from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime
from framework.llm.anthropic import AnthropicProvider
from .config import default_config, RuntimeConfig
from .nodes import all_nodes

class DSAMentorAgent:
    """DSA Mentor Agent for algorithm learning."""
    
    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or default_config
        self.goal = goal
        # Will add nodes, edges later
        
    def _build_graph(self) -> GraphSpec:
        # Placeholder - will implement after nodes are defined
        pass
        
    def _create_executor(self):
        runtime = Runtime(storage_path=Path(self.config.storage_path).expanduser())
        llm = AnthropicProvider(model=self.config.model)
        return GraphExecutor(runtime=runtime, llm=llm)

default_agent = DSAMentorAgent()
```

**✅ Validation Checkpoint 2.2:**
```bash
# Test agent class
uv run python -c "from examples.templates.dsa_mentor.agent import DSAMentorAgent, default_agent; print('✓ Agent class works')"
```
- [ ] Agent class instantiates
- [ ] No import errors
- [ ] Basic structure is correct

---

### Phase 3: Build First Node (1 hour)
**Goal**: Create the intake node and verify it works

#### Step 3.1: Create Intake Node
**File: `examples/templates/dsa_mentor/nodes/__init__.py`**

Add the first node:

```python
"""Node definitions for DSA Mentor Agent."""

from framework.graph import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect problem statement, user code, and questions",
    node_type="event_loop",
    input_keys=[],
    output_keys=["problem_statement", "user_code", "user_question", "difficulty_level"],
    nullable_output_keys=["user_code", "user_question", "difficulty_level"],
    client_facing=True,
    system_prompt="""\
You are a DSA mentor helping a student learn algorithms.

**STEP 1 — Greet the user (text only, NO tool calls):**
Greet the user warmly and explain that you're here to help them learn algorithms through guided hints and code review.

**STEP 2 — Collect information:**
Ask the user to provide:
1. The problem statement (required) - what algorithm problem are they working on?
2. Their code attempt (optional) - if they have code, they can share it
3. Their specific question (optional) - what do they need help with?
4. Difficulty level (optional) - easy, medium, or hard

Be friendly and encouraging. If the user provides partial info, ask for what's missing.

**STEP 3 — After collecting ALL required information, call set_output:**
- set_output("problem_statement", "<the problem statement>")
- set_output("user_code", "<their code or empty string if not provided>")
- set_output("user_question", "<their question or empty string if not provided>")
- set_output("difficulty_level", "<easy/medium/hard or empty string if not provided>")
""",
    tools=[],
    max_retries=3,
    max_node_visits=1,
)

all_nodes = [intake_node]
```

**✅ Validation Checkpoint 3.1:**
```bash
# Test node definition
uv run python -c "from examples.templates.dsa_mentor.nodes import intake_node; print(f'✓ Node: {intake_node.name}')"
```
- [ ] Node creates successfully
- [ ] System prompt is valid
- [ ] Node type is correct (event_loop)
- [ ] Client-facing is True

#### Step 3.2: Wire Node into Agent
Update `agent.py` to include the node:

```python
from .nodes import all_nodes

class DSAMentorAgent:
    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = all_nodes  # Add this
        self.entry_node = "intake"  # Add this
```

**✅ Validation Checkpoint 3.2:**
```bash
# Test agent with node
uv run python -c "
from examples.templates.dsa_mentor.agent import DSAMentorAgent
agent = DSAMentorAgent()
print(f'✓ Agent has {len(agent.nodes)} node(s)')
print(f'✓ Entry node: {agent.entry_node}')
"
```
- [ ] Agent has nodes
- [ ] Entry node is set correctly

---

### Phase 4: Create Minimal Working Agent (1 hour)
**Goal**: Get a runnable agent with just the intake node

#### Step 4.1: Complete Agent Class
Update `agent.py` with full graph building:

```python
# Add edges (empty for now)
edges = []

# Graph structure
entry_node = "intake"
entry_points = {"start": "intake"}
terminal_nodes = ["intake"]  # Temporary - will update later
pause_nodes = []

class DSAMentorAgent:
    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="dsa-mentor-graph",
            goal_id=self.goal.id,
            entry_node=self.entry_node,
            entry_points=entry_points,
            terminal_nodes=terminal_nodes,
            pause_nodes=pause_nodes,
            nodes=self.nodes,
            edges=edges,  # Empty for now
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            description="DSA Mentor Agent workflow",
        )
    
    async def run(self, context: dict, mock_mode: bool = False) -> dict:
        graph = self._build_graph()
        executor = self._create_executor()
        result = await executor.execute(
            graph=graph,
            goal=self.goal,
            input_data=context,
        )
        return {
            "success": result.success,
            "output": result.output,
            "steps": result.steps_executed,
            "path": result.path,
        }
```

#### Step 4.2: Create CLI Entry Point
**File: `examples/templates/dsa_mentor/__main__.py`**

```python
"""CLI entry point for DSA Mentor Agent."""

import asyncio
import json
import sys

def main():
    from .agent import DSAMentorAgent
    from .config import default_config

    # Default input for testing
    input_data = {
        "problem_statement": "Find two numbers in array that sum to target",
    }

    # Accept JSON input from command line
    if len(sys.argv) > 1 and sys.argv[1] == "--input":
        input_data = json.loads(sys.argv[2])

    agent = DSAMentorAgent(config=default_config)
    result = asyncio.run(agent.run(input_data))

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
```

#### Step 4.3: Update `__init__.py`
```python
"""DSA Mentor Agent — template example."""

from .agent import DSAMentorAgent, goal, edges, nodes
from .config import default_config

__all__ = ["DSAMentorAgent", "goal", "edges", "nodes", "default_config"]
```

**✅ Validation Checkpoint 4.1: CRITICAL - First Working Test**
```bash
# Test the agent runs (in mock mode to avoid API calls)
MOCK_MODE=1 uv run python -m examples.templates.dsa_mentor --input '{"problem_statement": "test"}'
```
- [ ] Agent runs without errors
- [ ] Graph builds successfully
- [ ] Intake node executes (or at least doesn't crash)
- [ ] Returns some output

**If this fails:**
- Check import paths
- Verify node definitions
- Check graph structure
- Review error messages carefully

---

### Phase 5: Add Remaining Nodes Incrementally (2-3 hours)
**Goal**: Add one node at a time, test after each

#### Step 5.1: Add Analyze Problem Node
1. Create `analyze_problem_node` in `nodes/__init__.py`
2. Add to `all_nodes` list
3. Update edges to connect intake → analyze
4. Update terminal_nodes

**✅ Validation Checkpoint 5.1:**
```bash
# Test with analyze node
uv run python -c "
from examples.templates.dsa_mentor.agent import DSAMentorAgent
agent = DSAMentorAgent()
print(f'✓ Agent has {len(agent.nodes)} nodes')
"
```
- [ ] Node added successfully
- [ ] Edge connects correctly
- [ ] Graph structure is valid

#### Step 5.2: Add Provide Hint Node
Repeat the process for each node:
1. Create node definition
2. Add to all_nodes
3. Add edges
4. Test

**✅ Validation Checkpoint 5.2:**
After each node:
- [ ] Node definition is correct
- [ ] System prompt enforces no solutions
- [ ] Edges connect properly
- [ ] Graph validates

#### Step 5.3: Add Review Code Node
- [ ] Conditional edge (only if code provided)
- [ ] Code review logic in prompt

#### Step 5.4: Add Identify Weaknesses Node
- [ ] Tracks patterns
- [ ] Outputs structured weakness data

#### Step 5.5: Add Suggest Practice Node
- [ ] Creates practice plan
- [ ] Uses weakness data

**✅ Validation Checkpoint 5.5: Full Node Graph**
```bash
# Test complete graph structure
uv run python -c "
from examples.templates.dsa_mentor.agent import DSAMentorAgent
agent = DSAMentorAgent()
graph = agent._build_graph()
print(f'✓ Graph has {len(graph.nodes)} nodes')
print(f'✓ Graph has {len(graph.edges)} edges')
print(f'✓ Entry: {graph.entry_node}')
print(f'✓ Terminal: {graph.terminal_nodes}')
"
```
- [ ] All 6 nodes present
- [ ] All edges defined
- [ ] Graph structure is valid
- [ ] No circular dependencies

---

### Phase 6: Testing & Refinement (2 hours)
**Goal**: Test with real scenarios and refine prompts

#### Step 6.1: Test Hint Progression
```bash
# Test hint system doesn't reveal solutions
uv run python -m examples.templates.dsa_mentor --input '{
  "problem_statement": "Find two sum",
  "user_question": "Can you give me the solution?"
}'
```

**✅ Validation Checkpoint 6.1:**
- [ ] Agent refuses to give full solution
- [ ] Provides hints instead
- [ ] Hints are progressive

#### Step 6.2: Test Code Review Path
```bash
# Test code review
uv run python -m examples.templates.dsa_mentor --input '{
  "problem_statement": "Two sum problem",
  "user_code": "def two_sum(nums, target): return [0, 1]"
}'
```

**✅ Validation Checkpoint 6.2:**
- [ ] Code review executes
- [ ] Provides complexity analysis
- [ ] Suggests optimizations

#### Step 6.3: Test Full Workflow
```bash
# Test complete flow
uv run python -m examples.templates.dsa_mentor --input '{
  "problem_statement": "Binary tree inorder traversal",
  "user_code": "def inorder(root): ...",
  "user_question": "Is this optimal?",
  "difficulty_level": "medium"
}'
```

**✅ Validation Checkpoint 6.3:**
- [ ] All nodes execute in order
- [ ] Output contains all expected fields
- [ ] Practice plan is generated
- [ ] Weaknesses are identified

---

### Phase 7: Code Quality & Documentation (1-2 hours)
**Goal**: Polish code and add documentation

#### Step 7.1: Code Quality
```bash
# Run linting
make check

# Fix any issues
make lint
```

**✅ Validation Checkpoint 7.1:**
- [ ] `make check` passes
- [ ] No linting errors
- [ ] Code is formatted correctly

#### Step 7.2: Create README
Create comprehensive README with:
- Workflow diagram
- Usage examples
- Node descriptions
- Customization ideas

**✅ Validation Checkpoint 7.2:**
- [ ] README is complete
- [ ] Examples work as documented
- [ ] Clear and helpful

---

## 🔄 Continuous Validation Strategy

### After Each Phase:
1. **Import Test**: Verify imports work
2. **Structure Test**: Verify graph structure is valid
3. **Run Test**: Try to execute (even if minimal)
4. **Lint Check**: Run `make check` frequently

### Quick Validation Commands:
```bash
# Quick import test
uv run python -c "from examples.templates.dsa_mentor.agent import DSAMentorAgent; print('✓')"

# Quick structure test
uv run python -c "
from examples.templates.dsa_mentor.agent import DSAMentorAgent
agent = DSAMentorAgent()
graph = agent._build_graph()
print(f'✓ {len(graph.nodes)} nodes, {len(graph.edges)} edges')
"

# Quick lint check
make check 2>&1 | head -20
```

### Red Flags to Watch For:
- ❌ Import errors → Check file paths and module names
- ❌ Graph validation errors → Check node IDs, edge sources/targets
- ❌ Runtime errors → Check system prompts, tool usage
- ❌ Linting errors → Fix immediately, don't accumulate

---

## 📊 Progress Tracking

### Milestone 1: Foundation (Phase 1-2)
- [ ] Directory structure created
- [ ] Config file works
- [ ] Goal defined
- [ ] Agent class skeleton

**Time**: ~1.5 hours  
**Validation**: Imports work, basic structure valid

### Milestone 2: First Node (Phase 3-4)
- [ ] Intake node created
- [ ] Agent runs with one node
- [ ] CLI works

**Time**: ~2 hours  
**Validation**: Agent executes without errors

### Milestone 3: All Nodes (Phase 5)
- [ ] All 6 nodes created
- [ ] All edges connected
- [ ] Graph structure complete

**Time**: ~3 hours  
**Validation**: Graph has 6 nodes, edges connect properly

### Milestone 4: Testing (Phase 6)
- [ ] Hint system works
- [ ] Code review works
- [ ] Full workflow tested

**Time**: ~2 hours  
**Validation**: All features work as expected

### Milestone 5: Polish (Phase 7)
- [ ] Code quality passes
- [ ] README complete
- [ ] Ready for PR

**Time**: ~1-2 hours  
**Validation**: `make check` passes, documentation complete

---

## 🚀 Getting Started Right Now

### Immediate Next Steps:

1. **Create the directory structure** (5 minutes)
```bash
mkdir -p examples/templates/dsa_mentor/nodes
```

2. **Create config.py** (10 minutes)
   - Copy from marketing_agent
   - Update metadata

3. **Test config imports** (2 minutes)
```bash
uv run python -c "from examples.templates.dsa_mentor.config import default_config; print('✓')"
```

4. **Create minimal agent.py** (20 minutes)
   - Just goal definition first
   - Test it works

5. **Create intake node** (30 minutes)
   - First working node
   - Test it executes

**Total Time for First Working Version**: ~1.5 hours

---

## 💡 Pro Tips

1. **Work incrementally**: One node at a time, test after each
2. **Validate frequently**: Run quick tests after every change
3. **Fix errors immediately**: Don't accumulate technical debt
4. **Reference existing templates**: Marketing agent is a great reference
5. **Test in mock mode first**: Avoid API costs during development
6. **Keep prompts simple initially**: Refine later
7. **Use git commits**: Commit after each working milestone

---

## 🎯 Success Criteria

You'll know you're done when:
- ✅ Agent runs: `uv run python -m examples.templates.dsa_mentor`
- ✅ All 6 nodes execute in correct order
- ✅ Hints are progressive and never reveal solutions
- ✅ Code review provides useful feedback
- ✅ Weaknesses are identified
- ✅ Practice plans are generated
- ✅ `make check` passes
- ✅ README is complete
- ✅ Ready for PR submission

---

**Next Action**: Start with Phase 1 - Create directory structure and config file!
