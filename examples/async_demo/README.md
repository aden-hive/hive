# Async Benchmark Agent

This agent demonstrates the high-performance async architecture of the Hive framework.

## Features
- **Parallel Execution**: Runs 3 "heavy" research tasks concurrently.
- **Async I/O**: Simulates non-blocking network operations.
- **Throughput**: Demonstrates how async architecture handles multiple tool calls simultaneously.

## How to Run

1. Navigate to the root directory.
2. Run the demo script:

```bash
python examples/async_demo/run_demo.py
```

## Expected Behavior
You should see 3 "Starting research" logs almost simultaneously, and then 3 "Finished research" logs appearing after ~1 second, proving they ran in parallel instead of sequentially (which would take 3+ seconds).
