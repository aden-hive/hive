# Fixes and Optimizations

## Runtime error fixes applied

### 1. **`load_agent_export` (core/framework/runner/runner.py)**

**Problem:** Malformed or incomplete `agent.json` (or export dict) caused opaque `KeyError` or `TypeError` when required keys were missing (e.g. `edge_data["id"]`, `sc_data["description"]`).

**Fix:**
- Added `_require_key()` helper that raises `ValueError` with a clear message and context (e.g. `"missing required key 'id' in graph.edges[0]"`).
- Wrapped `json.loads()` in try/except so invalid JSON raises `ValueError` with an explicit message instead of `json.JSONDecodeError` propagating.
- Validated that root and nested values are dicts before building specs (e.g. `graph`, `goal`, each `nodes[i]`, `edges[i]`).
- Wrapped NodeSpec/EdgeSpec/SuccessCriterion/Constraint construction in try/except and re-raise with context (e.g. `"graph.nodes[2] has invalid node spec"`).

**Result:** Invalid exports now fail with actionable errors instead of raw KeyError/TypeError.

---

### 2. **`get_secure_path` (tools/src/aden_tools/tools/file_system_toolkits/security.py)**

**Problem:** On Windows, `os.path.commonpath([final_path, session_dir])` raises `ValueError` when the two paths are on different drives (e.g. `C:\` vs `D:\`). That was unhandled and could crash the process.

**Fix:**
- Wrapped `commonpath` in try/except.
- On `ValueError`, raise a clear `ValueError`: `"Path '...' is on a different drive or outside the session sandbox."`
- Normalized paths with `os.path.normpath()` before calling `commonpath` and before comparing, for consistent behavior across platforms.

**Result:** Cross-drive or invalid paths are rejected with a clear error instead of an uncaught exception.

---

## Tests added

- **core/tests/test_runner_load_export.py**  
  Covers:
  - Valid minimal export (dict and JSON string)
  - Invalid JSON → `ValueError` with message
  - Missing required edge key → `ValueError` with context
  - Missing required success_criterion key → `ValueError` with context
  - Non-dict root → `ValueError`

Run after setup:
```bash
./scripts/setup-python.sh   # installs pytest and deps
PYTHONPATH=core python -m pytest core/tests/test_runner_load_export.py -v
```

---

## Further optimization ideas

1. **Run full test suite**
   - After `./scripts/setup-python.sh`, run:  
     `PYTHONPATH=core:tools pytest core/tests tools/tests -v`  
   - Fix any remaining failures and flakiness.

2. **Agent export schema**
   - Consider validating the export with a Pydantic model or JSON Schema before building `GraphSpec`/`Goal`, so all structural errors are caught in one place with consistent messages.

3. **Security path normalization**
   - For Windows, consider resolving to a single canonical form (e.g. `pathlib.Path.resolve()`) so different representations of the same path are treated identically.

4. **MCP / runner config loading**
   - `runner.py` and MCP code already catch `Exception` when loading MCP config; consider logging with `logging.warning` (and optional stack trace) instead of only `print`, and validating config shape before use.

5. **Executor / runtime**
   - Ensure all async paths in the executor and stream runtime use `try/except` and log or re-raise with context so failures are debuggable and don’t leave runs in an inconsistent state.

6. **Dependencies and env**
   - Document and, if possible, pin minimal Python (e.g. 3.11+) and key deps (e.g. in `pyproject.toml`) to avoid “works on my machine” and reduce runtime errors from version skew.

7. **Type checking**
   - Run mypy (or your preferred checker) on `core` and `tools` and fix reported issues to catch type-related bugs early.

8. **CI**
   - Add a GitHub Actions (or similar) job that runs `setup-python.sh`, then the full test suite and lint/type checks, so these fixes and future changes stay green.
