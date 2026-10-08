"""The single CLI-style ``credentials`` synthetic tool.

Surfaced to the queen agent loop as ONE tool with an ``action`` discriminator
so the LLM sees a tiny schema. Calling it with no ``action`` (or
``action="help"``) returns fresh usage text, which keeps the tool description
short and re-shows the instructions on every use.

Heavy logic lives here as pure-ish helpers so the agent-loop dispatch stays
lean (mirrors ``synthetic_tools.py``). Each non-blocking action returns a
plain string; the agent loop wraps it in a ``ToolResult``. The blocking
``collect`` action is validated here and parked by the agent loop.

Security model:
- ``browse`` / ``inspect`` return METADATA ONLY — never secret values.
- ``reveal`` is the only path that returns a decrypted secret. It is explicit,
  logged, and its output DOES enter the conversation history.
- ``collect`` never returns secrets to the loop. It parks the loop and emits a
  form-request event; the frontend POSTs the secret straight to the encrypted
  store via ``POST /api/sessions/{id}/credential-form``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from framework.llm.provider import Tool

logger = logging.getLogger(__name__)

# Secret field-name hints used to pick the "primary" key and to default a
# field's masked-input flag when the agent doesn't say.
_SECRET_NAME_HINTS = ("api_key", "apikey", "token", "access_token", "secret", "password", "key")

_MAX_BROWSE_PROVIDERS = 40
_MAX_FIELDS = 8


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

CREDENTIALS_TOOL_DESCRIPTION = (
    "Manage credentials (a CLI-style tool). Call with no arguments (or "
    'action="help") to see the available actions and their parameters. '
    "Actions: help, browse, inspect, reveal, collect, attach, detach. Use "
    "this to discover what credentials are available, pop a secure form to "
    "the user to collect a new API key / login, attach a credential to this "
    "session so you remember it's available, or read a secret value."
)

CREDENTIALS_HELP = """\
`credentials` — manage credentials for this session.

Call this tool with an `action`. With no action (or action="help") you get this
usage text. Secrets you collect are stored encrypted; you never need to handle
raw secret values yourself unless you explicitly `reveal` one.

Actions:

- help
    Show this usage text.

- browse  [query]
    List what credentials are available: connected accounts you can use now,
    plus providers you could connect. Metadata only — no secret values.
    Optional `query` filters by provider name / description.

- inspect  credential_id  [account]
    Show details for one credential (type, key names, identity, status).
    Metadata only — no secret values.

- collect  credential_id  [account]  [title]  [fields]  [instructions]
    Pop a SECURE FORM to the user to collect a credential, then store it
    encrypted. Use this when a credential is missing. The form values go
    straight to the store — they are NOT shown to you. You get back only a
    confirmation. `account` is an alias (e.g. "work"); defaults to "default".
    `fields` is an optional list of objects:
      {"name": "api_key", "label": "API key", "secret": true, "required": true}
    If you omit `fields`, a single secret "api_key" field is used (or the
    fields for a known provider). `instructions` is optional help text shown
    above the form (e.g. where to find the key).

- attach  credential_id  [account]
    Pin a credential to THIS session so a reminder that it's available is
    re-injected into your context each turn. Do this for credentials you'll
    use repeatedly.

- detach  credential_id  [account]
    Remove a pinned credential from this session.

- reveal  credential_id  [account]  [key]
    Return the DECRYPTED secret value. Use ONLY when you must place the secret
    somewhere a tool can't resolve it for you. The value WILL appear in this
    conversation, so prefer letting tools resolve credentials by account=alias
    instead.

Examples:
  credentials({"action": "browse"})
  credentials({"action": "collect", "credential_id": "stripe", "account": "work",
               "title": "Connect Stripe",
               "fields": [{"name": "api_key", "label": "Secret key", "secret": true}]})
  credentials({"action": "attach", "credential_id": "stripe", "account": "work"})
"""


def build_credentials_tool() -> Tool:
    """Build the single CLI-style ``credentials`` tool."""
    return Tool(
        name="credentials",
        description=CREDENTIALS_TOOL_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "help",
                        "browse",
                        "inspect",
                        "collect",
                        "attach",
                        "detach",
                        "reveal",
                    ],
                    "description": ('What to do. Defaults to "help", which returns full usage. Call help first if unsure.'),
                },
                "credential_id": {
                    "type": "string",
                    "description": ("Logical credential / provider id (e.g. 'stripe', 'github'). Required for inspect/collect/attach/detach/reveal."),
                },
                "account": {
                    "type": "string",
                    "description": ("Account alias for multi-account providers (e.g. 'work'). Defaults to 'default'."),
                },
                "query": {
                    "type": "string",
                    "description": "Optional filter for browse.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional form title for collect.",
                },
                "instructions": {
                    "type": "string",
                    "description": "Optional help text shown above the collect form.",
                },
                "key": {
                    "type": "string",
                    "description": ("Specific key name for reveal (e.g. 'access_token'). Defaults to the primary key."),
                },
                "fields": {
                    "type": "array",
                    "description": ("Optional field specs for collect. Each: {name, label?, secret?, required?, placeholder?}."),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "label": {"type": "string"},
                            "secret": {"type": "boolean"},
                            "required": {"type": "boolean"},
                            "placeholder": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": [],
        },
    )


def render_help() -> str:
    """Fresh usage text. Returned for action=help or no action."""
    return CREDENTIALS_HELP


# ---------------------------------------------------------------------------
# Adapter / store access
# ---------------------------------------------------------------------------


def _get_adapter() -> Any | None:
    """Return the default CredentialStoreAdapter, or None if unavailable."""
    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        return CredentialStoreAdapter.default()
    except Exception:
        logger.debug("credentials tool: adapter unavailable", exc_info=True)
        return None


def _credential_specs() -> dict[str, Any]:
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        return CREDENTIAL_SPECS
    except Exception:
        return {}


def _account_provider(acct: dict) -> str:
    return str(acct.get("provider") or acct.get("credential_id") or "").strip()


def _format_identity(identity: Any) -> str:
    if not isinstance(identity, dict):
        return ""
    parts = [str(v) for v in identity.values() if v]
    return f" ({', '.join(parts)})" if parts else ""


def _format_account_line(acct: dict) -> str:
    provider = _account_provider(acct)
    alias = acct.get("alias", "") or "default"
    source = acct.get("source", "aden")
    status = acct.get("status")
    tag = " [local]" if source == "local" else ""
    status_tag = f" — {status}" if status and status != "active" else ""
    return f'- {provider} "{alias}"{_format_identity(acct.get("identity"))}{tag}{status_tag}'


# ---------------------------------------------------------------------------
# browse / inspect / reveal
# ---------------------------------------------------------------------------


def browse(query: str | None = None) -> str:
    """List available credentials — metadata only, never secret values."""
    adapter = _get_adapter()
    accounts: list[dict] = []
    if adapter is not None:
        try:
            accounts = adapter.get_all_account_info()
        except Exception:
            logger.debug("credentials.browse: get_all_account_info failed", exc_info=True)
            accounts = []

    q = (query or "").strip().lower()
    connected_providers = {_account_provider(a) for a in accounts}

    lines: list[str] = ["# Available credentials", ""]

    if accounts:
        shown = [a for a in accounts if not q or q in _format_account_line(a).lower()]
        if shown:
            lines.append("Connected (usable now via account=<alias>):")
            lines.extend(_format_account_line(a) for a in shown)
            lines.append("")
    else:
        lines.append("No credentials are connected yet.")
        lines.append("")

    # Connectable providers from the spec catalog (not yet connected).
    specs = _credential_specs()
    connectable: list[str] = []
    for name, spec in specs.items():
        cred_id = getattr(spec, "credential_id", None) or name
        provider = getattr(spec, "aden_provider_name", "") or cred_id
        if provider in connected_providers or cred_id in connected_providers:
            continue
        desc = getattr(spec, "description", "") or ""
        text = f"- {cred_id} — {desc}".rstrip(" —")
        if q and q not in text.lower():
            continue
        connectable.append(text)

    if connectable:
        lines.append("Connectable providers (use action=collect to add):")
        lines.extend(sorted(connectable)[:_MAX_BROWSE_PROVIDERS])
        if len(connectable) > _MAX_BROWSE_PROVIDERS:
            lines.append(f"… and {len(connectable) - _MAX_BROWSE_PROVIDERS} more (use a query to filter).")
        lines.append("")

    lines.append("Use action=inspect for details, action=attach to pin one to this session, or action=collect to add a new one.")
    return "\n".join(lines)


def inspect(credential_id: str, account: str = "") -> str:
    """Show metadata for one credential. Never returns secret values."""
    credential_id = (credential_id or "").strip()
    if not credential_id:
        return "ERROR: inspect requires credential_id."

    adapter = _get_adapter()
    out: list[str] = [f"# {credential_id}" + (f' (account "{account}")' if account else "")]

    # Connected account metadata.
    accounts: list[dict] = []
    if adapter is not None:
        try:
            accounts = [a for a in adapter.get_all_account_info() if _account_provider(a) == credential_id or a.get("credential_id") == credential_id]
        except Exception:
            accounts = []
    if account:
        accounts = [a for a in accounts if (a.get("alias") or "default") == account]

    if accounts:
        out.append("Accounts:")
        out.extend(_format_account_line(a) for a in accounts)
    else:
        out.append("No connected account found for this id.")

    # Key names from the underlying store (names only — no values).
    if adapter is not None:
        try:
            cred = adapter.store.get_credential(credential_id, refresh_if_needed=False)
            if cred is not None:
                public_keys = [k for k in cred.keys.keys() if not k.startswith("_")]
                if public_keys:
                    out.append(f"Keys: {', '.join(sorted(public_keys))}")
                out.append(f"Type: {cred.credential_type}")
        except Exception:
            logger.debug("credentials.inspect: store lookup failed", exc_info=True)

    out.append("")
    out.append("To use it, pass account=<alias> to the relevant tool. Use action=reveal only if you must read the raw value.")
    return "\n".join(out)


def reveal(credential_id: str, account: str = "", key: str = "") -> str:
    """Return a DECRYPTED secret value. Explicit + logged; enters the chat."""
    credential_id = (credential_id or "").strip()
    if not credential_id:
        return "ERROR: reveal requires credential_id."

    adapter = _get_adapter()
    if adapter is None:
        return "ERROR: credential store unavailable."

    logger.warning(
        "credentials.reveal: decrypted secret requested for %s/%s key=%s",
        credential_id,
        account or "default",
        key or "(default)",
    )

    value: str | None = None
    try:
        if account:
            try:
                from framework.credentials.local.registry import LocalCredentialRegistry

                value = LocalCredentialRegistry.default().get_key(credential_id, account, key or "api_key")
            except Exception:
                value = None
            if value is None:
                cred = adapter.store.get_credential_by_alias(credential_id, account)
                if cred is not None:
                    value = cred.get_key(key) if key else cred.get_default_key()
        else:
            # No account: try the un-aliased store credential, then fall back
            # to a collected local account (sole account, or one aliased
            # "default") so the agent doesn't have to guess the alias.
            cred = adapter.store.get_credential(credential_id)
            if cred is not None:
                value = cred.get_key(key) if key else cred.get_default_key()
            if value is None:
                from framework.credentials.local.registry import LocalCredentialRegistry

                registry = LocalCredentialRegistry.default()
                accounts = registry.list_accounts(credential_id)
                target = None
                if len(accounts) == 1:
                    target = accounts[0].alias
                elif any(a.alias == "default" for a in accounts):
                    target = "default"
                if target is not None:
                    value = registry.get_key(credential_id, target, key or "api_key")
    except Exception as exc:
        return f"ERROR: could not read credential: {exc}"

    if value is None:
        return f"No value found for {credential_id}" + (f"/{account}" if account else "") + (f" key '{key}'" if key else "") + "."

    label = f"{credential_id}" + (f"/{account}" if account else "") + (f" [{key}]" if key else "")
    return f"⚠️ Decrypted secret for {label} (now visible in this conversation):\n{value}"


# ---------------------------------------------------------------------------
# collect — validate the form request (no secret values pass through)
# ---------------------------------------------------------------------------


def _default_fields_for(credential_id: str) -> list[dict]:
    """Derive form fields from a known spec, else a single api_key field."""
    specs = _credential_specs()
    spec = specs.get(credential_id)
    if spec is None:
        # Spec dict may be keyed by name while credential_id differs.
        for s in specs.values():
            if (getattr(s, "credential_id", None) or "") == credential_id:
                spec = s
                break
    if spec is not None:
        key_name = getattr(spec, "credential_key", "") or "api_key"
        desc = getattr(spec, "description", "") or "API key"
        return [{"name": key_name, "label": desc, "secret": True, "required": True}]
    return [{"name": "api_key", "label": "API key", "secret": True, "required": True}]


def _sanitize_fields(raw: Any, credential_id: str) -> tuple[list[dict] | None, str | None]:
    if raw is None:
        # Fall through to the same normalization as agent-supplied fields so
        # default fields get the full {name,label,secret,required,placeholder}
        # shape too.
        raw = _default_fields_for(credential_id)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None, "fields must be a list of field objects."
    if not isinstance(raw, list) or not raw:
        return None, "fields must be a non-empty list of field objects."
    if len(raw) > _MAX_FIELDS:
        return None, f"too many fields (max {_MAX_FIELDS})."

    fields: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "each field must be an object with at least a 'name'."
        name = str(item.get("name", "")).strip()
        if not name or any(c in name for c in " /\\"):
            return None, f"invalid field name: {name!r}"
        if name in seen:
            continue
        seen.add(name)
        secret = item.get("secret")
        if not isinstance(secret, bool):
            secret = any(h in name.lower() for h in _SECRET_NAME_HINTS)
        fields.append(
            {
                "name": name,
                "label": str(item.get("label") or name.replace("_", " ").title()),
                "secret": bool(secret),
                "required": bool(item.get("required", True)),
                "placeholder": str(item.get("placeholder") or ""),
            }
        )
    if not fields:
        return None, "no valid fields provided."
    return fields, None


def validate_collect_input(tool_input: dict[str, Any]) -> tuple[dict | None, str | None]:
    """Validate a collect call and build the no-secret form payload.

    Returns ``(payload, None)`` on success or ``(None, error)`` on failure.
    The payload contains only field *specs* — never any values.
    """
    credential_id = str(tool_input.get("credential_id", "")).strip()
    if not credential_id or any(c in credential_id for c in " /\\"):
        return None, "collect requires a valid credential_id (e.g. 'stripe')."

    account = str(tool_input.get("account", "") or "default").strip() or "default"
    if any(c in account for c in " /\\"):
        return None, "account alias must not contain spaces or slashes."

    fields, err = _sanitize_fields(tool_input.get("fields"), credential_id)
    if err:
        return None, err

    payload = {
        "credential_id": credential_id,
        "account": account,
        "title": str(tool_input.get("title") or f"Connect {credential_id}"),
        "instructions": str(tool_input.get("instructions") or ""),
        "fields": fields,
    }
    return payload, None


# ---------------------------------------------------------------------------
# Session attachments (pinned credentials, re-injected each turn)
# ---------------------------------------------------------------------------


def attachments_path(session_id: str) -> Path:
    """Per-session file holding the list of attached credential refs."""
    from framework.config import HIVE_HOME

    return HIVE_HOME / "sessions" / session_id / "attached_credentials.json"


def read_attachments(session_id: str | None) -> list[dict]:
    """Return the list of attached {credential_id, account} refs (best effort)."""
    if not session_id:
        return []
    path = attachments_path(session_id)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict) and r.get("credential_id")]
    except Exception:
        logger.debug("read_attachments failed for %s", session_id, exc_info=True)
    return []


def _write_attachments(session_id: str, refs: list[dict]) -> None:
    path = attachments_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(refs, indent=2))


def add_attachment(session_id: str | None, credential_id: str, account: str = "") -> str:
    """Pin a credential to the session. Returns a user-facing message."""
    credential_id = (credential_id or "").strip()
    if not credential_id:
        return "ERROR: attach requires credential_id."
    if not session_id:
        return "ERROR: no active session to attach to."
    account = (account or "default").strip() or "default"
    refs = read_attachments(session_id)
    ref = {"credential_id": credential_id, "account": account}
    if ref in refs:
        return f"Credential '{credential_id}' (account '{account}') is already attached to this session."
    refs.append(ref)
    _write_attachments(session_id, refs)
    return f"Attached '{credential_id}' (account '{account}') to this session. It will be reminded in your context each turn."


def remove_attachment(session_id: str | None, credential_id: str, account: str = "") -> str:
    """Unpin a credential from the session. Returns a user-facing message."""
    credential_id = (credential_id or "").strip()
    if not credential_id:
        return "ERROR: detach requires credential_id."
    if not session_id:
        return "ERROR: no active session."
    account = (account or "default").strip() or "default"
    refs = read_attachments(session_id)
    kept = [r for r in refs if not (r.get("credential_id") == credential_id and (r.get("account") or "default") == account)]
    if len(kept) == len(refs):
        return f"Credential '{credential_id}' (account '{account}') was not attached."
    _write_attachments(session_id, kept)
    return f"Detached '{credential_id}' (account '{account}') from this session."


def attachment_matches(acct: dict, refs: list[dict]) -> bool:
    """True if a connected-account dict matches any attached ref."""
    provider = _account_provider(acct)
    cred_id = acct.get("credential_id") or provider
    alias = acct.get("alias") or "default"
    for r in refs:
        rid = r.get("credential_id")
        racct = r.get("account") or "default"
        if rid in (provider, cred_id) and racct == alias:
            return True
    return False
