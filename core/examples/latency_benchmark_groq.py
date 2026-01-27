"""
Latency Benchmark: Before/After Comparison with Groq API
---------------------------------------------------------
This script demonstrates the fix for the blocking LLM call issue.

It runs TWO scenarios:
1. AFTER (fixed): use_llm=False (default fast path) - ~0ms per call
2. BEFORE (old): use_llm=True with Groq API - ~500ms per call

To use:
1. Get a free API key from https://console.groq.com/keys
2. Run with:
    $env:GROQ_API_KEY="your-key-here"
    $env:PYTHONPATH="e:\\hive\\core"
    python e:\\hive\\core\\examples\\latency_benchmark_groq.py
"""

import asyncio
import json
import os
import time
from pathlib import Path

from framework.graph import EdgeCondition, EdgeSpec, Goal, GraphSpec, NodeSpec
from framework.graph.executor import GraphExecutor
from framework.graph.node import NodeResult
from framework.runtime.core import Runtime


# Global timing trackers
fast_path_times = []
llm_path_times = []


def timed_fast_summary(self, node_spec=None, use_llm=False):
    """Wrapper to time the fast path."""
    start = time.time()
    result = self._simple_summary()
    elapsed_ms = (time.time() - start) * 1000
    fast_path_times.append(elapsed_ms)
    print(f"    ⏱️  to_summary() fast path took {elapsed_ms:.2f}ms")
    return result


def groq_llm_summary(self, node_spec=None, use_llm=False):
    """
    Always uses Groq API to simulate the old blocking behavior.
    This is used in Scenario 2 to show BEFORE behavior.
    """
    if not self.success:
        return f"❌ Failed: {self.error}"

    if not self.output:
        return "✓ Completed (no output)"

    api_key = os.environ.get("GROQ_API_KEY")
    
    if not api_key:
        return self._simple_summary()

    try:
        from groq import Groq
        
        node_context = ""
        if node_spec:
            node_context = f"\nNode: {node_spec.name}\nPurpose: {node_spec.description}"

        output_json = json.dumps(self.output, indent=2, default=str)[:2000]
        prompt = (
            f"Generate a 1-2 sentence human-readable summary of "
            f"what this node produced.{node_context}\n\n"
            f"Node output:\n{output_json}\n\n"
            "Provide a concise, clear summary."
        )

        start = time.time()
        
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
        )
        
        elapsed_ms = (time.time() - start) * 1000
        llm_path_times.append(elapsed_ms)
        print(f"    ⏱️  to_summary() Groq API call took {elapsed_ms:.0f}ms")
        
        summary = response.choices[0].message.content.strip()
        return f"✓ {summary}"

    except Exception as e:
        print(f"    ⚠️  Groq API error: {e}")
        return self._simple_summary()


# Simple node functions
def step_one(input_data: str) -> str:
    return f"Step1: {input_data}"

def step_two(step1_output: str) -> str:
    return f"Step2: {step1_output}"

def step_three(step2_output: str) -> str:
    return f"Step3: {step2_output}"

def step_four(step3_output: str) -> str:
    return f"Step4: {step3_output}"

def step_five(step4_output: str) -> str:
    return f"Step5: {step4_output}"


def create_graph_and_executor():
    """Create a 5-node graph for benchmarking."""
    goal = Goal(
        id="benchmark-goal",
        name="Latency Benchmark",
        description="Measure blocking LLM call latency impact",
        success_criteria=[
            {"id": "complete", "description": "Complete", "metric": "custom", "target": "any"}
        ]
    )

    nodes = [
        NodeSpec(id="node1", name="Step 1", description="First step",
                 node_type="function", input_keys=["input_data"], output_keys=["step1_output"]),
        NodeSpec(id="node2", name="Step 2", description="Second step",
                 node_type="function", input_keys=["step1_output"], output_keys=["step2_output"]),
        NodeSpec(id="node3", name="Step 3", description="Third step",
                 node_type="function", input_keys=["step2_output"], output_keys=["step3_output"]),
        NodeSpec(id="node4", name="Step 4", description="Fourth step",
                 node_type="function", input_keys=["step3_output"], output_keys=["step4_output"]),
        NodeSpec(id="node5", name="Step 5", description="Fifth step",
                 node_type="function", input_keys=["step4_output"], output_keys=["final_output"]),
    ]

    edges = [
        EdgeSpec(id="e1", source="node1", target="node2", condition=EdgeCondition.ON_SUCCESS),
        EdgeSpec(id="e2", source="node2", target="node3", condition=EdgeCondition.ON_SUCCESS),
        EdgeSpec(id="e3", source="node3", target="node4", condition=EdgeCondition.ON_SUCCESS),
        EdgeSpec(id="e4", source="node4", target="node5", condition=EdgeCondition.ON_SUCCESS),
    ]

    graph = GraphSpec(
        id="benchmark-graph",
        goal_id="benchmark-goal",
        entry_node="node1",
        terminal_nodes=["node5"],
        nodes=nodes,
        edges=edges,
    )

    runtime = Runtime(storage_path=Path("./benchmark_logs"))
    executor = GraphExecutor(runtime=runtime)
    
    executor.register_function("node1", step_one)
    executor.register_function("node2", step_two)
    executor.register_function("node3", step_three)
    executor.register_function("node4", step_four)
    executor.register_function("node5", step_five)

    return graph, goal, executor


async def main():
    global fast_path_times, llm_path_times
    
    print("=" * 70)
    print("🔬 LATENCY BENCHMARK: Before/After Comparison")
    print("=" * 70)
    print()
    
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("⚠ GROQ_API_KEY not set!")
        print("  Get a free key at: https://console.groq.com/keys")
        print("  Then run with: $env:GROQ_API_KEY='your-key'")
        print()
        return

    print("✓ GROQ_API_KEY is set")
    print()

    # =========================================================================
    # SCENARIO 1: AFTER FIX (Fast Path - Default)
    # =========================================================================
    print("=" * 70)
    print("📗 SCENARIO 1: AFTER FIX (use_llm=False, default)")
    print("=" * 70)
    
    # Reset timings
    fast_path_times = []
    
    # Use the timed fast summary
    NodeResult.to_summary = timed_fast_summary
    
    graph, goal, executor = create_graph_and_executor()
    
    print()
    print("▶ Executing 5-node graph with FAST PATH...")
    print()
    
    start_after = time.time()
    result_after = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"input_data": "Hello World"}
    )
    elapsed_after = (time.time() - start_after) * 1000
    
    avg_fast = sum(fast_path_times) / len(fast_path_times) if fast_path_times else 0
    
    print()
    print(f"✓ Total time: {elapsed_after:.0f}ms")
    print(f"✓ Average to_summary(): {avg_fast:.2f}ms")
    print()

    # =========================================================================
    # SCENARIO 2: BEFORE FIX (LLM Path - Simulating Old Behavior)
    # =========================================================================
    print("=" * 70)
    print("📕 SCENARIO 2: BEFORE FIX (blocking LLM calls with Groq)")
    print("=" * 70)
    
    # Reset timings
    llm_path_times = []
    
    # Patch to ALWAYS use Groq LLM (simulating old blocking behavior)
    NodeResult.to_summary = groq_llm_summary
    
    # Need fresh executor
    graph, goal, executor = create_graph_and_executor()
    
    print()
    print("▶ Executing 5-node graph with LLM CALLS (old behavior)...")
    print()
    
    start_before = time.time()
    result_before = await executor.execute(
        graph=graph,
        goal=goal,
        input_data={"input_data": "Hello World"}
    )
    elapsed_before = (time.time() - start_before) * 1000
    
    avg_llm = sum(llm_path_times) / len(llm_path_times) if llm_path_times else 0

    print()
    print(f"✓ Total time: {elapsed_before:.0f}ms")
    print(f"✓ Average to_summary(): {avg_llm:.0f}ms")
    print()

    # =========================================================================
    # COMPARISON
    # =========================================================================
    print("=" * 70)
    print("📊 COMPARISON RESULTS")
    print("=" * 70)
    print()
    print(f"{'Metric':<30} {'AFTER (Fixed)':<20} {'BEFORE (Old)':<20}")
    print("-" * 70)
    print(f"{'Total wall-clock time':<30} {elapsed_after:.0f}ms{'':<15} {elapsed_before:.0f}ms")
    print(f"{'Avg to_summary() per call':<30} {avg_fast:.2f}ms{'':<14} {avg_llm:.0f}ms")
    print(f"{'Blocking event loop?':<30} {'No ✅':<20} {'Yes ❌':<20}")
    print()
    
    speedup = elapsed_before / elapsed_after if elapsed_after > 0 else float('inf')
    time_saved = elapsed_before - elapsed_after
    print(f"🚀 SPEEDUP: {speedup:.0f}x faster with the fix!")
    print(f"⏱️  TIME SAVED: {time_saved:.0f}ms per 5-node execution")
    print()
    print("=" * 70)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
