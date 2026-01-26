# PR Title: Security Hardening: DoS Prevention & Sandbox Escape Fixes

## Description
This PR addresses critical security vulnerabilities in the `CodeSandbox` component, specifically targeting Denial of Service (DoS) attacks on Windows and sandbox escape vectors.

## Key Changes
- **Windows DoS Prevention**: Implemented a `multiprocessing`-based execution model for Windows. This allows the parent process to strictly enforce timeouts and terminate the child process if it hangs (e.g., infinite loops), solving the previous limitation where threads could not be forcibly killed.
- **Unix Memory Limits**: Activated memory limit enforcement on Unix systems using the `resource` module. This prevents sandboxed code from exhausting system memory.
- **Sandbox Escape Hardening**: Enhanced `CodeValidator` to block access to dangerous attributes such as `__subclasses__`, `__bases__`, `__mro__`, `__globals__`, `__code__`, `__closure__`, `__func__`, `__self__`, `__module__`, `__dict__`, and `__class__`. This significantly reduces the attack surface for sandbox escapes.
- **Usability Fix**: Added `print` to `SAFE_BUILTINS` to allow legitimate use of print statements without triggering `NameError`.

## Testing
- Verified that infinite loops on Windows are now correctly terminated after the timeout.
- Verified that accessing blocked attributes raises a `SecurityError`.
- Verified that legitimate code (including `print`) continues to function correctly.

## Related Issues
- Fixes potential DoS vulnerability on Windows.
- Fixes missing memory limits on Unix.
- Fixes sandbox escape vulnerabilities.
