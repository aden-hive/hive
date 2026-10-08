"""
browser_script — run a bundled Python script from a skill, in-process,
against this agent's tab group.

Why this tool exists
--------------------
A multi-step browser flow (e.g. "search LinkedIn for X, open thread,
read messages, type reply, send, verify") costs ~15 LLM turns if the
agent drives each step via individual ``browser_*`` tool calls. That's
~50–70 s end-to-end and a lot of intermediate context to manage.

``browser_script`` collapses the deterministic chunk of such a flow
into one tool call: the agent picks WHICH script to run, the script
runs in-process here and does all the browser ops sequentially via
the bridge, and one structured result comes back.

Profile correctness is automatic via CONTEXT_PARAMS injection —
the same mechanism every other browser_* tool uses. A script CANNOT
run with the wrong profile; the framework strips ``profile`` from
the LLM-facing schema and fills it from the agent's identity.

Script contract
---------------
A script is a regular Python module at
``<skill_base_dir>/scripts/<script_name>.py`` that defines:

    async def run(ctx: BrowserScriptContext) -> dict:
        ...

``ctx`` exposes (read-only) the agent's identity, the args the agent
passed, the calling skill's directory (for reading sibling files),
and a small convenience API that defaults to the agent's tab.
``ctx.bridge`` is exposed for power use; touching tabs outside
``ctx.group_id`` via the raw bridge is possible but discouraged.

Security
--------
- ``script`` must not contain '/', '\\', or '..' and must end in '.py'.
- The resolved path must be a real file inside ``<skill_dir>/scripts/``
  (symlink-resolution-safe; any path escape is rejected).
- The script runs in this process with full Python access — only
  install / activate skills you trust.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..bridge import connection_error, get_bridge
from ..telemetry import log_tool_call
from .lifecycle import _ensure_context

logger = logging.getLogger(__name__)

# Hard cap so a runaway script can't hold the bridge indefinitely.
_TIMEOUT_HARD_MAX_S = 300.0
_TIMEOUT_DEFAULT_S = 60.0

# Cache of resolved skill base_dirs so we don't re-scan SkillDiscovery on
# every call. Skills don't move at runtime; restart the MCP server if you
# add a new skill while it's running.
_SKILL_BASE_DIR_CACHE: dict[str, Path] = {}


# ─────────────────────────────────────────────────────────────────────
# Context handed to the script
# ─────────────────────────────────────────────────────────────────────


@dataclass
class BrowserScriptContext:
    """Profile-scoped browser context passed to ``run(ctx)``.

    Identity fields are read-only — the framework set them from the
    calling agent's CONTEXT_PARAMS and the script must not override.
    Convenience methods default ``tab_id`` to ``self.tab_id``; pass an
    explicit tab to act on a different tab in the same group (use
    ``self.open_tab`` to create one).
    """

    # ── identity (immutable) ─────────────────────────────────────────
    profile: str
    profile_display_name: str | None
    group_id: int | None
    tab_id: int

    # ── what the agent passed ────────────────────────────────────────
    args: dict[str, Any]
    skill_dir: Path  # absolute; for reading bundled fixtures / sibling files

    # ── raw bridge (escape hatch) + logger ───────────────────────────
    bridge: Any
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("browser_script"))

    # ─── convenience methods (default tab_id, return raw bridge dicts)

    async def navigate(self, url: str, *, wait_until: str = "load") -> dict:
        return await self.bridge.navigate(self.tab_id, url, wait_until=wait_until)

    async def evaluate(self, script: str) -> dict:
        return await self.bridge.evaluate(self.tab_id, script)

    async def click(
        self,
        selector: str,
        *,
        button: str = "left",
        click_count: int = 1,
        timeout_ms: int = 5000,
    ) -> dict:
        return await self.bridge.click(self.tab_id, selector, button=button, click_count=click_count, timeout_ms=timeout_ms)

    async def type_text(
        self,
        text: str,
        *,
        selector: str | None = None,
        clear_first: bool = True,
        use_insert_text: bool = True,
        timeout_ms: int = 30000,
    ) -> dict:
        return await self.bridge.type_text(
            self.tab_id,
            selector,
            text,
            clear_first=clear_first,
            delay_ms=1,
            timeout_ms=timeout_ms,
            use_insert_text=use_insert_text,
        )

    async def press_key(
        self,
        key: str,
        *,
        selector: str | None = None,
        modifiers: list[str] | None = None,
    ) -> dict:
        return await self.bridge.press_key(self.tab_id, key, selector=selector, modifiers=modifiers)

    async def get_text(self, selector: str, *, timeout_ms: int = 30000) -> dict:
        return await self.bridge.get_text(self.tab_id, selector, timeout_ms=timeout_ms)

    async def wait_for_selector(self, selector: str, *, timeout_ms: int = 5000) -> dict:
        return await self.bridge.wait_for_selector(self.tab_id, selector, timeout_ms=timeout_ms)

    async def wait_for_text(self, text: str, *, timeout_ms: int = 5000) -> dict:
        return await self.bridge.wait_for_text(self.tab_id, text, timeout_ms=timeout_ms)

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 500,
        selector: str | None = None,
    ) -> dict:
        """Scroll the page (or a container if ``selector`` is given) by
        ``amount`` pixels in ``direction``. For lazy-loaded feeds (LinkedIn
        invitation manager, X timeline) pass amount=3000-6000 and the
        container selector — large amounts get chunked internally.
        """
        return await self.bridge.scroll(self.tab_id, direction=direction, amount=amount, selector=selector)

    async def wait(self, seconds: float) -> None:
        """asyncio.sleep, capped at 30s per call so a bad arg can't wedge the script."""
        await asyncio.sleep(max(0.0, min(30.0, seconds)))


# ─────────────────────────────────────────────────────────────────────
# Path / skill resolution
# ─────────────────────────────────────────────────────────────────────


def _resolve_skill_dir(skill_name: str) -> Path:
    """Find the absolute base_dir of ``skill_name`` via SkillDiscovery.

    Raises ``LookupError`` with a useful message if the skill isn't
    in any discoverable scope (framework defaults, presets, user, project).
    """
    cached = _SKILL_BASE_DIR_CACHE.get(skill_name)
    if cached is not None and cached.is_dir():
        return cached

    # Import lazily — SkillDiscovery pulls in a lot of framework code,
    # and most browser_* tools don't need it.
    from framework.skills.discovery import DiscoveryConfig, SkillDiscovery

    skills = SkillDiscovery(DiscoveryConfig()).discover()
    # The 'name' frontmatter and the directory name can differ
    # (e.g. directory ``linkedin-messaging`` declares ``name: hive.linkedin-messaging``).
    # Accept either the declared name OR the directory name as a key.
    for s in skills:
        base = Path(s.base_dir)
        candidates = {s.name, base.name}
        if skill_name in candidates:
            _SKILL_BASE_DIR_CACHE[skill_name] = base
            return base
    raise LookupError(
        f"skill '{skill_name}' not found in any discoverable scope. "
        f"Searched {len(skills)} skills; use one of: "
        f"{sorted({s.name for s in skills} | {Path(s.base_dir).name for s in skills})[:30]}"
    )


def _resolve_script_path(skill_dir: Path, script_name: str) -> Path:
    """Validate ``script_name`` and return the absolute path under
    ``<skill_dir>/scripts/``.

    Rejects anything that looks like a path escape: '/', '\\', '..',
    leading dots, non-'.py' suffix. After resolving symlinks the path
    must still be inside the scripts directory.
    """
    if not script_name:
        raise ValueError("script name is empty")
    # Accept a bare script name without the .py suffix — agents and the migrated
    # SKILL.md examples routinely pass e.g. `lk_get_identity`. Append it; the
    # path-escape checks below still run on the suffixed name, so a name with a
    # separator or leading dot is rejected exactly as before.
    if not script_name.endswith(".py"):
        script_name = f"{script_name}.py"
    for bad in ("/", "\\", ".."):
        if bad in script_name:
            raise ValueError(f"script '{script_name}' must not contain {bad!r}")
    if script_name.startswith("."):
        raise ValueError(f"script '{script_name}' must not start with '.'")

    scripts_root = (skill_dir / "scripts").resolve()
    if not scripts_root.is_dir():
        raise FileNotFoundError(f"skill has no scripts/ directory at {scripts_root}")

    candidate = (scripts_root / script_name).resolve()
    # Symlink-safety: the resolved path must still live under scripts_root.
    if scripts_root not in candidate.parents and candidate != scripts_root:
        raise ValueError(f"script '{script_name}' resolved outside scripts/")
    if not candidate.is_file():
        raise FileNotFoundError(f"script '{script_name}' not found at {candidate}")
    return candidate


def _load_script_module(path: Path, skill_name: str):
    """Fresh-load the script via importlib so dev edits take effect
    without restarting the MCP server. Module name is namespaced to
    avoid colliding with anything else on sys.modules.
    """
    mod_name = f"hive_browser_script.{skill_name.replace('.', '_').replace('-', '_')}.{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # Put it on sys.modules briefly so the loader can resolve siblings
    # (e.g. ``from helpers import X``) via the standard mechanism.
    # Skill scripts that import siblings need this; we clean up on exit.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    return module, mod_name


# ─────────────────────────────────────────────────────────────────────
# Script hooks — cross-cutting concerns that run around every script
# ─────────────────────────────────────────────────────────────────────

_SCRIPT_HOOKS: list[Any] = []
_HOOKS_LOADED = False


def register_script_hook(hook_module: Any) -> None:
    """Register a hook that runs before/after every ``browser_script`` call.

    *hook_module* may expose either or both of::

        async def before_run(module, bsc, bridge) -> dict | None
        async def after_run(module, bsc, bridge, result) -> dict

    ``before_run`` returning a dict short-circuits ``run()`` — the dict
    becomes the script result.  ``after_run`` may transform the result.
    """
    _SCRIPT_HOOKS.append(hook_module)


def _load_default_hooks() -> None:
    """Discover and register hooks from ``gcu.browser.hooks``.

    Called once (lazy) on first ``browser_script`` invocation.  Fails
    silently if any hook module is absent — hooks are optional.
    """
    global _HOOKS_LOADED
    if _HOOKS_LOADED:
        return
    _HOOKS_LOADED = True

    hooks_dir = Path(__file__).resolve().parent.parent / "hooks"
    if not hooks_dir.is_dir():
        return

    for hook_file in sorted(hooks_dir.glob("*.py")):
        if hook_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"gcu.browser.hooks.{hook_file.stem}",
                str(hook_file),
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            register_script_hook(mod)
            logger.info("registered script hook: %s", hook_file.name)
        except Exception:
            logger.warning("failed to load script hook %s", hook_file.name, exc_info=True)


# ─────────────────────────────────────────────────────────────────────
# Tool registration
# ─────────────────────────────────────────────────────────────────────


BROWSER_SCRIPT_DOC = """\
Run a bundled Python orchestration script from a skill, in-process,
against THIS agent's tab group.

Use this instead of stitching together many ``browser_*`` calls when a
flow is multi-step and deterministic (e.g. "reply to a LinkedIn DM",
"accept N pending connection requests"). The script encodes verified
selectors, waits, and retries; the agent only chooses whether to call
it and what to pass.

Arguments
* ``skill``: the skill's declared ``name`` frontmatter OR its directory
  name (e.g. ``"hive.linkedin-messaging"`` or ``"linkedin-messaging"``).
* ``script``: a ``.py`` file under ``<skill>/scripts/`` (no path
  separators, no ``..``).
* ``args``: a dict passed to the script as ``ctx.args``. Validate
  shape inside the script — this tool does not enforce a schema.
* ``timeout_s``: max wall time before the script is cancelled. Default
  60, hard cap 300.
* ``tab_id``: optional Chrome tab id to expose as ``ctx.tab_id``.
  Defaults to the profile's active tab. Only set if the script's docs
  say to — most scripts assume the active tab.

Returns a dict shaped like::

    {"ok": true,  "result": <whatever the script returned>, "duration_ms": ...}
    {"ok": false, "error": "<reason>", "duration_ms": ..., ...}

On exception inside the script::

    {"ok": false, "error": "<exception message>", "exception_type": "...",
     "traceback": "<tail>", "duration_ms": ...}

Discover available scripts by reading the calling skill's SKILL.md —
each script's contract (args, return shape, failure modes) is
documented there alongside the canonical flow."""


async def run_browser_script(
    *,
    skill: str,
    script: str,
    args: dict[str, Any] | None = None,
    timeout_s: float = _TIMEOUT_DEFAULT_S,
    tab_id: int | None = None,
    profile: str | None = None,
    profile_display_name: str | None = None,
    browser_profile: str | None = None,
) -> dict:
    """Run a skill-bundled ``async def run(ctx)`` script against the agent's tab group.

    This is the shared core behind BOTH the ``browser_script`` MCP tool and the
    ``hive-browser script`` CLI command. Keeping it a single function is what
    guarantees the ``BrowserScriptContext`` (``ctx``) contract is byte-identical
    across the two surfaces — a ``run(ctx)`` script cannot tell which invoked it,
    because in both cases ``ctx.bridge`` is the same ``RemoteBridge`` talking to
    the same ``bridge_host``. Do NOT reimplement this loop elsewhere; call it.
    """
    _load_default_hooks()

    start = time.perf_counter()
    log_params = {
        "skill": skill,
        "script": script,
        "args": args,
        "timeout_s": timeout_s,
        "tab_id": tab_id,
        "profile": profile,
    }

    # ── bridge + per-agent tab group ─────────────────────────────
    bridge = get_bridge()
    if not bridge or not bridge.is_connected:
        err = {"ok": False, "error": connection_error(bridge)}
        log_tool_call("browser_script", log_params, result=err)
        return err

    try:
        profile_name, ctx, _ = await _ensure_context(bridge, profile, profile_display_name, browser_profile)
    except Exception as e:
        err = {"ok": False, "error": f"failed to ensure browser context: {e}"}
        log_tool_call(
            "browser_script",
            log_params,
            error=e,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        return err

    target_tab = tab_id or ctx.get("activeTabId")
    group_id = ctx.get("groupId")
    if target_tab is None:
        err = {"ok": False, "error": "no active tab in this profile's group"}
        log_tool_call("browser_script", log_params, result=err)
        return err

    # ── resolve skill + script path ──────────────────────────────
    try:
        skill_dir = _resolve_skill_dir(skill)
        script_path = _resolve_script_path(skill_dir, script)
    except (LookupError, ValueError, FileNotFoundError) as e:
        err = {"ok": False, "error": str(e), "phase": "resolve"}
        log_tool_call("browser_script", log_params, result=err)
        return err

    # ── load + invoke ────────────────────────────────────────────
    timeout = max(1.0, min(_TIMEOUT_HARD_MAX_S, float(timeout_s)))
    try:
        module, mod_name = _load_script_module(script_path, skill)
    except BaseException as e:
        err = {
            "ok": False,
            "error": f"failed to import script: {e}",
            "exception_type": type(e).__name__,
            "traceback": traceback.format_exc(limit=10),
            "phase": "import",
        }
        log_tool_call("browser_script", log_params, error=e)
        return err

    run = getattr(module, "run", None)
    if run is None or not asyncio.iscoroutinefunction(run):
        with contextlib.suppress(KeyError):
            sys.modules.pop(mod_name)
        err = {
            "ok": False,
            "error": f"script {script_path.name} must define `async def run(ctx) -> dict`",
            "phase": "contract",
        }
        log_tool_call("browser_script", log_params, result=err)
        return err

    bsc = BrowserScriptContext(
        profile=profile_name,
        profile_display_name=profile_display_name,
        group_id=group_id,
        tab_id=target_tab,
        args=dict(args or {}),
        skill_dir=skill_dir,
        bridge=bridge,
        log=logging.getLogger(f"browser_script.{Path(script).stem}"),
    )

    try:
        # ── script hooks: before_run ────────────────────────────
        result = None
        for hook in _SCRIPT_HOOKS:
            before = getattr(hook, "before_run", None)
            if before is not None:
                hook_result = await before(module, bsc, bridge)
                if hook_result is not None:
                    result = hook_result
                    break

        if result is None:
            result = await asyncio.wait_for(run(bsc), timeout=timeout)

        # ── script hooks: after_run ─────────────────────────────
        if isinstance(result, dict):
            for hook in _SCRIPT_HOOKS:
                after = getattr(hook, "after_run", None)
                if after is not None:
                    result = await after(module, bsc, bridge, result)
    except TimeoutError:
        err = {
            "ok": False,
            "error": f"script exceeded timeout ({timeout}s)",
            "timeout": True,
            "duration_ms": (time.perf_counter() - start) * 1000,
        }
        await _attach_blockers(err, bridge, target_tab)
        log_tool_call("browser_script", log_params, result=err)
        return err
    except BaseException as e:
        err = {
            "ok": False,
            "error": str(e) or type(e).__name__,
            "exception_type": type(e).__name__,
            # Tail only — full traceback is in server logs.
            "traceback": "\n".join(traceback.format_exc(limit=8).splitlines()[-12:]),
            "duration_ms": (time.perf_counter() - start) * 1000,
            "phase": "run",
        }
        await _attach_blockers(err, bridge, target_tab)
        log_tool_call("browser_script", log_params, error=e)
        return err
    finally:
        # Drop the module from sys.modules so next call re-imports
        # fresh (lets dev edits take effect without server restart).
        with contextlib.suppress(KeyError):
            sys.modules.pop(mod_name)

    # ── normalize the script's return ────────────────────────────
    duration_ms = (time.perf_counter() - start) * 1000
    if not isinstance(result, dict):
        wrapped = {
            "ok": True,
            "result": {"value": repr(result)},
            "warning": f"script returned {type(result).__name__}, not dict; wrapped under .value",
            "duration_ms": duration_ms,
        }
        log_tool_call("browser_script", log_params, result=wrapped, duration_ms=duration_ms)
        return wrapped

    wrapped = {"ok": True, "result": result, "duration_ms": duration_ms}
    # If the script's own logic detected a soft failure (status != sent,
    # editor_not_found, …), surface any active per-tab blockers so the
    # agent can tell the user "Calendly is blocking this tab" instead of
    # parroting the script's opaque status code. We do this on
    # script-level success too because scripts typically return ok=True
    # with a non-sent status — the blocker is the real story there.
    inner = wrapped.get("result")
    if isinstance(inner, dict) and inner.get("status") and inner.get("status") not in ("sent", "ok", "dry_run_ok"):
        await _attach_blockers(wrapped, bridge, target_tab)
    log_tool_call("browser_script", log_params, result=wrapped, duration_ms=duration_ms)
    return wrapped


def register_script_tools(mcp: FastMCP) -> None:
    """Register ``browser_script`` on the MCP server — a thin wrapper over
    :func:`run_browser_script` (the shared core the ``hive-browser script`` CLI
    command also calls)."""

    @mcp.tool(description=BROWSER_SCRIPT_DOC)
    async def browser_script(
        skill: Annotated[
            str,
            Field(
                description=(
                    "Skill identifier. Use the SKILL.md `name:` frontmatter "
                    "(e.g. 'hive.linkedin-messaging') or the directory name "
                    "(e.g. 'linkedin-messaging')."
                )
            ),
        ],
        script: Annotated[
            str,
            Field(description=("Script filename, ending in .py, located in the skill's scripts/ directory. No path separators or '..'.")),
        ],
        args: Annotated[
            dict[str, Any] | None,
            Field(description=("Arbitrary JSON-serializable args passed to the script as ctx.args. Shape is per-script — see the skill's SKILL.md.")),
        ] = None,
        timeout_s: Annotated[
            float,
            Field(description="Wall-time cap, seconds. Default 60, max 300."),
        ] = _TIMEOUT_DEFAULT_S,
        tab_id: Annotated[
            int | None,
            Field(
                description=(
                    "Chrome tab ID to expose as ctx.tab_id. Defaults to the "
                    "profile's active tab. Only set this if the script's docs "
                    "say to — most scripts assume the active tab."
                )
            ),
        ] = None,
        profile: Annotated[
            str | None,
            Field(description='Browser profile name (default: "default"). Framework-injected.'),
        ] = None,
        # Framework-injected (CONTEXT_PARAM) — human-readable queen/colony
        # label for the tab group; stripped from the LLM-facing schema.
        profile_display_name: str | None = None,
        browser_profile: Annotated[
            str | None,
            Field(
                description=(
                    "Which Chrome profile to run in — a connected profile label from "
                    "list_browser_profiles. Set it to target a specific logged-in account; "
                    "omit to use the starred/sole connected profile."
                ),
            ),
        ] = None,
    ) -> dict:
        return await run_browser_script(
            skill=skill,
            script=script,
            args=args,
            timeout_s=timeout_s,
            tab_id=tab_id,
            profile=profile,
            profile_display_name=profile_display_name,
            browser_profile=browser_profile,
        )


async def _attach_blockers(envelope: dict, bridge, tab_id: int) -> None:
    """Mutate ``envelope`` to include any per-tab blockers in the bridge cache.

    Called from every failure-return path in ``browser_script`` so the
    agent's tool response carries the same culprit info the side panel
    renders. Idempotent (won't overwrite existing ``blockers``) and silent
    on errors — diagnostics must never break the tool's primary return.

    Three-tier resolution, matching ``advanced._resolve_blockers``:

    1. Read ``bridge.get_tab_blockers`` (the cache).
    2. If empty AND error string indicates a foreign-extension frame,
       run a synchronous ``tab_health(force_audit=True)`` to populate
       the cache with the offender's name via the page-DOM probe.
       Without this the agent gets the generic "Blocked by another
       extension" copy on the first failed call — the named blocker
       only appears on subsequent calls after a background reaudit.
    3. Final fallback: classify the error string itself.
    """
    try:
        if "blockers" in envelope:
            return
        blockers: list[dict] = []
        if bridge is not None:
            try:
                blockers = list(await bridge.get_tab_blockers(tab_id) or [])
            except Exception:
                blockers = []
        err_str = envelope.get("error") or ""
        looks_foreign_frame = isinstance(err_str, str) and "chrome-extension://" in err_str.lower() and "different extension" in err_str.lower()
        if not blockers and looks_foreign_frame and bridge is not None:
            try:
                await bridge.tab_health(tab_id, force_audit=True)
                blockers = list(await bridge.get_tab_blockers(tab_id) or [])
            except Exception:
                blockers = []
        if not blockers and err_str:
            from ..bridge import get_bridge
            from ..health import classify_all

            ext_id = getattr(get_bridge(), "_extension_id", None)
            ctx_kw = {"our_extension_id": ext_id} if ext_id else {}
            objs = classify_all({}, str(err_str), ctx=ctx_kw)
            blockers = [b.to_dict() for b in objs]
        if blockers:
            envelope["blockers"] = blockers
    except Exception:
        pass
