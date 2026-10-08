"""Exit-code taxonomy + dispatch harness for the ``hive-browser`` CLI.

Mirrors ``framework/crm/errors.py`` (the CRM CLI standard) adapted for an
in-process, async browser driver. The browser ops still live in
``gcu.browser.tools.*`` and return their existing ``{"ok": bool, ...}`` dicts —
this module does NOT change that wire contract (the MCP tools return the same
shape). Instead the CLI harness:

* stands up a client-mode bridge around dispatch (the bridge_host is long-lived
  and shared; each CLI invocation is a disposable client, exactly like the old
  ``gcu`` MCP server in client mode), and
* classifies the op's result dict onto a stable exit code so agents can branch
  on the exit status without parsing stdout. ``--json`` re-emits the full result
  (which already carries ``ok``/``error``).

Agents invoke the CLI through ``terminal_exec`` and always pass ``--json``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

# Exit codes — the stable agent contract. 0-2 align with hive-crm / hive-global-db.
EXIT_OK = 0
EXIT_DOMAIN = 1
EXIT_NOT_CONNECTED = 2  # extension/bridge down → run `hive-browser setup`
EXIT_NOT_STARTED = 3  # no context for this session → run `hive-browser open <url>`
EXIT_NOT_FOUND = 4  # tab / element / selector not found
EXIT_AMBIGUOUS = 5  # selector multi-match, or multiple Chrome profiles, none chosen
EXIT_VALIDATION = 6  # bad args (missing --intent, malformed coordinate, privileged scheme)
EXIT_PENDING_DIALOG = 7  # native dialog blocks the page → run `hive-browser dialog respond`
EXIT_RATE_LIMITED = 8  # SocialRateLimiter blocked (LinkedIn/IG view cap)


class BrowserError(Exception):
    """A classified CLI failure carrying its exit code and JSON error body.

    Raised CLIENT-SIDE (arg validation in ``cli_commands`` before any bridge
    round-trip). Op-level failures are NOT exceptions — the ops return
    ``{"ok": False, ...}`` and :func:`classify_result` maps them.
    """

    def __init__(self, code: str, message: str, exit_code: int, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details

    def envelope(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        body.update(self.details)
        return {"ok": False, "error": body}


def validation(message: str, **details: Any) -> BrowserError:
    return BrowserError("validation", message, EXIT_VALIDATION, **details)


# Error-string fragments that pin a result to a specific exit code. The browser
# ops return free-text ``error`` strings (not structured codes), so we match the
# distinctive fragments the tool layer emits. Order matters — most specific first.
_NOT_STARTED_HINT = "Browser not started"
_NOT_FOUND_FRAGMENTS = ("no active tab", "no tab to close", "no tab", "not found", "no such tab")


def classify_result(result: Any) -> int:
    """Map an op's result dict onto a CLI exit code.

    A non-dict, or a dict without ``ok: False``, is success (0). Everything else
    is inspected for the browser-specific failure signatures.
    """
    if not isinstance(result, dict):
        return EXIT_OK
    if result.get("ok", True):
        return EXIT_OK

    # Native dialog blocking the page — the cross-command state the
    # `dialog respond` verb clears.
    if "pending_dialog" in result:
        return EXIT_PENDING_DIALOG

    error = str(result.get("error") or "")
    low = error.lower()

    # Social rate limiter (navigation to a throttled LinkedIn/IG profile).
    if error == "rate_limited" or result.get("error") == "rate_limited":
        return EXIT_RATE_LIMITED

    # Extension/bridge not connected. The tool layer sets connected=False and/or
    # emits the connection_error() help string.
    if result.get("connected") is False or "browser bridge" in low or "extension" in low and "connect" in low:
        return EXIT_NOT_CONNECTED

    if _NOT_STARTED_HINT.lower() in low:
        return EXIT_NOT_STARTED

    if any(frag in low for frag in _NOT_FOUND_FRAGMENTS):
        return EXIT_NOT_FOUND

    if "ambiguous" in low or "multiple" in low and "match" in low:
        return EXIT_AMBIGUOUS

    return EXIT_DOMAIN


async def _run_with_bridge(make_coro: Callable[[], Awaitable[Any]]) -> Any:
    """Stand up a client-mode bridge, run one op, tear the client down.

    Reproduces the client-mode bring-up the gcu MCP server did in its lifespan
    (``server.py:_lifespan``): ensure the long-lived ``bridge_host`` is running,
    connect a disposable ``RemoteBridge`` client (which announces our owner PID
    via ``client_hello`` so the RPC reaper doesn't drop a >30s call), and
    rehydrate the profile→tab-group index so this fresh process REUSES the
    agent's existing tab group instead of creating a blank one.
    """
    from gcu.bridge_host import ensure_bridge_host_running
    from gcu.browser.bridge import init_bridge
    from gcu.browser.tools.lifecycle import rehydrate_contexts

    # Idempotent + cheap when the host is already up (the normal case); the
    # first call after a cold host pays the detached-spawn wait.
    ensure_bridge_host_running()
    bridge = init_bridge(mode="client")
    try:
        try:
            await bridge.connect()
            await rehydrate_contexts(bridge)
        except Exception:
            # Non-fatal: the op itself re-checks bridge.is_connected and returns
            # a clean not_connected envelope, which we classify to exit 2.
            pass
        return await make_coro()
    finally:
        # Client mode: stop() closes only THIS client — the bridge_host, the
        # extension link, and open tabs all survive for the next invocation.
        try:
            await bridge.stop()
        except Exception:
            pass


def run(
    make_coro: Callable[[], Awaitable[Any]],
    *,
    as_json: bool,
    render: Callable[[Any], None],
) -> None:
    """Invoke one CLI command coroutine, print its result, and exit.

    Handlers stay pure — they return a result dict (or raise ``BrowserError``
    for local arg-validation failures); this harness owns all printing and the
    ``sys.exit`` so the exit code is the single machine contract.
    """
    try:
        result = asyncio.run(_run_with_bridge(make_coro))
    except BrowserError as e:
        if as_json:
            print(json.dumps(e.envelope(), indent=2, default=str))
        else:
            print(f"error: {e.message}", file=sys.stderr)
        sys.exit(e.exit_code)

    exit_code = classify_result(result)
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        render(result)
    if exit_code != EXIT_OK:
        sys.exit(exit_code)
