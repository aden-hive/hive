from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture(scope="session")
def check_llm_key_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_llm_key.py"
    spec = importlib.util.spec_from_file_location("check_llm_key_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    status_code: int,
    payload: Any | None = None,
    text: str = "",
) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            calls["timeout"] = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any,
        ) -> bool:
            return False

        def get(
            self,
            endpoint: str,
            headers: dict[str, str] | None = None,
            params: dict[str, str] | None = None,
        ) -> _FakeResponse:
            calls["method"] = "get"
            calls["endpoint"] = endpoint
            calls["headers"] = headers
            calls["params"] = params
            return _FakeResponse(status_code, payload=payload, text=text)

        def post(
            self,
            endpoint: str,
            headers: dict[str, str] | None = None,
            json: dict[str, Any] | None = None,
        ) -> _FakeResponse:
            calls["method"] = "post"
            calls["endpoint"] = endpoint
            calls["headers"] = headers
            calls["json"] = json
            return _FakeResponse(status_code, payload=payload, text=text)

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    return calls


def _run_main(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> tuple[int | None, dict[str, Any]]:
    monkeypatch.setattr(module.sys, "argv", ["check_llm_key.py", *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    payload = json.loads(capsys.readouterr().out.strip())
    return exc.value.code, payload


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, {"valid": True, "message": "OpenAI API key valid"}),
        (401, {"valid": False, "message": "Invalid OpenAI API key"}),
        (403, {"valid": False, "message": "OpenAI API key lacks permissions"}),
        (429, {"valid": True, "message": "OpenAI API key valid"}),
        (500, {"valid": False, "message": "OpenAI API returned status 500"}),
    ],
)
def test_check_openai_compatible_statuses(check_llm_key_module, monkeypatch, status_code, expected):
    module = check_llm_key_module
    calls = _patch_client(monkeypatch, module, status_code=status_code)

    result = module.check_openai_compatible(
        "test-key",
        "https://api.openai.com/v1/models",
        "OpenAI",
    )

    assert result == expected
    assert calls["method"] == "get"
    assert calls["endpoint"] == "https://api.openai.com/v1/models"
    assert calls["headers"] == {"Authorization": "Bearer test-key"}


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, {"valid": True, "message": "API key valid"}),
        (400, {"valid": True, "message": "API key valid"}),
        (401, {"valid": False, "message": "Invalid API key"}),
        (403, {"valid": False, "message": "API key lacks permissions"}),
        (429, {"valid": True, "message": "API key valid"}),
        (500, {"valid": False, "message": "Unexpected status 500"}),
    ],
)
def test_check_anthropic_statuses(check_llm_key_module, monkeypatch, status_code, expected):
    module = check_llm_key_module
    calls = _patch_client(monkeypatch, module, status_code=status_code)

    result = module.check_anthropic("test-key")

    assert result == expected
    assert calls["method"] == "post"
    assert calls["endpoint"] == "https://api.anthropic.com/v1/messages"
    assert calls["headers"]["x-api-key"] == "test-key"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, {"valid": True, "message": "Gemini API key valid"}),
        (400, {"valid": False, "message": "Invalid Gemini API key"}),
        (401, {"valid": False, "message": "Invalid Gemini API key"}),
        (403, {"valid": False, "message": "Invalid Gemini API key"}),
        (429, {"valid": True, "message": "Gemini API key valid"}),
        (500, {"valid": False, "message": "Gemini API returned status 500"}),
    ],
)
def test_check_gemini_statuses(check_llm_key_module, monkeypatch, status_code, expected):
    module = check_llm_key_module
    calls = _patch_client(monkeypatch, module, status_code=status_code)

    result = module.check_gemini("test-key")

    assert result == expected
    assert calls["method"] == "get"
    assert calls["endpoint"] == "https://generativelanguage.googleapis.com/v1beta/models"
    assert calls["params"] == {"key": "test-key"}


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, {"valid": True, "message": "MiniMax API key valid"}),
        (400, {"valid": True, "message": "MiniMax API key valid"}),
        (401, {"valid": False, "message": "Invalid MiniMax API key"}),
        (403, {"valid": False, "message": "MiniMax API key lacks permissions"}),
        (422, {"valid": True, "message": "MiniMax API key valid"}),
        (429, {"valid": True, "message": "MiniMax API key valid"}),
        (500, {"valid": False, "message": "MiniMax API returned status 500"}),
    ],
)
def test_check_minimax_statuses(check_llm_key_module, monkeypatch, status_code, expected):
    module = check_llm_key_module
    calls = _patch_client(monkeypatch, module, status_code=status_code)

    result = module.check_minimax("test-key")

    assert result == expected
    assert calls["method"] == "post"
    assert calls["endpoint"] == "https://api.minimax.io/v1/text/chatcompletion_v2"
    assert calls["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, {"valid": True, "message": "Kimi API key valid"}),
        (400, {"valid": True, "message": "Kimi API key valid"}),
        (401, {"valid": False, "message": "Invalid Kimi API key"}),
        (403, {"valid": False, "message": "Kimi API key lacks permissions"}),
        (429, {"valid": True, "message": "Kimi API key valid"}),
        (500, {"valid": False, "message": "Kimi API returned status 500"}),
    ],
)
def test_check_anthropic_compatible_statuses(
    check_llm_key_module,
    monkeypatch,
    status_code,
    expected,
):
    module = check_llm_key_module
    calls = _patch_client(monkeypatch, module, status_code=status_code)

    result = module.check_anthropic_compatible(
        "test-key",
        "https://api.kimi.com/coding/v1/messages",
        "Kimi",
    )

    assert result == expected
    assert calls["method"] == "post"
    assert calls["endpoint"] == "https://api.kimi.com/coding/v1/messages"
    assert calls["headers"]["x-api-key"] == "test-key"


def test_check_openrouter_unexpected_status(check_llm_key_module, monkeypatch):
    module = check_llm_key_module
    calls = _patch_client(monkeypatch, module, status_code=500)

    result = module.check_openrouter("test-key", api_base="https://router.example/v1/")

    assert result == {
        "valid": False,
        "message": "OpenRouter API returned status 500",
    }
    assert calls["endpoint"] == "https://router.example/v1/models"


def test_main_usage_when_args_missing(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module
    code, payload = _run_main(module, monkeypatch, capsys, [])

    assert code == 2
    assert payload["valid"] is False
    assert "Usage: check_llm_key.py" in payload["message"]


def test_main_routes_openrouter_model_branch(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module
    calls = {}

    def fake_openrouter_model(api_key, model, api_base):
        calls["api_key"] = api_key
        calls["model"] = model
        calls["api_base"] = api_base
        return {"valid": True, "message": "model ok"}

    monkeypatch.setattr(module, "check_openrouter_model", fake_openrouter_model)
    code, payload = _run_main(
        module,
        monkeypatch,
        capsys,
        ["openrouter", "test-key", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"],
    )

    assert code == 0
    assert payload == {"valid": True, "message": "model ok"}
    assert calls == {
        "api_key": "test-key",
        "model": "openai/gpt-4o-mini",
        "api_base": "https://openrouter.ai/api/v1",
    }


def test_main_routes_kimi_custom_api_base(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module
    calls = {}

    def fake_anthropic_compatible(api_key, endpoint, name):
        calls["api_key"] = api_key
        calls["endpoint"] = endpoint
        calls["name"] = name
        return {"valid": True, "message": "kimi ok"}

    monkeypatch.setattr(module, "check_anthropic_compatible", fake_anthropic_compatible)
    code, payload = _run_main(
        module,
        monkeypatch,
        capsys,
        ["kimi", "test-key", "https://api.kimi.com/coding/"],
    )

    assert code == 0
    assert payload == {"valid": True, "message": "kimi ok"}
    assert calls == {
        "api_key": "test-key",
        "endpoint": "https://api.kimi.com/coding/v1/messages",
        "name": "Kimi",
    }


def test_main_routes_custom_api_base_for_zai(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module
    calls = {}

    def fake_openai_compatible(api_key, endpoint, name):
        calls["api_key"] = api_key
        calls["endpoint"] = endpoint
        calls["name"] = name
        return {"valid": True, "message": "zai ok"}

    monkeypatch.setattr(module, "check_openai_compatible", fake_openai_compatible)
    code, payload = _run_main(
        module,
        monkeypatch,
        capsys,
        ["zai", "test-key", "https://api.z.ai/api/coding/paas/v4/"],
    )

    assert code == 0
    assert payload == {"valid": True, "message": "zai ok"}
    assert calls == {
        "api_key": "test-key",
        "endpoint": "https://api.z.ai/api/coding/paas/v4/models",
        "name": "ZAI",
    }


def test_main_unknown_provider_exits_zero(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module
    code, payload = _run_main(module, monkeypatch, capsys, ["unknown-provider", "test-key"])

    assert code == 0
    assert payload == {
        "valid": True,
        "message": "No health check for unknown-provider",
    }


def test_main_returns_exit_one_for_invalid_provider_result(
    check_llm_key_module,
    monkeypatch,
    capsys,
):
    module = check_llm_key_module
    monkeypatch.setitem(
        module.PROVIDERS,
        "openai",
        lambda _key: {"valid": False, "message": "bad key"},
    )

    code, payload = _run_main(module, monkeypatch, capsys, ["openai", "test-key"])

    assert code == 1
    assert payload == {"valid": False, "message": "bad key"}


def test_main_timeout_exception_exits_two(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module

    def raise_timeout(_key):
        raise module.httpx.TimeoutException("timed out")

    monkeypatch.setitem(module.PROVIDERS, "openai", raise_timeout)
    code, payload = _run_main(module, monkeypatch, capsys, ["openai", "test-key"])

    assert code == 2
    assert payload == {"valid": None, "message": "Request timed out"}


def test_main_request_error_redacts_api_key(check_llm_key_module, monkeypatch, capsys):
    module = check_llm_key_module

    def raise_request_error(api_key):
        request = module.httpx.Request("GET", "https://example.test/models")
        raise module.httpx.RequestError(f"auth failed for {api_key}", request=request)

    monkeypatch.setitem(module.PROVIDERS, "openai", raise_request_error)
    code, payload = _run_main(module, monkeypatch, capsys, ["openai", "super-secret-key"])

    assert code == 2
    assert payload["valid"] is None
    assert payload["message"].startswith("Connection failed: ")
    assert "***" in payload["message"]
    assert "super-secret-key" not in payload["message"]

