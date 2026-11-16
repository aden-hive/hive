"""``hive-cred token`` — a script gets a FRESH value, never a stale one.

Encodes the 2026-08-12/20 incident: an agent pasted a revealed OAuth access
token into a send script; one run got a token that was already 26 minutes into
its hour (the alias lookup never refreshed), another outlived the hour, and both
died with Gmail 401s mid-batch. The properties under test:

* an expired OAuth token is refreshed BEFORE it is printed;
* the plain output is the value and nothing else (so ``$(...)`` composes);
* a refresh failure is a distinct "reconnect" exit, not a stale token;
* an unknown credential / account is a not-found exit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from framework.credentials import cli
from framework.credentials.models import (
    CredentialKey,
    CredentialObject,
    CredentialRefreshError,
    CredentialType,
)
from framework.credentials.provider import CredentialProvider
from framework.credentials.storage import InMemoryStorage
from framework.credentials.store import CredentialStore
from framework.trackerdb import errors


class _AliasStorage(InMemoryStorage):
    """InMemoryStorage plus the provider scan ``get_credential_by_alias`` needs."""

    def load_all_for_provider(self, provider_name: str) -> list[CredentialObject]:
        return [c for c in self._data.values() if c.provider_type == provider_name]


class _FakeOAuthProvider(CredentialProvider):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.refreshes = 0

    @property
    def provider_id(self) -> str:
        return "fake_oauth"

    @property
    def supported_types(self) -> list[CredentialType]:
        return [CredentialType.OAUTH2]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        self.refreshes += 1
        if self.fail:
            raise CredentialRefreshError("refresh token revoked")
        fresh = credential.model_copy(deep=True)
        fresh.set_key("access_token", "ya29.FRESH", expires_at=datetime.now(UTC) + timedelta(hours=1))
        return fresh

    def validate(self, credential: CredentialObject) -> bool:  # noqa: ARG002
        return True

    def should_refresh(self, credential: CredentialObject) -> bool:
        key = credential.keys.get("access_token")
        return bool(key and key.expires_at and datetime.now(UTC) >= key.expires_at)


def _google_cred(alias: str, expires_in: timedelta) -> CredentialObject:
    now = datetime.now(UTC)
    return CredentialObject(
        id=f"google_{alias}",
        credential_type=CredentialType.OAUTH2,
        provider_id="fake_oauth",
        auto_refresh=True,
        keys={
            "access_token": CredentialKey(name="access_token", value=SecretStr("ya29.STALE"), expires_at=now + expires_in),
            "_alias": CredentialKey(name="_alias", value=SecretStr(alias)),
            "_integration_type": CredentialKey(name="_integration_type", value=SecretStr("google")),
        },
    )


class _Adapter:
    def __init__(self, store: CredentialStore) -> None:
        self.store = store


@pytest.fixture
def stale_store(monkeypatch: pytest.MonkeyPatch):
    provider = _FakeOAuthProvider()
    cred = _google_cred("email3", timedelta(minutes=-5))
    store = CredentialStore(storage=_AliasStorage({cred.id: cred}), providers=[provider], auto_refresh=True)
    monkeypatch.setattr(cli, "_adapter", lambda: _Adapter(store))
    return provider


def _run(argv: list[str], capsys) -> tuple[int, str]:
    try:
        cli.main(argv)
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    return code, capsys.readouterr().out


def test_token_refreshes_expired_oauth_before_printing(stale_store, capsys):
    code, out = _run(["token", "google", "--account", "email3", "--json"], capsys)
    body = json.loads(out)
    assert code == 0
    assert body["ok"] is True
    assert body["value"] == "ya29.FRESH", "the stale on-disk token must never be handed out"
    assert stale_store.refreshes == 1
    assert body["expires_in_seconds"] > 3000
    assert body["account"] == "email3" and body["key"] == "access_token"


def test_plain_output_is_the_value_only(stale_store, capsys):
    """``TOK=$(hive-cred token ...)`` must capture nothing but the token."""
    code, out = _run(["token", "google", "--account", "email3"], capsys)
    assert code == 0
    assert out == "ya29.FRESH\n"


def test_refresh_failure_is_a_reauth_exit_not_a_stale_token(monkeypatch, capsys):
    provider = _FakeOAuthProvider(fail=True)
    cred = _google_cred("email3", timedelta(minutes=-5))
    store = CredentialStore(storage=_AliasStorage({cred.id: cred}), providers=[provider], auto_refresh=True)
    monkeypatch.setattr(cli, "_adapter", lambda: _Adapter(store))

    code, out = _run(["token", "google", "--account", "email3", "--json"], capsys)
    body = json.loads(out)
    assert code == cli.EXIT_REAUTH
    assert body["ok"] is False and body["error"]["code"] == "reauth_required"
    assert "ya29" not in out


def test_unknown_account_is_not_found(stale_store, capsys):
    code, out = _run(["token", "google", "--account", "Timothy", "--json"], capsys)
    body = json.loads(out)
    assert code == errors.EXIT_NOT_FOUND
    assert body["error"]["code"] == "not_found"


def test_not_found_names_the_id_namespace_that_actually_works(stale_store, capsys):
    """`get_account_info` reports opaque ids (`Z29vZ2xlOnJpY2hhcmQ6...`); this
    takes the credential name (`google`). Passing the first got exit 4 with
    nothing saying which namespace was wanted."""
    code, out = _run(["token", "Z29vZ2xlOnJpY2hhcmQ6MTg3Njc6MTYzNzc", "--account", "richard", "--json"], capsys)
    body = json.loads(out)
    assert code == errors.EXIT_NOT_FOUND
    message = body["error"]["message"]
    assert "credential name" in message and "opaque" in message


def test_known_credential_ids_hint_reads_the_same_field_listings_report(monkeypatch):
    """Must name the exact string account listings show as `credential_id`,
    or it is a third spelling to guess between."""
    accounts = [{"credential_id": "google"}, {"credential_id": "slack_token"}, {"credential_id": "google"}]
    monkeypatch.setattr(cli, "_adapter", lambda: type("_A", (), {"get_all_account_info": lambda self: accounts})())
    assert cli._known_credential_ids_hint() == " Known credential ids: google, slack_token."

    # An error path must not raise its own error.
    monkeypatch.setattr(cli, "_adapter", lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    assert cli._known_credential_ids_hint() == ""


def test_console_script_registered():
    import tomllib
    from pathlib import Path

    data = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["hive-cred"] == "framework.credentials.cli:main"


# --------------------------------------------------------------------------
# browse / inspect — metadata only, never a value
# --------------------------------------------------------------------------


class _AccountsAdapter(_Adapter):
    def __init__(self, store: CredentialStore, accounts: list[dict]) -> None:
        super().__init__(store)
        self._accounts = accounts

    def get_all_account_info(self) -> list[dict]:
        return self._accounts


@pytest.fixture
def accounts_store(monkeypatch: pytest.MonkeyPatch):
    cred = _google_cred("email3", timedelta(hours=1))
    store = CredentialStore(storage=_AliasStorage({cred.id: cred}), providers=[_FakeOAuthProvider()], auto_refresh=True)
    accounts = [
        {"provider": "google", "alias": "email3", "identity": {"email": "vincent@acho.io"}, "source": "aden", "status": "active"},
        {"provider": "google", "alias": "primary", "identity": {"email": "vincent@adenhq.com"}, "source": "aden", "status": "active"},
    ]
    monkeypatch.setattr(cli, "_adapter", lambda: _AccountsAdapter(store, accounts))
    monkeypatch.setattr("framework.credentials.catalog.credential_specs", lambda: {})


def test_browse_lists_accounts_but_never_a_value(accounts_store, capsys):
    code, out = _run(["browse", "--json"], capsys)
    body = json.loads(out)
    assert code == 0 and body["ok"] is True
    aliases = {a["alias"] for a in body["connected"]}
    assert aliases == {"email3", "primary"}
    assert body["connected"][0]["identity"] == {"email": "vincent@acho.io"}
    assert "ya29" not in out

    code, out = _run(["browse", "acho"], capsys)
    assert code == 0
    assert 'google "email3"' in out and "primary" not in out
    assert "ya29" not in out


def test_inspect_shows_key_names_not_values(accounts_store, capsys):
    code, out = _run(["inspect", "google_email3", "--json"], capsys)
    body = json.loads(out)
    assert code == 0
    assert body["keys"] == ["access_token"]
    assert body["type"] == "oauth2"
    assert "ya29" not in out


def test_token_resolves_a_collected_local_account(monkeypatch, capsys):
    """Keys collected through the secure form (LocalCredentialRegistry) resolve
    too, with and without --account — the same fallback the tools use."""
    from framework.credentials.local.registry import LocalCredentialRegistry
    from framework.credentials.storage import InMemoryStorage as _Mem

    reg = LocalCredentialRegistry(_Mem())
    reg.save_account("stripe", "default", "sk_local_value", run_health_check=False)
    monkeypatch.setattr(LocalCredentialRegistry, "default", staticmethod(lambda: reg))
    monkeypatch.setattr(cli, "_adapter", lambda: _Adapter(CredentialStore(storage=_AliasStorage({}))))

    assert _run(["token", "stripe"], capsys) == (0, "sk_local_value\n")
    assert _run(["token", "stripe", "--account", "default"], capsys) == (0, "sk_local_value\n")
