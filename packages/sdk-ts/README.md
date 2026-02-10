# @aden/sdk

TypeScript SDK for building goal-driven, self-improving AI agents with the Aden framework.

## Installation

```bash
npm install @aden/sdk
# or
pnpm add @aden/sdk
```

## Quick Start

```typescript
import {
  Goal,
  GoalStatus,
  GraphSpec,
  NodeSpec,
  EdgeSpec,
  Runtime,
  SharedMemory,
} from "@aden/sdk";

// 1. Define a Goal
const goal: Goal = {
  id: "calculator-001",
  name: "Calculator Agent",
  description: "Perform mathematical calculations accurately",
  status: GoalStatus.DRAFT,
  successCriteria: [
    {
      id: "accuracy",
      description: "Result matches expected mathematical answer",
      metric: "output_equals",
      target: "expected_result",
      weight: 1.0,
      met: false,
    },
  ],
  constraints: [
    {
      id: "no-crash",
      description: "Handle invalid inputs gracefully",
      constraintType: "hard",
      category: "safety",
      check: "output != exception",
    },
  ],
  context: {},
  requiredCapabilities: ["llm"],
  inputSchema: { expression: { type: "string" } },
  outputSchema: { result: { type: "number" } },
  version: "1.0.0",
  parentVersion: null,
  evolutionReason: null,
  createdAt: new Date(),
  updatedAt: new Date(),
};

// 2. Define Nodes
const nodes: NodeSpec[] = [
  {
    id: "parser",
    name: "Expression Parser",
    description: "Parse the mathematical expression",
    nodeType: "function",
    inputKeys: ["expression"],
    outputKeys: ["parsed_expr"],
    // ... other fields with defaults
  },
  {
    id: "calculator",
    name: "Calculator",
    description: "Evaluate the parsed expression",
    nodeType: "llm_tool_use",
    inputKeys: ["parsed_expr"],
    outputKeys: ["result"],
    tools: ["calculate"],
    systemPrompt: "You are a calculator. Evaluate expressions accurately.",
  },
];

// 3. Define Edges
const edges: EdgeSpec[] = [
  {
    id: "parser-to-calc",
    source: "parser",
    target: "calculator",
    condition: "on_success",
  },
];

// 4. Create Graph
const graph: GraphSpec = {
  id: "calculator-agent",
  name: "Calculator Agent",
  version: "1.0.0",
  nodes,
  edges,
  entryNode: "parser",
  goalId: goal.id,
};

// 5. Use Runtime for Decision Logging
const runtime = new Runtime();
const runId = runtime.startRun(goal.id, goal.description, { expression: "2 + 2" });

const decisionId = runtime.decide({
  nodeId: "calculator",
  intent: "Evaluate expression 2 + 2",
  options: [
    { id: "direct", description: "Direct evaluation" },
    { id: "stepwise", description: "Step-by-step calculation" },
  ],
  chosen: "direct",
  reasoning: "Simple addition, direct evaluation is sufficient",
});

runtime.recordOutcome(decisionId, {
  success: true,
  result: 4,
  summary: "Evaluated 2 + 2 = 4",
});

runtime.endRun(true, "Calculation completed successfully", { result: 4 });
```

## Core Concepts

### Goal

The source of truth for agent behavior. Defines WHAT to achieve, not HOW.

```typescript
import { Goal, isGoalSuccess, goalToPromptContext } from "@aden/sdk";

// Check if goal is achieved
if (isGoalSuccess(goal)) {
  console.log("Goal achieved!");
}

// Generate LLM prompt context
const promptContext = goalToPromptContext(goal);
```

### Graph

Defines the agent's execution structure: nodes, edges, and flow.

```typescript
import { GraphSpec, validateGraph, getOutgoingEdges } from "@aden/sdk";

// Validate graph structure
const errors = validateGraph(graph);
if (errors.length > 0) {
  console.error("Graph validation errors:", errors);
}

// Get edges from a node
const edges = getOutgoingEdges(graph, "parser");
```

### Shared Memory

State shared between nodes during execution.

```typescript
import { SharedMemory } from "@aden/sdk";

const memory = new SharedMemory({ initial: "data" });
memory.write("key", "value");
const value = memory.read<string>("key");
```

### Runtime

Records agent decisions for analysis and improvement.

```typescript
import { Runtime } from "@aden/sdk";

const runtime = new Runtime();
const runId = runtime.startRun("goal-id", "Description");

// Record decisions and outcomes
const decisionId = runtime.decide({ ... });
runtime.recordOutcome(decisionId, { success: true, result: ... });

runtime.endRun(true, "Completed");
```

### LLM Provider

Abstract interface for LLM backends.

```typescript
import { LLMProvider, MockLLMProvider } from "@aden/sdk";

// Use mock for testing
const mockLLM = new MockLLMProvider(["Response 1", "Response 2"]);
const response = await mockLLM.complete({
  messages: [{ role: "user", content: "Hello" }],
});
```

## API Reference

### Schemas (Zod)

- `GoalSchema` - Goal validation
- `NodeSpecSchema` - Node specification
- `EdgeSpecSchema` - Edge specification
- `GraphSpecSchema` - Complete graph

### Types

- `Goal`, `SuccessCriterion`, `Constraint`
- `NodeSpec`, `NodeResult`, `NodeContext`
- `EdgeSpec`, `EdgeCondition`
- `GraphSpec`
- `LLMProvider`, `LLMResponse`, `Tool`, `ToolUse`, `ToolResult`
- `Runtime`, `Run`, `Decision`, `Option`, `Outcome`

### Utilities

- `isGoalSuccess(goal)` - Check if goal is achieved
- `goalToPromptContext(goal)` - Generate LLM prompt
- `validateGraph(graph)` - Validate graph structure
- `shouldTraverse(edge, ...)` - Check edge traversal
- `getOutgoingEdges(graph, nodeId)` - Get node's outgoing edges
- `getNode(graph, nodeId)` - Get node by ID

## Development

```bash
# Install dependencies
npm install

# Build
npm run build

# Run tests
npm test

# Watch mode
npm run dev
```

## License

Apache-2.0
