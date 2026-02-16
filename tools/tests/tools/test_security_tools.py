"""Tests for security scanning tools — cookie analysis and port scanner fixes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from aden_tools.tools.tech_stack_detector.tech_stack_detector import (
    _analyze_cookies,
    _extract_samesite,
)

# ---------------------------------------------------------------------------
# Cookie Analysis (_analyze_cookies)
# ---------------------------------------------------------------------------


class FakeHeaders:
    """Minimal stand-in for httpx.Headers.get_list()."""

    def __init__(self, set_cookie_values: list[str]):
        self._cookies = set_cookie_values

    def get_list(self, name: str) -> list[str]:
        if name == "set-cookie":
            return self._cookies
        return []


class TestAnalyzeCookies:
    """Tests for _analyze_cookies parsing raw Set-Cookie headers."""

    def test_secure_and_httponly_detected(self):
        headers = FakeHeaders(
            [
                "session_id=abc123; Path=/; Secure; HttpOnly",
            ]
        )
        result = _analyze_cookies(headers)

        assert len(result) == 1
        assert result[0]["name"] == "session_id"
        assert result[0]["secure"] is True
        assert result[0]["httponly"] is True

    def test_missing_flags_detected(self):
        headers = FakeHeaders(
            [
                "tracking=xyz; Path=/",
            ]
        )
        result = _analyze_cookies(headers)

        assert len(result) == 1
        assert result[0]["name"] == "tracking"
        assert result[0]["secure"] is False
        assert result[0]["httponly"] is False

    def test_case_insensitive(self):
        headers = FakeHeaders(
            [
                "tok=val; SECURE; HTTPONLY",
            ]
        )
        result = _analyze_cookies(headers)

        assert result[0]["secure"] is True
        assert result[0]["httponly"] is True

    def test_samesite_lax(self):
        headers = FakeHeaders(
            [
                "pref=dark; SameSite=Lax; Secure",
            ]
        )
        result = _analyze_cookies(headers)

        assert result[0]["samesite"] == "Lax"
        assert result[0]["secure"] is True

    def test_samesite_strict(self):
        headers = FakeHeaders(
            [
                "csrf=token; SameSite=Strict; Secure; HttpOnly",
            ]
        )
        result = _analyze_cookies(headers)

        assert result[0]["samesite"] == "Strict"

    def test_samesite_none(self):
        headers = FakeHeaders(
            [
                "cross=val; SameSite=None; Secure",
            ]
        )
        result = _analyze_cookies(headers)

        assert result[0]["samesite"] == "None"
        assert result[0]["secure"] is True

    def test_no_samesite(self):
        headers = FakeHeaders(
            [
                "id=123; Path=/; Secure",
            ]
        )
        result = _analyze_cookies(headers)

        assert result[0]["samesite"] is None

    def test_multiple_cookies(self):
        headers = FakeHeaders(
            [
                "a=1; Secure; HttpOnly",
                "b=2; Path=/",
                "c=3; Secure; SameSite=Strict",
            ]
        )
        result = _analyze_cookies(headers)

        assert len(result) == 3
        assert result[0] == {"name": "a", "secure": True, "httponly": True, "samesite": None}
        assert result[1] == {"name": "b", "secure": False, "httponly": False, "samesite": None}
        assert result[2] == {"name": "c", "secure": True, "httponly": False, "samesite": "Strict"}

    def test_no_cookies(self):
        headers = FakeHeaders([])
        result = _analyze_cookies(headers)

        assert result == []

    def test_cookie_value_with_equals(self):
        """Cookie values containing '=' should not break name parsing."""
        headers = FakeHeaders(
            [
                "token=abc=def==; Secure; HttpOnly",
            ]
        )
        result = _analyze_cookies(headers)

        assert result[0]["name"] == "token"
        assert result[0]["secure"] is True

    def test_grade_input_reflects_real_flags(self):
        """Verify the grade_input logic works with our parsed cookies."""
        cookies_all_secure = [
            {"name": "a", "secure": True, "httponly": True, "samesite": None},
            {"name": "b", "secure": True, "httponly": True, "samesite": None},
        ]
        cookies_one_insecure = [
            {"name": "a", "secure": True, "httponly": True, "samesite": None},
            {"name": "b", "secure": False, "httponly": True, "samesite": None},
        ]

        # Replicate the grade_input logic from tech_stack_detector
        assert all(c.get("secure", False) for c in cookies_all_secure) is True
        assert all(c.get("httponly", False) for c in cookies_all_secure) is True
        assert all(c.get("secure", False) for c in cookies_one_insecure) is False

    def test_secure_at_end_of_header(self):
        """Secure flag at the very end without trailing semicolon."""
        headers = FakeHeaders(
            [
                "id=val; Path=/; Secure",
            ]
        )
        result = _analyze_cookies(headers)
        assert result[0]["secure"] is True

    def test_no_space_after_semicolons(self):
        """Servers may omit space after semicolons (RFC 6265 Section 5.2)."""
        headers = FakeHeaders(
            [
                "id=val;Secure;HttpOnly;Path=/",
            ]
        )
        result = _analyze_cookies(headers)
        assert result[0]["name"] == "id"
        assert result[0]["secure"] is True
        assert result[0]["httponly"] is True


class TestExtractSamesite:
    """Tests for _extract_samesite helper."""

    def test_lax(self):
        assert _extract_samesite("id=val; path=/; samesite=lax") == "Lax"

    def test_strict(self):
        assert _extract_samesite("id=val; samesite=strict; secure") == "Strict"

    def test_none(self):
        assert _extract_samesite("id=val; samesite=none; secure") == "None"

    def test_missing(self):
        assert _extract_samesite("id=val; secure; httponly") is None

    def test_with_spaces(self):
        assert _extract_samesite("id=val;  samesite=lax  ; secure") == "Lax"


# ---------------------------------------------------------------------------
# Port Scanner (_check_port)
# ---------------------------------------------------------------------------


class TestCheckPort:
    """Tests for _check_port using a single connection."""

    @pytest.mark.asyncio
    async def test_open_port_with_banner(self):
        """Open port reads banner from the same connection (no second connect)."""
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=b"SSH-2.0-OpenSSH_8.9\r\n")
        mock_writer = AsyncMock()
        mock_writer.close = lambda: None
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (mock_reader, mock_writer)
            result = await _check_port("127.0.0.1", 22, timeout=2.0)

        assert result["open"] is True
        assert result["banner"] == "SSH-2.0-OpenSSH_8.9"
        # The critical assertion: open_connection called exactly ONCE
        mock_conn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_open_port_no_banner(self):
        """Open port where banner read times out still reports open."""
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_writer = AsyncMock()
        mock_writer.close = lambda: None
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (mock_reader, mock_writer)
            result = await _check_port("127.0.0.1", 80, timeout=2.0)

        assert result["open"] is True
        assert result["banner"] == ""
        mock_conn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_closed_port(self):
        """Closed port (ConnectionRefusedError) returns open=False."""
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError
            result = await _check_port("127.0.0.1", 12345, timeout=2.0)

        assert result["open"] is False

    @pytest.mark.asyncio
    async def test_timeout_port(self):
        """Timed-out port returns open=False."""
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = TimeoutError
            result = await _check_port("127.0.0.1", 12345, timeout=0.5)

        assert result["open"] is False

    @pytest.mark.asyncio
    async def test_writer_closed_even_on_banner_failure(self):
        """Writer from the connection is always closed, even if banner read fails."""
        from aden_tools.tools.port_scanner.port_scanner import _check_port

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(side_effect=Exception("unexpected"))
        mock_writer = AsyncMock()
        mock_writer.close = Mock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (mock_reader, mock_writer)
            result = await _check_port("127.0.0.1", 80, timeout=2.0)

        assert result["open"] is True
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()
