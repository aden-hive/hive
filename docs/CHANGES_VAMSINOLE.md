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

## Summary table

| Type | Description | Files |
|------|-------------|-------|
| micro-fix | print → logger for runner warnings | `core/framework/runner/runner.py` |
| docs | OpenRouter & Hive LLM setup | `docs/llm_providers.md`, `docs/configuration.md`, `docs/developer-guide.md`, `docs/environment-setup.md`, `README.md` |
| feat | `hive --version` / `hive -V` | `core/framework/cli.py` |
