"""``hive-browser script`` — mirror of the ``browser_script`` MCP tool.

Both call the shared :func:`gcu.browser.tools.script.run_browser_script`, so a
skill's ``async def run(ctx)`` script runs identically whether the agent reached
it via the tool or this CLI command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gcu.errors import validation


def read_arg_value(raw: str | None) -> str | None:
    """Resolve an inline value, ``@file`` (read from path), or ``-`` (stdin).

    Used by ``--args`` / ``--js`` so large / quote-heavy payloads never have to
    survive the shell on argv.
    """
    if raw is None:
        return None
    if raw == "-":
        return sys.stdin.read()
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            raise validation(f"could not read {path}: {e}") from e
    return raw


async def cmd_script(args: argparse.Namespace) -> dict:
    from gcu.browser.tools.script import run_browser_script

    if not args.skill:
        raise validation("--skill is required (scripts are scoped to a skill dir). For ad-hoc JavaScript, use: hive-browser evaluate --js '<code>'")
    if not args.script:
        raise validation("--script is required (a script file under <skill>/scripts/)")

    if args.browser_profile:
        from gcu.browser.bridge import get_bridge
        from gcu.cli_commands.nav import validate_browser_profile

        await validate_browser_profile(get_bridge(), args.browser_profile)

    args_raw = read_arg_value(getattr(args, "args_json", None))
    parsed_args: dict = {}
    if args_raw:
        try:
            parsed_args = json.loads(args_raw)
        except json.JSONDecodeError as e:
            raise validation(f"--args must be valid JSON: {e}") from e
        if not isinstance(parsed_args, dict):
            raise validation("--args must be a JSON object (dict)")

    return await run_browser_script(
        skill=args.skill,
        script=args.script,
        args=parsed_args,
        timeout_s=args.timeout_s,
        tab_id=args.tab,
        profile=args.profile,
        profile_display_name=args._display_name,
        browser_profile=args.browser_profile,
    )
