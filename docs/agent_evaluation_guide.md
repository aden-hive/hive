# Agent Evaluation Guide

This document outlines a simple framework for evaluating Hive agents in production environments.

## Key Metrics

- Task success rate
- End-to-end latency
- Node execution latency
- Retry counts
- Failure categories
- Human-in-the-loop intervention frequency
- Tool-call correctness
- Cost per workflow execution

## Why Evaluation Matters

AI agent systems operate probabilistically and interact with external tools and APIs. Evaluating reliability and performance across workflows is critical before deploying agents in production.

## Suggested Failure Categories

- External API timeout
- Authentication failure
- Invalid tool input
- LLM output parsing failure
- Dependency failure
- Rate limiting
- Non-retryable logic error
