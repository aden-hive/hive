"""
Stress Test for Aden Hive Framework
------------------------------------
Tests the graph executor with:
1. Large graphs (many nodes)
2. Concurrent execution
3. Deep chains
4. Wide branches
5. Memory stress
"""

import asyncio
import time
import tracemalloc
from pathlib import Path
from typing import Dict, Any

from framework.graph import Goal, NodeSpec, EdgeSpec, GraphSpec, EdgeCondition
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime


# Test functions
def passthrough(data: str) -> str:
    """Simple passthrough function."""
    return data

def compute_heavy(n: int) -> int:
    """CPU-intensive computation."""
    result = 0
    for i in range(n * 1000):
        result += i * i
    return result

def concat(*args) -> str:
    """Concatenate all string args."""
    return " ".join(str(a) for a in args)


async def test_large_chain(num_nodes: int = 50):
    """Test a chain of many sequential nodes."""
    print(f"\n{'='*60}")
    print(f"TEST: Large Chain ({num_nodes} nodes)")
    print('='*60)
    
    start = time.time()
    
    goal = Goal(
        id="chain-test",
        name="Chain Test",
        description=f"Execute {num_nodes} nodes in sequence",
        success_criteria=[{"id": "done", "description": "Complete chain", "metric": "custom", "target": "any"}]
    )
    
    # Create nodes
    nodes = []
    for i in range(num_nodes):
        nodes.append(NodeSpec(
            id=f"node_{i}",
            name=f"Node {i}",
            description=f"Node {i} in chain",
            node_type="function",
            function=f"node_{i}",
            input_keys=["data"] if i > 0 else ["input"],
            output_keys=["data"]
        ))
    
    # Create edges
    edges = []
    for i in range(num_nodes - 1):
        edges.append(EdgeSpec(
            id=f"edge_{i}",
            source=f"node_{i}",
            target=f"node_{i+1}",
            condition=EdgeCondition.ON_SUCCESS
        ))
    
    graph = GraphSpec(
        id="chain-graph",
        goal_id="chain-test",
        entry_node="node_0",
        terminal_nodes=[f"node_{num_nodes-1}"],
        nodes=nodes,
        edges=edges,
    )
    
    runtime = Runtime(storage_path=Path("./stress_test_logs"))
    executor = GraphExecutor(runtime=runtime)
    
    # Register all functions
    for i in range(num_nodes):
        executor.register_function(f"node_{i}", passthrough)
    
    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"input": "test_data"}
    )
    
    elapsed = time.time() - start
    
    print(f"✓ Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"✓ Path length: {len(result.path)}")
    print(f"✓ Time: {elapsed:.3f}s")
    print(f"✓ Nodes/sec: {num_nodes/elapsed:.1f}")
    
    return result.success, elapsed


async def test_wide_branch(num_branches: int = 20):
    """Test a graph with many parallel branches."""
    print(f"\n{'='*60}")
    print(f"TEST: Wide Branch ({num_branches} branches)")
    print('='*60)
    
    start = time.time()
    
    goal = Goal(
        id="branch-test",
        name="Branch Test",
        description=f"Execute {num_branches} parallel branches",
        success_criteria=[{"id": "done", "description": "Complete all branches", "metric": "custom", "target": "any"}]
    )
    
    # Create nodes: 1 entry -> num_branches parallel -> each branch has 3 nodes
    nodes = [
        NodeSpec(
            id="entry",
            name="Entry Node",
            description="Entry point",
            node_type="function",
            function="entry",
            input_keys=["input"],
            output_keys=["data"]
        )
    ]
    
    edges = []
    terminal_nodes = []
    
    for b in range(num_branches):
        for depth in range(3):
            node_id = f"branch_{b}_node_{depth}"
            nodes.append(NodeSpec(
                id=node_id,
                name=f"Branch {b} Node {depth}",
                description=f"Branch {b} depth {depth}",
                node_type="function",
                function=node_id,
                input_keys=["data"],
                output_keys=["data"]
            ))
            
            if depth == 0:
                edges.append(EdgeSpec(
                    id=f"entry_to_branch_{b}",
                    source="entry",
                    target=node_id,
                    condition=EdgeCondition.ON_SUCCESS
                ))
            else:
                edges.append(EdgeSpec(
                    id=f"branch_{b}_edge_{depth}",
                    source=f"branch_{b}_node_{depth-1}",
                    target=node_id,
                    condition=EdgeCondition.ON_SUCCESS
                ))
        
        terminal_nodes.append(f"branch_{b}_node_2")
    
    graph = GraphSpec(
        id="branch-graph",
        goal_id="branch-test",
        entry_node="entry",
        terminal_nodes=terminal_nodes,
        nodes=nodes,
        edges=edges,
    )
    
    runtime = Runtime(storage_path=Path("./stress_test_logs"))
    executor = GraphExecutor(runtime=runtime)
    
    # Register functions
    executor.register_function("entry", passthrough)
    for b in range(num_branches):
        for depth in range(3):
            executor.register_function(f"branch_{b}_node_{depth}", passthrough)
    
    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"input": "test_data"}
    )
    
    elapsed = time.time() - start
    
    print(f"✓ Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"✓ Time: {elapsed:.3f}s")
    print(f"✓ Total nodes: {len(nodes)}")
    
    return result.success, elapsed


async def test_memory_stress():
    """Test memory usage with large data passing."""
    print(f"\n{'='*60}")
    print("TEST: Memory Stress")
    print('='*60)
    
    tracemalloc.start()
    start_memory = tracemalloc.get_traced_memory()[0]
    
    def generate_data(size: int) -> str:
        return "x" * size
    
    def process_data(data: str) -> str:
        return data.upper()
    
    goal = Goal(
        id="memory-test",
        name="Memory Test",
        description="Process large data",
        success_criteria=[{"id": "done", "description": "Complete", "metric": "custom", "target": "any"}]
    )
    
    nodes = [
        NodeSpec(id="generate", name="Generate", description="Generate data",
                 node_type="function", function="generate", input_keys=["size"], output_keys=["data"]),
        NodeSpec(id="process", name="Process", description="Process data",
                 node_type="function", function="process", input_keys=["data"], output_keys=["result"])
    ]
    
    edges = [EdgeSpec(id="e1", source="generate", target="process", condition=EdgeCondition.ON_SUCCESS)]
    
    graph = GraphSpec(
        id="memory-graph",
        goal_id="memory-test",
        entry_node="generate",
        terminal_nodes=["process"],
        nodes=nodes,
        edges=edges,
    )
    
    runtime = Runtime(storage_path=Path("./stress_test_logs"))
    executor = GraphExecutor(runtime=runtime)
    executor.register_function("generate", generate_data)
    executor.register_function("process", process_data)
    
    # Test with 1MB data
    result = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"size": 1024 * 1024}  # 1MB
    )
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    print(f"✓ Result: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"✓ Memory used: {(current - start_memory) / 1024 / 1024:.2f} MB")
    print(f"✓ Peak memory: {peak / 1024 / 1024:.2f} MB")
    
    return result.success


async def test_rapid_execution(iterations: int = 100):
    """Test rapid repeated execution."""
    print(f"\n{'='*60}")
    print(f"TEST: Rapid Execution ({iterations} iterations)")
    print('='*60)
    
    goal = Goal(
        id="rapid-test",
        name="Rapid Test",
        description="Quick execution",
        success_criteria=[{"id": "done", "description": "Complete", "metric": "custom", "target": "any"}]
    )
    
    nodes = [
        NodeSpec(id="quick", name="Quick", description="Quick node",
                 node_type="function", function="quick", input_keys=["n"], output_keys=["result"])
    ]
    
    graph = GraphSpec(
        id="rapid-graph",
        goal_id="rapid-test",
        entry_node="quick",
        terminal_nodes=["quick"],
        nodes=nodes,
        edges=[],
    )
    
    runtime = Runtime(storage_path=Path("./stress_test_logs"))
    executor = GraphExecutor(runtime=runtime)
    executor.register_function("quick", lambda n: n * 2)
    
    start = time.time()
    successes = 0
    
    for i in range(iterations):
        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"n": i}
        )
        if result.success:
            successes += 1
    
    elapsed = time.time() - start
    
    print(f"✓ Successes: {successes}/{iterations}")
    print(f"✓ Time: {elapsed:.3f}s")
    print(f"✓ Executions/sec: {iterations/elapsed:.1f}")
    
    return successes == iterations


async def main():
    """Run all stress tests."""
    print("=" * 60)
    print("ADEN HIVE FRAMEWORK - STRESS TEST SUITE")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Large Chain
    try:
        success, elapsed = await test_large_chain(50)
        results["large_chain"] = {"success": success, "time": elapsed}
    except Exception as e:
        print(f"❌ Large chain test failed: {e}")
        results["large_chain"] = {"success": False, "error": str(e)}
    
    # Test 2: Wide Branch
    try:
        success, elapsed = await test_wide_branch(10)
        results["wide_branch"] = {"success": success, "time": elapsed}
    except Exception as e:
        print(f"❌ Wide branch test failed: {e}")
        results["wide_branch"] = {"success": False, "error": str(e)}
    
    # Test 3: Memory Stress
    try:
        success = await test_memory_stress()
        results["memory_stress"] = {"success": success}
    except Exception as e:
        print(f"❌ Memory stress test failed: {e}")
        results["memory_stress"] = {"success": False, "error": str(e)}
    
    # Test 4: Rapid Execution
    try:
        success = await test_rapid_execution(50)
        results["rapid_execution"] = {"success": success}
    except Exception as e:
        print(f"❌ Rapid execution test failed: {e}")
        results["rapid_execution"] = {"success": False, "error": str(e)}
    
    # Summary
    print("\n" + "=" * 60)
    print("STRESS TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for r in results.values() if r.get("success"))
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result.get("success") else "❌ FAIL"
        extra = f" ({result.get('time', 0):.3f}s)" if "time" in result else ""
        print(f"  {name}: {status}{extra}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    asyncio.run(main())
