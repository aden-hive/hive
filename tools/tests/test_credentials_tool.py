"""Tests for the single CLI-style ``credentials`` synthetic tool helpers.

Covers what is left in-process after browse/inspect/reveal were retired to the
``hive-cred`` CLI: collect only carries field specs, the schema no longer offers
the retired actions and the help teaches the CLI, retired calls return the
replacement command, session attachments round-trip, and the compact prompt
summary. The secret boundary of browse/inspect/token is tested with the CLI in
``core/tests/test_hive_cred_cli.py``.
"""

from __future__ import annotations

import json

import pytest
from framework.agent_loop.internals import credential_tool as ct
from framework.credentials.catalog import format_account_line
from framework.orchestrator.prompting import build_accounts_prompt, build_credentials_summary

from aden_tools.credentials.store_adapter import CredentialStoreAdapter

# ---------------------------------------------------------------------------
# Tool definition + help
# ---------------------------------------------------------------------------


def test_build_tool_shape():
    tool = ct.build_credentials_tool()
    assert tool.name == "credentials"
    props = tool.parameters["properties"]
    assert set(tool.parameters.get("required", [])) == set()  # action defaults to help
    actions = props["action"]["enum"]
    assert set(actions) == {"help", "collect", "attach", "detach"}
    # The retired actions must not be offered in the schema at all — an LLM
    # picks from the enum, so leaving them there keeps teaching the old path.
    for retired in ct.RETIRED_ACTIONS:
        assert retired not in actions
    assert "key" not in props and "query" not in props


def test_help_lists_every_action_and_teaches_the_cli():
    text = ct.render_help()
    for a in ("collect", "attach", "detach"):
        assert a in text
    # Discovery: the tool's own help is where an agent learns the CLI surface.
    assert "hive-cred browse" in text
    assert "hive-cred inspect" in text
    assert "hive-cred token" in text
    assert "never paste" in text.lower()


def test_description_points_at_cli():
    assert "hive-cred" in ct.CREDENTIALS_TOOL_DESCRIPTION


def test_retired_actions_return_the_replacement_command():
    """A stale reveal call gets the exact CLI command back, never a value."""
    msg = ct.retired_action_message("reveal", "google", "email3", "access_token")
    assert msg.startswith("ERROR")
    assert "hive-cred token google --account email3 --key access_token" in msg
    assert "never paste" in msg
    assert "hive-cred browse --json" in ct.retired_action_message("browse")
    assert "hive-cred inspect google --account email3 --json" in ct.retired_action_message("inspect", "google", "email3")


# ---------------------------------------------------------------------------
# collect — validation builds a no-secret form payload
# ---------------------------------------------------------------------------


def test_collect_requires_credential_id():
    payload, err = ct.validate_collect_input({"action": "collect"})
    assert payload is None
    assert err and "credential_id" in err


def test_collect_default_field_is_secret_api_key():
    # Unknown id → deterministic fallback field.
    payload, err = ct.validate_collect_input({"credential_id": "my_custom_service"})
    assert err is None
    assert payload["credential_id"] == "my_custom_service"
    assert payload["account"] == "default"
    assert payload["fields"] == [{"name": "api_key", "label": "API key", "secret": True, "required": True, "placeholder": ""}]


def test_collect_default_field_for_known_spec():
    # A known spec derives a single secret field; shape is fully normalized.
    payload, err = ct.validate_collect_input({"credential_id": "stripe"})
    assert err is None
    assert len(payload["fields"]) == 1
    field = payload["fields"][0]
    assert field["secret"] is True
    assert set(field.keys()) == {"name", "label", "secret", "required", "placeholder"}


def test_collect_infers_secret_from_field_name():
    payload, err = ct.validate_collect_input(
        {
            "credential_id": "db",
            "account": "prod",
            "fields": [
                {"name": "username"},
                {"name": "password"},
            ],
        }
    )
    assert err is None
    by_name = {f["name"]: f for f in payload["fields"]}
    assert by_name["password"]["secret"] is True  # inferred from name
    assert by_name["username"]["secret"] is False
    assert payload["account"] == "prod"


def test_collect_payload_carries_no_values():
    """The collect payload must never contain entered secret values."""
    payload, err = ct.validate_collect_input({"credential_id": "stripe", "fields": [{"name": "api_key", "secret": True}]})
    assert err is None
    blob = json.dumps(payload)
    # Field specs only — keys describing the field, never a "value" of a secret.
    for field in payload["fields"]:
        assert set(field.keys()) == {"name", "label", "secret", "required", "placeholder"}
    assert "value" not in blob


def test_collect_rejects_bad_field():
    payload, err = ct.validate_collect_input({"credential_id": "stripe", "fields": [{"label": "no name here"}]})
    assert payload is None
    assert err


def test_collect_rejects_bad_account_alias():
    payload, err = ct.validate_collect_input({"credential_id": "stripe", "account": "a b"})
    assert payload is None
    assert err


# ---------------------------------------------------------------------------
# Session attachments
# ---------------------------------------------------------------------------


@pytest.fixture
def hive_home(tmp_path, monkeypatch):
    monkeypatch.setattr("framework.config.HIVE_HOME", tmp_path)
    return tmp_path


def test_attachments_round_trip(hive_home):
    sid = "session_test_1"
    assert ct.read_attachments(sid) == []

    msg = ct.add_attachment(sid, "stripe", "work")
    assert "Attached" in msg
    refs = ct.read_attachments(sid)
    assert refs == [{"credential_id": "stripe", "account": "work"}]

    # Idempotent
    msg2 = ct.add_attachment(sid, "stripe", "work")
    assert "already attached" in msg2
    assert len(ct.read_attachments(sid)) == 1

    # Remove
    msg3 = ct.remove_attachment(sid, "stripe", "work")
    assert "Detached" in msg3
    assert ct.read_attachments(sid) == []

    # Remove non-existent
    msg4 = ct.remove_attachment(sid, "stripe", "work")
    assert "was not attached" in msg4


def test_attachment_defaults_account(hive_home):
    sid = "session_test_2"
    ct.add_attachment(sid, "github")
    assert ct.read_attachments(sid) == [{"credential_id": "github", "account": "default"}]


def test_attachment_matches():
    refs = [{"credential_id": "github", "account": "work"}]
    assert ct.attachment_matches({"provider": "github", "alias": "work"}, refs)
    assert ct.attachment_matches({"credential_id": "github", "alias": "work"}, refs)
    assert not ct.attachment_matches({"provider": "github", "alias": "personal"}, refs)
    assert not ct.attachment_matches({"provider": "slack", "alias": "work"}, refs)


def test_add_attachment_without_session():
    assert "no active session" in ct.add_attachment(None, "stripe")


# ---------------------------------------------------------------------------
# local-account resolution (the paths tools use)
# ---------------------------------------------------------------------------


def _inmemory_registry_with(credential_id: str, alias: str, key: str):
    from framework.credentials.local.registry import LocalCredentialRegistry
    from framework.credentials.storage import InMemoryStorage

    reg = LocalCredentialRegistry(InMemoryStorage())
    reg.save_account(credential_id, alias, key, run_health_check=False)
    return reg


def test_adapter_resolves_collected_local_account(monkeypatch):
    """get / get_by_alias resolve a collected local account (the paths tools use)."""
    from framework.credentials.local.registry import LocalCredentialRegistry

    reg = _inmemory_registry_with("stripe", "default", "sk_adapter_local")
    monkeypatch.setattr(LocalCredentialRegistry, "default", staticmethod(lambda: reg))
    adapter = CredentialStoreAdapter.for_testing({})

    assert adapter.get("stripe") == "sk_adapter_local"  # no account (single-local fallback)
    assert adapter.get("stripe", account="default") == "sk_adapter_local"
    assert adapter.get_by_alias("stripe", "default") == "sk_adapter_local"


def test_strict_mode_counts_local_accounts(monkeypatch):
    """Queen strict-account-mode must surface ambiguity from local accounts too."""
    import pytest as _pytest
    from framework.credentials.local.registry import LocalCredentialRegistry
    from framework.credentials.models import AccountSelectionRequiredError
    from framework.credentials.storage import InMemoryStorage

    from aden_tools.credentials.store_adapter import queen_strict_account_mode

    # Two local accounts → must force disambiguation, not silently return None.
    multi = LocalCredentialRegistry(InMemoryStorage())
    multi.save_account("stripe", "work", "k1", run_health_check=False)
    multi.save_account("stripe", "home", "k2", run_health_check=False)
    monkeypatch.setattr(LocalCredentialRegistry, "default", staticmethod(lambda: multi))
    adapter = CredentialStoreAdapter.for_testing({})
    with queen_strict_account_mode():
        with _pytest.raises(AccountSelectionRequiredError):
            adapter.get("stripe")

    # Exactly one local account → no ambiguity, resolves it.
    single = LocalCredentialRegistry(InMemoryStorage())
    single.save_account("stripe", "only", "kX", run_health_check=False)
    monkeypatch.setattr(LocalCredentialRegistry, "default", staticmethod(lambda: single))
    with queen_strict_account_mode():
        assert adapter.get("stripe") == "kX"


# ---------------------------------------------------------------------------
# Prompt summary
# ---------------------------------------------------------------------------


def test_summary_empty():
    text = build_credentials_summary([])
    assert "collect" in text


def test_summary_counts_providers_without_leaking_aliases():
    accounts = [
        {"provider": "github", "alias": "work", "identity": {"email": "a@b.com"}},
        {"provider": "github", "alias": "personal", "identity": {}},
        {"provider": "slack", "alias": "team"},
    ]
    text = build_credentials_summary(accounts)
    assert "github (2)" in text
    assert "slack" in text
    # Compact summary must not dump per-account aliases / identities.
    assert "work" not in text
    assert "a@b.com" not in text


def test_account_line_renderer_serves_cli_and_prompt_shapes():
    account = {
        "provider": "github",
        "alias": "work",
        "identity": {"email": "a@b.com"},
        "source": "local",
        "status": "failed",
    }

    assert format_account_line(account) == '- github "work" (a@b.com) [local] — failed'
    prompt = build_accounts_prompt([account])
    assert '- "work" (a@b.com) [local]' in prompt
    assert "— failed" not in prompt
