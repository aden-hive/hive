"""``hive-browser`` command handlers — one module per noun/group.

Each handler is ``async def cmd_<name>(args) -> dict`` and returns the same
``{"ok": bool, ...}`` envelope the corresponding ``browser_*`` MCP tool returned;
the ``gcu.errors.run`` harness prints it and maps it to an exit code. Handlers
reuse the existing helpers in ``gcu.browser.tools.*`` so there is one source of
truth for the browser orchestration (rate limits, context creation, screenshot
rendering, …) shared with the MCP tools during the transition.
"""
