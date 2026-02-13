# 🐝 Hive Dev Loop: Enterprise Autonomous TDD Agent

**Hive Dev Loop** is a specialized autonomous agent designed to execute the **Test-Driven Development (TDD)** lifecycle without human intervention. Unlike standard coding assistants that merely output snippets, this agent plans, tests, implements, verifies, and debugs its own code in a closed execution loop.

##  Why This Agent is Better

Standard LLM agents often hallucinate code that looks correct but fails to run. **Hive Dev Loop** solves this by enforcing a strict **Verification Loop**:

1.  **Self-Correction Protocol:** If tests fail, the agent automatically transitions to a `debugger` node, analyzes the error logs, patches the code, and re-runs the tests. It does not stop until the code passes or max retries are reached.
2.  **TDD Enforcement:** It is architecturally constrained to write tests *before* implementation, ensuring high-quality, testable code by design.
3.  **Clean State Isolation:** Every run occurs in a sandboxed workspace (`.hive/agents/hive_dev_loop/workspace`), preventing pollution of your main project files.

## Hive Framework Integration

This agent demonstrates the full power of the **Hive Agent Framework** by utilizing:

### 1. Graph-Based State Machine (`GraphSpec`)
Instead of a linear chain, the agent is defined as a directed graph with conditional edges:
* **Conditional Routing:** The edge from `run_pytest` splits based on the execution result:
    * `if test_status == 'FAIL'` → Go to **Debugger**.
    * `if test_status == 'PASS'` → Go to **Report**.
* **Cyclic Execution:** The graph allows looping back from `debugger` to `write_code`, enabling iterative refinement.



### 2. Professional Tool Registry
It leverages the Hive `ToolRegistry` to inject secure, Python-native tools directly into the LLM's context:
* `write_to_file`: For creating implementation and test files.
* `execute_command_tool`: For running the `pytest` harness in a controlled subprocess.
* `view_file`: For inspecting code during debugging sessions.

### 3. Production-Ready Configuration (`RuntimeConfig`)
The agent uses Hive's smart configuration system (`framework.config`), allowing it to seamlessly load API keys from the environment for secure, enterprise-grade deployment using **Anthropic Claude 3.5 Sonnet**.

##  Prerequisites & Setup

Before running the agent, you must set your API key. Choose your platform below:

### 🐧 Linux / macOS
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
export LITELLM_MODEL=anthropic/claude-3-5-sonnet-20240620
```
### Windows (PowerShell)
- $env:ANTHROPIC_API_KEY="sk-ant-api03-..."
- $env:LITELLM_MODEL="anthropic/claude-3-5-sonnet-20240620"
### Windows (Command Prompt / cmd)
- set ANTHROPIC_API_KEY=sk-ant-api03-...
- set LITELLM_MODEL=anthropic/claude-3-5-sonnet-20240620
