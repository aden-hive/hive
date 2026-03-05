from types import SimpleNamespace

from framework.credentials.validation import validate_agent_credentials


def test_web_search_is_keyless_prefight(monkeypatch, tmp_path):
    """web_search should not block agent startup on missing Brave credentials."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HIVE_CREDENTIAL_KEY", raising=False)
    monkeypatch.delenv("ADEN_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)

    node = SimpleNamespace(tools=["web_search"], node_type="function")
    result = validate_agent_credentials([node], verify=False, raise_on_error=False)

    assert result.has_errors is False
    assert result.failed == []


def test_exa_search_still_requires_credential(monkeypatch, tmp_path):
    """Non-keyless search tools should continue to enforce credentials."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HIVE_CREDENTIAL_KEY", raising=False)
    monkeypatch.delenv("ADEN_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    node = SimpleNamespace(tools=["exa_search"], node_type="function")
    result = validate_agent_credentials([node], verify=False, raise_on_error=False)

    assert result.has_errors is True
    assert any(c.credential_name == "exa_search" for c in result.failed)
