# Code Quality Improvements and Security Hardening

This PR addresses multiple code quality issues identified through static analysis and security scanning.

## Summary

- Fix deprecated `datetime.utcnow()` usage (Python 3.12+ deprecation)
- Correct import paths in demo files
- Add `hvac` as optional dependency for HashiCorp Vault
- Improve type safety with None checks
- Follow PEP 484 conventions for abstract methods
- Add security annotations for sandboxed code execution

## Changes

### 1. Deprecated API Fix
**File:** `core/framework/credentials/aden/client.py`
- Replace `datetime.utcnow()` with `datetime.now(UTC)`
- Python 3.12+ deprecates `utcnow()` in favor of timezone-aware datetimes

### 2. Import Path Corrections
**Files:** `core/demos/*.py`
- Fix `core.framework.credentials` → `framework.credentials`
- Imports now resolve correctly with the path setup
- Auto-formatted to comply with isort rules

### 3. GraphSpec API Fix
**File:** `core/demos/github_outreach_demo.py`
- Replace undeclared `name` parameter with `description`
- Uses the actual declared field in `GraphSpec`

### 4. Optional Dependency
**File:** `core/pyproject.toml`
- Add `hvac>=2.0.0` as optional dependency under `[vault]`
- Install with: `pip install framework[vault]`

### 5. Abstract Method Conventions
**Files:** `core/framework/credentials/storage.py`, `core/framework/credentials/provider.py`
- Replace `pass` with `...` (ellipsis) in abstract methods
- Follows PEP 484 type annotation conventions

### 6. Type Safety Improvements
**File:** `core/framework/credentials/tests/test_credential_store.py`
- Add `assert cred is not None` before accessing `.get_key()`
- Prevents type checker warnings about potentially None values

### 7. Security Annotations
**File:** `core/framework/graph/code_sandbox.py`
- Add `# nosec B102` for intentional `exec()` usage
- Add `# nosec B307` for intentional `eval()` usage
- Both are in sandboxed environment with restricted builtins, timeouts, and memory limits

## Security Scan Results

### Bandit Security Scanner
```
Run metrics:
  Total lines of code: 33,083
  Total issues (by severity):
    High: 0
    Medium: 0 (2 acknowledged with nosec)
    Low: 313 (informational - subprocess usage, etc.)

  Files skipped: 0
  Issues skipped via nosec: 2
```

The 2 Medium severity issues were for `exec()` and `eval()` usage in the code sandbox. These are:
- **Intentional**: The sandbox is designed to execute dynamic code
- **Mitigated**: Restricted builtins whitelist, timeout enforcement, memory limits, namespace isolation
- **Documented**: Security measures are documented in the module docstring

### Low Severity Findings (Informational)
Low severity findings are primarily:
- Subprocess calls (expected for tool execution)
- Assert statements in tests
- Try-except-pass patterns in cleanup code

These are acceptable patterns for this codebase.

## Testing

```bash
# All tests pass
$ cd core && uv run pytest tests/ -v
================ 683 passed, 51 skipped, 228 warnings in 19.49s ================

# Linter passes
$ uv run ruff check .
All checks passed!
```

## Test Plan

- [x] Run `uv run pytest tests/` - All 683 tests pass
- [x] Run `uv run ruff check .` - No linting errors
- [x] Run `uv run bandit -r core/framework -ll` - No High/Medium issues
- [x] Verify demo files import correctly
- [x] Verify credential store functionality unchanged

## Notes for Reviewers

1. **Strix Security Scanner**: Could not run due to Docker daemon connectivity issues. Used Bandit as alternative.
2. **Low severity findings**: Not addressed as they are acceptable patterns (subprocess, assertions, cleanup handlers)
3. **Breaking changes**: None - all changes are backward compatible

---

🤖 Generated with [Claude Code](https://claude.ai/code)
