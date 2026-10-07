"""Harness tools: the framework's own tools, run in-process.

The terminal, file, chart, memory and core Hive tools used to ship as bundled
MCP servers, each a ``uv run python …_server.py --stdio`` subprocess the host
spawned at boot and spoke MCP to. They are the harness's own capabilities, so
they now run inside the host process instead: no subprocess, no MCP session.

Each bundled server name becomes a *harness group* of the same name. Allowlists,
``@server:<name>`` category references, the Tool Library and per-colony gating
all key off those names through ``ToolRegistry``'s server bookkeeping, so they
keep working unchanged. ``ToolRegistry.register_mcp_server`` routes a request
for a group name here rather than spawning anything.

The tool modules are still written against FastMCP's ``@mcp.tool()`` decorator.
:class:`_Collector` stands in for the FastMCP instance so they register
unchanged. The JSON schema, argument validation and calling convention are
rebuilt here with pydantic.

Only ``hive_tools`` shrinks. It now holds the subset of the old ``aden_tools``
suite that the default queen categories use. The ~850 third-party integrations
are no longer loaded; a user who wants one adds it as an external MCP server.
"""

from __future__ import annotations

import atexit
import inspect
import json
import logging
import threading
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

logger = logging.getLogger(__name__)

# group name -> description shown in the Tool Library.
HARNESS_GROUPS: dict[str, str] = {
    "terminal-tools": "Terminal: command execution, background jobs, PTY sessions, ripgrep/glob search",
    "files-tools": "File system: read, write, edit and search files",
    "chart-tools": "BI/financial chart + diagram rendering: ECharts, Mermaid",
    "memory-tools": "System memory: regex search across a queen/colony's messages",
    "hive_tools": "Core Hive tools: attachments, PDFs, web scraping, spreadsheets, image generation",
}
HARNESS_GROUP_NAMES: frozenset[str] = frozenset(HARNESS_GROUPS)

ScopeEnvGetter = Callable[[], Mapping[str, str]]


@dataclass
class HarnessTool:
    """One in-process tool: what the registry needs to expose and call it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    invoke: Callable[[dict[str, Any]], Any]
    # Parameter names the function accepts, so the registry injects only the
    # context params a tool actually declares (same rule as the MCP path).
    params: set[str] = field(default_factory=set)


class _Collector:
    """Stands in for FastMCP so ``register_*(mcp)`` functions run unchanged.

    Supports the decorator forms the tool modules use: ``@mcp.tool()``,
    ``@mcp.tool("name")`` and ``@mcp.tool(description=...)``.
    """

    def __init__(self) -> None:
        self.functions: list[tuple[str, str, Callable[..., Any]]] = []

    def tool(self, name_or_fn: Any = None, *, name: str | None = None, description: str | None = None, **_ignored: Any) -> Any:
        if callable(name_or_fn):
            self._add(name_or_fn, None, None)
            return name_or_fn
        tool_name = name if name is not None else name_or_fn

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._add(fn, tool_name, description)
            return fn

        return decorator

    def _add(self, fn: Callable[..., Any], name: str | None, description: str | None) -> None:
        self.functions.append((name or fn.__name__, description or inspect.getdoc(fn) or "", fn))


# ---------------------------------------------------------------------------
# Schema + invocation
# ---------------------------------------------------------------------------


def _resolve_annotations(fn: Callable[..., Any]) -> dict[str, Any]:
    """Evaluate *fn*'s (possibly stringified) annotations, keeping ``Annotated``."""
    try:
        return typing.get_type_hints(fn, include_extras=True)
    except Exception:
        # One unresolvable name shouldn't cost every parameter its type.
        hints: dict[str, Any] = {}
        for pname, ann in getattr(fn, "__annotations__", {}).items():
            if isinstance(ann, str):
                try:
                    ann = eval(ann, fn.__globals__)  # noqa: S307 - our own tool modules' annotations
                except Exception:
                    ann = Any
            hints[pname] = ann
        return hints


def _strip_titles(schema: Any) -> Any:
    """Drop pydantic's auto-generated ``title`` keywords; they are prompt noise.

    Only removes ``title`` as a schema keyword: the ``properties`` map is
    walked by value, so a parameter that is itself named ``title`` survives.
    """
    if isinstance(schema, list):
        return [_strip_titles(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title" and isinstance(value, str):
            continue
        if key in ("properties", "$defs") and isinstance(value, dict):
            out[key] = {k: _strip_titles(v) for k, v in value.items()}
        else:
            out[key] = _strip_titles(value)
    return out


def _normalize_result(result: Any) -> Any:
    """Shape a tool's return value the way the MCP client used to deliver it.

    MCP content lists (``TextContent`` / ``ImageContent``) become text or the
    ``{"_text", "_images"}`` dict the registry wraps into image content. Plain
    dicts and lists become JSON text, as FastMCP serialised them, which also
    lets ``_maybe_inline_browser_image`` find a ``hive-browser`` screenshot
    pointer inside a ``terminal_exec`` result.
    """
    if result is None or isinstance(result, str):
        return result
    if isinstance(result, list) and result and all(hasattr(item, "text") or hasattr(item, "data") for item in result):
        from framework.loader.mcp_client import _split_mcp_content

        text, images = _split_mcp_content(result)
        if images:
            return {"_text": text, "_images": images}
        return text
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def build_harness_tool(name: str, description: str, fn: Callable[..., Any]) -> HarnessTool:
    """Turn a plain (sync or async) tool function into a :class:`HarnessTool`."""
    sig = inspect.signature(fn)
    hints = _resolve_annotations(fn)
    fields: dict[str, Any] = {}
    accepts_var_kw = False
    for pname, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_var_kw = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        annotation = hints.get(pname, Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[pname] = (annotation, default)

    model: type[BaseModel] = create_model(  # type: ignore[call-overload]
        f"{name}_arguments",
        __config__=ConfigDict(arbitrary_types_allowed=True, extra="ignore"),
        **fields,
    )
    schema = _strip_titles(model.model_json_schema())
    schema.setdefault("properties", {})
    schema["type"] = "object"
    field_names = list(model.model_fields)

    def _kwargs(inputs: dict[str, Any]) -> dict[str, Any]:
        validated = model.model_validate(inputs)
        kwargs = {fname: getattr(validated, fname) for fname in field_names}
        if accepts_var_kw:
            kwargs.update({k: v for k, v in inputs.items() if k not in kwargs})
        return kwargs

    if inspect.iscoroutinefunction(fn):

        async def invoke_async(inputs: dict[str, Any]) -> Any:
            try:
                kwargs = _kwargs(inputs)
            except ValidationError as exc:
                return {"error": f"Invalid arguments for {name}: {exc}"}
            return _normalize_result(await fn(**kwargs))

        invoke: Callable[[dict[str, Any]], Any] = invoke_async
    else:

        def invoke_sync(inputs: dict[str, Any]) -> Any:
            try:
                kwargs = _kwargs(inputs)
            except ValidationError as exc:
                return {"error": f"Invalid arguments for {name}: {exc}"}
            return _normalize_result(fn(**kwargs))

        invoke = invoke_sync

    return HarnessTool(
        name=name,
        description=description,
        input_schema=schema,
        invoke=invoke,
        params=set(sig.parameters) - {"self", "cls"},
    )


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

_shutdown_registered = False
_shutdown_lock = threading.Lock()


def _reap_terminal_children() -> None:
    """Stop background jobs and PTYs at host exit (was the server's lifespan)."""
    try:
        from terminal_tools.jobs.manager import get_manager

        get_manager().shutdown_all(grace_sec=2.0)
    except Exception:
        logger.debug("harness: job manager shutdown failed", exc_info=True)
    try:
        from terminal_tools.pty.tools import get_registry

        get_registry().shutdown_all()
    except Exception:
        logger.debug("harness: PTY registry shutdown failed", exc_info=True)


def _terminal(mcp: _Collector, scope_env: ScopeEnvGetter) -> None:  # noqa: ARG001
    from terminal_tools.exec import register_exec_tools
    from terminal_tools.jobs.tools import register_job_tools
    from terminal_tools.output import register_output_tools
    from terminal_tools.pty.tools import register_pty_tools
    from terminal_tools.search.tools import register_search_tools

    register_exec_tools(mcp)
    register_job_tools(mcp)
    register_pty_tools(mcp)
    register_search_tools(mcp)
    register_output_tools(mcp)

    global _shutdown_registered
    with _shutdown_lock:
        if not _shutdown_registered:
            atexit.register(_reap_terminal_children)
            _shutdown_registered = True


def _files(mcp: _Collector, scope_env: ScopeEnvGetter) -> None:  # noqa: ARG001
    from aden_tools.file_ops import register_file_tools

    register_file_tools(mcp)


def _charts(mcp: _Collector, scope_env: ScopeEnvGetter) -> None:  # noqa: ARG001
    from chart_tools.tools import register_tools

    register_tools(mcp)


def _memory(mcp: _Collector, scope_env: ScopeEnvGetter) -> None:
    from memory_tools.timeline import register_search_timeline
    from memory_tools.tool import register_search_messages

    register_search_messages(mcp, scope_env=scope_env)
    register_search_timeline(mcp, scope_env=scope_env)


class _LazyCredentials:
    """Defers ``CredentialStoreAdapter.default()`` to the first real use.

    Building the adapter outside the host process (tests, CLI catalog reads,
    before the server has loaded ``HIVE_CREDENTIAL_KEY``) would mint a
    throwaway encryption key. The MCP subprocess never hit this because it
    was only ever spawned by a fully booted host.
    """

    def __init__(self) -> None:
        self._adapter: Any = None

    def __getattr__(self, item: str) -> Any:
        if self._adapter is None:
            from aden_tools.credentials import CredentialStoreAdapter

            self._adapter = CredentialStoreAdapter.default()
        return getattr(self._adapter, item)


def _hive_core(mcp: _Collector, scope_env: ScopeEnvGetter) -> None:  # noqa: ARG001
    """The ``aden_tools`` subset the default queen categories reference."""
    from aden_tools.file_ops import register_file_tools
    from aden_tools.tools import _email_senders_enabled
    from aden_tools.tools.account_info_tool import register_tools as register_account_info
    from aden_tools.tools.attach_file_tool import register_tools as register_attach_file
    from aden_tools.tools.csv_tool import register_tools as register_csv
    from aden_tools.tools.excel_tool import register_tools as register_excel
    from aden_tools.tools.image_gen_tool import register_tools as register_image_gen
    from aden_tools.tools.pdf_read_tool import register_tools as register_pdf_read
    from aden_tools.tools.time_tool import register_tools as register_time

    try:
        from aden_tools.tools.web_scrape_tool import register_tools as register_web_scrape
    except ImportError:  # playwright not installed
        register_web_scrape = None

    if register_web_scrape is not None:
        register_web_scrape(mcp)
    register_pdf_read(mcp)
    register_attach_file(mcp)
    register_time(mcp)
    register_image_gen(mcp)
    # Opt-in developer feature; absent unless HIVE_EMAIL_SENDERS is on.
    if _email_senders_enabled():
        from aden_tools.tools.senders_tool import register_tools as register_senders

        register_senders(mcp)
    register_account_info(mcp, credentials=_LazyCredentials())
    # read_file ships with edit_file: it records the state the stale-edit guard checks.
    register_file_tools(mcp, tool_names={"read_file", "edit_file"})
    register_csv(mcp)
    register_excel(mcp)


_BUILDERS: dict[str, Callable[[_Collector, ScopeEnvGetter], None]] = {
    "terminal-tools": _terminal,
    "files-tools": _files,
    "chart-tools": _charts,
    "memory-tools": _memory,
    "hive_tools": _hive_core,
}


def build_harness_group(name: str, *, scope_env: ScopeEnvGetter | None = None) -> list[HarnessTool]:
    """Build the tools in harness group *name*.

    *scope_env* returns the owning agent's identity env (``HIVE_QUEEN_ID`` …).
    It replaces the per-subprocess environment the MCP servers used to read.
    """
    builder = _BUILDERS[name]
    collector = _Collector()
    builder(collector, scope_env or dict)
    tools: list[HarnessTool] = []
    for tool_name, description, fn in collector.functions:
        try:
            tools.append(build_harness_tool(tool_name, description, fn))
        except Exception:
            logger.warning("harness: could not build tool '%s' in group '%s'", tool_name, name, exc_info=True)
    return tools
