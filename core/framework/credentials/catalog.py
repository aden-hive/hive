"""Read-only metadata and rendering for ``hive-cred browse`` and ``inspect``."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_BROWSE_PROVIDERS = 40


def credential_specs() -> dict[str, Any]:
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        return CREDENTIAL_SPECS
    except Exception:
        return {}


def account_provider(acct: dict) -> str:
    return str(acct.get("provider") or acct.get("credential_id") or "").strip()


def _format_identity(identity: Any) -> str:
    if not isinstance(identity, dict):
        return ""
    parts = [str(v) for v in identity.values() if v]
    return f" ({', '.join(parts)})" if parts else ""


def format_account_line(
    acct: dict,
    *,
    include_provider: bool = True,
    include_status: bool = True,
    default_alias: str = "default",
) -> str:
    provider = f"{account_provider(acct)} " if include_provider else ""
    alias = acct.get("alias", "") or default_alias
    source = acct.get("source", "aden")
    status = acct.get("status")
    tag = " [local]" if source == "local" else ""
    status_tag = f" — {status}" if include_status and status and status != "active" else ""
    return f'- {provider}"{alias}"{_format_identity(acct.get("identity"))}{tag}{status_tag}'


def _public_account(acct: dict) -> dict[str, Any]:
    """The JSON shape of one connected account. Whitelisted keys only."""
    return {
        "provider": account_provider(acct),
        "alias": acct.get("alias") or "default",
        "identity": acct.get("identity") if isinstance(acct.get("identity"), dict) else None,
        "source": acct.get("source", "aden"),
        "status": acct.get("status") or "active",
    }


def browse(adapter: Any, query: str | None = None, specs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Connected accounts + connectable providers, filtered by ``query``."""
    accounts: list[dict] = []
    if adapter is not None:
        try:
            accounts = adapter.get_all_account_info()
        except Exception:
            logger.debug("catalog.browse: get_all_account_info failed", exc_info=True)
            accounts = []

    q = (query or "").strip().lower()
    connected_providers = {account_provider(a) for a in accounts}
    shown = [a for a in accounts if not q or q in format_account_line(a).lower()]

    connectable: list[dict[str, str]] = []
    for name, spec in (specs if specs is not None else credential_specs()).items():
        cred_id = getattr(spec, "credential_id", None) or name
        provider = getattr(spec, "aden_provider_name", "") or cred_id
        if provider in connected_providers or cred_id in connected_providers:
            continue
        desc = getattr(spec, "description", "") or ""
        if q and q not in f"{cred_id} {desc}".lower():
            continue
        connectable.append({"credential_id": cred_id, "description": desc})
    connectable.sort(key=lambda c: c["credential_id"])

    return {
        "ok": True,
        "connected": [_public_account(a) for a in shown],
        "connectable": connectable[:MAX_BROWSE_PROVIDERS],
        "connectable_truncated": max(0, len(connectable) - MAX_BROWSE_PROVIDERS),
    }


def render_browse(result: dict[str, Any]) -> str:
    lines: list[str] = ["# Available credentials", ""]
    connected = result.get("connected") or []
    if connected:
        lines.append("Connected (usable now via account=<alias>):")
        lines.extend(format_account_line(a) for a in connected)
        lines.append("")
    else:
        lines.append("No credentials are connected yet.")
        lines.append("")
    connectable = result.get("connectable") or []
    if connectable:
        lines.append("Connectable providers (ask the user to connect one with the credentials tool, action=collect):")
        lines.extend(f"- {c['credential_id']} — {c['description']}".rstrip(" —") for c in connectable)
        more = result.get("connectable_truncated") or 0
        if more:
            lines.append(f"… and {more} more (pass a query to filter).")
        lines.append("")
    lines.append("`hive-cred inspect <id> --account <alias>` for details; `hive-cred token <id> --account <alias>` for a fresh value.")
    return "\n".join(lines)


def inspect(adapter: Any, credential_id: str, account: str = "") -> dict[str, Any]:
    """Metadata for one credential: accounts, key NAMES, type. No values."""
    accounts: list[dict] = []
    if adapter is not None:
        try:
            accounts = [a for a in adapter.get_all_account_info() if account_provider(a) == credential_id or a.get("credential_id") == credential_id]
        except Exception:
            accounts = []
    if account:
        accounts = [a for a in accounts if (a.get("alias") or "default") == account]

    keys: list[str] = []
    cred_type: str | None = None
    if adapter is not None:
        try:
            cred = adapter.store.get_credential(credential_id, refresh_if_needed=False)
            if cred is not None:
                keys = sorted(k for k in cred.keys if not k.startswith("_"))
                cred_type = str(cred.credential_type)
        except Exception:
            logger.debug("catalog.inspect: store lookup failed", exc_info=True)

    return {
        "ok": True,
        "credential_id": credential_id,
        "account": account or None,
        "accounts": [_public_account(a) for a in accounts],
        "keys": keys,
        "type": cred_type,
    }


def render_inspect(result: dict[str, Any]) -> str:
    cid = result.get("credential_id")
    account = result.get("account")
    out: list[str] = [f"# {cid}" + (f' (account "{account}")' if account else "")]
    accounts = result.get("accounts") or []
    if accounts:
        out.append("Accounts:")
        out.extend(format_account_line(a) for a in accounts)
    else:
        out.append("No connected account found for this id.")
    if result.get("keys"):
        out.append(f"Keys: {', '.join(result['keys'])}")
    if result.get("type"):
        out.append(f"Type: {result['type']}")
    out.append("")
    out.append(
        "To use it, pass account=<alias> to the relevant tool. Need the raw value in a script? `hive-cred token` fetches a fresh one at call time."
    )
    return "\n".join(out)
