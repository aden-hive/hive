import importlib.util
from pathlib import Path


def _load_check_llm_key_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_llm_key.py"
    spec = importlib.util.spec_from_file_location("check_llm_key_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_openrouter_check(monkeypatch, status_code: int):
    module = _load_check_llm_key_module()
    calls = {}

    class FakeResponse:
        def __init__(self, code):
            self.status_code = code

    class FakeClient:
        def __init__(self, timeout):
            calls["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, endpoint, headers):
            calls["endpoint"] = endpoint
            calls["headers"] = headers
            return FakeResponse(status_code)

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    result = module.check_openrouter("test-key")
    return result, calls


def _run_openrouter_model_check(monkeypatch, status_code: int, payload: dict | None = None):
    module = _load_check_llm_key_module()
    calls = {}

    class FakeResponse:
        def __init__(self, code):
            self.status_code = code
            self._payload = payload
            self.text = ""

        def json(self):
            if self._payload is None:
                raise ValueError("no json")
            return self._payload

    class FakeClient:
        def __init__(self, timeout):
            calls["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, headers, json):
            calls["endpoint"] = endpoint
            calls["headers"] = headers
            calls["json"] = json
            return FakeResponse(status_code)

    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    result = module.check_openrouter_model("test-key", "openai/gpt-4o-mini")
    return result, calls


def test_check_openrouter_200(monkeypatch):
    result, calls = _run_openrouter_check(monkeypatch, 200)
    assert result == {"valid": True, "message": "OpenRouter API key valid"}
    assert calls["endpoint"] == "https://openrouter.ai/api/v1/models"
    assert calls["headers"] == {"Authorization": "Bearer test-key"}


def test_check_openrouter_401(monkeypatch):
    result, _ = _run_openrouter_check(monkeypatch, 401)
    assert result == {"valid": False, "message": "Invalid OpenRouter API key"}


def test_check_openrouter_403(monkeypatch):
    result, _ = _run_openrouter_check(monkeypatch, 403)
    assert result == {"valid": False, "message": "OpenRouter API key lacks permissions"}


def test_check_openrouter_429(monkeypatch):
    result, _ = _run_openrouter_check(monkeypatch, 429)
    assert result == {"valid": True, "message": "OpenRouter API key valid"}


def test_check_openrouter_model_200(monkeypatch):
    result, calls = _run_openrouter_model_check(monkeypatch, 200)
    assert result == {
        "valid": True,
        "message": "OpenRouter model is available: openai/gpt-4o-mini",
    }
    assert calls["endpoint"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert calls["json"]["model"] == "openai/gpt-4o-mini"
    assert calls["json"]["max_tokens"] == 1


def test_check_openrouter_model_404_with_error_message(monkeypatch):
    result, _ = _run_openrouter_model_check(
        monkeypatch,
        404,
        {"error": {"message": "No endpoints available for this model"}},
    )
    assert result == {
        "valid": False,
        "message": (
            "OpenRouter model is not available: openai/gpt-4o-mini. "
            "No endpoints available for this model"
        ),
    }


def test_check_openrouter_model_429(monkeypatch):
    result, _ = _run_openrouter_model_check(monkeypatch, 429)
    assert result == {
        "valid": True,
        "message": "OpenRouter model check rate-limited; assuming model is reachable",
    }
