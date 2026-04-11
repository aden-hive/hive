"""Unit tests for scripts/check_llm_key.py.

All HTTP calls are mocked — no real network requests are made.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import setup
# ---------------------------------------------------------------------------
# The module under test lives in the same directory as this file.  Add the
# scripts directory to sys.path so we can import it as a plain module, and
# stub out `framework.config` (an optional runtime dependency) so the import
# doesn't blow up in environments where the full framework package is not
# installed.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_framework_mock = MagicMock()
_framework_mock.HIVE_LLM_ENDPOINT = "https://api.adenhq.com"
sys.modules.setdefault("framework", MagicMock())
sys.modules.setdefault("framework.config", _framework_mock)

import check_llm_key as clk  # noqa: E402  (imported after sys.path / sys.modules setup)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, json_body: object | None = None, text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_body is not None:
        response.json.return_value = json_body
    else:
        response.json.side_effect = Exception("no body")
    return response


# ---------------------------------------------------------------------------
# _extract_error_message
# ---------------------------------------------------------------------------

class TestExtractErrorMessage:
    def test_dict_error_dict_message(self):
        r = _mock_response(400, {"error": {"message": "bad request"}})
        assert clk._extract_error_message(r) == "bad request"

    def test_dict_error_string(self):
        r = _mock_response(400, {"error": "some error string"})
        assert clk._extract_error_message(r) == "some error string"

    def test_dict_message_field(self):
        r = _mock_response(400, {"message": "top-level message"})
        assert clk._extract_error_message(r) == "top-level message"

    def test_non_json_response(self):
        r = _mock_response(500, text="Internal Server Error")
        assert clk._extract_error_message(r) == "Internal Server Error"

    def test_empty_body(self):
        r = _mock_response(500, text="")
        assert clk._extract_error_message(r) == ""


# ---------------------------------------------------------------------------
# _sanitize_openrouter_model_id / _normalize_openrouter_model_id
# ---------------------------------------------------------------------------

class TestSanitizeOpenRouterModelId:
    def test_strips_openrouter_prefix(self):
        assert clk._sanitize_openrouter_model_id("openrouter/gpt-4o") == "gpt-4o"

    def test_replaces_unicode_hyphens(self):
        # U+2013 EN DASH → ASCII hyphen
        assert clk._sanitize_openrouter_model_id("gpt\u20134o") == "gpt-4o"

    def test_replaces_unicode_slashes(self):
        # U+2044 FRACTION SLASH → ASCII /
        assert clk._sanitize_openrouter_model_id("provider\u2044model") == "provider/model"

    def test_strips_whitespace(self):
        assert clk._sanitize_openrouter_model_id("gpt 4o") == "gpt4o"

    def test_empty_string(self):
        assert clk._sanitize_openrouter_model_id("") == ""


# ---------------------------------------------------------------------------
# check_anthropic
# ---------------------------------------------------------------------------

ANTHROPIC_POST = "httpx.Client.post"


class TestCheckAnthropic:
    def _run(self, status_code: int, json_body=None):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.return_value = _mock_response(status_code, json_body)
            return clk.check_anthropic("sk-ant-test-key")

    def test_200_valid(self):
        result = self._run(200)
        assert result == {"valid": True, "message": "API key valid"}

    def test_400_valid(self):
        # Empty messages triggers 400 — still means key is accepted
        result = self._run(400)
        assert result["valid"] is True

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True

    def test_401_invalid(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid API key"}

    def test_403_no_permissions(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "API key lacks permissions"}

    def test_unexpected_status(self):
        result = self._run(500)
        assert result["valid"] is False
        assert "500" in result["message"]

    def test_timeout_propagates(self):
        import httpx
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(httpx.TimeoutException):
                clk.check_anthropic("sk-ant-test-key")


# ---------------------------------------------------------------------------
# check_openai_compatible  (covers OpenAI, Groq, Cerebras, DeepSeek, etc.)
# ---------------------------------------------------------------------------

class TestCheckOpenAICompatible:
    def _run(self, status_code: int, endpoint: str = "https://api.openai.com/v1/models", name: str = "OpenAI"):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(status_code)
            return clk.check_openai_compatible("sk-test", endpoint, name)

    def test_200_valid(self):
        result = self._run(200)
        assert result == {"valid": True, "message": "OpenAI API key valid"}

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True

    def test_401_invalid(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid OpenAI API key"}

    def test_403_no_permissions(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "OpenAI API key lacks permissions"}

    def test_unexpected_status(self):
        result = self._run(503)
        assert result["valid"] is False
        assert "503" in result["message"]

    def test_timeout_propagates(self):
        import httpx
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(httpx.TimeoutException):
                clk.check_openai_compatible("sk-test", "https://api.openai.com/v1/models", "OpenAI")

    @pytest.mark.parametrize("provider,endpoint,name", [
        ("groq", "https://api.groq.com/openai/v1/models", "Groq"),
        ("cerebras", "https://api.cerebras.ai/v1/models", "Cerebras"),
        ("deepseek", "https://api.deepseek.com/v1/models", "DeepSeek"),
        ("together", "https://api.together.xyz/v1/models", "Together AI"),
        ("mistral", "https://api.mistral.ai/v1/models", "Mistral"),
        ("xai", "https://api.x.ai/v1/models", "xAI"),
        ("perplexity", "https://api.perplexity.ai/v1/models", "Perplexity"),
    ])
    def test_provider_200_valid(self, provider, endpoint, name):
        result = self._run(200, endpoint=endpoint, name=name)
        assert result["valid"] is True
        assert name in result["message"]


# ---------------------------------------------------------------------------
# check_openrouter
# ---------------------------------------------------------------------------

class TestCheckOpenRouter:
    def _run(self, status_code: int, api_base: str = "https://openrouter.ai/api/v1"):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(status_code)
            return clk.check_openrouter("or-test-key", api_base=api_base)

    def test_200_valid(self):
        result = self._run(200)
        assert result == {"valid": True, "message": "OpenRouter API key valid"}

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True

    def test_401_invalid(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid OpenRouter API key"}

    def test_403_no_permissions(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "OpenRouter API key lacks permissions"}

    def test_custom_api_base(self):
        # Ensure trailing slash is stripped and /models is appended
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(200)
            clk.check_openrouter("key", api_base="https://custom.openrouter.ai/api/v1/")
            call_url = instance.get.call_args[0][0]
            assert call_url == "https://custom.openrouter.ai/api/v1/models"

    def test_timeout_propagates(self):
        import httpx
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(httpx.TimeoutException):
                clk.check_openrouter("or-test-key")


# ---------------------------------------------------------------------------
# check_openrouter_model
# ---------------------------------------------------------------------------

class TestCheckOpenRouterModel:
    _MODELS_PAYLOAD = {
        "data": [
            {"id": "openai/gpt-4o", "canonical_slug": "gpt-4o"},
            {"id": "anthropic/claude-3-5-sonnet", "canonical_slug": "claude-3-5-sonnet"},
        ]
    }

    def _run(self, status_code: int, model: str = "gpt-4o", json_body=None):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(status_code, json_body or self._MODELS_PAYLOAD)
            return clk.check_openrouter_model("or-key", model=model)

    def test_200_model_found(self):
        result = self._run(200, model="gpt-4o")
        assert result["valid"] is True
        assert "gpt-4o" in result["message"]
        assert result.get("model") == "gpt-4o"

    def test_200_model_not_found(self):
        result = self._run(200, model="unknown-model-xyz")
        assert result["valid"] is False
        assert "not available" in result["message"]

    def test_200_suggests_close_match(self):
        result = self._run(200, model="gpt-4")  # close to gpt-4o
        # May or may not suggest — just ensure valid=False and message present
        assert result["valid"] is False

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True
        assert "rate-limited" in result["message"]

    def test_401_invalid_key(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid OpenRouter API key"}

    def test_403_no_permissions(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "OpenRouter API key lacks permissions"}

    def test_404_model_not_available(self):
        result = self._run(404, json_body={"error": {"message": "not found"}})
        assert result["valid"] is False
        assert "not available" in result["message"]

    def test_500_unexpected_status(self):
        result = self._run(500, json_body={"error": {"message": "server error"}})
        assert result["valid"] is False
        assert "500" in result["message"]

    def test_timeout_propagates(self):
        import httpx
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(httpx.TimeoutException):
                clk.check_openrouter_model("or-key", model="gpt-4o")


# ---------------------------------------------------------------------------
# check_minimax
# ---------------------------------------------------------------------------

class TestCheckMinimax:
    def _run(self, status_code: int, api_base: str = "https://api.minimax.io/v1"):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.return_value = _mock_response(status_code)
            return clk.check_minimax("minimax-key", api_base=api_base)

    def test_200_valid(self):
        result = self._run(200)
        assert result == {"valid": True, "message": "MiniMax API key valid"}

    def test_400_valid(self):
        result = self._run(400)
        assert result["valid"] is True

    def test_422_valid(self):
        result = self._run(422)
        assert result["valid"] is True

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True

    def test_401_invalid(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid MiniMax API key"}

    def test_403_no_permissions(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "MiniMax API key lacks permissions"}

    def test_timeout_propagates(self):
        import httpx
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(httpx.TimeoutException):
                clk.check_minimax("minimax-key")


# ---------------------------------------------------------------------------
# check_anthropic_compatible  (covers Kimi, Hive)
# ---------------------------------------------------------------------------

class TestCheckAnthropicCompatible:
    def _run(self, status_code: int, endpoint: str = "https://api.kimi.com/coding/v1/messages", name: str = "Kimi"):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.return_value = _mock_response(status_code)
            return clk.check_anthropic_compatible("kimi-key", endpoint, name)

    def test_200_valid(self):
        result = self._run(200)
        assert result == {"valid": True, "message": "Kimi API key valid"}

    def test_400_valid(self):
        result = self._run(400)
        assert result["valid"] is True

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True

    def test_401_invalid(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid Kimi API key"}

    def test_403_no_permissions(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "Kimi API key lacks permissions"}

    def test_hive_provider(self):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.return_value = _mock_response(400)
            result = clk.check_anthropic_compatible("hive-key", "https://api.adenhq.com/v1/messages", "Hive")
            assert result == {"valid": True, "message": "Hive API key valid"}


# ---------------------------------------------------------------------------
# check_gemini
# ---------------------------------------------------------------------------

class TestCheckGemini:
    def _run(self, status_code: int):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(status_code)
            return clk.check_gemini("gemini-key")

    def test_200_valid(self):
        result = self._run(200)
        assert result == {"valid": True, "message": "Gemini API key valid"}

    def test_429_rate_limited_valid(self):
        result = self._run(429)
        assert result["valid"] is True

    def test_400_invalid(self):
        result = self._run(400)
        assert result == {"valid": False, "message": "Invalid Gemini API key"}

    def test_401_invalid(self):
        result = self._run(401)
        assert result == {"valid": False, "message": "Invalid Gemini API key"}

    def test_403_invalid(self):
        result = self._run(403)
        assert result == {"valid": False, "message": "Invalid Gemini API key"}

    def test_unexpected_status(self):
        result = self._run(500)
        assert result["valid"] is False
        assert "500" in result["message"]

    def test_timeout_propagates(self):
        import httpx
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(httpx.TimeoutException):
                clk.check_gemini("gemini-key")


# ---------------------------------------------------------------------------
# Edge cases: empty / whitespace keys
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Empty or whitespace keys are passed through to the provider validators.

    The validators do not reject them locally — the server returns 401.  These
    tests confirm the functions still return a well-formed dict, not an exception.
    """

    @pytest.mark.parametrize("key", ["", "   ", "\t"])
    def test_anthropic_empty_key(self, key):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.post.return_value = _mock_response(401)
            result = clk.check_anthropic(key)
            assert isinstance(result, dict)
            assert result["valid"] is False

    @pytest.mark.parametrize("key", ["", "   "])
    def test_openai_compatible_empty_key(self, key):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(401)
            result = clk.check_openai_compatible(key, "https://api.openai.com/v1/models", "OpenAI")
            assert isinstance(result, dict)
            assert result["valid"] is False

    @pytest.mark.parametrize("key", ["", "   "])
    def test_gemini_empty_key(self, key):
        with patch("httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.return_value = _mock_response(401)
            result = clk.check_gemini(key)
            assert isinstance(result, dict)
            assert result["valid"] is False


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for the CLI entry point."""

    def _call_main(self, argv, mock_result=None, timeout=False, request_error=False):
        """Invoke main() with a patched sys.argv and mocked HTTP."""
        import httpx

        with patch("sys.argv", argv):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                with patch("httpx.Client") as MockClient:
                    instance = MockClient.return_value.__enter__.return_value
                    if timeout:
                        instance.post.side_effect = httpx.TimeoutException("timed out")
                        instance.get.side_effect = httpx.TimeoutException("timed out")
                    elif request_error:
                        instance.post.side_effect = httpx.RequestError("conn failed")
                        instance.get.side_effect = httpx.RequestError("conn failed")
                    else:
                        response = _mock_response(
                            mock_result["status"],
                            mock_result.get("json"),
                        )
                        instance.post.return_value = response
                        instance.get.return_value = response

                    with pytest.raises(SystemExit) as exc:
                        clk.main()
                    return exc.value.code, mock_stdout.getvalue()

    def test_too_few_args_exits_2(self):
        with patch("sys.argv", ["check_llm_key.py"]):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                with pytest.raises(SystemExit) as exc:
                    clk.main()
                assert exc.value.code == 2
                output = json.loads(mock_stdout.getvalue())
                assert output["valid"] is False
                assert "Usage" in output["message"]

    def test_anthropic_valid_key_exits_0(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "anthropic", "sk-ant-key"],
            mock_result={"status": 400},
        )
        assert exit_code == 0
        assert json.loads(stdout)["valid"] is True

    def test_openai_invalid_key_exits_1(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "openai", "bad-key"],
            mock_result={"status": 401},
        )
        assert exit_code == 1
        assert json.loads(stdout)["valid"] is False

    def test_timeout_exits_2(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "openai", "some-key"],
            timeout=True,
        )
        assert exit_code == 2
        output = json.loads(stdout)
        assert output["valid"] is None
        assert "timed out" in output["message"]

    def test_request_error_exits_2(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "openai", "some-key"],
            request_error=True,
        )
        assert exit_code == 2
        output = json.loads(stdout)
        assert output["valid"] is None
        assert "Connection failed" in output["message"]

    def test_request_error_redacts_key(self):
        """API key must not appear in error output."""
        secret_key = "super-secret-key-12345"
        import httpx
        with patch("sys.argv", ["check_llm_key.py", "openai", secret_key]):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                with patch("httpx.Client") as MockClient:
                    instance = MockClient.return_value.__enter__.return_value
                    instance.get.side_effect = httpx.RequestError(f"error with {secret_key}")
                    with pytest.raises(SystemExit):
                        clk.main()
                    assert secret_key not in mock_stdout.getvalue()

    def test_unknown_provider_exits_0(self):
        """Unknown providers pass through without HTTP call."""
        with patch("sys.argv", ["check_llm_key.py", "unknown_provider_xyz", "key"]):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                with pytest.raises(SystemExit) as exc:
                    clk.main()
                assert exc.value.code == 0
                output = json.loads(mock_stdout.getvalue())
                assert output["valid"] is True

    def test_openrouter_with_model_calls_check_openrouter_model(self):
        """When provider=openrouter and model arg provided, uses model validator."""
        models_payload = {"data": [{"id": "openai/gpt-4o", "canonical_slug": "gpt-4o"}]}
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "openrouter", "or-key", "https://openrouter.ai/api/v1", "gpt-4o"],
            mock_result={"status": 200, "json": models_payload},
        )
        assert exit_code == 0
        output = json.loads(stdout)
        assert output["valid"] is True

    def test_custom_api_base_openai_compatible(self):
        """Custom api_base for unknown provider uses OpenAI-compatible /models check."""
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "zai", "zai-key", "https://api.zai.ai/v1"],
            mock_result={"status": 200},
        )
        assert exit_code == 0

    def test_minimax_with_custom_api_base(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "minimax", "mm-key", "https://custom.minimax.io/v1"],
            mock_result={"status": 200},
        )
        assert exit_code == 0

    def test_kimi_with_custom_api_base(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "kimi", "kimi-key", "https://custom.kimi.ai"],
            mock_result={"status": 400},
        )
        assert exit_code == 0

    def test_hive_with_custom_api_base(self):
        exit_code, stdout = self._call_main(
            ["check_llm_key.py", "hive", "hive-key", "https://custom.adenhq.com"],
            mock_result={"status": 400},
        )
        assert exit_code == 0
