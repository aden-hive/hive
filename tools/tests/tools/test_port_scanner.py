"""Tests for Port Scanner tool."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.port_scanner import register_tools


@pytest.fixture
def port_tools(mcp: FastMCP):
    """Register port scanner tools and return tool functions."""
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def scan_fn(port_tools):
    return port_tools["port_scan"]


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Test hostname and port input validation."""

    @pytest.mark.asyncio
    async def test_strips_https_prefix(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("https://example.com", ports="80")
                assert result["hostname"] == "example.com"

    @pytest.mark.asyncio
    async def test_strips_path(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("example.com/path", ports="80")
                assert result["hostname"] == "example.com"

    @pytest.mark.asyncio
    async def test_invalid_port_list(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            result = await scan_fn("example.com", ports="invalid,ports")
            assert "error" in result
            assert "Invalid port list" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_port_list(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("example.com", ports="22,80,443")
                assert result["ports_scanned"] == 3

    @pytest.mark.asyncio
    async def test_timeout_clamped(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                # Timeout > 10 should be clamped
                result = await scan_fn("example.com", ports="80", timeout=100.0)
                assert "error" not in result
                assert mock_check.call_args[0][2] <= 10.0


# ---------------------------------------------------------------------------
# DNS Resolution Errors
# ---------------------------------------------------------------------------


class TestDnsResolution:
    """Test DNS resolution error handling."""

    @pytest.mark.asyncio
    async def test_hostname_not_found(self, scan_fn):
        with patch("socket.gethostbyname", side_effect=socket.gaierror("not found")):
            result = await scan_fn("nonexistent.invalid")
            assert "error" in result
            assert "resolve hostname" in result["error"]


# ---------------------------------------------------------------------------
# Port Scanning
# ---------------------------------------------------------------------------


class TestPortScanning:
    """Test port scanning functionality."""

    @pytest.mark.asyncio
    async def test_open_port_detected(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": True, "banner": ""}
                result = await scan_fn("example.com", ports="80")
                assert len(result["open_ports"]) == 1
                assert result["open_ports"][0]["port"] == 80

    @pytest.mark.asyncio
    async def test_closed_port_detected(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("example.com", ports="12345")
                assert len(result["open_ports"]) == 0
                assert 12345 in result["closed_ports"]

    @pytest.mark.asyncio
    async def test_banner_captured(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": True, "banner": "SSH-2.0-OpenSSH_8.9"}
                result = await scan_fn("example.com", ports="22")
                assert result["open_ports"][0]["banner"] == "SSH-2.0-OpenSSH_8.9"


# ---------------------------------------------------------------------------
# Risky Port Detection
# ---------------------------------------------------------------------------


class TestRiskyPorts:
    """Test detection of risky exposed ports."""

    @pytest.mark.asyncio
    async def test_database_port_flagged(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": True, "banner": ""}
                result = await scan_fn("example.com", ports="3306")  # MySQL
                assert result["open_ports"][0]["severity"] == "high"
                assert "MySQL" in result["open_ports"][0]["finding"]
                assert result["grade_input"]["no_database_ports_exposed"] is False

    @pytest.mark.asyncio
    async def test_admin_port_flagged(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": True, "banner": ""}
                result = await scan_fn("example.com", ports="3389")  # RDP
                assert result["open_ports"][0]["severity"] == "high"
                assert result["grade_input"]["no_admin_ports_exposed"] is False

    @pytest.mark.asyncio
    async def test_legacy_port_flagged(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": True, "banner": ""}
                result = await scan_fn("example.com", ports="23")  # Telnet
                assert result["open_ports"][0]["severity"] == "medium"
                assert result["grade_input"]["no_legacy_ports_exposed"] is False


# ---------------------------------------------------------------------------
# Grade Input
# ---------------------------------------------------------------------------


class TestGradeInput:
    """Test grade_input dict is properly constructed."""

    @pytest.mark.asyncio
    async def test_grade_input_keys_present(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("example.com", ports="80")
                assert "grade_input" in result
                grade = result["grade_input"]
                assert "no_database_ports_exposed" in grade
                assert "no_admin_ports_exposed" in grade
                assert "no_legacy_ports_exposed" in grade
                assert "only_web_ports" in grade

    @pytest.mark.asyncio
    async def test_only_web_ports_true(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                # Only 80 and 443 open
                async def check_port(ip, port, timeout):
                    if port in (80, 443):
                        return {"open": True, "banner": ""}
                    return {"open": False}

                mock_check.side_effect = check_port
                result = await scan_fn("example.com", ports="22,80,443")
                assert result["grade_input"]["only_web_ports"] is True

    @pytest.mark.asyncio
    async def test_only_web_ports_false(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                # SSH port also open
                async def check_port(ip, port, timeout):
                    if port in (22, 80, 443):
                        return {"open": True, "banner": ""}
                    return {"open": False}

                mock_check.side_effect = check_port
                result = await scan_fn("example.com", ports="22,80,443")
                assert result["grade_input"]["only_web_ports"] is False


# ---------------------------------------------------------------------------
# Top20/Top100 Port Lists
# ---------------------------------------------------------------------------


class TestPortLists:
    """Test predefined port lists."""

    @pytest.mark.asyncio
    async def test_top20_ports(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("example.com", ports="top20")
                assert result["ports_scanned"] == 20

    @pytest.mark.asyncio
    async def test_top100_ports(self, scan_fn):
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            with patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                new_callable=AsyncMock,
            ) as mock_check:
                mock_check.return_value = {"open": False}
                result = await scan_fn("example.com", ports="top100")
                assert result["ports_scanned"] > 20
