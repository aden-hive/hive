"""Role-based default tool allowlists for queens.

Every queen inherits the same MCP surface (all servers loaded for the
queen agent), but exposing 94+ tools to every persona clutters the LLM
tool catalog and wastes prompt tokens. This module defines a sensible
default allowlist per queen persona so, e.g., Head of Legal doesn't
see port scanners and Head of Brand & Design doesn't see CSV/SQL tools.

Defaults apply only when the queen has no ``tools.json`` sidecar — the
moment the user saves an allowlist through the Tool Library, the
sidecar becomes authoritative. A DELETE on the tools endpoint removes
the sidecar and brings the queen back to her role default.

Category entries support a ``@server:NAME`` shorthand that expands to
every tool name registered against that MCP server in the current
catalog. This keeps the category table short and drift-free when new
tools are added (e.g. browser_* auto-joins the ``browser`` category).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from framework.agents.queen.queen_profiles import DEFAULT_QUEENS

logger = logging.getLogger(__name__)


def _current_app_version() -> str:
    """The app version that spawned this runtime.

    Set by Electron's runtime spawn (``runtime.ts``). Falls back to
    ``0.0.0`` in stripped-down test/OSS environments so version compares
    don't blow up — that floor is identical to a missing sidecar field.
    """
    return os.environ.get("HIVE_APP_VERSION") or "0.0.0"


# ---------------------------------------------------------------------------
# Categories — reusable bundles of MCP tool names.
# ---------------------------------------------------------------------------
#
# Each category is a flat list of either concrete tool names or the
# ``@server:NAME`` shorthand. The shorthand expands to every tool the
# given MCP server currently exposes (requires a live catalog; when one
# is not available the shorthand is silently dropped so we fall back to
# the named entries only).

_TOOL_CATEGORIES: dict[str, list[str]] = {
    # Document tools. The read/write/edit/search file tools were removed in
    # favor of the terminal tools (see terminal_basic) — file I/O now goes
    # through terminal_exec / terminal_rg / terminal_glob, which default their
    # cwd to the session workdir. pdf_read lets queens read PDF documents;
    # attach_file rehydrates a PDF or image from disk back into the LLM's
    # next-turn context (to re-look at attachments that aged out of image_content).
    "file_ops": [
        "pdf_read",
        "attach_file",
    ],
    # Terminal basic — the subset queens get out of the box.
    #   terminal_exec — foreground command execution (Bash equivalent)
    #   terminal_rg   — ripgrep content search (Grep equivalent)
    #   terminal_glob — name/glob file listing (Glob equivalent)
    #   terminal_output_get — see INVARIANT below
    #
    # INVARIANT (ported from the desktop runtime): terminal_exec hands out
    # a deferred-result handle — ``output_handle`` — when output overflows
    # max_output_kb. The tool that redeems it MUST ship in the same tier as
    # terminal_exec; a handle nobody can redeem is worse than no handle at
    # all. (Slow commands are separately handled by
    # ``LoopConfig.background_tools`` + the synthetic ``collect_result``,
    # which bypass this allowlist entirely.)
    "terminal_basic": [
        "terminal_exec",
        "terminal_rg",
        "terminal_glob",
        "terminal_output_get",
    ],
    # Terminal advanced — the power-user tools beyond the basics. Not in
    # any role default; opt in explicitly per-queen via the Tool Library.
    #   terminal_job_*   — background job lifecycle (start/manage/logs)
    #   terminal_output_get — fetch captured output from foreground exec
    #   terminal_pty_*   — persistent PTY sessions (open/run/close)
    "terminal_advanced": [
        "terminal_job_start",
        "terminal_job_manage",
        "terminal_job_logs",
        "terminal_output_get",
        "terminal_pty_open",
        "terminal_pty_run",
        "terminal_pty_close",
    ],
    # Tabular data. CSV/Excel read/write + DuckDB SQL.
    "spreadsheet_advanced": [
        "csv_read",
        "csv_info",
        "csv_write",
        "csv_append",
        "csv_sql",
        "excel_read",
        "excel_info",
        "excel_write",
        "excel_append",
        "excel_search",
        "excel_sheet_list",
        "excel_sql",
    ],
    # The browser is driven from the terminal via the `hive-browser` CLI, not MCP
    # tools. The four legacy browser_* categories all collapse to the single
    # in-process discovery tool `browser_setup`: its presence pre-activates the
    # browser-automation skill (which teaches the CLI), and `browser_core` is in
    # the always-enabled tiers, so every queen/worker gets browser capability up
    # front. The four keys are kept (rather than merged) so existing per-queen
    # category configs that name any of them keep resolving.
    "browser_basic": ["browser_setup"],
    "browser_interaction": ["browser_setup"],
    "browser_core": ["browser_setup"],
    "browser_extended": ["browser_setup"],
    # terminal_core / terminal_extended: terminal_exec measured at 200/1k
    # carries (the single most-invoked tool); rg (3.3/1k) and glob (1.3/1k)
    # are cold — terminal_exec can express both when loaded ad hoc.
    # output_get is cold by call count but rides along anyway: it redeems
    # the output_handle terminal_exec hands out, and a handle is useless in
    # a tier that can't cash it (test_deferred_handle_redeemers enforces
    # this for every emitter/tier pair). Correctness beats the carry cost.
    "terminal_core": [
        "terminal_exec",
        "terminal_output_get",
    ],
    "terminal_extended": [
        "terminal_rg",
        "terminal_glob",
    ],
    # files_core: attach_file (7.8/1k — rehydrates attachments into context).
    # pdf_read (0.7/1k) stays deferred via the research/file_ops categories.
    "files_core": [
        "attach_file",
    ],
    # context_core: the cheap ambient helpers minus search_messages, whose
    # 4.3 KB schema was carried on every call and invoked 0.7×/1k.
    "context_core": [
        "get_current_time",
        "get_account_info",
    ],
    # web_core: web_scrape measured hot (34/1k) — eager for workers even
    # though the broader research bundle stays deferred.
    "web_core": [
        "web_scrape",
    ],
    # Research — paper search, Wikipedia, ad-hoc web scrape. Pair with
    # browser_basic for richer site-by-site research; this category is the
    # lightweight always-available fallback.
    "research": ["web_scrape", "pdf_read"],
    # Security — defensive scanning and reconnaissance. Engineering-only
    # surface; the rest of the queens shouldn't see port scanners.
    "security": [
        "port_scan",
        "dns_security_scan",
        "http_headers_scan",
        "ssl_tls_scan",
        "subdomain_enumerate",
        "tech_stack_detect",
        "risk_score",
    ],
    # Lightweight context helpers — good default for every queen.
    "context_awareness": [
        "get_current_time",
        "get_account_info",
        # System memory — regex search across the queen's own message history
        # (across sessions). In-scope content: user text, assistant prose,
        # and tool result bodies. Never includes tool names, tool inputs,
        # reasoning, finish reasons, token counts, or timestamps.
        "search_messages",
    ],
    # BI / financial chart + diagram rendering. Calling chart_render
    # both embeds the chart live in chat and produces a downloadable PNG.
    "charts": [
        "@server:chart-tools",
    ],
    # Media generation — text-to-image and reference-image editing via the
    # Hive image proxy (gpt-image-2). Each call is billed to the user's
    # credits per image, so this is opt-in for visual roles (content,
    # brand/design, growth) rather than always-enabled.
    "media": [
        "image_generate",
    ],
    # ----- OAuth-bound categories ------------------------------------
    # These tools require an OAuth provider connection (Google, GitHub,
    # HubSpot, Notion, Slack). They are listed in the Library catalog
    # regardless of whether the provider is currently authorized — the
    # UI shows a greyed-out checkbox + Connect button when not — and
    # are filtered out of the worker prompt at spawn time if the
    # provider has no live account. New OAuth tools added under each
    # provider here will auto-light up once the user authorizes.
    "email_oauth": [
        "send_email",
        "gmail_list_messages",
        "gmail_get_message",
        "gmail_create_draft",
        "gmail_reply_email",
        "gmail_modify_message",
        "gmail_trash_message",
        "gmail_create_label",
        "gmail_list_labels",
        "gmail_batch_get_messages",
        "gmail_batch_modify_messages",
    ],
    # Team email senders — the cloud-configured sender pool + rotation. These
    # tools are credential-less at the MCP layer (secrets come from the sender
    # registry), so unlike "email_oauth" they are NOT gated on a connected
    # provider: a queen with this category always has the send surface, which
    # self-describes an empty pool until the team configures senders.
    "email_senders": [
        "list_senders",
        "setup_email_sender",
        "send_from_sender",
        "pick_sender",
        "send_campaign",
        "sender_history",
        "suppress_recipient",
        "list_suppressed",
        "adjust_sender",
    ],
    "calendar_oauth": [
        "calendar_list_calendars",
        "calendar_get_calendar",
        "calendar_list_events",
        "calendar_get_event",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
        "calendar_check_availability",
    ],
    "google_workspace": [
        "google_docs_create_document",
        "google_docs_get_document",
        "google_docs_insert_text",
        "google_docs_format_text",
        "google_docs_replace_all_text",
        "google_docs_batch_update",
        "google_docs_insert_image",
        "google_docs_create_list",
        "google_docs_add_comment",
        "google_docs_list_comments",
        "google_docs_export_content",
        "google_sheets_create_spreadsheet",
        "google_sheets_get_spreadsheet",
        "google_sheets_get_values",
        "google_sheets_update_values",
        "google_sheets_append_values",
        "google_sheets_clear_values",
        "google_sheets_batch_update_values",
        "google_sheets_batch_clear_values",
        "google_sheets_add_sheet",
        "google_sheets_delete_sheet",
    ],
    "github_oauth": [
        "github_list_repos",
        "github_get_repo",
        "github_search_repos",
        "github_list_issues",
        "github_get_issue",
        "github_create_issue",
        "github_update_issue",
        "github_list_pull_requests",
        "github_get_pull_request",
        "github_create_pull_request",
        "github_search_code",
        "github_list_branches",
        "github_get_branch",
        "github_list_stargazers",
        "github_get_user_profile",
        "github_get_user_emails",
        "github_list_commits",
        "github_create_release",
        "github_list_workflow_runs",
    ],
    "hubspot_oauth": [
        "hubspot_search_contacts",
        "hubspot_get_contact",
        "hubspot_create_contact",
        "hubspot_update_contact",
        "hubspot_search_companies",
        "hubspot_get_company",
        "hubspot_create_company",
        "hubspot_update_company",
        "hubspot_search_deals",
        "hubspot_get_deal",
        "hubspot_create_deal",
        "hubspot_update_deal",
        "hubspot_delete_object",
        "hubspot_list_associations",
        "hubspot_create_association",
    ],
    "notion_oauth": [
        "notion_search",
        "notion_get_page",
        "notion_create_page",
        "notion_update_page",
        "notion_query_database",
        "notion_get_database",
        "notion_create_database",
        "notion_update_database",
        "notion_get_block_children",
        "notion_get_block",
        "notion_update_block",
        "notion_delete_block",
        "notion_append_blocks",
    ],
    # Slack is currently "Coming soon" in the desktop integrations UI,
    # but queens still get the category — the per-spawn credential
    # filter drops the tools until the provider is connected, so when
    # Slack ships the queens auto-light up without any sidecar churn.
    "slack_oauth": [
        "slack_send_message",
        "slack_list_channels",
        "slack_get_channel_history",
        "slack_get_channel_info",
        "slack_list_users",
        "slack_get_user_info",
        "slack_find_user_by_email",
        "slack_send_dm",
        "slack_search_messages",
        "slack_get_thread_replies",
        "slack_get_messages_for_analysis",
        "slack_get_conversation_context",
        "slack_update_message",
        "slack_delete_message",
        "slack_schedule_message",
        "slack_add_reaction",
        "slack_remove_reaction",
        "slack_pin_message",
        "slack_unpin_message",
        "slack_upload_file",
        "slack_get_permalink",
    ],
}


# ---------------------------------------------------------------------------
# Category additions — generally-available tools added to a category AFTER
# a prior release shipped.
# ---------------------------------------------------------------------------
#
# A saved ``tools.json`` sidecar is a frozen flat list of tool names — it
# never picks up a tool added to a category later. Two consumers heal that:
#
#   * ``grant_role_default_additions`` (preferred) — used by the GA tool
#     migration on runtime startup and by ``load_queen_tools_config`` when
#     the queen has a role default. Grants every addition whose GA-promotion
#     version is newer than the sidecar's ``saved_on_version``, when its
#     category appears in the queen's role default.
#
#   * ``infer_category_additions`` (legacy fallback) — used for queens
#     without a role default. Grants additions only when the saved
#     allowlist fully covered the category's pre-addition baseline. Skipped
#     for small categories to avoid coincidental baseline matches.
#
# In both cases, an addition whose version is <= ``saved_on_version`` is
# left alone — the sidecar was saved on a release that already knew about
# the tool, so its absence is a deliberate untick.
#
# When adding a tool to a category, add it to BOTH ``_TOOL_CATEGORIES`` and
# here, keyed by the release version that promotes the tool to GA (the
# version that ships this dict entry).
#
# Versions are compared by ``_parse_version`` as tuples of ints split on
# ``.`` — ``"0.2.19"`` → ``(0, 2, 19)``. Anything malformed/missing
# collapses to ``(0, 0, 0)`` so legacy sidecars without ``saved_on_version``
# receive every addition on first migration.
#
# GRADUATION: once a release cycle has passed and sidecars have had a chance
# to re-save, drop the entry from this table. The tool stays a normal
# ``_TOOL_CATEGORIES`` member; leaving it here forever slowly erodes the
# ``baseline`` set the legacy fallback compares against.
#
# Shape: category -> { tool_name -> GA-promotion version (e.g. "0.2.19") }.
_CATEGORY_ADDITIONS: dict[str, dict[str, str]] = {
    # The browser_* MCP tools were replaced by the terminal-driven hive-browser CLI
    # in 0.3.0; the sole in-process tool is now browser_setup (in browser_core,
    # always-enabled). Heal saved sidecars that predate the switch — whose lists
    # name now-removed browser_* tools — so they regain the browser capability.
    "browser_core": {"browser_setup": "0.3.0"},
    "file_ops": {"attach_file": "0.2.19"},
    # image_generate shipped in 0.2.27 but "media" was only in three visual
    # roles' defaults, so the other ten queens could see the image-generation
    # skill while the tool it documents was filtered out of their allowlist.
    # 0.3.0 grants "media" to every role, so re-tag the addition to 0.3.0 —
    # sidecars saved on 0.2.27–0.2.x never had media in their role default and
    # must heal. Cost: for the three roles that already had media, a
    # deliberate untick saved on 0.2.27+ is re-granted once.
    "media": {"image_generate": "0.3.0"},
    # Email senders suite ships in 0.2.30; heal existing explicit-allowlist
    # sidecars of queens whose role default now includes "email_senders".
    "email_senders": {
        "list_senders": "0.2.30",
        "send_from_sender": "0.2.30",
        "pick_sender": "0.2.30",
        "send_campaign": "0.2.30",
        # Agent-driven sender setup ships in 0.3.0.
        "setup_email_sender": "0.3.0",
        # The team-wide send log (audit + dedupe) ships in 0.3.0.
        "sender_history": "0.3.0",
        # Do-not-contact list. Ships in 0.3.0.
        "suppress_recipient": "0.3.0",
        "list_suppressed": "0.3.0",
        # Agent-tunable sender volume/rotation. Ships in 0.3.0.
        "adjust_sender": "0.3.0",
    },
}


# ---------------------------------------------------------------------------
# Per-queen mapping.
# ---------------------------------------------------------------------------
#
# DERIVED from ``queen_profiles.DEFAULT_QUEENS`` — each queen entry is the
# single place its defaults live (persona + ``default_tool_categories`` +
# ``default_preset_skills``). To change what tools a queen gets by default,
# edit its ``default_tool_categories`` there; this dict just projects it.
#
# A queen whose ID is NOT in this map falls through to "allow every MCP
# tool" (the original behavior), which keeps the system compatible with
# user-added custom queen IDs that we don't know about.

QUEEN_DEFAULT_CATEGORIES: dict[str, list[str]] = {
    queen_id: list(profile["default_tool_categories"]) for queen_id, profile in DEFAULT_QUEENS.items() if profile.get("default_tool_categories")
}


def has_role_default(queen_id: str) -> bool:
    """Return True when ``queen_id`` is known to the category table."""
    return queen_id in QUEEN_DEFAULT_CATEGORIES


def list_category_names() -> list[str]:
    """Return every category name defined in the table, in declaration order."""
    return list(_TOOL_CATEGORIES.keys())


def queen_role_categories(queen_id: str) -> list[str]:
    """Return the category names assigned to ``queen_id`` by role default.

    Returns an empty list for queens not in the persona table (they fall
    through to allow-all and have no implicit category membership).
    """
    return list(QUEEN_DEFAULT_CATEGORIES.get(queen_id, []))


def resolve_category_tools(
    category: str,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    """Expand a single category to its concrete tool names.

    Mirrors ``resolve_queen_default_tools`` but for a single category, so
    callers (e.g. the Tool Library API) can present per-category tool
    membership without re-implementing the ``@server:NAME`` shorthand
    expansion.
    """
    names: list[str] = []
    seen: set[str] = set()
    for entry in _TOOL_CATEGORIES.get(category, []):
        if entry.startswith("@server:"):
            server_name = entry[len("@server:") :]
            if mcp_catalog is None:
                continue
            for tool in mcp_catalog.get(server_name, []) or []:
                tname = tool.get("name") if isinstance(tool, dict) else None
                if tname and tname not in seen:
                    seen.add(tname)
                    names.append(tname)
        elif entry not in seen:
            seen.add(entry)
            names.append(entry)
    return names


# ---------------------------------------------------------------------------
# Always-enabled categories — the global, role-independent set whose tools
# are loaded into the queen's prompt up front (full schemas).
# ---------------------------------------------------------------------------
#
# This is THE single source of truth for the "always-enabled" tier. Add a
# category name here and its tools are loaded up front for EVERY queen,
# regardless of persona. Everything else the queen is allowed to use defaults
# to *searchable* — only its name + one-line description ship in the prompt
# manifest, and the full schema is fetched on demand via the ``search_tools``
# tool (see ``QueenPhaseState``).
#
# Always-enabled tools bypass the per-queen allowlist (see
# ``QueenPhaseState._passes_allowlist``): the frontend disallows un-ticking
# them, and the backend enforces that by always granting them — a stale or
# malformed sidecar can never disable them. This is checked BEFORE the
# allowlist, so "always" means always.
#
# Lifecycle / synthetic tools (run_worker, suggest_colony, task_*, …) are
# already always-on because they are not MCP-origin tools and bypass the
# allowlist for free — they deliberately do NOT need listing here.
ALWAYS_ENABLED_CATEGORIES: frozenset[str] = frozenset(
    {
        "file_ops",
        "terminal_basic",
        "context_awareness",
        # Browser: the measured automation core only. The earlier
        # "all-or-nothing bundle" assumption did not survive contact with the
        # data — prod carry-vs-invoke sampling (2026-07) showed the
        # browser_extended tail (upload / dialog_respond / html / console /
        # get_text / shadow_query / select / resize) at 0–2 invocations per
        # 1k carries while being re-sent on every call. The core keeps every
        # tool a browser session needs to start and act; the tail is one
        # search_tools call away.
        "browser_core",
    }
)


def configured_always_enabled_categories() -> frozenset[str]:
    """Always-enabled tool categories, overridable via ``configuration.json``.

    Reads ``queen_tools.always_enabled_categories`` from the active
    HIVE_HOME ``configuration.json``. When set (a list of category names),
    it REPLACES the hardcoded :data:`ALWAYS_ENABLED_CATEGORIES` default —
    e.g. a chat-only persona can set ``["context_awareness"]`` to drop the
    file / terminal / browser bundles that otherwise bypass the per-queen
    allowlist and hand the model real machine control. When the field is
    absent, the hardcoded default applies (unchanged behavior).
    """
    try:
        from framework.config import get_hive_config

        override = get_hive_config().get("queen_tools", {}).get("always_enabled_categories")
        if isinstance(override, list) and all(isinstance(x, str) for x in override):
            return frozenset(override)
    except Exception:  # noqa: BLE001 — config is best-effort; fall back to default
        pass
    return ALWAYS_ENABLED_CATEGORIES


def always_enabled_tool_names(
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> set[str]:
    """Expand the always-enabled categories to concrete tool names.

    Uses :func:`configured_always_enabled_categories` (config override or
    the hardcoded :data:`ALWAYS_ENABLED_CATEGORIES` default). Resolves
    ``@server:NAME`` shorthands against ``mcp_catalog`` (e.g.
    ``@server:files-tools`` inside ``file_ops``). Returns a set for cheap
    membership tests. The searchable set is never enumerated here — it is the
    complement (everything allowed that is not in this set), so adding a tool
    to a category is the only edit needed to make it always-enabled.
    """
    names: set[str] = set()
    for category in configured_always_enabled_categories():
        names.update(resolve_category_tools(category, mcp_catalog))
    return names


# ---------------------------------------------------------------------------
# Worker keep-set — the eager tier for colony workers' tool tiering.
# ---------------------------------------------------------------------------
#
# Mirrors the queen trio above but drives ``ToolTierState`` at worker spawn
# (see ColonyRuntime._build_worker). The default is the MEASURED keep-set
# from the 2026-07 tool-cost analysis: everything at ≥5 invocations/1k
# carries plus the lifecycle tools those need to function. Everything else —
# integration bundles (senders / hubspot / github / crm), the browser and
# terminal extended tails, search_messages, pdf_read, chart_render — ships as
# a searchable manifest entry instead of a full schema (the measured-cold set
# was 56% of tool-schema spend). Non-MCP framework tools (task_* / tracker_* /
# report_to_parent / ask_user) bypass the split entirely — see
# ``ToolTierState.is_eager``. Set ``worker_tools.always_enabled_categories``
# in configuration.json to override; an empty list turns the split OFF
# (every tool eager).
WORKER_ALWAYS_ENABLED_CATEGORIES: frozenset[str] = frozenset(
    {
        "browser_core",
        "terminal_core",
        "files_core",
        "context_core",
        "web_core",
    }
)


def configured_worker_always_enabled_categories() -> frozenset[str]:
    """Worker keep-set categories, overridable via ``configuration.json``.

    Reads ``worker_tools.always_enabled_categories``. When set (a list of
    category names), it REPLACES :data:`WORKER_ALWAYS_ENABLED_CATEGORIES`.
    When absent, the hardcoded default applies.
    """
    try:
        from framework.config import get_hive_config

        override = get_hive_config().get("worker_tools", {}).get("always_enabled_categories")
        if isinstance(override, list) and all(isinstance(x, str) for x in override):
            return frozenset(override)
    except Exception:  # noqa: BLE001 — config is best-effort; fall back to default
        pass
    return WORKER_ALWAYS_ENABLED_CATEGORIES


def worker_always_enabled_tool_names(
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> set[str]:
    """Expand the worker keep-set categories to concrete tool names.

    Empty result ⇒ worker tiering stays dark (split disabled at spawn).
    """
    names: set[str] = set()
    for category in configured_worker_always_enabled_categories():
        names.update(resolve_category_tools(category, mcp_catalog))
    return names


def _parse_version(value: str | None) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple of ints.

    ``"0.2.19"`` → ``(0, 2, 19)``. Missing/malformed input → ``(0, 0, 0)``
    floor so legacy sidecars without ``saved_on_version`` are treated as
    older than every tracked addition and receive every GA grant on the
    first migration pass.
    """
    floor = (0, 0, 0)
    if not value:
        return floor
    parts: list[int] = []
    for chunk in value.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            return floor
    return tuple(parts) if parts else floor


def _category_fully_resolvable(
    category: str,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None,
) -> bool:
    """True iff every ``@server:`` shorthand in the category resolves to >=1 tool.

    A category with an unresolved shorthand (no catalog, or a stale/partial
    catalog missing that server) would expand to a too-small member set —
    inference must skip it rather than risk a false-positive grant.
    """
    for entry in _TOOL_CATEGORIES.get(category, []):
        if not entry.startswith("@server:"):
            continue
        server_name = entry[len("@server:") :]
        if not (mcp_catalog or {}).get(server_name):
            return False
    return True


def infer_category_additions(
    enabled: list[str],
    saved_on_version: str | None,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    """Grant recently-added category tools to a saved flat allowlist.

    A saved ``tools.json`` sidecar is a frozen list and never picks up a
    tool added to a category later. For each category in
    ``_CATEGORY_ADDITIONS``: if ``enabled`` already covers the whole
    category as it existed *before* any tracked addition, grant every
    addition whose GA-promotion version is newer than the sidecar's
    ``saved_on_version``. An addition with version <= ``saved_on_version``
    is left alone — the sidecar was saved on a release that already knew
    about the tool, so its absence is a deliberate untick.

    ``enabled`` is the queen's saved ``enabled_mcp_tools`` list. An empty
    list (``[]`` = disable-all) is returned unchanged; otherwise a new
    sorted list is returned.
    """
    if not enabled:
        return enabled

    saved = set(enabled)
    sidecar_version = _parse_version(saved_on_version)

    for category, additions in _CATEGORY_ADDITIONS.items():
        if not _category_fully_resolvable(category, mcp_catalog):
            continue
        members = set(resolve_category_tools(category, mcp_catalog))
        # The category as it predates every tracked addition.
        baseline = members - set(additions)
        if not baseline or not baseline.issubset(saved):
            continue
        saved |= {tool for tool, ver in additions.items() if sidecar_version < _parse_version(ver)}

    return sorted(saved)


def grant_role_default_additions(
    queen_id: str,
    enabled: list[str],
    saved_on_version: str | None,
) -> list[str]:
    """Append GA additions whose category sits in the queen's role default.

    Used by the runtime-startup GA tool migration AND by ``load_queen_tools_config``
    for queens with a known role. For each tool in ``_CATEGORY_ADDITIONS``
    whose category appears in ``QUEEN_DEFAULT_CATEGORIES[queen_id]``, grant
    it when its GA-promotion version is newer than the sidecar's
    ``saved_on_version``. An addition with version <= ``saved_on_version``
    is respected as a deliberate untick (the user saved on a release that
    already knew about the tool).
    Returns a new sorted list when grants were made, otherwise the original.

    Differs from ``infer_category_additions``: the signal is role-default
    membership (deterministic, works for small categories) rather than
    baseline coverage (heuristic, false-positive-prone). Queens without a
    role default — custom IDs — are skipped to avoid over-granting; callers
    fall through to ``infer_category_additions`` for that path.
    """
    if not enabled:
        return enabled
    categories = QUEEN_DEFAULT_CATEGORIES.get(queen_id)
    if not categories:
        return enabled

    saved = set(enabled)
    sidecar_version = _parse_version(saved_on_version)
    additions: set[str] = set()
    for category in categories:
        for tool, ver in _CATEGORY_ADDITIONS.get(category, {}).items():
            if tool in saved:
                continue
            if sidecar_version < _parse_version(ver):
                additions.add(tool)
    if not additions:
        return enabled
    return sorted(saved | additions)


def _credentialed_tool_names() -> set[str]:
    """Return the set of MCP tool names that are bound to an OAuth provider.

    Reads the credential adapter so the answer reflects every provider
    declared in ``CREDENTIAL_SPECS`` (Gmail, GitHub, Notion, …) without
    needing the live MCP catalog. Falls back to an empty set if
    ``aden_tools`` is unavailable so the rest of the resolver keeps
    working in stripped-down test environments.
    """
    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        return {name for name, provider in CredentialStoreAdapter.default().get_tool_provider_map().items() if provider}
    except Exception:
        logger.debug("Provider map unavailable for default-tools filter", exc_info=True)
        return set()


def resolve_queen_default_tools(
    queen_id: str,
    mcp_catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[str] | None:
    """Return the role-based default allowlist for ``queen_id``.

    Arguments:
        queen_id: Profile ID (e.g. ``"queen_technology"``).
        mcp_catalog: Optional mapping of ``{server_name: [{"name": ...}, ...]}``
            used to expand ``@server:NAME`` shorthands in categories AND
            to enumerate credential-less tools for the unknown-queen
            fallback. When absent, shorthand entries are dropped and the
            unknown-queen fallback returns ``None`` (legacy "allow all").

    Returns:
        A deduplicated list of tool names. OAuth-credentialed tools are
        always excluded from the default — for known queens because
        none of the role categories contain them, for unknown queens
        because the unknown-queen fallback (when given a catalog)
        explicitly drops every name with a provider. Users opt OAuth
        tools in per-queen via the Tool Library; that save writes a
        sidecar which then takes precedence over this function.

        Returns ``None`` only when the queen is unknown AND no catalog
        was supplied — preserving the legacy "allow every MCP tool"
        path for environments that can't enumerate the catalog.
    """
    credentialed = _credentialed_tool_names()
    categories = QUEEN_DEFAULT_CATEGORIES.get(queen_id)
    if not categories:
        # Unknown queen — fall back to "every credential-less MCP tool"
        # when we have a catalog to enumerate from. Without a catalog
        # there's nothing to filter against, so preserve the legacy
        # ``None`` (allow-all) so we don't accidentally lock the queen
        # out of every tool in stripped-down boot paths.
        if mcp_catalog is None:
            return None
        names: list[str] = []
        seen: set[str] = set()
        for entries in mcp_catalog.values():
            for tool in entries or []:
                tname = tool.get("name") if isinstance(tool, dict) else None
                if not tname or tname in seen:
                    continue
                if tname in credentialed:
                    continue
                seen.add(tname)
                names.append(tname)
        return names

    names = []
    seen = set()

    def _add(name: str) -> None:
        if not name or name in seen:
            return
        # Belt-and-braces: even if a category accidentally references a
        # credentialed tool (e.g. via ``@server:hive_tools`` picking up
        # gmail_*), drop it from the default. OAuth tools are opt-in
        # everywhere — users add them per-queen via the Tool Library.
        if name in credentialed:
            return
        seen.add(name)
        names.append(name)

    for cat in categories:
        for entry in _TOOL_CATEGORIES.get(cat, []):
            if entry.startswith("@server:"):
                server_name = entry[len("@server:") :]
                if mcp_catalog is None:
                    logger.debug(
                        "resolve_queen_default_tools: catalog missing; cannot expand %s",
                        entry,
                    )
                    continue
                for tool in mcp_catalog.get(server_name, []) or []:
                    tname = tool.get("name") if isinstance(tool, dict) else None
                    if tname:
                        _add(tname)
            else:
                _add(entry)

    return names
