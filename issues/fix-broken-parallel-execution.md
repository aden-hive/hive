# Issue: Fix Broken Parallel Execution Logic in GraphExecutor

## Summary
The `GraphExecutor` correctly identifies fan-out nodes and attempts to execute branches in parallel. However, the current implementation (`_execute_parallel_branches`) only executes the **immediately** connected nodes for each branch. It does not recursively execute the subgraph for each branch until convergence.

## Problem
If a parallel branch consists of multiple steps (e.g., `Node A` -> `Node B` -> `Convergence Node`), the executor will:
1.  Execute `Node A` in parallel with other branches.
2.  Immediately jump to the `fan_in_node`.
3.  **Skip `Node B` entirely.**

This effectively limits all parallel branches to a length of exactly one node.

## Affected Code
`core/framework/graph/executor.py`

## Root Cause
In `_execute_parallel_branches`:
1.  It creates `ParallelBranch` objects for the *immediate edges*.
2.  It runs `execute_single_branch`, which executes **one node**.
3.  It returns the result of that single node execution.
4.  The main `execute` loop then sets `current_node_id = fan_in_node` (lines 494-496), bypassing any intermediate nodes in the branches.

## Proposed Solution
The `execute_single_branch` function needs to be a mini-executor that continues executing its branch until:
1.  It reaches the `fan_in_node` (convergence point), OR
2.  It reaches a terminal node.

ref: `core/framework/graph/executor.py`

```python
        async def execute_single_branch(branch: ParallelBranch) -> ...:
            current = branch.node_id
            while current != fan_in_node:
                # Execute node...
                # Check next edge...
                # Update current...
```

## Impact
*   **Critical Correctness**: Multi-step parallel workflows are silently broken (steps skipped).
*   **Feature Parity**: Prevents complex map-reduce style agent patterns.
