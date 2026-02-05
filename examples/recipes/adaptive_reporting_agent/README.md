# Adaptive Reporting Agent

This example demonstrates Hive’s failure → adaptation → retry loop using a simple reporting workflow.

## Goal
Generate a short report from input data.  
If required data is missing or invalid, the agent fails, captures the error, adapts its behavior, and retries successfully.

## What This Example Shows
- Goal-driven agent definition
- Intentional first-run failure
- Automatic failure capture
- Agent adaptation
- Successful retry

## How It Works
1. The agent is given a reporting goal.
2. On the first run, required input data is missing or malformed.
3. The framework records the failure.
4. The agent adapts its execution strategy.
5. The agent retries and completes the task successfully.

## Why This Matters
Real-world business workflows often fail due to incomplete or bad data.  
Hive enables agents to recover and adapt automatically instead of requiring manual fixes.
