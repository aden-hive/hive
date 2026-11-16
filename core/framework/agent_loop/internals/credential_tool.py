"""The single CLI-style ``credentials`` synthetic tool.

Surfaced to the queen agent loop as ONE tool with an ``action`` discriminator
so the LLM sees a tiny schema. Calling it with no ``action`` (or
``action="help"``) returns fresh usage text, which keeps the tool description
short and re-shows the instructions on every use.

Heavy logic lives here as pure-ish helpers so the agent-loop dispatch stays
lean (mirrors ``synthetic_tools.py``). Each non-blocking action returns a
plain string; the agent loop wraps it in a ``ToolResult``. The blocking
``collect`` action is validated here and parked by the agent loop.

What this tool still does, and why the rest moved to the ``hive-cred`` CLI:
- ``collect`` parks the loop and pops a secure form — an in-process concern.
- ``attach`` / ``detach`` pin credentials to THIS session's prompt — the
  session id only exists in-process.
- ``browse`` / ``inspect`` / ``reveal`` were RETIRED (2026-08-25) in favour of
  ``hive-cred browse|inspect|token``. ``reveal`` in particular dropped a raw,
  un-refreshed OAuth access token into the conversation; agents pasted it into
  scripts and every run longer than the token's lifetime died with a 401.
  ``hive-cred token`` refreshes on every call, so scripts fetch at call time
  and never hold a token. Calling a retired action returns the CLI equivalent.

Security model:
- ``collect`` never returns secrets to the loop. It parks the loop and emits a
  form-request event; the frontend POSTs the secret straight to the encrypted
  store via ``POST /api/sessions/{id}/credential-form``.
- No action of this tool returns a secret value any more.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from framework.credentials.catalog import account_provider, credential_specs
from framework.llm.provider import Tool

logger = logging.getLogger(__name__)

# Secret field-name hints used to pick the "primary" key and to default a
# field's masked-input flag when the agent doesn't say.
_SECRET_NAME_HINTS = ("api_key", "apikey", "token", "access_token", "secret", "password", "key")

_MAX_FIELDS = 8

# Actions that used to live here. Each maps to the terminal command that
# replaced it, so a stale call still teaches the agent the new surface.
RETIRED_ACTIONS: dict[str, str] = {
    "browse": "hive-cred browse [query] --json",
    "inspect": "hive-cred inspect <credential_id> [--account <alias>] --json",
    "reveal": "hive-cred token <credential_id> [--account <alias>] [--key <name>]",
}


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

CREDENTIALS_TOOL_DESCRIPTION = (
    "Collect a new credential from the user via a secure form, or pin one to "
    "this session (a CLI-style tool; call with no arguments for usage). "
    "Actions: help, collect, attach, detach. To SEE what is connected or to "
    "USE a credential value in a script, run the `hive-cred` CLI in the "
    "terminal instead: `hive-cred browse --json`, `hive-cred inspect <id> --json`, "
    "`hive-cred token <id> --account <alias>`."
)

CREDENTIALS_HELP = """\
`credentials` — collect or pin credentials for this session.

Call this tool with an `action`. With no action (or action="help") you get this
usage text. Secrets you collect are stored encrypted and are never shown to you.

Actions:

- help
    Show this usage text.

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

Everything else is the `hive-cred` CLI, run with terminal_exec (always --json
when you will parse it):

  hive-cred browse [query] --json               what is connected (aliases,
                                                identities) and what could be
  hive-cred inspect <id> [--account <alias>] --json
                                                one credential: accounts, key
                                                names, type — no values
  hive-cred token <id> --account <alias>        a FRESH value for a script.
                                                OAuth tokens are refreshed on
                                                every call; add --json for
                                                expires_at

Rules for token values: never paste one into a script or file. OAuth access
tokens last about an hour; a script that embeds one will 401 mid-run. Call
`hive-cred token` right before each request instead:
  TOK=$(hive-cred token google --account email3)
Prefer letting tools resolve credentials by account=<alias> whenever a tool
exists for the job.

Examples:
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
                        "collect",
                        "attach",
                        "detach",
                    ],
                    "description": ('What to do. Defaults to "help", which returns full usage. Call help first if unsure.'),
                },
                "credential_id": {
                    "type": "string",
                    "description": ("Logical credential / provider id (e.g. 'stripe', 'github'). Required for collect/attach/detach."),
                },
                "account": {
                    "type": "string",
                    "description": ("Account alias for multi-account providers (e.g. 'work'). Defaults to 'default'."),
                },
                "title": {
                    "type": "string",
                    "description": "Optional form title for collect.",
                },
                "instructions": {
                    "type": "string",
                    "description": "Optional help text shown above the collect form.",
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


def retired_action_message(action: str, credential_id: str = "", account: str = "", key: str = "") -> str:
    """The reply to a retired action: the exact CLI call to make instead."""
    cid = credential_id or "<credential_id>"
    acct = f" --account {account}" if account else ""
    cmd = {
        "browse": "hive-cred browse --json",
        "inspect": f"hive-cred inspect {cid}{acct} --json",
        "reveal": f"hive-cred token {cid}{acct}" + (f" --key {key}" if key else ""),
    }[action]
    why = ""
    if action == "reveal":
        why = " It returns a fresh, refreshed value each call; never paste the output into a script — call it at request time."
    return f"ERROR: `credentials` action '{action}' was retired. Run this in the terminal instead: `{cmd}`.{why}"


def _credential_specs() -> dict[str, Any]:
    return credential_specs()


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
    provider = account_provider(acct)
    cred_id = acct.get("credential_id") or provider
    alias = acct.get("alias") or "default"
    for r in refs:
        rid = r.get("credential_id")
        racct = r.get("account") or "default"
        if rid in (provider, cred_id) and racct == alias:
            return True
    return False
