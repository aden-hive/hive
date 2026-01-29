## Glossary

This section defines common terms used throughout the Hive project to help new contributors and users better understand the system.

### Agent
An autonomous unit responsible for executing tasks. Agents can use tools, make decisions, and interact with other agents as part of a workflow.

### Task
A discrete unit of work assigned to an agent. Tasks define what needs to be done and may depend on the output of other tasks.

### Tool
A callable function or capability that an agent can use to perform a specific action, such as reading a file, making an API request, or processing data.

### Workflow
A structured sequence of tasks and agents designed to accomplish a larger goal. Workflows define execution order and dependencies.

### Graph
An internal representation of a workflow, where nodes represent tasks or agents and edges define dependencies between them.

### Executor
The component responsible for running a workflow or graph, managing task execution, and handling errors.

### MCP (Model Context Protocol)
A protocol used to manage and exchange context between models, tools, and agents during execution.

### Node
A single unit within a graph, typically representing a task or an agent.

### Edge
A dependency or relationship between two nodes in a graph, indicating execution order or data flow.
