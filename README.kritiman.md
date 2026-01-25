You can update your README to reflect the **current implementation of `FunctionNode`** while keeping it formal and precise. Since your class no longer uses `eval()` directly but may handle arbitrary expressions, the README should focus on **safe alternatives and developer guidance**. Here's a clean, updated version in Markdown:

````markdown
# 🔒 Issue : Unsafe `eval()` in node.py and edge.py 

## Overview

The Hive AI agent framework previously used Python's built-in `eval()` function in:

**File:** `hive/core/framework/graph/node.py`  
**Method:** `FunctionNode.execute`

```python
result = eval(expression)
````

This allowed evaluating dynamically generated expressions from user input or external sources. Although `FunctionNode` now executes deterministic Python functions via `self.func`, any future usage of user-provided expressions may still pose a risk.

## Problem

Directly evaluating untrusted input introduces a **critical security vulnerability**, allowing:

* Arbitrary code execution
* Manipulation of runtime context
* Potential system compromise

## Risk

* **Code injection** via malicious expressions
* **Unauthorized access** to memory or system resources
* **Runtime instability** or denial-of-service attacks

## Recommendation

If `FunctionNode` or similar nodes need to execute user-provided expressions, use **secure expression evaluators** instead of `eval()`.

## Options

### 1. `ast.literal_eval` (Python built-in)

Safely evaluates Python literals (strings, numbers, tuples, lists, dicts, booleans, None). **Cannot execute arbitrary code.**

```python
import ast

result = ast.literal_eval(expression)
```

**Official Documentation:** [ast.literal_eval](https://docs.python.org/3/library/ast.html#ast.literal_eval)

### 2. Math expression parsers / safe evaluators

Libraries like `simpleeval` or `asteval` allow arithmetic and logical expressions safely. You can define allowed operators and functions.

**Example using `simpleeval`:**

```python
from simpleeval import simple_eval

result = simple_eval(expression)
```

## Action Items

1. Replace any `eval(expression)` calls with one of the secure alternatives
2. Restrict evaluated expressions strictly to arithmetic and safe literals
3. Add unit tests to ensure invalid or malicious expressions fail safely
4. Document allowed syntax and usage for developers and agent authors

## References

* [Python eval() Security Warning](https://docs.python.org/3/library/functions.html#eval)
* [Python ast.literal_eval()](https://docs.python.org/3/library/ast.html#ast.literal_eval)
* [simpleeval GitHub Repository](https://github.com/danthedeckie/simpleeval)
* [asteval Documentation](https://newville.github.io/asteval/)

```