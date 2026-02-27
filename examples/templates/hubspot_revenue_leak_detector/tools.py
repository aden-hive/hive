"""
HubSpot Revenue Leak Detector — Custom Tools

Architecture
------------
The LLM uses HubSpot MCP tools to fetch live deal data, then passes that data
to our Python tools which process it and store state via contextvars so it
flows cleanly across nodes without re-passing through the LLM.

Node flow:
  monitor   → hubspot_search_deals (MCP) + hubspot_get_contact (MCP)
              → scan_pipeline(cycle, deals)        [stores deals for analysis]
  analyze   → detect_revenue_leaks(cycle)          [reads stored deals]
  notify    → build_telegram_alert(...)            [returns HTML + chat_id]
              → telegram_send_message (MCP)
  followup  → prepare_followup_emails(cycle)       [reads GHOSTED leaks]
              → send_email (MCP) per GHOSTED contact

Required credentials (via env vars / MCP credential store):
  HUBSPOT_ACCESS_TOKEN  — HubSpot Private App token
  TELEGRAM_BOT_TOKEN    — Telegram bot token (chat_id auto-fetched if unset)
  TELEGRAM_CHAT_ID      — Optional; auto-fetched from getUpdates if not set
  RESEND_API_KEY        — Resend API key for email
                          (or Google OAuth configured via Aden for gmail provider)
"""

import contextvars
import html as _html
import httpx
import json
import os
from datetime import datetime, timezone
from typing import Any

from framework.llm.provider import Tool, ToolUse, ToolResult


# ---------------------------------------------------------------------------
# Session-isolated state (contextvars — thread + session safe)
# ---------------------------------------------------------------------------
_leaks_var: contextvars.ContextVar[list] = contextvars.ContextVar("_leaks")
_deals_cache_var: contextvars.ContextVar[list] = contextvars.ContextVar("_deals_cache", default=[])

MAX_CYCLES = 3         # halt after this many consecutive low-severity cycles
MAX_TOTAL_CYCLES = 10  # absolute cap — prevents infinite loops

_SEVERITY_EMOJI: dict[str, str] = {
    "low":      "🟢",
    "medium":   "🟡",
    "high":     "🔴",
    "critical": "🚨",
}

# HubSpot API deal stage → human-readable name
_STAGE_MAP: dict[str, str] = {
    "appointmentscheduled":  "Demo Scheduled",
    "qualifiedtobuy":        "Qualified",
    "presentationscheduled": "Proposal Sent",
    "decisionmakerboughtin": "Negotiation",
    "contractsent":          "Contract Sent",
    "closedwon":             "Closed Won",
    "closedlost":            "Closed Lost",
}


# ---------------------------------------------------------------------------
# Telegram chat_id auto-fetch helper
# ---------------------------------------------------------------------------

def _auto_fetch_telegram_chat_id() -> str:
    """
    Return TELEGRAM_CHAT_ID from env, or auto-fetch via getUpdates API.

    This is a bootstrapping/discovery call — there is no MCP tool that exposes
    getUpdates, and users have no practical way to find their chat_id otherwise.
    Returns empty string if Telegram is not configured.
    """
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if chat_id:
        return chat_id

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return ""

    try:
        resp = httpx.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok") and data.get("result"):
                for update in reversed(data["result"]):
                    msg = update.get("message") or update.get("channel_post")
                    if msg and "chat" in msg:
                        found = str(msg["chat"]["id"])
                        name = msg["chat"].get("username") or msg["chat"].get("first_name", "")
                        print(f"\n📱 Auto-detected Telegram chat_id: {found}  ({name})")
                        print(f'   Tip: export TELEGRAM_CHAT_ID="{found}" to skip auto-fetch\n')
                        return found
        print("\n⚠️  No Telegram updates found — send any message to your bot first, then retry.\n")
    except Exception as exc:
        print(f"\n⚠️  Could not auto-fetch Telegram chat_id: {exc}\n")

    return ""


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _scan_pipeline(cycle: int, deals: list | None = None) -> dict:
    """
    Process HubSpot deals fetched by the LLM via MCP tools and store them
    in module-level state for use by detect_revenue_leaks this cycle.

    The LLM should:
      1. Call hubspot_search_deals to get open deals (skip closedwon/closedlost)
      2. For each deal call hubspot_get_contact to get the contact email
      3. Call this tool with cycle and the assembled deals array

    Each deal object must include:
      id, contact, email, stage, days_inactive (int), value (int)

    Args:
        cycle: Current cycle number from context (0 on first run).
        deals: List of HubSpot deal objects assembled by the LLM.

    Returns:
        next_cycle         — incremented cycle number
        deals_scanned      — number of open deals processed
        overdue_invoices   — always 0 (not tracked via HubSpot deals API)
        support_escalations — always 0 (not tracked via HubSpot deals API)
        status             — "ok" or "no_deals"
    """
    try:
        cycle_num = int(float(cycle or 0))
    except (ValueError, TypeError):
        cycle_num = 0
    next_cycle = cycle_num + 1

    # Reset session state for this cycle
    _leaks_var.set([])
    _deals_cache_var.set([])

    if not deals:
        print(
            f"\n[scan_pipeline] Cycle {next_cycle} — no deals provided.\n"
            "  Ensure HUBSPOT_ACCESS_TOKEN is set and hubspot_search_deals returned results."
        )
        return {
            "next_cycle":             next_cycle,
            "deals_scanned":          0,
            "overdue_invoices":       0,
            "support_escalations":    0,
            "status":                 "no_deals",
        }

    # Normalise each deal — guard against LLM sending partial objects
    now = datetime.now(timezone.utc)
    normalised: list[dict] = []
    for raw in deals:
        if not isinstance(raw, dict):
            continue

        # Resolve days_inactive — accept pre-computed or calculate from timestamp
        days_inactive = raw.get("days_inactive", 0)
        if not days_inactive:
            last_mod = raw.get("hs_lastmodifieddate") or raw.get("lastmodifieddate", "")
            if last_mod:
                try:
                    dt = datetime.fromisoformat(str(last_mod).replace("Z", "+00:00"))
                    days_inactive = max(0, (now - dt).days)
                except (ValueError, OverflowError):
                    days_inactive = 0

        # Resolve stage — accept raw API key or already-mapped name
        raw_stage = str(raw.get("stage") or raw.get("dealstage") or "unknown")
        stage = _STAGE_MAP.get(raw_stage, raw_stage.replace("_", " ").title())

        # Skip closed deals
        if raw_stage in ("closedwon", "closedlost"):
            continue

        try:
            value = int(float(raw.get("value") or raw.get("amount") or 0))
        except (ValueError, TypeError):
            value = 0

        normalised.append({
            "id":            str(raw.get("id", "")),
            "contact":       str(raw.get("contact") or raw.get("dealname") or "Unknown Deal"),
            "email":         str(raw.get("email", "")),
            "stage":         stage,
            "days_inactive": int(days_inactive),
            "value":         value,
        })

    _deals_cache_var.set(normalised)

    print(f"\n[scan_pipeline] Cycle {next_cycle} — {len(normalised)} open deal(s) from HubSpot")
    for d in normalised:
        print(
            f"  • {d['contact']}  stage={d['stage']}  "
            f"inactive={d['days_inactive']}d  value=${d['value']:,}  "
            f"email={d['email'] or '—'}"
        )

    return {
        "next_cycle":             next_cycle,
        "deals_scanned":          len(normalised),
        "overdue_invoices":       0,
        "support_escalations":    0,
        "status":                 "ok",
    }


def _detect_revenue_leaks(cycle: int) -> dict:
    """
    Analyse the deals stored by scan_pipeline and detect revenue leak patterns.

    Must be called AFTER scan_pipeline in the same cycle.

    Leak types:
      GHOSTED  — deal silent for 21+ days (highest priority)
      STALLED  — deal inactive 10–20 days, stuck in same stage

    Args:
        cycle: Current monitoring cycle (use next_cycle from scan_pipeline).

    Returns:
        leak_count      — total leaks detected
        severity        — low / medium / high / critical
        total_at_risk   — USD sum of at-risk deal values
        halt            — True when agent should stop looping
    """
    try:
        cycle_num = int(float(cycle or 0))
    except (ValueError, TypeError):
        cycle_num = 0

    deals = _deals_cache_var.get([])

    if not deals:
        _no_data_halt = cycle_num >= MAX_CYCLES
        print(
            f"[detect_revenue_leaks] Cycle {cycle_num} — no deal data in cache, "
            f"halt={_no_data_halt}"
        )
        return {
            "cycle":         cycle_num,
            "leak_count":    0,
            "severity":      "low",
            "total_at_risk": 0,
            "halt":          _no_data_halt,
            "warning":       "No deal data — call scan_pipeline first each cycle",
        }

    leaks: list[dict] = []
    for deal in deals:
        days  = deal.get("days_inactive", 0)
        did   = deal.get("id", "")
        name  = deal.get("contact", "Unknown")
        value = deal.get("value", 0)
        stage = deal.get("stage", "Unknown")
        email = deal.get("email", "")

        if days >= 21:
            leaks.append({
                "type":           "GHOSTED",
                "deal_id":        did,
                "contact":        name,
                "email":          email,
                "value":          value,
                "days_inactive":  days,
                "stage":          stage,
                "recommendation": (
                    f"Send re-engagement sequence to {name} immediately — "
                    f"silent for {days} days."
                ),
            })
        elif days >= 10:
            leaks.append({
                "type":           "STALLED",
                "deal_id":        did,
                "contact":        name,
                "email":          email,
                "value":          value,
                "days_inactive":  days,
                "stage":          stage,
                "recommendation": (
                    f"Schedule an unblocking call with {name} — "
                    f"stuck in \'{stage}\' for {days} days."
                ),
            })

    _leaks_var.set(leaks)

    total_at_risk = int(sum(l.get("value", 0) for l in leaks))
    ghosted_count = sum(1 for l in leaks if l["type"] == "GHOSTED")

    if ghosted_count >= 2 or total_at_risk >= 50_000:
        severity = "critical"
        halt     = True
    elif len(leaks) >= 3 or total_at_risk >= 20_000:
        severity = "high"
        halt     = False
    elif len(leaks) >= 1:
        severity = "medium"
        halt     = False
    else:
        severity = "low"
        halt     = cycle_num >= MAX_CYCLES

    if not halt and cycle_num >= MAX_TOTAL_CYCLES:
        halt = True

    print(
        f"[detect_revenue_leaks] Cycle {cycle_num} — "
        f"{len(leaks)} leak(s) | severity={severity} | "
        f"at_risk=${total_at_risk:,} | halt={halt}"
    )

    return {
        "cycle":         cycle_num,
        "leak_count":    len(leaks),
        "severity":      severity,
        "total_at_risk": total_at_risk,
        "halt":          halt,
    }


def _build_telegram_alert(
    cycle: int,
    leak_count: int,
    severity: str,
    total_at_risk: int,
) -> dict:
    """
    Print a rich console report and build an HTML Telegram alert.

    Auto-fetches TELEGRAM_CHAT_ID via getUpdates if not set in env.
    Users often don't know their chat_id — this discovery call removes that friction.

    Args:
        cycle:         Current monitoring cycle.
        leak_count:    Total leaks detected this cycle.
        severity:      Overall severity (low / medium / high / critical).
        total_at_risk: Total USD value at risk.

    Returns:
        html_message  — HTML string ready for telegram_send_message
        chat_id       — Telegram chat ID (from env or auto-fetched; empty if unavailable)
        cycle / severity / leak_count / total_at_risk — echoed for context
    """
    try:
        cycle_num      = int(float(cycle or 0))
        leak_count_int = int(float(leak_count or 0))
        at_risk_int    = int(float(total_at_risk or 0))
    except (ValueError, TypeError):
        cycle_num = leak_count_int = at_risk_int = 0

    sev   = str(severity).lower()
    emoji = _SEVERITY_EMOJI.get(sev, "⚪")
    leaks = _leaks_var.get([])
    esc   = _html.escape

    # ── Console report ──────────────────────────────────────────────────────
    border = "═" * 64
    thin   = "─" * 64
    print(f"\n{border}")
    print(f"  💰  HUBSPOT REVENUE LEAK DETECTOR  ·  Cycle {cycle_num}")
    print(f"{border}")
    print(f"  Severity        : {emoji}  {sev.upper()}")
    print(f"  Leaks Detected  : {leak_count_int}")
    print(f"  Total At Risk   : ${at_risk_int:,}")
    print(f"{thin}")

    if not leaks:
        print("  ✅  Pipeline healthy — no revenue leaks detected.")
    else:
        for i, leak in enumerate(leaks, 1):
            lt = leak.get("type", "UNKNOWN")
            print(f"\n  [{i}]  {lt}")
            print(f"        Deal     :  {leak.get('deal_id', '')}  ({leak.get('contact', '')})")
            print(f"        Stage    :  {leak.get('stage', '')}")
            print(f"        Inactive :  {leak.get('days_inactive', 0)} days")
            print(f"        Value    :  ${leak.get('value', 0):,}")
            print(f"        ➜  {leak.get('recommendation', '')}")

    print(f"\n{thin}")
    action_console = {
        "critical": "🚨  CRITICAL — Escalating to VP Sales & Finance immediately.",
        "high":     "🔴  HIGH PRIORITY — Assign owners, act within 24 hours.",
        "medium":   "🟡  MEDIUM — Review findings and schedule follow-ups.",
        "low":      "🟢  Pipeline healthy — continue monitoring.",
    }.get(sev, "")
    print(f"  {action_console}")
    print(f"{border}\n")

    # ── Telegram HTML message ─────────────────────────────────────────────
    lines = [
        f"<b>💰 HubSpot Revenue Leak Detector — Cycle {cycle_num}</b>",
        "",
        f"Severity:       {emoji} <b>{sev.upper()}</b>",
        f"Leaks detected: <b>{leak_count_int}</b>",
        f"Total at risk:  <b>${at_risk_int:,}</b>",
        "",
    ]

    if not leaks:
        lines.append("✅ Pipeline healthy — no leaks found.")
    else:
        for i, leak in enumerate(leaks, 1):
            lt = esc(leak.get("type", "UNKNOWN"))
            lines.append(f"<b>[{i}] {lt}</b>")
            lines.append(
                f"  Deal    : {esc(str(leak.get('deal_id', '')))} "
                f"({esc(str(leak.get('contact', '')))}) "
            )
            lines.append(
                f"  Stage   : {esc(str(leak.get('stage', '')))}  |  "
                f"Inactive {esc(str(leak.get('days_inactive', 0)))}d"
            )
            lines.append(f"  Value   : ${leak.get('value', 0):,}")
            lines.append(f"  ➜ {esc(str(leak.get('recommendation', '')))}")
            lines.append("")

    action_tg = {
        "critical": "🚨 ESCALATE to VP Sales &amp; Finance immediately.",
        "high":     "🔴 Assign owners — act within 24 hours.",
        "medium":   "🟡 Review and schedule follow-ups.",
        "low":      "🟢 Continue monitoring.",
    }.get(sev, "")
    if action_tg:
        lines.append(action_tg)

    html_message = "\n".join(lines)
    chat_id      = _auto_fetch_telegram_chat_id()

    if not chat_id:
        print(
            "  ⚠️  Telegram alert cannot be sent — TELEGRAM_BOT_TOKEN not set or "
            "no updates found.\n"
            "     Set TELEGRAM_BOT_TOKEN and send any message to your bot first."
        )

    return {
        "cycle":         cycle_num,
        "severity":      sev,
        "leak_count":    leak_count_int,
        "total_at_risk": at_risk_int,
        "html_message":  html_message,
        "chat_id":       chat_id,
    }


def _prepare_followup_emails(cycle: int) -> dict:
    """
    Build follow-up email payloads for every GHOSTED contact this cycle.

    The LLM should call send_email MCP tool for each contact in the
    returned `contacts` list.

    Args:
        cycle: Current monitoring cycle.

    Returns:
        contacts: List of dicts — one per GHOSTED contact — each with:
          contact   — display name
          email     — recipient address
          deal_id   — HubSpot deal ID
          subject   — email subject line
          html      — full HTML email body ready to pass to send_email
        message: Human-readable summary
    """
    try:
        cycle_num = int(float(cycle or 0))
    except (ValueError, TypeError):
        cycle_num = 0

    ghosted = [l for l in _leaks_var.get([]) if l.get("type") == "GHOSTED"]

    if not ghosted:
        print(
            f"\n[prepare_followup_emails] Cycle {cycle_num} — "
            "no GHOSTED contacts this cycle, nothing to send."
        )
        return {
            "contacts": [],
            "message":  f"No GHOSTED contacts in Cycle {cycle_num}.",
        }

    contacts: list[dict] = []
    skipped: list[str]   = []

    for leak in ghosted:
        contact  = str(leak.get("contact", "there"))
        to_email = str(leak.get("email", "")).strip()
        days     = int(leak.get("days_inactive", 0))
        value    = int(leak.get("value", 0))
        deal_id  = str(leak.get("deal_id", ""))

        if not to_email:
            skipped.append(contact)
            continue

        subject = f"Following up on our conversation — {contact}"
        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body  {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333;
              max-width: 600px; margin: 0 auto; padding: 20px; }}
    h2    {{ color: #2c3e50; }}
    p     {{ margin: 12px 0; }}
    hr    {{ border: none; border-top: 1px solid #e0e0e0; margin: 20px 0; }}
    .meta {{ color: #888; font-size: 12px; }}
  </style>
</head>
<body>
  <h2>Following up — {_html.escape(contact)}</h2>
  <p>Hi {_html.escape(contact)},</p>
  <p>It has been <strong>{days} days</strong> since we last connected, and I
  wanted to make sure our conversation did not fall through the cracks.</p>
  <p>There is a real opportunity here that could deliver meaningful value for
  your team. Could we find <strong>15 minutes this week</strong> to reconnect?</p>
  <p>Just reply to this email and we can find a time that works.</p>
  <hr>
  <p class="meta">Deal ref: {_html.escape(deal_id)} &nbsp;|&nbsp; Value: ${value:,}</p>
</body>
</html>"""

        contacts.append({
            "contact": contact,
            "email":   to_email,
            "deal_id": deal_id,
            "subject": subject,
            "html":    html,
        })

    parts = [f"{len(contacts)} follow-up email(s) prepared for Cycle {cycle_num}"]
    if skipped:
        parts.append(
            f"{len(skipped)} skipped (no email on record): {', '.join(skipped)}"
        )
    summary = ".  ".join(parts) + "."

    print(f"\n[prepare_followup_emails] {summary}")
    for c in contacts:
        print(f"  ✉️  To: {c['contact']} <{c['email']}>")

    return {"contacts": contacts, "message": summary}


# ---------------------------------------------------------------------------
# TOOLS dict — discovered by ToolRegistry.discover_from_module()
# ---------------------------------------------------------------------------

TOOLS: dict[str, Tool] = {
    "scan_pipeline": Tool(
        name="scan_pipeline",
        description=(
            "Process and store HubSpot deals fetched via MCP tools for analysis. "
            "Call AFTER fetching deals with hubspot_search_deals and contact emails "
            "with hubspot_get_contact. Pass the assembled deals array."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type":        "integer",
                    "description": "Current cycle number from context (0 on first run).",
                },
                "deals": {
                    "type":        "array",
                    "description": (
                        "Array of open HubSpot deal objects. Each must include: "
                        "id (string), contact (string — deal/company name), "
                        "email (string — primary contact email), "
                        "stage (string — deal stage name), "
                        "days_inactive (integer — days since last activity), "
                        "value (integer — deal amount in USD). "
                        "Omit closedwon and closedlost deals."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":            {"type": "string"},
                            "contact":       {"type": "string"},
                            "email":         {"type": "string"},
                            "stage":         {"type": "string"},
                            "days_inactive": {"type": "integer"},
                            "value":         {"type": "integer"},
                        },
                        "required": ["id", "contact", "stage", "days_inactive", "value"],
                    },
                },
            },
            "required": ["cycle"],
        },
    ),
    "detect_revenue_leaks": Tool(
        name="detect_revenue_leaks",
        description=(
            "Analyse stored HubSpot deals and classify revenue leak patterns: "
            "GHOSTED (21+ days silent) and STALLED (10-20 days inactive). "
            "Must be called AFTER scan_pipeline. Returns leak_count, severity, "
            "total_at_risk, and halt flag."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type":        "integer",
                    "description": "Cycle number (use next_cycle returned by scan_pipeline).",
                },
            },
            "required": ["cycle"],
        },
    ),
    "build_telegram_alert": Tool(
        name="build_telegram_alert",
        description=(
            "Print a rich console cycle report and build an HTML Telegram alert. "
            "Returns html_message and chat_id — pass both to telegram_send_message. "
            "Auto-fetches chat_id via getUpdates if TELEGRAM_CHAT_ID is not set. "
            "Call AFTER detect_revenue_leaks."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle":         {"type": "integer", "description": "Current cycle number."},
                "leak_count":    {"type": "integer", "description": "Total leaks detected."},
                "severity":      {"type": "string",  "description": "low / medium / high / critical"},
                "total_at_risk": {"type": "integer", "description": "Total USD value at risk."},
            },
            "required": ["cycle", "leak_count", "severity", "total_at_risk"],
        },
    ),
    "prepare_followup_emails": Tool(
        name="prepare_followup_emails",
        description=(
            "Build ready-to-send email payloads for all GHOSTED contacts this cycle. "
            "Returns a contacts array — call send_email MCP tool for each entry "
            "using provider=\"resend\" (or \"gmail\"). "
            "Must be called AFTER detect_revenue_leaks."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type":        "integer",
                    "description": "Current monitoring cycle.",
                },
            },
            "required": ["cycle"],
        },
    ),
}


# ---------------------------------------------------------------------------
# Unified tool executor — dispatches to private handler functions
# ---------------------------------------------------------------------------

_TOOL_HANDLERS: dict[str, Any] = {
    "scan_pipeline":           _scan_pipeline,
    "detect_revenue_leaks":    _detect_revenue_leaks,
    "build_telegram_alert":    _build_telegram_alert,
    "prepare_followup_emails": _prepare_followup_emails,
}


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch a ToolUse to the correct handler and return a JSON ToolResult."""
    handler = _TOOL_HANDLERS.get(tool_use.name)
    if handler is None:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
            is_error=True,
        )
    try:
        result = handler(**tool_use.input)
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps(result),
        )
    except Exception as exc:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": str(exc)}),
            is_error=True,
        )
