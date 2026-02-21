"""
Revenue Leak Detector — Custom Tools

Scans a CRM / invoice / support pipeline each cycle and detects four
revenue-leak patterns:

  GHOSTED         — prospect silent for 21+ days
  STALLED         — deal stuck in same stage for 10-20 days
  OVERDUE_PAYMENT — invoice unpaid past due date
  CHURN_RISK      — 3+ unresolved support escalations

Tools are registered via TOOLS dict + tool_executor() — discovered automatically
by ToolRegistry.discover_from_module() at agent startup.

Optional environment variables:
  HUBSPOT_API_KEY      — HubSpot Private App token for live CRM data
  TELEGRAM_BOT_TOKEN   — token from @BotFather for real Telegram alerts
  TELEGRAM_CHAT_ID     — your chat / group / channel ID
  GMAIL_USER           — Gmail address for follow-up emails
  GMAIL_APP_PASSWORD   — Gmail App Password (16-char token)

All integrations are optional — the agent runs fully offline without any
credentials set.
"""

import contextvars
import json
import os
from typing import Any

from framework.llm.provider import Tool, ToolUse, ToolResult


# ---------------------------------------------------------------------------
# Session-isolated in-process state (contextvars — thread + session safe)
# ---------------------------------------------------------------------------
_cycle_data_var: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_cycle_data", default={}
)
_leaks_var: contextvars.ContextVar[list] = contextvars.ContextVar(
    "_leaks", default=[]
)

MAX_CYCLES = 3  # halt after this many consecutive low-severity cycles


# ---------------------------------------------------------------------------
# HubSpot CRM integration helpers  
# ---------------------------------------------------------------------------

def _fetch_hubspot_contact_emails(headers: dict, deal_ids: list) -> dict:
    """
    Batch-fetch the primary contact email for each HubSpot deal_id.
    Returns {deal_id: email}.  Silently ignores any per-deal failures.
    """
    result: dict = {}
    try:
        import httpx
        for deal_id in deal_ids[:10]:          # cap at 10 to avoid rate limits
            r = httpx.get(
                f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}/associations/contacts",
                headers=headers,
                timeout=10.0,
            )
            if r.status_code != 200:
                continue
            contact_ids = [x["id"] for x in r.json().get("results", [])]
            if not contact_ids:
                continue
            cr = httpx.get(
                f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_ids[0]}"
                "?properties=email,firstname,lastname",
                headers=headers,
                timeout=10.0,
            )
            if cr.status_code == 200:
                email = cr.json().get("properties", {}).get("email", "")
                if email:
                    result[str(deal_id)] = email
    except Exception:
        pass
    return result


def _fetch_hubspot_deals() -> "dict | None":
    """
    Pull open deals from HubSpot CRM v3 API and return a pipeline snapshot
    dict (same shape as _PIPELINE_DB entries), or None when HUBSPOT_API_KEY
    is absent / the request fails — caller then falls back to _PIPELINE_DB.

    Required env var:
      HUBSPOT_API_KEY  — Private App token from HubSpot:
                         Settings → Integrations → Private Apps → Create
                         (scopes needed: crm.objects.deals.read,
                                         crm.objects.contacts.read)
    """
    api_key = os.getenv("HUBSPOT_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        import httpx
        from datetime import datetime, timezone

        headers = {"Authorization": f"Bearer {api_key}"}
        now     = datetime.now(timezone.utc)

        stage_map = {
            "appointmentscheduled":  "Demo Scheduled",
            "qualifiedtobuy":        "Qualified",
            "presentationscheduled": "Proposal Sent",
            "decisionmakerboughtin": "Negotiation",
            "contractsent":          "Contract Sent",
        }

        resp = httpx.get(
            "https://api.hubapi.com/crm/v3/objects/deals",
            headers=headers,
            params={
                "properties": "dealname,dealstage,amount,hs_lastmodifieddate",
                "limit": 50,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            print(f"[HubSpot] API {resp.status_code} — falling back to simulated data")
            return None

        deals: list = []
        deal_ids: list = []
        for item in resp.json().get("results", []):
            props = item.get("properties", {})
            stage = props.get("dealstage", "unknown")
            if stage in ("closedwon", "closedlost"):
                continue

            days_inactive = 0
            last_mod = props.get("hs_lastmodifieddate", "")
            if last_mod:
                try:
                    dt = datetime.fromisoformat(last_mod.replace("Z", "+00:00"))
                    days_inactive = max(0, (now - dt).days)
                except Exception:
                    pass

            value = 0
            try:
                value = int(float(props.get("amount") or 0))
            except (ValueError, TypeError):
                pass

            deals.append({
                "id":           item["id"],
                "contact":      props.get("dealname", "Unknown Deal"),
                "email":        "",
                "stage":        stage_map.get(stage, stage.replace("_", " ").title()),
                "days_inactive": days_inactive,
                "value":        value,
            })
            deal_ids.append(item["id"])

        emails = _fetch_hubspot_contact_emails(headers, deal_ids)
        for deal in deals:
            deal["email"] = emails.get(str(deal["id"]), "")

        print(f"[HubSpot] Fetched {len(deals)} open deals via API")
        return {
            "deals":              deals,
            "overdue_payments":   [],
            "support_escalations": 0,
            "_source":            "hubspot",
        }

    except Exception as exc:
        print(f"[HubSpot] Error: {exc} — falling back to simulated data")
        return None


# ---------------------------------------------------------------------------
# Tool implementations (private — called via tool_executor)
# ---------------------------------------------------------------------------

def _scan_pipeline(cycle: int) -> dict:
    """
    Scan the CRM pipeline for the next monitoring cycle.

    Args:
        cycle: Current cycle number from context (0 on first run).

    Returns:
        next_cycle      — incremented cycle number
        deals_scanned   — number of open deals found
        overdue_invoices — number of overdue invoices
        support_escalations — open support tickets needing action
    """
    next_cycle = int(cycle) + 1

    # Use HubSpot CRM; fall back to empty snapshot if API key not set
    hs_data = _fetch_hubspot_deals()
    data = hs_data if hs_data is not None else {
        "deals": [],
        "overdue_payments": [],
        "support_escalations": 0,
    }

    _cycle_data_var.set(data)

    source = data.get("_source", "simulated")
    print(
        f"\n[scan_pipeline] Cycle {next_cycle} [{source}] — "
        f"{len(data['deals'])} deals | "
        f"{len(data['overdue_payments'])} overdue invoices | "
        f"{data['support_escalations']} escalations"
    )

    return {
        "next_cycle": next_cycle,
        "deals_scanned": len(data["deals"]),
        "overdue_invoices": len(data["overdue_payments"]),
        "support_escalations": data["support_escalations"],
    }


def _detect_revenue_leaks(cycle: int) -> dict:
    """
    Analyse the latest pipeline snapshot and detect revenue leak patterns.

    Leak types:
      GHOSTED         — prospect silent for 21+ days (deal still open)
      STALLED         — deal inactive 10-20 days, stuck in same stage
      OVERDUE_PAYMENT — invoice unpaid after due date
      CHURN_RISK      — 3+ unresolved support escalations

    Args:
        cycle: Current monitoring cycle (for report labelling).

    Returns:
        leak_count      — total number of leaks found
        severity        — overall severity (low / medium / high / critical)
        total_at_risk   — USD value at risk across all leaks
        halt            — True when severity reaches critical
    """
    data = _cycle_data_var.get()
    leaks: list[dict] = []

    # ---- Deal-level leak detection ----
    for deal in data.get("deals", []):
        days = deal.get("days_inactive", 0)
        if days >= 21:
            leaks.append({
                "type": "GHOSTED",
                "deal_id": deal["id"],
                "contact": deal["contact"],
                "email": deal.get("email", ""),
                "value": deal["value"],
                "days_inactive": days,
                "stage": deal["stage"],
                "recommendation": (
                    f"Send re-engagement sequence to {deal['contact']} immediately. "
                    f"Deal has been silent for {days} days."
                ),
            })
        elif days >= 10:
            leaks.append({
                "type": "STALLED",
                "deal_id": deal["id"],
                "contact": deal["contact"],
                "email": deal.get("email", ""),
                "value": deal["value"],
                "days_inactive": days,
                "stage": deal["stage"],
                "recommendation": (
                    f"Schedule an unblocking call with {deal['contact']} — "
                    f"stuck in '{deal['stage']}' for {days} days."
                ),
            })

    # ---- Invoice-level leak detection ----
    for payment in data.get("overdue_payments", []):
        leaks.append({
            "type": "OVERDUE_PAYMENT",
            "invoice_id": payment["id"],
            "client": payment["client"],
            "amount": payment["amount"],
            "days_overdue": payment["days_overdue"],
            "recommendation": (
                f"Escalate {payment['id']} (${payment['amount']:,}) to Finance — "
                f"{payment['days_overdue']} days overdue."
            ),
        })

    # ---- Support escalation risk ----
    escalations = data.get("support_escalations", 0)
    if escalations >= 3:
        leaks.append({
            "type": "CHURN_RISK",
            "escalations": escalations,
            "value": 0,
            "recommendation": (
                f"Assign a Senior CSM immediately: {escalations} open support "
                f"escalations — high churn risk."
            ),
        })

    _leaks_var.set(leaks)

    # ---- Severity calculation ----
    total_at_risk = sum(l.get("value", l.get("amount", 0)) for l in leaks)
    critical_signals = [l for l in leaks if l["type"] in ("GHOSTED", "CHURN_RISK")]

    if len(critical_signals) >= 2 or total_at_risk >= 50000:
        severity = "critical"
        halt = True
    elif len(leaks) >= 3 or total_at_risk >= 20000:
        severity = "high"
        halt = False
    elif len(leaks) >= 1:
        severity = "medium"
        halt = False
    else:
        severity = "low"
        halt = int(cycle) >= MAX_CYCLES  # stop after MAX_CYCLES with no leaks

    print(
        f"[detect_revenue_leaks] Cycle {cycle} — "
        f"{len(leaks)} leaks | severity={severity} | at_risk=${total_at_risk:,} | halt={halt}"
    )

    return {
        "cycle": int(cycle),
        "leak_count": len(leaks),
        "severity": severity,
        "total_at_risk": total_at_risk,
        "halt": halt,
    }


# ---------------------------------------------------------------------------
# Telegram delivery helper
# ---------------------------------------------------------------------------

def _send_telegram(text: str) -> dict:
    """
    Send *text* to Telegram if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set.

    Returns a dict describing what happened:
      {"telegram": "sent",   "message_id": <int>}   — real message delivered
      {"telegram": "skipped","reason": "<why>"}      — env vars missing / disabled
      {"telegram": "error",  "detail": "<message>"}  — API call failed
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()

    if not bot_token or not chat_id:
        missing = []
        if not bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return {
            "telegram": "skipped",
            "reason": f"env vars not set: {', '.join(missing)}",
        }

    try:
        import httpx  # already in the workspace venv via aden_tools
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15.0,
        )
        data = resp.json()
        if data.get("ok"):
            return {"telegram": "sent", "message_id": data["result"]["message_id"]}
        return {"telegram": "error", "detail": data.get("description", str(data))}
    except Exception as exc:
        return {"telegram": "error", "detail": str(exc)}


def _build_telegram_message(
    cycle: int,
    severity: str,
    leak_count: int,
    total_at_risk: int,
    leaks: list,
) -> str:
    """Build an HTML-formatted Telegram message from the current leak report."""
    sev = str(severity).lower()
    emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨"}.get(sev, "⚪")

    lines = [
        f"<b>💰 Revenue Leak Detector — Cycle {cycle}</b>",
        "",
        f"Severity:       {emoji} <b>{sev.upper()}</b>",
        f"Leaks detected: <b>{int(leak_count)}</b>",
        f"Total at risk:  <b>${int(total_at_risk):,}</b>",
        "",
    ]

    if not leaks:
        lines.append("✅ Pipeline healthy — no leaks found.")
    else:
        for i, leak in enumerate(leaks, 1):
            t = leak.get("type", "UNKNOWN")
            lines.append(f"<b>[{i}] {t}</b>")
            if t in ("GHOSTED", "STALLED"):
                lines.append(f"  Deal    : {leak.get('deal_id')} ({leak.get('contact')})")
                lines.append(f"  Stage   : {leak.get('stage')}  |  Inactive {leak.get('days_inactive')}d")
                lines.append(f"  Value   : ${leak.get('value', 0):,}")
            elif t == "OVERDUE_PAYMENT":
                lines.append(f"  Invoice : {leak.get('invoice_id')} ({leak.get('client')})")
                lines.append(f"  Amount  : ${leak.get('amount', 0):,}  |  {leak.get('days_overdue')}d overdue")
            elif t == "CHURN_RISK":
                lines.append(f"  Open escalations: {leak.get('escalations')}")
            lines.append(f"  ➜ {leak.get('recommendation')}")
            lines.append("")

    action = {
        "critical": "🚨 ESCALATE to VP Sales &amp; Finance immediately.",
        "high":     "🔴 Assign owners — act within 24 hours.",
        "medium":   "🟡 Review and schedule follow-ups.",
        "low":      "🟢 Continue monitoring.",
    }.get(sev, "")
    if action:
        lines.append(action)

    return "\n".join(lines)


def _send_revenue_alert(cycle: int, leak_count: int, severity: str, total_at_risk: int) -> dict:
    """
    Send a formatted revenue leak alert to the operations team.

    Prints a full structured report to the console AND — when
    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set in the environment —
    delivers the same alert to a real Telegram chat/group.

    How to enable Telegram:
      1. Message @BotFather on Telegram → /newbot → copy the token
      2. Add the bot to your group, or DM it and visit:
         https://api.telegram.org/bot<TOKEN>/getUpdates  to find your chat_id
      3. Export the variables before running:
           export TELEGRAM_BOT_TOKEN="7123456789:AAF..."
           export TELEGRAM_CHAT_ID="-1001234567890"

    Args:
        cycle:          Current monitoring cycle number.
        leak_count:     Number of leaks found this cycle.
        severity:       Overall severity (low / medium / high / critical).
        total_at_risk:  Total USD value at risk this cycle.

    Returns:
        Confirmation dict including telegram delivery status.
    """
    sev = str(severity).lower()
    severity_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨",
    }.get(sev, "⚪")

    leaks = _leaks_var.get()

    # ---- Console report (always printed) ----
    border = "═" * 64
    thin   = "─" * 64

    print(f"\n{border}")
    print(f"  💰  REVENUE LEAK DETECTOR  ·  Cycle {cycle} Report")
    print(f"{border}")
    print(f"  Severity        : {severity_emoji}  {sev.upper()}")
    print(f"  Leaks Detected  : {int(leak_count)}")
    print(f"  Total At Risk   : ${int(total_at_risk):,}")
    print(f"{thin}")

    if not leaks:
        print("  ✅  Pipeline healthy — no revenue leaks detected.")
    else:
        for i, leak in enumerate(leaks, 1):
            leak_type = leak.get("type", "UNKNOWN")
            print(f"\n  [{i}]  {leak_type}")
            if leak_type in ("GHOSTED", "STALLED"):
                print(f"        Deal     :  {leak.get('deal_id')}  ({leak.get('contact')})")
                print(f"        Stage    :  {leak.get('stage')}")
                print(f"        Inactive :  {leak.get('days_inactive')} days")
                print(f"        Value    :  ${leak.get('value', 0):,}")
            elif leak_type == "OVERDUE_PAYMENT":
                print(f"        Invoice  :  {leak.get('invoice_id')}  ({leak.get('client')})")
                print(f"        Amount   :  ${leak.get('amount', 0):,}")
                print(f"        Overdue  :  {leak.get('days_overdue')} days")
            elif leak_type == "CHURN_RISK":
                print(f"        Open Escalations :  {leak.get('escalations')}")
            print(f"        ➜  {leak.get('recommendation')}")

    print(f"\n{thin}")
    if sev == "critical":
        print(f"  🚨  CRITICAL — Escalating to VP Sales & Finance immediately.")
        print(f"      Immediate action required across {int(leak_count)} revenue risks.")
    elif sev == "high":
        print(f"  🔴  HIGH PRIORITY — Assign owners and act within 24 hours.")
    elif sev == "medium":
        print(f"  🟡  MEDIUM — Review findings and schedule follow-ups.")
    else:
        print(f"  🟢  Pipeline healthy — continue monitoring.")
    print(f"{border}\n")

    # ---- Real Telegram delivery ----
    tg_message = _build_telegram_message(
        cycle=int(cycle),
        severity=severity,
        leak_count=int(leak_count),
        total_at_risk=int(total_at_risk),
        leaks=leaks,
    )
    tg_result = _send_telegram(tg_message)

    if tg_result["telegram"] == "sent":
        print(f"  ✅  Telegram alert sent (message_id={tg_result['message_id']})")
    elif tg_result["telegram"] == "skipped":
        print(f"  ℹ️   Telegram skipped — {tg_result['reason']}")
        print(f"       Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to enable real alerts.")
    else:
        print(f"  ⚠️   Telegram delivery failed: {tg_result.get('detail')}")

    return {
        "sent": True,
        "cycle": int(cycle),
        "severity": severity,
        "leaks_reported": int(leak_count),
        "total_at_risk_usd": int(total_at_risk),
        "telegram": tg_result,
    }


def _send_followup_emails(cycle: int) -> dict:
    """
    Send re-engagement emails to every GHOSTED contact found this cycle.

    Uses Gmail SMTP when GMAIL_USER + GMAIL_APP_PASSWORD are set; otherwise
    prints a dry-run preview so the agent runs fully offline.

    How to enable Gmail:
      1. Enable 2-Step Verification on your Google account.
      2. Go to myaccount.google.com → Security → App Passwords → generate.
      3. Export before running:
           export GMAIL_USER="you@gmail.com"
           export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"

    How to get contact emails automatically:
      Set HUBSPOT_API_KEY — scan_pipeline will fetch real contact emails
      from HubSpot and they will appear in GHOSTED/STALLED leak records.

    Args:
        cycle: Current monitoring cycle (for log labels).

    Returns:
        emails_sent:      number of emails dispatched (or dry-run previewed)
        contacts_emailed: list of contact names
        delivery_method:  "gmail" | "console"
    """
    ghosted = [l for l in _leaks_var.get() if l.get("type") == "GHOSTED"]

    if not ghosted:
        print(f"\n[send_followup_emails] Cycle {cycle} — no GHOSTED contacts, skipping.")
        return {"emails_sent": 0, "contacts_emailed": [], "delivery_method": "none"}

    gmail_user = os.getenv("GMAIL_USER", "").strip()
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    sent:   list[str] = []
    method: str       = "console"
    border = "─" * 64

    print(f"\n{border}")
    print(f"  ✉️   FOLLOWUP EMAILS  ·  Cycle {cycle}")
    print(f"{border}")

    for leak in ghosted:
        contact  = leak["contact"]
        to_email = leak.get("email", "")
        days     = leak.get("days_inactive", 0)
        value    = leak.get("value", 0)
        deal_id  = leak.get("deal_id", "")

        subject = f"Re: {deal_id} — Checking in with {contact}"
        body = (
            f"Hi {contact},\n\n"
            f"I wanted to follow up — it's been {days} days since we last connected "
            f"and I didn't want our discussion to fall through the cracks.\n\n"
            f"We believe our solution could deliver real value for your team. "
            f"Could we find 15 minutes this week to reconnect?\n\n"
            f"Best regards,\nSales Team\n\n"
            f"Deal ref: {deal_id}  |  Value: ${value:,}"
        )

        if gmail_user and gmail_pass and to_email:
            try:
                import smtplib
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText

                msg = MIMEMultipart()
                msg["From"]    = gmail_user
                msg["To"]      = to_email
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))

                with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                    server.login(gmail_user, gmail_pass)
                    server.sendmail(gmail_user, to_email, msg.as_string())

                print(f"  ✅  Sent to {contact} <{to_email}>")
                method = "gmail"
            except Exception as exc:
                print(f"  ⚠️   Gmail failed for {contact}: {exc}")
                print(f"  📋  [DRY-RUN] To: {to_email}  |  {subject}")
        else:
            label = to_email if to_email else "(no email — set HUBSPOT_API_KEY to fetch from CRM)"
            print(f"  📋  [DRY-RUN] To      : {label}")
            print(f"       Subject : {subject}")
            print(f"       Preview : {body[:100].strip()}...")

        sent.append(contact)

    print(f"\n  Total: {len(sent)} followup(s)  |  method={method}")
    print(f"{border}")

    if not (gmail_user and gmail_pass):
        print(
            "  ℹ️   Dry-run mode — set GMAIL_USER + GMAIL_APP_PASSWORD to send real emails."
        )

    return {
        "emails_sent":      len(sent),
        "contacts_emailed": sent,
        "delivery_method":  method,
    }


# ---------------------------------------------------------------------------
# TOOLS dict — discovered by ToolRegistry.discover_from_module()
# ---------------------------------------------------------------------------

TOOLS: dict[str, Tool] = {
    "scan_pipeline": Tool(
        name="scan_pipeline",
        description=(
            "Scan the CRM pipeline for the next monitoring cycle. "
            "Increments the cycle counter and loads a fresh deal snapshot."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type": "integer",
                    "description": "Current cycle number from context (0 on first run).",
                },
            },
            "required": ["cycle"],
        },
    ),
    "detect_revenue_leaks": Tool(
        name="detect_revenue_leaks",
        description=(
            "Analyse the latest pipeline snapshot and detect revenue leak patterns: "
            "GHOSTED (21+ days silent), STALLED (10-20 days stuck), "
            "OVERDUE_PAYMENT (unpaid invoice), CHURN_RISK (3+ escalations)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type": "integer",
                    "description": "Current monitoring cycle (for report labelling).",
                },
            },
            "required": ["cycle"],
        },
    ),
    "send_revenue_alert": Tool(
        name="send_revenue_alert",
        description=(
            "Send a formatted revenue leak alert to the operations team. "
            "Prints a full structured report to console and delivers a real "
            "Telegram message when TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {"type": "integer", "description": "Current monitoring cycle number."},
                "leak_count": {"type": "integer", "description": "Number of leaks found this cycle."},
                "severity": {"type": "string", "description": "Overall severity (low / medium / high / critical)."},
                "total_at_risk": {"type": "integer", "description": "Total USD value at risk this cycle."},
            },
            "required": ["cycle", "leak_count", "severity", "total_at_risk"],
        },
    ),
    "send_followup_emails": Tool(
        name="send_followup_emails",
        description=(
            "Send re-engagement emails to every GHOSTED contact found this cycle. "
            "Uses Gmail SMTP when GMAIL_USER + GMAIL_APP_PASSWORD are set; "
            "otherwise prints a dry-run preview."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type": "integer",
                    "description": "Current monitoring cycle (for log labels).",
                },
            },
            "required": ["cycle"],
        },
    ),
}


# ---------------------------------------------------------------------------
# Unified tool executor — dispatches to private handler functions
# ---------------------------------------------------------------------------

def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch a ToolUse to the correct handler and return a JSON ToolResult."""
    _handlers: dict[str, Any] = {
        "scan_pipeline":       _scan_pipeline,
        "detect_revenue_leaks": _detect_revenue_leaks,
        "send_revenue_alert":  _send_revenue_alert,
        "send_followup_emails": _send_followup_emails,
    }
    handler = _handlers.get(tool_use.name)
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
