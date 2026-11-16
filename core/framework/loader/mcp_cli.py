"""Reach an MCP server from the terminal instead of the tool list, through mcp2cli.

A server in CLI mode (``hive mcp add --as-cli``, ``hive mcp mode <name> cli``)
is never loaded into an agent's tools, whose schemas would ride along on
every model call (ComfyUI's 39 tools are about 15,600 tokens). The agent gets
one line per server in its prompt (:func:`cli_servers_prompt`) and runs it
with ``terminal_exec``::

    hive mcp run comfy --list
    hive mcp run comfy run-workflow --help
    hive mcp run comfy run-workflow --workflow-path wf.json --wait

``hive mcp run`` reads the server's connection from the registry and hands it
to mcp2cli, which turns the server's tools into subcommands. Env vars and
headers travel in the server's environment, never on a command line.

mcp2cli is Stephan Fitzpatrick's (https://github.com/knowsuchagency/mcp2cli,
MIT license), a dependency of Hive; this module only feeds it the registry's
connection details.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
import subprocess
import sys

from framework.loader.mcp_client import MCPServerConfig
from framework.loader.mcp_errors import MCPError, MCPErrorCode

logger = logging.getLogger(__name__)


def mcp2cli_invocation(config: MCPServerConfig) -> tuple[list[str], dict[str, str], str | None]:
    """The mcp2cli flags that name ``config``'s server, the env they need,
    and the directory to run in.

    Raises:
        MCPError: for a unix-socket server, which mcp2cli can't reach.
    """
    env: dict[str, str] = {}
    match config.transport:
        case "stdio":
            command = [config.command or "", *config.args]
            # mcp2cli splits this back with the platform's own rules.
            joined = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
            argv = ["--mcp-stdio", joined]
            env.update(config.env)
            return [*argv, *_cache_key(argv, env)], env, config.cwd
        case "http" | "sse":
            # "http" lets mcp2cli negotiate: streamable HTTP, else SSE. (Hive's
            # own http client posts JSON-RPC to <url>/mcp/v1 instead.)
            argv = ["--mcp", config.url or ""]
            if config.transport == "sse":
                argv += ["--transport", "sse"]
            for i, (header, value) in enumerate(config.headers.items()):
                var = f"HIVE_MCP_HEADER_{i}"
                env[var] = value
                argv += ["--auth-header", f"{header}:env:{var}"]
            return [*argv, *_cache_key(argv, env)], env, None
        case _:
            raise MCPError(
                code=MCPErrorCode.MCP_PROTOCOL_MISMATCH,
                what=f"Cannot run '{config.name}' from the terminal",
                why=f"mcp2cli can't reach a server over the {config.transport} transport.",
                fix=f"Run: hive mcp mode {config.name} tools  — to load its tools instead.",
            )


def _cache_key(argv: list[str], env: dict[str, str]) -> list[str]:
    """mcp2cli caches a server's tool list under a key derived from its
    flags, which can't see values passed in the environment; fold those in
    (hashed, so no secret lands on disk) so a changed env refetches."""
    digest = hashlib.sha256(json.dumps([argv, sorted(env.items())]).encode()).hexdigest()[:16]
    return ["--cache-key", f"hive-{digest}"]


def run(config: MCPServerConfig, args: list[str]) -> int:
    """Run mcp2cli against ``config``'s server with ``args`` (a subcommand
    and its flags, or ``--list``); returns its exit code. Output goes
    straight to this process's stdout and stderr.

    mcp2cli runs in this process, not a child one: a new interpreter started
    from a uv-made virtualenv on Windows gets uv's ``PYTHONHOME`` back, and
    the server it starts would inherit it (see framework.utils.python_env).
    The environment, working directory and ``sys.argv`` it needs are restored
    afterwards.
    """
    import mcp2cli

    from framework.config import HIVE_HOME

    source, env, cwd = mcp2cli_invocation(config)
    saved_environ, saved_argv, saved_cwd = dict(os.environ), sys.argv, os.getcwd()
    os.environ.update(env)
    # Keep mcp2cli's tool-list cache and usage stats with the rest of Hive's state.
    os.environ.setdefault("MCP2CLI_CACHE_DIR", str(HIVE_HOME / "cache" / "mcp2cli"))
    sys.argv = ["mcp2cli", *source, *(args or ["--list"])]
    try:
        if cwd:
            os.chdir(cwd)
        mcp2cli.main()
    except SystemExit as exc:
        if exc.code is None or isinstance(exc.code, int):
            return exc.code or 0
        print(exc.code, file=sys.stderr)
        return 1
    finally:
        os.chdir(saved_cwd)
        sys.argv = saved_argv
        os.environ.clear()
        os.environ.update(saved_environ)
    return 0


def cli_servers_prompt(servers: list[dict]) -> str:
    """The prompt block that tells an agent which servers it runs from the
    terminal (``MCPRegistry.cli_servers()``); ``""`` when there are none."""
    if not servers:
        return ""
    lines = ["Command-line MCP servers (run them with terminal_exec; their tools are not in your tool list):"]
    for server in servers:
        count = server.get("tool_count")
        detail = f" ({count} commands)" if count else ""
        description = server.get("description") or "no description"
        lines.append(f"- {server['name']}: {description}{detail}")
    lines.append(
        "List a server's commands with `hive mcp run <server> --list` (add `--search <word>` to filter), "
        "read one's flags with `hive mcp run <server> <command> --help`, then run "
        "`hive mcp run <server> <command> --flag value`. Add `--json` before the command for the full "
        "result envelope. Use absolute paths in flags: the server may run in another directory."
    )
    return "\n".join(lines)


def registry_cli_servers_prompt() -> str:
    """:func:`cli_servers_prompt` for the servers in Hive's MCP registry; ``""``
    when the registry can't be read, so a broken registry never blocks a session."""
    from framework.loader.mcp_registry import MCPRegistry

    try:
        registry = MCPRegistry()
        registry.initialize()
        return cli_servers_prompt(registry.cli_servers())
    except Exception:  # noqa: BLE001 - the block is optional
        logger.warning("Could not list command-line MCP servers", exc_info=True)
        return ""
