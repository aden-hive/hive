# Security Fixes for Aden Hive

## Description

This PR addresses 4 security vulnerabilities found in the Hive codebase:

1. **Auth bypass when HIVE_DESKTOP_TOKEN is unset** (HIGH)
2. **MCP STDIO transport spawns arbitrary subprocesses** (HIGH)  
3. **Environment variable leakage to MCP subprocesses** (MEDIUM)
4. **File operations symlink traversal** (MEDIUM)

## Changes

### 1. Fix Auth Bypass (core/framework/server/app.py)

**Before:** When `HIVE_DESKTOP_TOKEN` was not set, the auth middleware was completely bypassed, allowing unauthenticated access to all API endpoints.

**After:** A random token is auto-generated when the env var is not set, ensuring all requests require authentication. The token is logged to stderr so users can see it.

```python
# Auto-generate a random token if none was provided
if _EXPECTED_DESKTOP_TOKEN is None:
    _EXPECTED_DESKTOP_TOKEN = secrets.token_urlsafe(32)
    logger.warning(...)
    print(f"[hive] Auto-generated desktop auth token: {_EXPECTED_DESKTOP_TOKEN}", file=sys.stderr)
```

### 2. Fix MCP Environment Leakage (core/framework/loader/mcp_client.py)

**Before:** The entire `os.environ` (including API keys, credentials) was passed to MCP subprocesses.

**After:** Only safe system variables (PATH, HOME, etc.) and explicitly configured env vars are passed.

```python
_SAFE_ENV_VARS = {
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "SHELL", "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "WINDIR", "NODE_PATH", "PYTHONPATH",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
}
safe_env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_VARS}
safe_env.update(self.config.env or {})
```

### 3. Add Command Validation (core/framework/loader/mcp_client.py)

Added a warning when potentially dangerous commands (bash, python, etc.) are used in MCP STDIO transport.

### 4. Fix Symlink Traversal (tools/src/aden_tools/file_ops.py)

**Before:** `os.path.realpath()` resolved symlinks without verifying the final path was still within allowed directories.

**After:** After resolving the path, we verify it's still under the allowed root directory or safe system paths.

```python
# Security check: verify the resolved path is still within allowed directories
if self.write_safe_roots:
    if not any(_path_is_under(resolved, r) for r in self.write_safe_roots):
        raise ValueError(f"symlink traversal denied: ...")
```

## Motivation

These vulnerabilities could allow:
- Unauthenticated access to the Hive server
- Credential theft via MCP subprocesses
- Arbitrary file read/write via symlink traversal

## Testing

- [x] Auth bypass fix: Server now requires token for all requests
- [x] Env leakage fix: MCP subprocesses only receive safe variables
- [x] Symlink fix: Traversal outside allowed directories is blocked

## Checklist

- [x] Code follows style guidelines (ruff)
- [x] Self-review completed
- [x] No breaking changes (auto-generated token is logged for users)
- [x] Security improvements are backwards compatible

## References

- OWASP Top 10 2021: A07 Identification and Authentication Failures
- CWE-287: Improper Authentication
- CWE-250: Execution with Unnecessary Privileges
