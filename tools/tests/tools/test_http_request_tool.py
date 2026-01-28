"""Tests for http_request tool (FastMCP)."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.http_request_tool import register_tools


@pytest.fixture
def http_request_fn(mcp: FastMCP):
    """Register and return the http_request tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["http_request"].fn


class TestHttpRequestValidation:
    """Tests for input validation."""

    def test_empty_url_returns_error(self, http_request_fn):
        """Empty URL returns error."""
        result = http_request_fn(url="")
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_invalid_scheme_returns_error(self, http_request_fn):
        """Non-http/https scheme returns error."""
        result = http_request_fn(url="ftp://example.com")
        assert "error" in result
        assert "http://" in result["error"] or "https://" in result["error"]

    def test_file_scheme_returns_error(self, http_request_fn):
        """File scheme is blocked."""
        result = http_request_fn(url="file:///etc/passwd")
        assert "error" in result

    def test_missing_hostname_returns_error(self, http_request_fn):
        """URL without hostname returns error."""
        result = http_request_fn(url="http://")
        assert "error" in result
        assert "hostname" in result["error"].lower()

    def test_invalid_method_returns_error(self, http_request_fn):
        """Invalid HTTP method returns error."""
        result = http_request_fn(url="https://example.com", method="INVALID")
        assert "error" in result
        assert "method" in result["error"].lower()

    def test_both_body_and_json_body_returns_error(self, http_request_fn):
        """Specifying both body and json_body returns error."""
        result = http_request_fn(url="https://example.com", body="raw", json_body={"key": "value"})
        assert "error" in result
        assert "both" in result["error"].lower()

    def test_headers_must_be_dict(self, http_request_fn):
        """Non-dict headers returns error."""
        result = http_request_fn(url="https://example.com", headers="invalid")
        assert "error" in result
        assert "dict" in result["error"].lower()

    def test_params_must_be_dict(self, http_request_fn):
        """Non-dict params returns error."""
        result = http_request_fn(url="https://example.com", params="invalid")
        assert "error" in result
        assert "dict" in result["error"].lower()

    def test_json_body_must_be_dict(self, http_request_fn):
        """Non-dict json_body returns error."""
        result = http_request_fn(url="https://example.com", json_body="invalid")
        assert "error" in result
        assert "dict" in result["error"].lower()

    def test_body_must_be_string(self, http_request_fn):
        """Non-string body returns error."""
        result = http_request_fn(url="https://example.com", body={"key": "value"})
        assert "error" in result
        assert "string" in result["error"].lower()


class TestSsrfProtection:
    """Tests for SSRF protection."""

    def test_localhost_blocked(self, http_request_fn):
        """Requests to localhost are blocked."""
        result = http_request_fn(url="http://localhost/api")
        assert "error" in result
        assert "not allowed" in result["error"].lower()

    def test_127_0_0_1_blocked(self, http_request_fn):
        """Requests to 127.0.0.1 are blocked."""
        result = http_request_fn(url="http://127.0.0.1/api")
        assert "error" in result
        assert "not allowed" in result["error"].lower()

    def test_0_0_0_0_blocked(self, http_request_fn):
        """Requests to 0.0.0.0 are blocked."""
        result = http_request_fn(url="http://0.0.0.0/api")
        assert "error" in result
        assert "not allowed" in result["error"].lower()

    def test_aws_metadata_blocked(self, http_request_fn):
        """Requests to AWS metadata endpoint are blocked."""
        result = http_request_fn(url="http://169.254.169.254/latest/meta-data/")
        assert "error" in result
        assert "not allowed" in result["error"].lower()

    def test_private_ip_10_x_blocked(self, http_request_fn):
        """Requests to 10.x.x.x private IPs are blocked."""
        result = http_request_fn(url="http://10.0.0.1/api")
        assert "error" in result
        assert "private" in result["error"].lower() or "not allowed" in result["error"].lower()

    def test_private_ip_172_16_blocked(self, http_request_fn):
        """Requests to 172.16.x.x private IPs are blocked."""
        result = http_request_fn(url="http://172.16.0.1/api")
        assert "error" in result
        assert "private" in result["error"].lower() or "not allowed" in result["error"].lower()

    def test_private_ip_192_168_blocked(self, http_request_fn):
        """Requests to 192.168.x.x private IPs are blocked."""
        result = http_request_fn(url="http://192.168.1.1/api")
        assert "error" in result
        assert "private" in result["error"].lower() or "not allowed" in result["error"].lower()

    def test_allow_private_ips_override(self, http_request_fn):
        """allow_private_ips=True allows private IP requests (but they may fail connection)."""
        # This will fail at connection time, but should NOT be blocked by SSRF check
        result = http_request_fn(url="http://192.168.1.1/api", allow_private_ips=True, timeout=1)
        # Should either succeed or fail with connection error, not SSRF error
        if "error" in result:
            assert "private" not in result["error"].lower() or "allow" in result["error"].lower()


class TestHttpMethods:
    """Tests for HTTP method handling."""

    def test_get_method_default(self, http_request_fn):
        """GET is the default method."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(url="https://example.com/api")

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["method"] == "GET"

    def test_post_method(self, http_request_fn):
        """POST method works."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {"id": 1}
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(
                url="https://example.com/api", method="POST", json_body={"name": "test"}
            )

            assert result["status_code"] == 201
            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["method"] == "POST"
            assert call_args.kwargs["json"] == {"name": "test"}

    def test_method_case_insensitive(self, http_request_fn):
        """HTTP method is case-insensitive."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(url="https://example.com/api", method="post")

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["method"] == "POST"

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    def test_all_allowed_methods(self, http_request_fn, method):
        """All allowed HTTP methods are accepted."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(url="https://example.com/api", method=method)

            assert "error" not in result
            assert result["status_code"] == 200


class TestResponseParsing:
    """Tests for response parsing."""

    def test_json_response_parsed(self, http_request_fn):
        """JSON responses are automatically parsed."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json; charset=utf-8"}
            mock_response.json.return_value = {"data": [1, 2, 3]}
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(url="https://api.example.com/data")

            assert result["is_json"] is True
            assert result["body"] == {"data": [1, 2, 3]}

    def test_text_response_not_parsed(self, http_request_fn):
        """Text responses are returned as-is."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.text = "<html>Hello</html>"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(url="https://example.com")

            assert result["is_json"] is False
            assert result["body"] == "<html>Hello</html>"

    def test_response_includes_headers(self, http_request_fn):
        """Response includes headers."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json", "x-request-id": "abc123"}
            mock_response.json.return_value = {}
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(url="https://api.example.com")

            assert "headers" in result
            assert result["headers"]["x-request-id"] == "abc123"

    def test_response_includes_elapsed_time(self, http_request_fn):
        """Response includes elapsed time in milliseconds."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.245
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(url="https://example.com")

            assert result["elapsed_ms"] == 245


class TestErrorHandling:
    """Tests for error handling."""

    def test_timeout_error(self, http_request_fn):
        """Timeout returns appropriate error."""
        import httpx

        with patch("httpx.Client") as mock_client:
            mock_request = mock_client.return_value.__enter__.return_value.request
            mock_request.side_effect = httpx.TimeoutException("timeout")

            result = http_request_fn(url="https://example.com", timeout=5)

            assert "error" in result
            assert "timed out" in result["error"].lower()
            assert "5" in result["error"]

    def test_connection_error(self, http_request_fn):
        """Connection error returns appropriate error."""
        import httpx

        with patch("httpx.Client") as mock_client:
            mock_request = mock_client.return_value.__enter__.return_value.request
            mock_request.side_effect = httpx.ConnectError("connection refused")

            result = http_request_fn(url="https://example.com")

            assert "error" in result
            assert "connection" in result["error"].lower() or "failed" in result["error"].lower()

    def test_too_many_redirects(self, http_request_fn):
        """Too many redirects returns appropriate error."""
        import httpx

        with patch("httpx.Client") as mock_client:
            mock_request = mock_client.return_value.__enter__.return_value.request
            mock_request.side_effect = httpx.TooManyRedirects("too many")

            result = http_request_fn(url="https://example.com")

            assert "error" in result
            assert "redirect" in result["error"].lower()


class TestTimeoutHandling:
    """Tests for timeout configuration."""

    def test_timeout_clamped_minimum(self, http_request_fn):
        """Timeout is clamped to minimum of 1."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(url="https://example.com", timeout=0)

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["timeout"] == 1.0

    def test_timeout_clamped_maximum(self, http_request_fn):
        """Timeout is clamped to maximum of 120."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(url="https://example.com", timeout=999)

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["timeout"] == 120.0


class TestRequestOptions:
    """Tests for request options."""

    def test_custom_headers_sent(self, http_request_fn):
        """Custom headers are included in request."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(
                url="https://api.example.com", headers={"Authorization": "Bearer token123"}
            )

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["headers"]["Authorization"] == "Bearer token123"

    def test_query_params_sent(self, http_request_fn):
        """Query params are included in request."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(url="https://api.example.com/search", params={"q": "test", "limit": 10})

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["params"] == {"q": "test", "limit": 10}

    def test_follow_redirects_default_true(self, http_request_fn):
        """follow_redirects defaults to True."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(url="https://example.com")

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["follow_redirects"] is True

    def test_follow_redirects_can_be_disabled(self, http_request_fn):
        """follow_redirects can be set to False."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 302
            mock_response.headers = {"content-type": "text/plain", "location": "/new"}
            mock_response.text = ""
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            result = http_request_fn(url="https://example.com", follow_redirects=False)

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["follow_redirects"] is False
            assert result["status_code"] == 302

    def test_raw_body_sent(self, http_request_fn):
        """Raw body is sent as content."""
        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "OK"
            mock_response.elapsed.total_seconds.return_value = 0.1
            mock_client.return_value.__enter__.return_value.request.return_value = mock_response

            http_request_fn(
                url="https://api.example.com/webhook", method="POST", body="raw content here"
            )

            call_args = mock_client.return_value.__enter__.return_value.request.call_args
            assert call_args.kwargs["content"] == "raw content here"
