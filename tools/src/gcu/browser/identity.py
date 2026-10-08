"""Which agent/session is driving the browser — resolved for the CLI subprocess.

The MCP tools received the acting agent's ``profile`` (the stable session id /
tab-group key) and ``profile_display_name`` (a human label) as framework-injected
CONTEXT_PARAMS, stripped from the LLM-facing schema. A ``hive-browser`` CLI
subprocess has no execution context of its own, so — exactly like the CRM CLI's
``HIVE_PRINCIPAL`` (see ``framework/crm/principal.py``) — the runtime hands these
down as environment variables:

* ``HIVE_BROWSER_SESSION``            → the session id, set as the ``_active_profile``
  contextvar so every tab-scoped op resolves to THIS agent's tab group.
* ``HIVE_BROWSER_PROFILE_DISPLAY_NAME`` → the tab-group / side-panel label used on
  cold-start (``open`` / ``navigate`` / ``script``).

``HIVE_BROWSER_SESSION`` is deliberately distinct from ``--browser-profile`` (which
Chrome connection to drive): the latter stays a visible flag the agent passes,
never injected — injecting it once made every worker run on the default Chrome
profile. The ``--profile`` flag is the debug override for the session id (the CRM
CLI's ``--as`` analog): a human can drive a specific agent's tab group locally
without the runtime present.
"""

from __future__ import annotations

import os
from typing import Any

SESSION_ENV = "HIVE_BROWSER_SESSION"
DISPLAY_NAME_ENV = "HIVE_BROWSER_PROFILE_DISPLAY_NAME"


def resolve_session(explicit: str | None = None) -> str | None:
    """The session id to act as: an explicit ``--profile`` wins, else the env."""
    if explicit and explicit.strip():
        return explicit.strip()
    return os.environ.get(SESSION_ENV, "").strip() or None


def resolve_display_name() -> str | None:
    """The human tab-group label handed down for cold-start context creation."""
    return os.environ.get(DISPLAY_NAME_ENV, "").strip() or None


def apply_env_identity(args: Any) -> None:
    """Bind this process to the acting agent's tab group, from ``--profile``/env.

    Called once at ``main()`` startup, BEFORE any op runs. Setting the
    ``_active_profile`` contextvar is load-bearing: without it every op's
    default-profile resolution lands on the shared ``"default"`` tab group and
    concurrent agents cross-contaminate each other's tabs — the isolation the
    CONTEXT_PARAM used to provide in-process.

    Stashes the resolved session + display name back onto ``args`` so cold-start
    handlers (``open``/``navigate``/``script``) can label a freshly created
    context. A no-op session (no flag, no env) leaves the ``"default"`` profile,
    matching the CLI's unbound/manual behaviour.
    """
    session = resolve_session(getattr(args, "profile", None))
    if session:
        from gcu.browser.session import set_active_profile

        set_active_profile(session)
    args._session = session
    args._display_name = resolve_display_name()
