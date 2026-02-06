# 🚀 Release v0.4.0

**79 commits since v0.3.2** | **Target: `main` @ `80a41b4`**

---

## ✨ Highlights

This is a major release introducing the **Event Loop Node architecture**, an **interactive TUI dashboard**, **ClientIO gateway** for client-facing agents, a **GitHub tool**, **Slack tool integration** (45+ tools), and a full **migration from pip to uv** for package management.

---

## 🆕 Features

### 🔄 Event Loop Node Architecture
- Implement event loop node framework (WP1-4, WP8, WP9, WP10, WP12) — a new node type that supports iterative, multi-turn execution with tool calls, judge-based acceptance, and client-facing interaction
- Emit bus events for runtime observability
- Add graph validation for client-facing nodes
- Soft-fail on schema mismatch during context handoff (no more hard failures)

### 🖥️ Interactive TUI Dashboard
- Add interactive TUI dashboard for agent execution with 3-pane layout (logs/graph + chat)
- Implement selectable logging, interactive ChatREPL, and thread-safe event handling
- Screenshot feature, header polish, keybinding updates
- Lazy widget loading, Horizontal/Vertical layout fixes
- Integrate agent builder with TUI

### 💬 ClientIO Gateway
- Implement ClientIO gateway for client-facing node I/O routing
- Client-facing nodes can now request and receive user input at runtime

### 🐙 GitHub Tool
- Add GitHub tool for repository and issue management
- Security and integration fixes from PR feedback

### 💼 Slack Tool Integration
- Add Slack bot integration with 45+ tools for multipurpose integration
- Includes CRM support capabilities

### 🔑 Credential Store
- Provider-based credential store (`aden provider credential store by provider`)
- Support non-OAuth key setup in credential workflows
- Quickstart credential store integration

### 📦 Migration to uv
- Migrate from pip to uv for package management
- Consolidate workspace to uv monorepo
- Migrate all CI jobs from pip to uv
- Check for litellm import in both `CORE_PYTHON` and `TOOLS_PYTHON` environments

### 🛠️ Other Features
- Tool truncation for handling large tool outputs
- Inject runtime datetime into LLM system prompts
- Add sample agent folder structure and examples
- Add message when LLM key is not available
- Edit bot prompt to decide on technical size of issues
- Update skills and agent builder tools; bump pinned ruff version

---

## 🐛 Bug Fixes

- **ON_FAILURE edge routing**: Follow ON_FAILURE edges when a node fails after max retries
- **Malformed JSON tool arguments**: Handle malformed JSON tool arguments safely in LiteLLMProvider
- **Quickstart compatibility**: Fix quickstart.sh compatibility and provider selection issues
- **Silent exit fix**: Resolve silent exit when selecting non-Anthropic LLM provider
- **Robust compaction logic**: Fix conversation compaction edge cases
- **Loop prevention**: Prevent infinite loops in feedback edges
- **Tool pruning logic**: Fix incorrect tool pruning behavior
- **Text delta granularity**: Fix text delta granularity and tool limit problems
- **Tool call results**: Fix formulation of tool call results
- **Max retry reset**: Reset max retry counter to 0 for event loop nodes
- **Graph validation**: Fix graph validation logic
- **MCP exports directory**: Handle missing exports directory in test generation tools
- **Bash version support**: Fix bash version compatibility

---

## 🏗️ Chores & CI

- Consolidate workspace to uv monorepo
- Migrate remaining CI jobs from pip to uv
- Clean up use of `setup-python` in CI
- Windows lint fixes
- Various lint and formatting fixes
- Update `.gitignore` and remove local claude settings
- Update issue templates

---

## 📖 Documentation

- Add Windows compatibility warning
- Update architecture diagram source path in README

---

## 👏 Contributors

Thanks to all contributors for this release:

- **@mubarakar95** — Interactive TUI dashboard (3-pane layout, ChatREPL, selectable logging, screenshot feature, lazy widget loading)
- **@levxn** — Slack bot integration with 45+ tools including CRM support
- **@lakshitaa-chellaramani** — GitHub tool for repository and issue management
- **@Acid-OP** — ON_FAILURE edge routing fix after max retries
- **@Siddharth2624** — Malformed JSON tool argument handling in LiteLLMProvider
- **@Antiarin** — Runtime datetime injection into LLM system prompts
- **@kuldeepgaur02** — Fix silent exit when selecting non-Anthropic LLM provider
- **@Anjali Yadav** — Fix missing exports directory in MCP test generation tools
- **@Hundao** — Migrate remaining CI jobs from pip to uv
- **@ranjithkumar9343** — Windows compatibility warning documentation
- **@Yogesh Sakharam Diwate** — Architecture diagram path update in README
