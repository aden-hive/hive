# Math Tool

A safe, deterministic arithmetic evaluator for agents.

## Description

This tool provides a safe way for agents to perform mathematical calculations. Unlike using an LLM to "guess" the answer to a math problem, this tool uses a strict Python abstract syntax tree (AST) evaluator to compute the exact result. It is sandboxed and does not allow execution of arbitrary code, imports, or external calls.

## Capabilities

Safely evaluates expressions containing:
- Integers and Floats
- Basic operators: `+`, `-`, `*`, `/`
- Exponents: `**`
- Parentheses for grouping: `( )`

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `expression` | str | Yes | - | The mathematical expression to evaluate (e.g., `(10 + 2) * 5`) |

## Error Handling

Returns error strings for various failure cases:
- `Error: Invalid syntax in expression` - Malformed math string
- `Error: Division by zero` - e.g., `1/0`
- `Error: Unsupported syntax: <type>` - Only arithmetic is allowed (no variables/functions)