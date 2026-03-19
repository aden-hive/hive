# Changes (vamsinole branch)

Summary of all changes made on the `vamsinole` branch for the Aden Hive contribution.

---

## 1. micro-fix: Replace print with logger for runner warning messages

**File:** `core/framework/runner/runner.py`

**Problem:** Warning messages for missing credentials were emitted via `print()`, bypassing the logging system. This made it harder to filter, redirect, or integrate with log aggregation.

**Change:** Replaced four `print()` calls with `logger.warning()`:

| Location | Before | After |
|----------|--------|-------|
| Claude Code token missing | `print("Warning: ...")` | `logger.warning("Claude Code subscription configured but no token found. Run 'claude' to authenticate, then try again.")` |
| Codex token missing | `print("Warning: ...")` | `logger.warning("Codex subscription configured but no token found. Run 'codex' to authenticate, then try again.")` |
| Kimi Code key missing | `print("Warning: ...")` | `logger.warning("Kimi Code subscription configured but no key found. Run 'kimi /login' to authenticate, then try again.")` |
| API key env var not set | `print(f"Warning: {api_key_env} not set...")` | `logger.warning("%s not set. LLM calls will fail. export %s=your-api-key", api_key_env, api_key_env)` |

**Impact:** Warnings now flow through the standard logging pipeline and can be controlled via log level and handlers.

---

## 2. docs: Add OpenRouter and Hive LLM provider setup (closes #6634)

**Files changed:**
- `docs/llm_providers.md` (new)
- `docs/configuration.md`
- `docs/developer-guide.md`
- `docs/environment-setup.md`
- `README.md`

**Problem:** OpenRouter and Hive LLM were supported in quickstart and runtime but not documented. Users could configure them interactively but had no written guidance.

**Change:**

### New: `docs/llm_providers.md`
- **OpenRouter:** Setup steps, env var (`OPENROUTER_API_KEY`), API base, model format, example config, privacy/guardrail note
- **Hive LLM:** Setup steps, env var (`HIVE_API_KEY`), model names (queen, kimi-2.5, GLM-5), example config
- Switching providers via re-running quickstart

### Updated docs
- **configuration.md:** Added `OPENROUTER_API_KEY` and `HIVE_API_KEY` to env vars list; link to `llm_providers.md`
- **developer-guide.md:** Added OpenRouter and Hive LLM to API keys section; link to `llm_providers.md`
- **environment-setup.md:** Mention OpenRouter and Hive LLM in quickstart description; link to `llm_providers.md`
- **README.md:** Tip for setting `OPENROUTER_API_KEY` or `HIVE_API_KEY` before quickstart; link to `llm_providers.md`

---

## 3. feat: Add `hive --version` / `hive -V` CLI flag

**File:** `core/framework/cli.py`

**Problem:** No way to check the installed Hive/framework version from the CLI.

**Change:**
- Added `--version` and `-V` arguments to the main parser
- Version is read from package metadata (`importlib.metadata.version("framework")`) with fallback to `0.7.1`
- Usage: `hive --version` or `hive -V` → prints `hive 0.7.1` (or current version)

---

## 4. feat: Add `hive doctor` environment diagnostics

**File:** `core/framework/runner/cli.py`

**Problem:** No quick way to diagnose setup issues. Users hitting "API key not found" or config errors had to dig through docs and source.

**Change:**
- New `hive doctor` command that checks:
  - Config file exists and is valid JSON
  - LLM provider and model are configured
  - API key presence (env var, Claude Code, Codex, Kimi, credential store)
  - Optional `--verify` to ping the LLM API (reuses `scripts/check_llm_key.py`)
- `--json` flag for machine-readable output (e.g. CI, scripting)
- Exit code 1 when issues found, 0 when all checks pass

**Usage:**
```bash
hive doctor              # Human-readable report
hive doctor --verify     # Also ping LLM API to confirm key works
hive doctor --json       # JSON output for scripting
```

**Impact:** Faster debugging for onboarding and support. Similar to `brew doctor` / `flutter doctor`.

---

## 5. feat: Stack Overflow integration (agent capability)

**Files:** `tools/src/aden_tools/tools/stack_overflow_tool/`

**Problem:** Agents had no way to look up coding solutions, error fixes, or technical Q&A from Stack Overflow.

**Change:**
- New integration with Stack Exchange API (no API key required, 10k req/day)
- Two tools:
  - `stack_overflow_search` — search questions by query, returns titles, excerpts, links, scores, answer counts
  - `stack_overflow_get_answers` — fetch top answers for a question by ID (accepted first, then by votes)
- Supports stackoverflow, serverfault, superuser, askubuntu
- Registered in verified tools (available to all agents by default)

**Use cases:**
- Coding agents: look up solutions for errors, best practices, library usage
- Support agents: find answers to technical questions
- Research agents: gather community knowledge on a topic

**Example:**
```python
# In agent config: tools = ["stack_overflow_search", "stack_overflow_get_answers", ...]
# Agent can call: stack_overflow_search(query="python asyncio timeout")
# Then: stack_overflow_get_answers(question_id=12345)
```

---

## Summary table

| Type | Description | Files |
|------|-------------|-------|
| micro-fix | print → logger for runner warnings | `core/framework/runner/runner.py` |
| docs | OpenRouter & Hive LLM setup | `docs/llm_providers.md`, `docs/configuration.md`, `docs/developer-guide.md`, `docs/environment-setup.md`, `README.md` |
| feat | `hive --version` / `hive -V` | `core/framework/cli.py` |
| feat | `hive doctor` environment diagnostics | `core/framework/runner/cli.py` |
| feat | Stack Overflow integration | `tools/src/aden_tools/tools/stack_overflow_tool/` |
