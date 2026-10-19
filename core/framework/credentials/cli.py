"""``hive-cred`` — hand a script a FRESH credential value at call time.

Why this exists: when an agent needed to call a provider API from a script it
had one option, ``credentials reveal``, which drops a raw OAuth access token
into the conversation. The agent then pasted that token into ``/tmp/send_*.py``
and every run longer than the token's lifetime died with a 401 (dozens of
re-reveals in one session). Scripts should not hold tokens at all; they should
ask for one when they are about to use it:

    TOK=$(hive-cred token google --account email3)
    curl -H "Authorization: Bearer $TOK" https://gmail.googleapis.com/...

Every call goes through the runtime's credential store, which refreshes an
expired OAuth token via the platform before returning it. The agent never sees
the platform API key, and nothing long-lived lands in a file.

Same argparse / ``errors.run`` standard as ``hive-tracker`` and ``hive-email``:
``--json`` on every leaf, stable exit codes. Without ``--json`` the ``token``
command prints ONLY the value, so it composes with ``$(...)``.

``browse`` and ``inspect`` are the metadata half (what is connected, which
aliases, which key names — never values). They replaced the same-named actions
of the in-process ``credentials`` tool, which now only keeps ``collect`` (the
secure form has to park the agent loop, which a subprocess cannot do) and the
session pins ``attach`` / ``detach``.

Run:  ``hive-cred token <credential_id> [--account ALIAS] [--key NAME] [--json]``
      ``hive-cred browse [query] [--json]``
      ``hive-cred inspect <credential_id> [--account ALIAS] [--json]``
      (fallback: ``python -m framework.credentials.cli ...``)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, NoReturn

from framework.trackerdb import errors

_ARGV: list[str] = []

# Exit codes beyond the shared taxonomy in trackerdb.errors. 3 is "unavailable"
# in hive-email's contract, so the store being unreachable maps there.
EXIT_UNAVAILABLE = errors.EXIT_PERMISSION
EXIT_REAUTH = errors.EXIT_DOMAIN


def _setup_cli_logging() -> None:
    """Keep stdout clean: the caller captures it as the token."""
    root = logging.getLogger()
    log_file = os.environ.get("HIVE_CRED_LOG")
    if log_file:
        handler: logging.Handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
    elif not root.handlers:
        root.addHandler(logging.NullHandler())


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        err = errors.validation(f"{self.prog}: {message}")
        if "--json" in _ARGV:
            print(json.dumps(err.envelope(), indent=2, default=str))
        else:
            self.print_usage(sys.stderr)
            print(f"error: {err.message}", file=sys.stderr)
        raise SystemExit(err.exit_code)


def _adapter() -> Any:
    """The same store the runtime's tools use (encrypted local + platform sync)."""
    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        return CredentialStoreAdapter.default()
    except Exception as exc:  # pragma: no cover - environment-specific
        raise errors.TrackerError("unavailable", f"credential store unavailable: {exc}", EXIT_UNAVAILABLE) from exc


def _known_credential_ids_hint() -> str:
    """ " Known credential ids: a, b." — or "" when they can't be read.

    The same string account listings report as ``credential_id``. Best-effort:
    an error path must not raise its own error.
    """
    try:
        ids = sorted({a.get("credential_id", "") for a in _adapter().get_all_account_info() if a.get("credential_id")})
    except Exception:
        return ""
    return f" Known credential ids: {', '.join(ids)}." if ids else ""


def cmd_token(args: argparse.Namespace) -> dict[str, Any]:
    from framework.credentials.resolve import CredentialExpiredError, SecretNotFound, resolve_secret

    credential_id = (args.credential_id or "").strip()
    if not credential_id:
        raise errors.validation("credential_id is required.")
    account = (args.account or "").strip()
    key = (args.key or "").strip()
    try:
        resolved = resolve_secret(_adapter(), credential_id, account, key)
    except SecretNotFound as exc:
        raise errors.not_found(
            f"no value stored for {exc}. `credential_id` is the credential name (e.g. `google`), not the opaque "
            f"account id reported by get_account_info.{_known_credential_ids_hint()} "
            "Run `hive-cred browse` for the accounts and their aliases, then retry with the right --account.",
            credential_id=credential_id,
            account=account or None,
        ) from exc
    except CredentialExpiredError as exc:
        raise errors.TrackerError(
            "reauth_required",
            f"{credential_id}"
            + (f"/{account}" if account else "")
            + " is expired and could not be refreshed. The user must reconnect it; do not retry.",
            EXIT_REAUTH,
            credential_id=credential_id,
            account=account or None,
            help_url=exc.help_url,
        ) from exc
    return {
        "ok": True,
        "credential_id": resolved.credential_id,
        "account": resolved.account,
        "key": resolved.key,
        "value": resolved.value,
        "expires_at": resolved.expires_at.isoformat() if resolved.expires_at else None,
        "expires_in_seconds": resolved.expires_in_seconds,
    }


def cmd_browse(args: argparse.Namespace) -> dict[str, Any]:
    from framework.credentials import catalog

    return catalog.browse(_adapter(), args.query)


def cmd_inspect(args: argparse.Namespace) -> dict[str, Any]:
    from framework.credentials import catalog

    credential_id = (args.credential_id or "").strip()
    if not credential_id:
        raise errors.validation("credential_id is required.")
    return catalog.inspect(_adapter(), credential_id, (args.account or "").strip())


def _render(result: Any) -> None:
    from framework.credentials import catalog

    if isinstance(result, dict):
        # Value only: `TOK=$(hive-cred token ...)` must capture nothing else.
        if "value" in result:
            print(result["value"])
            return
        if "connectable" in result:
            print(catalog.render_browse(result))
            return
        if "keys" in result:
            print(catalog.render_inspect(result))
            return
    print(result)


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit a JSON envelope on stdout")

    p = _Parser(prog="hive-cred", description="Fetch a fresh credential value for use in a script.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("token", help="print a fresh value (OAuth tokens are refreshed first)", parents=[common])
    sp.add_argument("credential_id", help="provider / credential id, e.g. google, apollo")
    sp.add_argument("--account", default="", metavar="ALIAS", help="connected-account alias, e.g. email3 (required when several are connected)")
    sp.add_argument("--key", default="", metavar="NAME", help="which key to print (default: the credential's primary key, e.g. access_token)")
    sp.epilog = (
        "Call this right before each request rather than once per script: the value printed is\n"
        "fresh now, and OAuth access tokens last about an hour.\n"
        "\n"
        "examples:\n"
        "  TOK=$(hive-cred token google --account email3)\n"
        "  hive-cred token google --account email3 --json     # adds expires_at / expires_in_seconds\n"
        "  hive-cred token apollo --key api_key"
    )
    sp.formatter_class = argparse.RawDescriptionHelpFormatter
    sp.set_defaults(func=cmd_token)

    sp = sub.add_parser("browse", help="list connected accounts and connectable providers (metadata only)", parents=[common])
    sp.add_argument("query", nargs="?", default=None, help="optional filter on provider / alias / identity")
    sp.epilog = "examples:\n  hive-cred browse --json\n  hive-cred browse google"
    sp.formatter_class = argparse.RawDescriptionHelpFormatter
    sp.set_defaults(func=cmd_browse)

    sp = sub.add_parser("inspect", help="show one credential's accounts, key names and type (no values)", parents=[common])
    sp.add_argument("credential_id", help="provider / credential id, e.g. google")
    sp.add_argument("--account", default="", metavar="ALIAS", help="restrict to one connected-account alias")
    sp.epilog = "examples:\n  hive-cred inspect google --json\n  hive-cred inspect google --account email3"
    sp.formatter_class = argparse.RawDescriptionHelpFormatter
    sp.set_defaults(func=cmd_inspect)
    return p


def main(argv: list[str] | None = None) -> None:
    _setup_cli_logging()
    argv = list(sys.argv[1:] if argv is None else argv)
    _ARGV[:] = argv
    args = _build_parser().parse_args(argv)
    as_json = bool(args.json) or "--json" in argv
    errors.run(lambda: args.func(args), as_json=as_json, render=_render)


if __name__ == "__main__":
    main()
