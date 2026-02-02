# Issue: "The First Five Minutes" - DX Friction in Example Agents

## Perspective: Product / Design / Manager

**Core Problem:** A new developer’s first interaction with "advanced" examples fails due to a disconnect between the core framework's evolution, missing dependencies, and a fragile tool registration system.

### The Friction Points
1. **Broken Contracts:** The core code was updated to a new configuration schema (`{"servers": [...]}`), but the example agent was left on the old schema. This caused a "Zero Tools Found" error that is confusing to a user who just wants to see the product work.
2. **Environment Assumptions:** The example hardcodes `python` instead of `python3`, failing on modern macOS/Linux setups.
3. **Brittle Pathing:** The use of relative paths (`../../tools`) for core dependencies means that if a user moves a folder or runs the agent from a different context, the agent "loses its brain."
4. **Dependency Cascading Failure:** The MCP server is a monolith. If a single optional tool (e.g., the new `email_tool`) has a missing dependency (`resend`, `playwright`), the **entire server crashes**. This blocks the user from using *any* tools, even basic ones like "Web Search."
5. **Incomplete Requirements:** New tools were merged into the main branch without updating the core `requirements.txt` files, leading to immediate `ModuleNotFoundError` for new users.
6. **Onboarding Interruption:** The setup scripts do not handle virtual environment (venv) creation automatically. This triggers IDE security warnings and leads to "Empty Environment" confusion.
7. **Broken Mock Mode (Mock != Disabled):** The implementation of `--mock` in example agents simply disables the LLM provider instead of providing a mock implementation. This causes nodes that require an LLM to fail immediately.
8. **Blind Retry on Fatal Errors:** The framework retries LLM calls 3 times even for fatal, non-recoverable errors (like `402 Payment Required`). This adds unnecessary latency and frustration.
9. **The "Success-Failure" Loop (Rigid Validation):** The framework enforces an arbitrary 10,000 character limit on node outputs. When an LLM produces a high-quality report exceeding this limit (e.g., 13,512 chars), the framework treats it as a "Fatal Error" and retries the expensive generation 3 times without telling the LLM to shorten its response. This "burns" user credits on guaranteed failures.
10. **Silent Tool Credential Gaps:** The agent started and executed Step 1 without checking if Step 2's required tools (Google/Brave Search) had valid credentials. This led to a "Hallucination of Success" where the agent tried to write a report based on empty search results.
11. **"All-or-Nothing" Loss of Work:** Because the framework halts execution on any validation failure, subsequent steps like "Save Report" are never reached. This means if an agent spends $0.50 on a great report but it's 100 characters too long, the user loses the data and the money.

### Why This Matters (PM POV)
* **High Bounce Rate:** If the "Deep Dive" examples don't work out of the box, developers lose trust.
* **Financial Waste:** Retrying a "too long" response 3 times is an expensive bug for the user.
* **Data Loss:** Users lose the output they paid for because a final "save" step was skipped.
* **Maintenance Burden:** Examples are documentation. When they fall out of sync, they become "mis-documentation."

### Proposed Solution
* **Fault-Tolerant Tool Loading:** Implement "Try-Except" blocks around tool registration to keep the server alive.
* **Intelligent Error Categorization:** Distinguish between transient (timeout) and fatal (billing/auth) errors. Only retry transient ones.
* **Feedback-Driven Retries:** If a node fails due to output length, the retry prompt should explicitly tell the LLM: *"Your previous response was too long, please summarize it."*
* **Pre-Flight Credential Validation:** Agents should check if required tool credentials exist *before* starting the first LLM node.
* **Soft Output Limits / Checkpointing:** Replace hard character crashes with warnings, or implement checkpointing that saves node outputs even if the full agent run fails.
