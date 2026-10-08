"""``hive-browser`` — the CLI that replaces the ``browser_*`` MCP tools.

An argparse noun/verb tree following the CRM CLI standard (``framework/crm/cli.py``):
a shared ``common`` parent parser gives every leaf ``--json`` and ``--profile``;
each leaf sets ``func`` (an async ``cmd_*`` handler) via ``set_defaults``; the
``gcu.errors.run`` harness stands up a client-mode bridge around dispatch, prints
the result (JSON with ``--json``, else a terse table), and maps it to an exit code.

Run:  ``python -m gcu.cli <cmd> ... --json``   (or the ``hive-browser`` console script)
Identity (which agent's tab group) comes from ``HIVE_BROWSER_SESSION`` env, stamped
by the runtime into the terminal subprocess — see ``gcu/browser/identity.py``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from gcu import errors
from gcu.browser import identity


def _setup_cli_logging() -> None:
    """Keep the agent's stderr clean on error paths (audit B9).

    The CLI is a short-lived asyncio process. When ``RemoteBridge``'s 2s health
    poller races ``bridge.stop()`` at exit, an orphaned RPC future gets a
    ``BridgeClientError`` set on it that nobody awaits, and asyncio's default
    reporter dumps that traceback to stderr. Because the CLI configures no
    logging, Python's ``lastResort`` handler emits every WARNING+ (including that
    asyncio ERROR) to stderr. Attaching ANY handler to root bypasses
    ``lastResort``; we also pin down the ``asyncio`` and ``gcu`` loggers. Nothing
    useful is lost — the actionable failure is already the JSON envelope on stdout
    plus the exit code. Set ``GCU_LOG_FILE`` to capture full diagnostics to a file.
    """
    root = logging.getLogger()
    log_file = os.environ.get("GCU_LOG_FILE")
    if log_file:
        level_name = os.environ.get("GCU_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        if not isinstance(level, int):
            level = logging.INFO
        already = any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(log_file) for h in root.handlers)
        if not already:
            fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
            root.addHandler(fh)
            if root.level == logging.NOTSET or root.level > level:
                root.setLevel(level)
    elif not root.handlers:
        # No file sink → drop propagated records (this bypasses lastResort's stderr).
        root.addHandler(logging.NullHandler())
    # Silence the two noisy sources regardless of sink: asyncio's unretrieved-future
    # ERROR and gcu.* teardown WARNINGs are not agent-actionable.
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    logging.getLogger("gcu").setLevel(logging.ERROR)


_WAIT_UNTIL = ["commit", "domcontentloaded", "load", "networkidle"]
_INTERACT_ACTIONS = [
    "left_click",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "hover",
    "type",
    "key",
    "scroll",
    "drag",
    "screenshot",
    "zoom",
    "wait",
]
_SNAPSHOT_MODES = ["default", "simple", "interactive"]
_AUTO_SNAPSHOT_MODES = ["simple", "default", "interactive", "off"]


def _floats(expected: int):
    """argparse ``type`` for a comma-separated fraction list, e.g. "0.3,0.6"."""

    def parse(value: str) -> list[float]:
        try:
            parts = [float(p) for p in value.split(",")]
        except ValueError as e:
            raise argparse.ArgumentTypeError(f"expected {expected} comma-separated numbers, got {value!r}") from e
        if len(parts) != expected:
            raise argparse.ArgumentTypeError(f"expected {expected} comma-separated numbers, got {len(parts)}")
        return parts

    return parse


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine output (agent mode)")
    # Debug override for HIVE_BROWSER_SESSION (identity normally comes from the
    # env the runtime stamps). Hidden from per-command help so it doesn't drown
    # out the command-specific flags; still fully functional.
    common.add_argument("--profile", metavar="<session>", help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(
        prog="hive-browser",
        parents=[common],
        description="Drive the Hive browser (Beeline extension) from the terminal. "
        "Replaces the browser_* MCP tools; agents invoke it via terminal_exec with --json.",
    )
    cmds = p.add_subparsers(dest="cmd", required=True)

    def leaf(name, help_, *, always_json=False):
        sp = cmds.add_parser(name, parents=[common], help=help_)
        if always_json:
            sp.set_defaults(always_json=True)
        return sp

    # help — first-class discovery command (CRM standard)
    sp = leaf("help", "usage for the CLI or a command: `hive-browser help [cmd]`")
    sp.add_argument("topic", nargs="?", help="a command to show help for")
    sp.set_defaults(func=_help)

    # ── lifecycle ────────────────────────────────────────────────────
    from gcu.cli_commands import lifecycle as lc

    leaf("setup", "check the extension/bridge and show install steps", always_json=True).set_defaults(func=lc.cmd_setup)
    sp = leaf("status", "connection + running state + connected Chrome profiles")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=lc.cmd_status)
    leaf("stop", "close this session's tab group (all its tabs)").set_defaults(func=lc.cmd_stop)

    # ── navigation / entry ───────────────────────────────────────────
    from gcu.cli_commands import nav

    sp = leaf("open", "open a tab at <url> (cold-start entry point)")
    sp.add_argument("url")
    sp.add_argument("--background", action="store_true")
    sp.add_argument("--browser-profile", dest="browser_profile", help="which connected Chrome profile to open in")
    sp.set_defaults(func=nav.cmd_open)

    sp = leaf("navigate", "redirect an existing tab to <url>")
    sp.add_argument("url")
    sp.add_argument("--tab", type=int)
    sp.add_argument("--wait-until", dest="wait_until", choices=_WAIT_UNTIL, default="load")
    sp.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=30000, help="how long to wait for the --wait-until condition (ms)")
    sp.add_argument("--browser-profile", dest="browser_profile")
    sp.set_defaults(func=nav.cmd_navigate)

    sp = leaf("reload", "reload the current page")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=nav.cmd_reload)

    # ── interaction ──────────────────────────────────────────────────
    from gcu.cli_commands import interact as it

    sp = leaf("interact", "click / type / key / scroll / drag / screenshot / zoom / wait")
    sp.add_argument("--action", required=True, choices=_INTERACT_ACTIONS)
    sp.add_argument("--tab", type=int)
    sp.add_argument("--selector")
    sp.add_argument("--coordinate", type=_floats(2), metavar="x,y", help="[x,y] viewport fractions 0..1")
    sp.add_argument("--start-selector", dest="start_selector")
    sp.add_argument("--start-coordinate", dest="start_coordinate", type=_floats(2), metavar="x,y")
    sp.add_argument("--text")
    sp.add_argument("--no-clear-first", dest="no_clear_first", action="store_true")
    sp.add_argument("--no-insert-text", dest="no_insert_text", action="store_true")
    sp.add_argument("--modifiers")
    sp.add_argument("--repeat", type=int, default=1)
    sp.add_argument("--scroll-direction", dest="scroll_direction", choices=["up", "down", "left", "right"], default="down")
    sp.add_argument("--scroll-amount", dest="scroll_amount", type=int, default=500)
    sp.add_argument("--intent")
    sp.add_argument("--full-page", dest="full_page", action="store_true")
    sp.add_argument("--no-annotate", dest="no_annotate", action="store_true")
    sp.add_argument("--region", type=_floats(4), metavar="x0,y0,x1,y1")
    sp.add_argument("--duration", type=float)
    sp.add_argument("--wait-for-selector", dest="wait_for_selector")
    sp.add_argument("--wait-for-text", dest="wait_for_text")
    sp.add_argument("--timeout-ms", dest="timeout_ms", type=int)
    sp.add_argument("--auto-snapshot-mode", dest="auto_snapshot_mode", choices=_AUTO_SNAPSHOT_MODES, default="simple")
    sp.add_argument("--wait-after-ms", dest="wait_after_ms", type=int, default=0)
    sp.set_defaults(func=it.cmd_interact)

    sp = leaf("select", "select option(s) in a <select> dropdown")
    sp.add_argument("selector")
    sp.add_argument("--value", action="append", required=True, help="option value (repeatable)")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=it.cmd_select)

    sp = leaf("upload", "set files on a file input (direct or via trigger)")
    sp.add_argument("selector")
    sp.add_argument("--file", action="append", required=True, help="file path (repeatable)")
    sp.add_argument("--trigger-selector", dest="trigger_selector")
    sp.add_argument("--tab", type=int)
    sp.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=30000)
    sp.set_defaults(func=it.cmd_upload)

    # ── capture / evaluate / script ──────────────────────────────────
    from gcu.cli_commands import capture, evaluate, script as script_cmd

    sp = leaf("screenshot", "capture the tab (JPEG spilled to a file, path returned)", always_json=True)
    sp.add_argument("--intent")
    sp.add_argument(
        "--full-page", dest="full_page", action="store_true", help="capture the document region (bounded; downscaled to 800px wide like the default)"
    )
    sp.add_argument("--selector")
    sp.add_argument("--no-annotate", dest="no_annotate", action="store_true")
    sp.add_argument(
        "--timeout-ms", dest="timeout_ms", type=int, default=5000, help="selector wait (ms) when --selector is given (polls like interact)"
    )
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=capture.cmd_screenshot)

    sp = leaf("evaluate", "run JavaScript in the page (value of last expression)")
    sp.add_argument("--js", metavar="SRC|@FILE|-", help="JS source: inline, @FILE (read from path), or - (stdin)")
    sp.add_argument("--script", dest="js", help="alias for --js")
    sp.add_argument("--tab", type=int)
    sp.epilog = (
        "Return semantics: a SINGLE expression is returned automatically (e.g.\n"
        "'document.title'). For MULTIPLE statements, wrap in an IIFE and `return`\n"
        "the value: '(()=>{ const n=[...document.links].length; return n; })()'.\n"
        "Bare multi-statement code without a return yields null; a top-level `throw`\n"
        "is a parse error (throw inside the IIFE instead).\n"
        "\n"
        "examples:\n"
        "  hive-browser evaluate --js 'document.title' --json\n"
        "  hive-browser evaluate --js @/tmp/probe.js --json   # quote-heavy JS: read from a file\n"
        "  echo 'location.href' | hive-browser evaluate --js - --json"
    )
    sp.formatter_class = argparse.RawDescriptionHelpFormatter
    sp.set_defaults(func=evaluate.cmd_evaluate)

    sp = leaf("script", "run a skill-bundled run(ctx) orchestration script")
    # Not required=True at the argparse level: cmd_script validates them and, when
    # --skill is missing, points the agent at `evaluate` for ad-hoc JS (a bare
    # argparse "required" error can't carry that hint).
    sp.add_argument("--skill", help="skill name or dir (e.g. hive.linkedin-core)")
    sp.add_argument("--script", help="a script under <skill>/scripts/ (the .py suffix is optional)")
    sp.add_argument("--args", dest="args_json", metavar="JSON|@file|-", help="ctx.args as JSON (inline, @file, or - for stdin)")
    sp.add_argument("--timeout-s", dest="timeout_s", type=float, default=60.0)
    sp.add_argument("--tab", type=int)
    sp.add_argument("--browser-profile", dest="browser_profile")
    sp.epilog = "example: hive-browser script --skill hive.linkedin-core --script lk_get_identity --args '{}' --json"
    sp.set_defaults(func=script_cmd.cmd_script)

    # ── tab (noun) ───────────────────────────────────────────────────
    from gcu.cli_commands import tab as tab_cmd

    tab_p = cmds.add_parser("tab", parents=[common], help="tab-group management: list / close / activate")
    tab_v = tab_p.add_subparsers(dest="verb", required=True)
    tab_v.add_parser("list", parents=[common], help="list tabs in this session's group").set_defaults(func=tab_cmd.cmd_tab_list)
    sp = tab_v.add_parser("close", parents=[common], help="close a tab (default: active)")
    sp.add_argument("tab_id", nargs="?", type=int)
    sp.set_defaults(func=tab_cmd.cmd_tab_close)
    sp = tab_v.add_parser("activate", parents=[common], help="bring a tab to the foreground")
    sp.add_argument("tab_id", type=int)
    sp.set_defaults(func=tab_cmd.cmd_tab_activate)

    # ── page (noun) ──────────────────────────────────────────────────
    from gcu.cli_commands import page

    page_p = cmds.add_parser("page", parents=[common], help="page reads + viewport: html / snapshot / text / shadow-query / console / resize")
    page_v = page_p.add_subparsers(dest="verb", required=True)

    # Selector is a positional across all `page` reads for one consistent
    # convention (optional on html — omit for the whole page).
    sp = page_v.add_parser("html", parents=[common], help="page or element outerHTML (spilled to a file)")
    sp.add_argument("selector", nargs="?", help="CSS selector (omit for the whole page)")
    sp.add_argument("--head", type=int, metavar="N", help="also return the first N chars of the payload inline")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=page.cmd_page_html, always_json=True)

    sp = page_v.add_parser("snapshot", parents=[common], help="accessibility tree (spilled to a file)")
    sp.add_argument("--mode", choices=_SNAPSHOT_MODES, default="default")
    sp.add_argument("--head", type=int, metavar="N", help="also return the first N chars of the tree inline")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=page.cmd_page_snapshot, always_json=True)

    sp = page_v.add_parser("text", parents=[common], help="text content of an element")
    sp.add_argument("selector")
    sp.add_argument("--tab", type=int)
    # 5s (not 30s): on a missing selector bridge.get_text waits the full timeout
    # before returning "Element not found", which looked frozen and tripped
    # terminal_exec's 30s auto-background. 5s gives fast miss-feedback.
    sp.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=5000)
    sp.set_defaults(func=page.cmd_page_text)

    sp = page_v.add_parser("shadow-query", parents=[common], help="element rect as viewport fractions (pierces shadow DOM with ' >>> ')")
    sp.add_argument("selector")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=page.cmd_page_shadow_query)

    sp = page_v.add_parser("console", parents=[common], help="console messages (stub — use `evaluate`)")
    sp.add_argument("--level")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=page.cmd_page_console)

    sp = page_v.add_parser("resize", parents=[common], help="resize the viewport")
    sp.add_argument("--width", type=int, required=True)
    sp.add_argument("--height", type=int, required=True)
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=page.cmd_page_resize)

    # ── dialog (noun) ────────────────────────────────────────────────
    from gcu.cli_commands import dialog

    dialog_p = cmds.add_parser("dialog", parents=[common], help="native dialogs: respond")
    dialog_v = dialog_p.add_subparsers(dest="verb", required=True)
    sp = dialog_v.add_parser("respond", parents=[common], help="accept/dismiss a pending native dialog")
    sp.add_argument("action", choices=["accept", "dismiss"])
    sp.add_argument("--prompt-text", dest="prompt_text")
    sp.add_argument("--tab", type=int)
    sp.set_defaults(func=dialog.cmd_dialog_respond)

    return p


def _help(args: argparse.Namespace) -> Any:
    """``hive-browser help [topic]`` — usage for the whole CLI or one command."""
    parser = _build_parser()
    topic = getattr(args, "topic", None)
    target: argparse.ArgumentParser | None = parser
    if topic:
        target = None
        for action in parser._subparsers._group_actions:  # noqa: SLF001
            if topic in action.choices:
                target = action.choices[topic]
                break
        if target is None:
            raise errors.validation(f"no such command {topic!r} — run `hive-browser help` for the full list")
    text = target.format_help()
    return {"topic": topic or "hive-browser", "help": text} if getattr(args, "json", False) else text


def _render(result: Any) -> None:
    """Minimal human output (v1). Agents use --json."""
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        rows = result["items"]
        if not rows:
            print("(no results)")
            return
        cols = list(rows[0].keys())
        print(" | ".join(cols))
        for r in rows:
            print(" | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
    elif isinstance(result, dict):
        for k, v in result.items():
            print(f"{k}: {v}")
    else:
        print(result)


def _force_utf8_lf() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", newline="")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> None:
    _force_utf8_lf()
    _setup_cli_logging()
    args = _build_parser().parse_args(argv)
    identity.apply_env_identity(args)
    as_json = bool(args.json) or getattr(args, "always_json", False)

    # `help` is pure local text — no bridge needed. Everything else dispatches
    # through the bridge-bootstrapping harness.
    if getattr(args, "func", None) is _help:
        result = _help(args)
        if as_json:
            import json

            print(json.dumps(result, indent=2, default=str))
        else:
            _render(result)
        return

    errors.run(lambda: args.func(args), as_json=as_json, render=_render)


if __name__ == "__main__":
    main()
