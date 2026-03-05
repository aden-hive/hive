"""Tests for port_scanner - TCP port scanning and service detection."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.port_scanner.port_scanner import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestPortScanValidation:
    @pytest.mark.asyncio
    async def test_invalid_port_list_returns_error(self, tool_fns):
        with patch("aden_tools.tools.port_scanner.port_scanner.socket") as mock_socket:
            mock_socket.gethostbyname.return_value = "93.184.216.34"
            mock_socket.gaierror = OSError
            result = await tool_fns["port_scan"](hostname="example.com", ports="notaport")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unresolvable_hostname_returns_error(self, tool_fns):
        with patch("aden_tools.tools.port_scanner.port_scanner.socket") as mock_socket:
            mock_socket.gaierror = OSError
            mock_socket.gethostbyname.side_effect = OSError("Name or service not known")
            result = await tool_fns["port_scan"](hostname="invalid.nonexistent.tld")
        assert "error" in result
        assert "resolve" in result["error"].lower()


class TestPortScanSuccessful:
    @pytest.mark.asyncio
    async def test_open_ports_returned(self, tool_fns):
        """HTTP (80) and HTTPS (443) open, database ports closed."""

        async def fake_check_port(ip, port, timeout):
            if port in (80, 443):
                return {"open": True, "banner": ""}
            return {"open": False}

        with (
            patch("aden_tools.tools.port_scanner.port_scanner.socket") as mock_socket,
            patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                side_effect=fake_check_port,
            ),
        ):
            mock_socket.gaierror = OSError
            mock_socket.gethostbyname.return_value = "93.184.216.34"
            result = await tool_fns["port_scan"](hostname="example.com", ports="80,443,3306")

        assert "error" not in result
        open_port_nums = {p["port"] for p in result["open_ports"]}
        assert 80 in open_port_nums
        assert 443 in open_port_nums
        assert 3306 not in open_port_nums

    @pytest.mark.asyncio
    async def test_grade_input_present(self, tool_fns):
        async def fake_check_port(ip, port, timeout):
            return {"open": port in (80, 443)}

        with (
            patch("aden_tools.tools.port_scanner.port_scanner.socket") as mock_socket,
            patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                side_effect=fake_check_port,
            ),
        ):
            mock_socket.gaierror = OSError
            mock_socket.gethostbyname.return_value = "93.184.216.34"
            result = await tool_fns["port_scan"](hostname="example.com", ports="80,443")

        assert "grade_input" in result
        assert result["grade_input"]["no_database_ports_exposed"] is True
        assert result["grade_input"]["only_web_ports"] is True

    @pytest.mark.asyncio
    async def test_database_port_flags_risk(self, tool_fns):
        async def fake_check_port(ip, port, timeout):
            return {"open": True, "banner": ""}

        with (
            patch("aden_tools.tools.port_scanner.port_scanner.socket") as mock_socket,
            patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                side_effect=fake_check_port,
            ),
        ):
            mock_socket.gaierror = OSError
            mock_socket.gethostbyname.return_value = "93.184.216.34"
            result = await tool_fns["port_scan"](hostname="example.com", ports="3306")

        assert result["grade_input"]["no_database_ports_exposed"] is False

    @pytest.mark.asyncio
    async def test_hostname_strips_protocol(self, tool_fns):
        async def fake_check_port(ip, port, timeout):
            return {"open": False}

        with (
            patch("aden_tools.tools.port_scanner.port_scanner.socket") as mock_socket,
            patch(
                "aden_tools.tools.port_scanner.port_scanner._check_port",
                side_effect=fake_check_port,
            ),
        ):
            mock_socket.gaierror = OSError
            mock_socket.gethostbyname.return_value = "93.184.216.34"
            result = await tool_fns["port_scan"](hostname="https://example.com", ports="80")

        assert result["hostname"] == "example.com"
