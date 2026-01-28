"""Structured CLI error handling with actionable guidance.

Provides user-friendly error messages with remediation hints,
inspired by the diagnostic-first approach of tools like rustc and cargo.

Usage:
    @cli_error_handler
    def cmd_run(args):
        ...

    # Or as context manager:
    with CLIErrorContext(verbose=True):
        ...

    # Or raise directly:
    raise CLIError("Agent schema key 'steps' not found",
                   hint="The agent graph uses 'nodes' instead of 'steps'.")
"""

from __future__ import annotations

import functools
import sys
import traceback
from collections.abc import Callable

# ---------------------------------------------------------------------------
# Core error type
# ---------------------------------------------------------------------------


class CLIError(Exception):
    """A CLI error that carries a user-facing message and optional remediation hint."""

    def __init__(self, message: str, hint: str = "", details: str = ""):
        self.message = message
        self.hint = hint
        self.details = details
        super().__init__(message)


# ---------------------------------------------------------------------------
# Error mapping registry
# ---------------------------------------------------------------------------

_ERROR_MAP: list[tuple[type, Callable[[Exception], CLIError | None]]] = []


def _register(exc_type: type):
    """Decorator to register an exception mapper."""

    def decorator(fn: Callable[[Exception], CLIError | None]):
        _ERROR_MAP.append((exc_type, fn))
        return fn

    return decorator


@_register(KeyError)
def _map_key_error(exc: KeyError) -> CLIError | None:
    key = exc.args[0] if exc.args else "unknown"
    known_renames = {
        "steps": ("nodes", "The agent graph uses 'nodes' instead of 'steps'."),
        "actions": ("nodes", "The agent graph uses 'nodes' instead of 'actions'."),
        "transitions": ("edges", "The agent graph uses 'edges' instead of 'transitions'."),
    }
    if key in known_renames:
        new_key, explanation = known_renames[key]
        return CLIError(
            f"Agent schema key '{key}' not found.",
            hint=(
                f"{explanation}\n"
                f"  This may indicate an outdated agent export. Try re-exporting, then run:\n"
                f"    hive validate <agent_path>"
            ),
        )
    return CLIError(
        f"Missing key: '{key}'",
        hint=(
            "This usually means the agent schema is missing a required field.\n"
            "  Run 'hive validate <agent_path>' to check for schema issues."
        ),
    )


@_register(FileNotFoundError)
def _map_file_not_found(exc: FileNotFoundError) -> CLIError:
    path = str(exc.filename or exc.args[0] if exc.args else "unknown")
    if "agent.json" in path:
        return CLIError(
            f"Agent not found at: {path}",
            hint=(
                "Verify the path points to a valid agent directory containing agent.json.\n"
                "  List available agents with:\n"
                "    hive list"
            ),
        )
    return CLIError(
        f"File not found: {path}",
        hint="Check that the path exists and you have read permissions.",
    )


@_register(ModuleNotFoundError)
def _map_module_not_found(exc: ModuleNotFoundError) -> CLIError:
    module = exc.name or str(exc)
    if module == "framework" or module.startswith("framework."):
        return CLIError(
            f"Cannot import '{module}'.",
            hint=(
                "The framework package is not on PYTHONPATH.\n"
                "  Run from project root with:\n"
                "    PYTHONPATH=core:exports python -m framework <command>\n"
                "  Or install in editable mode:\n"
                "    pip install -e core/"
            ),
        )
    return CLIError(
        f"Module '{module}' not found.",
        hint=(
            "A required Python package is missing. Install it with:\n"
            f"    pip install {module}\n"
            "  If this is an agent dependency, check the agent's requirements."
        ),
    )


@_register(PermissionError)
def _map_permission_error(exc: PermissionError) -> CLIError:
    return CLIError(
        f"Permission denied: {exc}",
        hint="Check file permissions or try running with appropriate privileges.",
    )


def _try_map_connection_error(exc: Exception) -> CLIError | None:
    """Handle connection-related errors from various HTTP libraries."""
    exc_type = type(exc).__qualname__
    exc_module = type(exc).__module__ or ""

    # httpx errors
    if "httpx" in exc_module or "ConnectError" in exc_type:
        return CLIError(
            "Cannot connect to the API endpoint.",
            hint=(
                "Check your network connection and API configuration.\n"
                "  Verify your API key is set:\n"
                "    export ANTHROPIC_API_KEY='sk-ant-...'\n"
                "  If using a proxy, check HTTPS_PROXY / HTTP_PROXY."
            ),
        )
    return None


def _try_map_auth_error(exc: Exception) -> CLIError | None:
    """Handle authentication errors from API clients."""
    exc_type = type(exc).__qualname__
    msg_lower = str(exc).lower()

    if "auth" in exc_type.lower() or "authentication" in msg_lower or "401" in str(exc):
        return CLIError(
            "API authentication failed.",
            hint=(
                "Your API key may be invalid or expired.\n"
                "  Set a valid key:\n"
                "    export ANTHROPIC_API_KEY='sk-ant-...'\n"
                "  Verify at: https://console.anthropic.com/settings/keys"
            ),
        )
    if "rate" in msg_lower and "limit" in msg_lower:
        return CLIError(
            "API rate limit exceeded.",
            hint=(
                "Wait a moment and try again, or use a different model:\n"
                "    hive run <agent> --model claude-haiku-4-5-20251001"
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


def format_error(error: CLIError, verbose: bool = False) -> str:
    """Format a CLIError for terminal output."""
    lines = [f"Error: {error.message}"]
    if error.hint:
        lines.append(f"  Hint: {error.hint}")
    if error.details:
        lines.append(f"  Details: {error.details}")
    if verbose and error.__cause__:
        lines.append("")
        lines.append("Traceback (use --verbose for full trace):")
        tb_line = traceback.format_exception_only(type(error.__cause__), error.__cause__)[-1]
        lines.append(tb_line.strip())
    return "\n".join(lines)


def _resolve_error(exc: Exception) -> CLIError:
    """Attempt to map a raw exception to a CLIError with actionable guidance."""
    # 1. Already a CLIError — pass through
    if isinstance(exc, CLIError):
        return exc

    # 2. Try registered mappers (exact type match first, then subclass)
    for exc_type, mapper in _ERROR_MAP:
        if isinstance(exc, exc_type):
            result = mapper(exc)
            if result is not None:
                return result

    # 3. Try heuristic mappers for network/auth errors
    for heuristic in (_try_map_connection_error, _try_map_auth_error):
        result = heuristic(exc)
        if result is not None:
            return result

    # 4. Fallback — generic error with traceback hint
    return CLIError(
        str(exc) or type(exc).__name__,
        hint=(
            "An unexpected error occurred.\n"
            "  Re-run with --verbose for the full traceback.\n"
            "  If the problem persists, report it at:\n"
            "    https://github.com/adenhq/hive/issues"
        ),
    )


# ---------------------------------------------------------------------------
# Decorator for CLI command functions
# ---------------------------------------------------------------------------


def cli_error_handler(fn: Callable) -> Callable:
    """Wrap a CLI command function with structured error handling.

    Catches unhandled exceptions and prints user-friendly diagnostics.
    The wrapped function should accept ``args`` (argparse.Namespace)
    and return an int exit code.
    """

    @functools.wraps(fn)
    def wrapper(args, *a, **kw):
        try:
            return fn(args, *a, **kw)
        except CLIError as e:
            verbose = getattr(args, "verbose", False)
            print(format_error(e, verbose=verbose), file=sys.stderr)
            if verbose:
                traceback.print_exc(file=sys.stderr)
            return 1
        except SystemExit:
            raise
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 130
        except Exception as e:
            verbose = getattr(args, "verbose", False)
            cli_err = _resolve_error(e)
            cli_err.__cause__ = e
            print(format_error(cli_err, verbose=verbose), file=sys.stderr)
            if verbose:
                traceback.print_exc(file=sys.stderr)
            return 1

    return wrapper


# ---------------------------------------------------------------------------
# Context manager variant
# ---------------------------------------------------------------------------


class CLIErrorContext:
    """Context manager that catches exceptions and prints structured diagnostics."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is None:
            return False
        if isinstance(exc_val, (SystemExit, KeyboardInterrupt)):
            return False

        cli_err = _resolve_error(exc_val)
        cli_err.__cause__ = exc_val
        print(format_error(cli_err, verbose=self.verbose), file=sys.stderr)
        if self.verbose:
            traceback.print_exception(exc_type, exc_val, exc_tb, file=sys.stderr)
        return True
