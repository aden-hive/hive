"""Sentinel notification-setup tool for the queen.

Exposes the same operations the desktop Sentinel UI performs, so the queen
can finish a browser-driven Slack / Telegram setup end to end instead of
bouncing the user back to the connector form:

- ``store_token`` — save a channel token to the encrypted credential store
  (the UI's "Connect" step: credential ids ``slack`` / ``slack_app`` /
  ``telegram``). Slack and Telegram tokens are validated before they're
  stored, mirroring the UI's validate-then-save.
- ``configure``   — write the per-colony ``notifications.json`` (channel,
  target, allowlist, enable) — the UI's "Save" step — and start the inbound
  listener so two-way replies work without a runtime restart.
- ``test``        — send a test message to the configured destination.
- ``status``      — report which tokens are stored + the colony's config.

Single-tool-with-``action`` shape mirrors :func:`build_credentials_tool`. All
work is in-process and writes to the same encrypted store + on-disk config the
Sentinel notifier and manager read, so the desktop UI reflects it immediately.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.llm.provider import Tool

logger = logging.getLogger(__name__)

_VALID_CHANNELS = {"hive", "telegram", "slack"}
# credential id used by the Sentinel notifier for each provider token.
_PROVIDER_IDS = {"slack", "slack_app", "telegram"}

SENTINEL_TOOL_DESCRIPTION = (
    "Set up Sentinel notifications (Slack / Telegram) for a colony — the same "
    "actions the desktop Sentinel connector performs. Call with no args (or "
    'action="help") for usage. Actions: help, status, store_token, detect_chat, '
    "configure, test. Use store_token to save a channel token you obtained (e.g. "
    "a Slack bot xoxb- / app-level xapp- token, or a Telegram bot token); "
    "detect_chat finds the Telegram chat id after the user messages the bot; "
    "configure sets the colony's channel + turns Sentinel on; test verifies a "
    "message lands. Tokens are stored encrypted; configure/test target the colony "
    "bound to this session unless you pass colony_id."
)

SENTINEL_TOOL_HELP = """sentinel_setup — connect Slack/Telegram notifications (Sentinel) for a colony.

This performs the same steps as the desktop Sentinel connector, so you can finish
a browser-driven setup yourself instead of asking the user to paste tokens.

Actions:

- status
    Show which channel tokens are stored (telegram / slack bot / slack app) and,
    if a colony is bound to this session, its current notifications config.

- store_token  provider  token
    Save a channel token to the encrypted credential store.
      provider="slack"      -> Slack Bot User OAuth Token (xoxb-…); validated via auth.test
      provider="slack_app"  -> Slack App-Level Token (xapp-…, connections:write)
      provider="telegram"   -> Telegram bot token (from @BotFather); validated via getMe
    Read the token off the page after creating the bot/app, then store it.

- detect_chat
    (Telegram) After the user sends ANY message to the bot, find the chat to
    notify. Returns the latest chat_id + the sender's id (use it for allowlist).
    Returns PENDING if no message has arrived yet — ask the user to message the
    bot, then retry. Requires the Telegram token to be stored first.

- configure  channel  target  [enabled]  [allowlist]  [classify_after_seconds]  [colony_id]
    Write the per-colony notifications config (the "Save" step).
      channel="slack",   target={"channel": "C0123ABC"}     (invite the bot to that channel first)
      channel="telegram", target={"chat_id": "123456789"}
      enabled=true turns Sentinel on; allowlist = sender ids allowed to reply.

- test  [channel]  [target]  [colony_id]
    Send a test message to the configured (or supplied) destination.

Examples:
  sentinel_setup({"action": "store_token", "provider": "slack", "token": "xoxb-…"})
  sentinel_setup({"action": "store_token", "provider": "slack_app", "token": "xapp-…"})
  sentinel_setup({"action": "configure", "channel": "slack", "target": {"channel": "C0123ABC"}, "enabled": true})
  sentinel_setup({"action": "store_token", "provider": "telegram", "token": "123456:ABC-…"})
  sentinel_setup({"action": "detect_chat"})
  sentinel_setup({"action": "configure", "channel": "telegram", "target": {"chat_id": "123456789"}, "allowlist": ["123456789"], "enabled": true})
  sentinel_setup({"action": "test"})
"""


def build_sentinel_setup_tool() -> Tool:
    """Build the single CLI-style ``sentinel_setup`` tool."""
    return Tool(
        name="sentinel_setup",
        description=SENTINEL_TOOL_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["help", "status", "store_token", "detect_chat", "configure", "test"],
                    "description": 'What to do. Defaults to "help", which returns full usage.',
                },
                "provider": {
                    "type": "string",
                    "enum": ["slack", "slack_app", "telegram"],
                    "description": ("For store_token: which token. 'slack' = bot xoxb-, 'slack_app' = app-level xapp-, 'telegram' = bot token."),
                },
                "token": {
                    "type": "string",
                    "description": "For store_token: the raw token value to store (kept encrypted).",
                },
                "channel": {
                    "type": "string",
                    "enum": ["slack", "telegram"],
                    "description": "For configure/test: the channel to deliver on.",
                },
                "target": {
                    "type": "object",
                    "description": ('For configure/test: destination. Slack: {"channel": "C0123ABC"}. Telegram: {"chat_id": "123456789"}.'),
                },
                "enabled": {
                    "type": "boolean",
                    "description": "For configure: turn Sentinel on (true) or off (false) for the colony.",
                },
                "allowlist": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For configure: sender ids allowed to reply and drive the colony.",
                },
                "classify_after_seconds": {
                    "type": "number",
                    "description": "For configure: per-colony idle budget before escalating; omit to inherit the default.",
                },
                "colony_id": {
                    "type": "string",
                    "description": ("For configure/test: target colony's on-disk directory name. Defaults to the colony bound to this session."),
                },
            },
            "required": [],
        },
    )


def render_help() -> str:
    """Fresh usage text. Returned for action=help or no action."""
    return SENTINEL_TOOL_HELP


# ---------------------------------------------------------------------------
# Token storage + validation
# ---------------------------------------------------------------------------


def _store_credential(cred_id: str, token: str) -> None:
    """Persist ``token`` under ``cred_id`` in the encrypted store.

    Saves under key name ``access_token`` to match the desktop UI's
    credential save, which is what ``notifier._credential`` reads back.
    """
    from pydantic import SecretStr

    from framework.credentials import CredentialStore
    from framework.credentials.models import CredentialKey, CredentialObject

    store = CredentialStore.with_encrypted_storage()
    store.save_credential(
        CredentialObject(
            id=cred_id,
            keys={"access_token": CredentialKey(name="access_token", value=SecretStr(token))},
        )
    )
    # Best-effort: drop the memoized adapter so in-process tools pick the new
    # token up this session (mirrors routes_credentials after a save).
    try:
        from aden_tools.credentials.store_adapter import _reset_default_adapter_cache

        _reset_default_adapter_cache()
    except Exception:
        logger.debug("sentinel_setup: adapter cache reset failed", exc_info=True)


async def _validate_slack(token: str) -> tuple[bool, str | None, str | None]:
    """(ok, team, error) via Slack auth.test — same check as the UI."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
        data = resp.json()
    except Exception as e:  # noqa: BLE001 — surface the network error to the queen
        return False, None, str(e)
    if not data.get("ok"):
        return False, None, data.get("error", "invalid token")
    return True, data.get("team"), None


async def _validate_telegram(token: str) -> tuple[bool, str | None, str | None]:
    """(ok, name, error) via Telegram getMe — same check as the UI."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return False, None, str(e)
    if not data.get("ok"):
        return False, None, data.get("description", "invalid token")
    res = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
    return True, res.get("username") or res.get("first_name"), None


def _format_detected(chat_id: Any, chat_title: Any, sender_id: Any, sender_name: Any) -> str:
    return (
        f'Detected Telegram chat "{chat_title or "chat"}": chat_id={chat_id}; '
        f"sender={sender_name or 'user'} (id {sender_id}). "
        f'Configure with target={{"chat_id": "{chat_id}"}} and '
        f'allowlist=["{sender_id}"], then enable.'
    )


async def _detect_chat() -> str:
    """(Telegram) Find the chat to notify after the user messages the bot.

    Two paths, because the running Sentinel daemon long-polls getUpdates and
    ACKS each update (advancing the offset) — so a competing getUpdates here
    would come back empty whenever a listener is running (e.g. the bot is
    already wired to another colony). When the daemon is listening we read the
    chat IT already saw; only when nothing is consuming updates do we poll the
    API ourselves. Non-ERROR "PENDING" means no message has arrived yet — ask
    the user to message the bot and retry.
    """
    from framework.sentinel import notifier

    token = notifier.telegram_token()
    if not token:
        return "ERROR: store the Telegram bot token first (store_token provider=telegram)."

    # Path 1 — a Sentinel listener owns the update stream: read its cache.
    try:
        from framework.sentinel.manager import get_sentinel_manager

        mgr = get_sentinel_manager()
    except Exception:
        mgr = None
    if mgr is not None:
        recent = None
        try:
            recent = mgr.recent_chat("telegram")
        except Exception:
            recent = None
        if recent and recent.get("chat_id"):
            return _format_detected(
                recent.get("chat_id"),
                recent.get("chat_title"),
                recent.get("sender_id"),
                recent.get("sender_name"),
            )
        try:
            listening = mgr.is_listening("telegram")
        except Exception:
            listening = False
        if listening:
            return (
                "PENDING: the Sentinel Telegram listener is running but hasn't seen a "
                "message yet. Ask the user to open the bot and tap Start (or send any "
                "message), then run detect_chat again. Don't decrypt tokens or poll the "
                "Telegram API by hand — the listener owns the update stream and will "
                "surface the chat here."
            )

    # Path 2 — nothing is consuming updates: poll getUpdates ourselves.
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": -1, "limit": 1, "allowed_updates": '["message"]'},
            )
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return f"ERROR: getUpdates failed: {e}"

    if not data.get("ok"):
        return f"ERROR: getUpdates rejected: {data.get('description', 'unknown')}"
    updates = data.get("result", [])
    if not updates:
        return (
            "PENDING: no message yet — ask the user to open the bot in Telegram and send it any message (or tap Start), then run detect_chat again."
        )
    msg = updates[-1].get("message", {}) or {}
    chat = msg.get("chat", {}) or {}
    sender = msg.get("from", {}) or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return "PENDING: latest update has no chat — send a direct message to the bot and retry."
    return _format_detected(
        chat_id,
        chat.get("title") or chat.get("first_name") or chat.get("username"),
        sender.get("id"),
        sender.get("username") or sender.get("first_name"),
    )


async def _store_token(ci: dict[str, Any]) -> str:
    provider = str(ci.get("provider", "") or "").strip().lower()
    token = str(ci.get("token", "") or "").strip()
    if provider not in _PROVIDER_IDS:
        return "ERROR: provider must be 'slack' (bot xoxb-), 'slack_app' (app-level xapp-), or 'telegram'."
    if not token:
        return "ERROR: token is required."

    if provider == "slack":
        if not token.startswith("xoxb-"):
            return "ERROR: a Slack bot token starts with 'xoxb-'. For the app-level token use provider='slack_app'."
        ok, team, err = await _validate_slack(token)
        if not ok:
            return f"ERROR: Slack rejected the bot token (auth.test): {err}"
        _store_credential("slack", token)
        return f"Stored Slack bot token — connected to workspace '{team or 'unknown'}'. Sentinel can now send to Slack."

    if provider == "slack_app":
        if not token.startswith("xapp-"):
            return "ERROR: a Slack app-level token starts with 'xapp-'."
        _store_credential("slack_app", token)
        return "Stored Slack app-level token. Sentinel can now receive replies over Socket Mode."

    # telegram
    ok, who, err = await _validate_telegram(token)
    if not ok:
        return f"ERROR: Telegram rejected the token (getMe): {err}"
    _store_credential("telegram", token)
    return f"Stored Telegram bot token (@{who})." if who else "Stored Telegram bot token."


# ---------------------------------------------------------------------------
# Per-colony config + test
# ---------------------------------------------------------------------------


def _status(default_colony_id: str | None) -> str:
    from framework.sentinel import notifier, store

    lines = ["Sentinel channel tokens:"]
    lines.append(f"  telegram        : {'configured' if notifier.telegram_token() else 'not set'}")
    lines.append(f"  slack bot (xoxb): {'configured' if notifier.slack_bot_token() else 'not set'}")
    lines.append(f"  slack app (xapp): {'configured' if notifier.slack_app_token() else 'not set'}")
    if default_colony_id:
        cfg = store.load_notifications_config(default_colony_id)
        lines.append("")
        lines.append(
            f"Colony '{default_colony_id}': enabled={cfg.sentinel_enabled} "
            f"channel={cfg.channel or '-'} target={cfg.target or {}} allowlist={cfg.allowlist or []}"
        )
    else:
        lines.append("")
        lines.append("No colony bound to this session — pass colony_id to configure/test.")
    return "\n".join(lines)


def _configure(ci: dict[str, Any], default_colony_id: str | None) -> str:
    from framework.sentinel import store

    cid = str(ci.get("colony_id", "") or "").strip() or default_colony_id
    if not cid:
        return "ERROR: no colony bound to this session — pass colony_id (the colony's on-disk directory name)."

    channel = ci.get("channel")
    enabled = bool(ci.get("enabled", False))
    if enabled and channel not in _VALID_CHANNELS:
        return "ERROR: channel must be 'telegram' or 'slack' when enabled=true."
    target = ci.get("target") if isinstance(ci.get("target"), dict) else {}
    allow = ci.get("allowlist") or []
    if not isinstance(allow, list):
        return "ERROR: allowlist must be a list."

    cas_raw = ci.get("classify_after_seconds")
    classify_after_seconds: float | None = None
    if cas_raw is not None:
        try:
            classify_after_seconds = float(cas_raw)
        except (TypeError, ValueError):
            return "ERROR: classify_after_seconds must be a number or null."
        if classify_after_seconds <= 0:
            return "ERROR: classify_after_seconds must be positive."

    try:
        store.update_notifications_config(
            cid,
            sentinel_enabled=enabled,
            channel=channel,
            target=target,
            allowlist=[str(x) for x in allow],
            classify_after_seconds=classify_after_seconds,
        )
    except FileNotFoundError:
        return f"ERROR: colony '{cid}' not found on disk."

    # Start the inbound listener now so two-way replies work without a restart.
    try:
        from framework.sentinel.manager import get_sentinel_manager

        mgr = get_sentinel_manager()
        if mgr is not None:
            mgr.refresh_listeners()
    except Exception:
        logger.debug("sentinel_setup: refresh_listeners failed", exc_info=True)

    state = "ENABLED" if enabled else "disabled"
    return f"Saved Sentinel config for colony '{cid}': {state}, channel={channel or '-'}, target={target or {}}."


async def _test(ci: dict[str, Any], default_colony_id: str | None) -> str:
    from framework.sentinel import notifier, store

    cid = str(ci.get("colony_id", "") or "").strip() or default_colony_id
    cfg = store.load_notifications_config(cid) if cid else None
    channel = ci.get("channel") or (cfg.channel if cfg else None)
    target = ci.get("target") or (cfg.target if cfg else None)
    if channel not in _VALID_CHANNELS or not target:
        return "ERROR: channel and target are required to send a test (pass them, or configure the colony first)."

    label = cid or "this colony"
    result = await notifier.send(
        channel,
        target,
        f'✅ Sentinel test for colony "{label}". If you can read this, replies will reach the queen.',
        None,
    )
    if result.ok:
        return f"Test message delivered to {channel} {target}."
    return f"ERROR: test send failed: {result.error}"


# ---------------------------------------------------------------------------
# Entrypoint (called from the agent loop tool dispatch)
# ---------------------------------------------------------------------------


async def _publish_refresh() -> None:
    """Nudge the desktop UI to refetch Sentinel state after an out-of-band
    store/configure.

    The Sentinel tab (and the credential/tool catalog surfaces) refresh off
    the process-wide ``tool_catalog_refreshed`` global event — that's the
    signal ``routes_credentials`` pairs with every human credential save. The
    queen's in-process writes bypass that route, so emit the same event here so
    ``SentinelSection``'s ``getConfig`` re-runs (which returns both the colony
    config and the embedded token status). Best-effort: never let a publish
    failure turn a successful store/configure into a tool error. We
    deliberately do NOT emit ``credential_provider_connected`` — that would pop
    the queens-authorization dialog the human Sentinel flow suppresses.
    """
    try:
        from framework.host.event_bus import AgentEvent, EventType, publish_global

        await publish_global(
            AgentEvent(
                type=EventType.TOOL_CATALOG_REFRESHED,
                stream_id="global",
                data={"trigger": "sentinel_setup"},
            )
        )
    except Exception:
        logger.debug("sentinel_setup: refresh publish failed", exc_info=True)


async def handle(tool_input: dict[str, Any], *, default_colony_id: str | None = None) -> str:
    """Resolve a ``sentinel_setup`` call and return the result text.

    ``default_colony_id`` is the colony bound to the current session (resolved
    by the caller from ``ctx.colony_binding_provider``); configure/test fall
    back to it when ``colony_id`` isn't passed explicitly.
    """
    ci = tool_input if isinstance(tool_input, dict) else {}
    action = str(ci.get("action", "") or "help").strip().lower()

    if action in ("", "help"):
        return render_help()
    if action == "status":
        return _status(default_colony_id)
    if action == "store_token":
        result = await _store_token(ci)
        if not result.startswith("ERROR:"):
            await _publish_refresh()
        return result
    if action == "detect_chat":
        return await _detect_chat()
    if action == "configure":
        result = _configure(ci, default_colony_id)
        if not result.startswith("ERROR:"):
            await _publish_refresh()
        return result
    if action == "test":
        return await _test(ci, default_colony_id)
    return f"ERROR: unknown sentinel_setup action '{action}'. Call sentinel_setup() for usage."
