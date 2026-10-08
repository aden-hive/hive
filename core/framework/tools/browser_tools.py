"""In-process browser discovery tool — ``browser_setup``.

The browser is driven from the terminal via the ``hive-browser`` CLI (which
replaced the ``browser_*`` MCP tools). But the runtime can only observe tool
NAMES, not opaque ``terminal_exec`` subprocess calls — so, exactly like
``crm_summary`` mirrors ``hive-crm``, this one in-process tool keeps the browser
capability discoverable and gate-able:

* Its name starts with ``browser_``, so ``framework.skills.tool_gating`` still
  pre-activates the foundational ``browser-automation`` skill whenever it's
  present (zero gating change from the MCP era).
* Its return teaches the agent the CLI surface and the golden rule: drive the
  browser with ``terminal_exec`` running ``hive-browser <command> ... --json``.

It is read-only, so both queens and workers may hold it.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.llm.provider import Tool
from framework.loader.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

_BROWSER_SETUP_DESC = (
    "Get everything you need to drive the web browser. The browser is controlled "
    "from the terminal via the `hive-browser` CLI — run its commands with "
    "terminal_exec, ALWAYS with `--json`. Call this first before any browser work: "
    "it returns the command surface and how to check the extension connection. "
    "Then run `hive-browser setup --json` in the terminal to confirm the Hive "
    "browser extension is connected (it returns the Chrome Web Store install steps "
    "if not) and to list the connected Chrome profiles."
)

# The command surface, kept in sync with gcu/cli.py. Static so this tool stays
# decoupled from the tools package (the runtime need not import gcu).
_COMMANDS: dict[str, str] = {
    "setup": "check the extension/bridge, list connected Chrome profiles, show install steps",
    "status": "connection + running state for your tab group",
    "open <url>": "open a tab (cold-start entry point); --browser-profile <label> targets a Chrome account",
    "navigate <url>": "redirect an existing tab (--tab, --wait-until)",
    "reload": "reload the current page",
    "interact --action <a>": "click/type/key/scroll/drag/screenshot/zoom/wait (--selector or --coordinate x,y as 0..1 fractions)",
    "select <sel> --value V": "choose option(s) in a <select>",
    "upload <sel> --file P": "set files on a file input (--trigger-selector for native pickers)",
    "screenshot --intent <p>": "capture the tab; the JPEG is saved and auto-attached to your session",
    "evaluate --js <src|@file|->": "run JavaScript in the page (value of last expression)",
    "script --skill S --script F.py --args '{...}'": "run a skill-bundled run(ctx) orchestration script",
    "tab list|close|activate": "manage tabs in your group",
    "page html|snapshot|text|shadow-query|console|resize": "page reads + viewport (large reads spill to a file path)",
    "dialog respond accept|dismiss": "resolve a pending native dialog",
}


def _make_browser_setup_executor():
    async def execute(inputs: dict) -> dict[str, Any]:  # noqa: ARG001 - no inputs
        return {
            "ok": True,
            "cli": "hive-browser",
            "how": (
                "Drive the browser by running `hive-browser <command> ... --json` in the "
                "terminal via terminal_exec. Always pass --json. Fallback if the console "
                "script isn't found: `uv run --project tools python -m gcu.cli <command> ... --json`."
            ),
            "first_step": "Run `hive-browser setup --json` to verify the extension is connected and list Chrome profiles.",
            "commands": _COMMANDS,
            "coordinates": "click/hover/key coordinates are FRACTIONS of the viewport (0..1), not pixels.",
            "screenshots": (
                "`hive-browser screenshot` (and `interact --action screenshot`) save a JPEG and "
                "return a `saved_to` file path. The framework attaches the image to your NEXT turn "
                "automatically — so do NOT also attach_file it. If you don't see the image inline, "
                "read the `saved_to` path (the Read/file tool renders images) as a fallback."
            ),
            "exit_codes": "0 ok · 2 not_connected · 3 not_started · 4 not_found · 6 bad_args · 7 pending_dialog · 8 rate_limited.",
        }

    return execute


def build_browser_tools() -> list[tuple[Tool, Any]]:
    """Build the (Tool, executor) pairs for the in-process browser tools."""
    return [
        (
            Tool(
                name="browser_setup",
                description=_BROWSER_SETUP_DESC,
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                concurrency_safe=True,
            ),
            _make_browser_setup_executor(),
        ),
    ]


def _wrap_async_executor(async_executor):
    def executor(inputs: dict) -> Any:
        return async_executor(inputs)

    return executor


def register_browser_tools(registry: ToolRegistry, *, role: str = "queen") -> None:
    """Register the in-process browser discovery tool on ``registry``.

    Idempotent. ``browser_setup`` is read-only, so ``role`` (``"queen"`` |
    ``"worker"``) selects the same set — the parameter mirrors
    ``register_crm_tools`` for symmetry.
    """
    if role not in ("queen", "worker"):
        raise ValueError(f"role must be 'queen' or 'worker', got {role!r}")
    registered: list[str] = []
    for tool, async_executor in build_browser_tools():
        registry.register(tool.name, tool, _wrap_async_executor(async_executor))
        registered.append(tool.name)
    logger.debug("Registered browser tools (role=%s): %s", role, registered)
