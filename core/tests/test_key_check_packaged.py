"""Provider key checks run from the installed package.

Regression: the server imported its key checks from the repo's ``scripts/``
directory, which is not shipped in the wheel. On an installed runtime, saving
a provider in Settings (``POST /api/config/provider-library/apply``) failed
with ``ModuleNotFoundError: No module named 'scripts.check_llm_key'``.
"""

from __future__ import annotations

import pytest

from framework.server.routes_config import _validate_provider_key


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict:
        return {}


@pytest.fixture
def requested(monkeypatch) -> list[str]:
    """Record the URLs the checks call, answering each with a 200."""
    import httpx

    urls: list[str] = []

    class _Client:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None, **_kw):
            urls.append(url)
            return _Response(200)

    monkeypatch.setattr(httpx, "Client", _Client)
    return urls


@pytest.mark.asyncio
async def test_server_validates_a_key_without_the_repo_scripts_dir(requested):
    result = await _validate_provider_key("OpenAI", "sk-test")

    assert result == {"valid": True, "message": "OpenAI API key valid"}
    assert requested == ["https://api.openai.com/v1/models"]


@pytest.mark.asyncio
async def test_custom_api_base_is_checked_at_its_models_endpoint(requested):
    result = await _validate_provider_key("zai", "sk-test", api_base="https://api.z.ai/v1/")

    assert result["valid"] is True
    assert requested == ["https://api.z.ai/v1/models"]
