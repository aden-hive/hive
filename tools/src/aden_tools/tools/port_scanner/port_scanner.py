"""
Port Scanner - Scan common ports and detect exposed services.

Performs non-intrusive TCP connect scans on common ports using Python stdlib.
Identifies open ports, grabs service banners, and flags risky exposures
(database ports, admin interfaces, legacy protocols).
"""

from __future__ import annotations

import asyncio
import socket

from fastmcp import FastMCP

# Well-known ports and their services
PORT_SERVICE_MAP = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    445: "SMB",
    993: "IMAPS",
    995: "POP3S",
    1433: "MSSQL",
    3306: "MySQL",
    3389: "RDP",
    5432: "PostgreSQL",
    5900: "VNC",
    6379: "Redis",
    8080: "HTTP-Alt",
    8443: "HTTPS-Alt",
}

TOP20_PORTS = sorted(PORT_SERVICE_MAP.keys())

TOP100_PORTS = sorted(
    set(TOP20_PORTS)
    | {
        # Additional common ports
        8,
        20,
        69,
        111,
        119,
        123,
        135,
        137,
        138,
        139,
        161,
        162,
        179,
        389,
        443,
        465,
        514,
        515,
        520,
        587,
        631,
        636,
        873,
        902,
        989,
        990,
        1080,
        1194,
        1443,
        1521,
        1723,
        2049,
        2082,
        2083,
        2086,
        2087,
        2096,
        2181,
        2222,
        3000,
        3128,
        4443,
        5000,
        5001,
        5060,
        5222,
        5601,
        5984,
        6443,
        6660,
        6661,
        6662,
        6663,
        6664,
        6665,
        6666,
        6667,
        7001,
        7002,
        7443,
        8000,
        8008,
        8081,
        8082,
        8083,
        8088,
        8443,
        8888,
        9000,
        9090,
        9200,
        9300,
        9443,
        10000,
        11211,
        27017,
        27018,
    }
)

# Ports that are risky when exposed to the internet
DATABASE_PORTS = {1433, 3306, 5432, 6379, 27017, 27018, 9200, 9300, 5984, 11211}
ADMIN_PORTS = {3389, 5900, 2082, 2083, 2086, 2087, 10000}
LEGACY_PORTS = {21, 23, 110, 143, 445}

# Security findings per port category
PORT_FINDINGS = {
    "database": {
        "severity": "high",
        "remediation": (
            "Restrict database ports to localhost or VPN only. "
            "Use firewall rules to block public access."
        ),
    },
    "admin": {
        "severity": "high",
        "remediation": (
            "Restrict remote admin ports to VPN or trusted IP ranges. "
            "Never expose RDP/VNC directly to the internet."
        ),
    },
    "legacy": {
        "severity": "medium",
        "remediation": (
            "Replace legacy protocols with secure alternatives. "
            "Use SFTP instead of FTP, SSH instead of Telnet, "
            "IMAPS/POP3S instead of IMAP/POP3."
        ),
    },
}


def register_tools(mcp: FastMCP) -> None:
    """Register port scanning tools with the MCP server."""

    @mcp.tool()
    async def port_scan(
        hostname: str,
        ports: str = "top20",
        timeout: float = 3.0,
    ) -> dict:
        """
        Scan a host for open ports using TCP connect probes.

        Non-intrusive scan that checks if ports accept connections, grabs service
        banners where possible, and flags risky exposures (databases, admin interfaces).

        Args:
            hostname: Domain or IP to scan (e.g., "example.com").
            ports: Which ports to scan. Options: "top20" (default), "top100",
                   or comma-separated list like "80,443,8080".
            timeout: Connection timeout per port in seconds (default 3.0, max 10.0).

        Returns:
            Dict with open/closed ports, service details, security findings,
            and grade_input for the risk_scorer tool.
        """
        # Clean hostname
        hostname = hostname.replace("https://", "").replace("http://", "").strip("/")
        hostname = hostname.split("/")[0]
        if ":" in hostname:
            hostname = hostname.split(":")[0]

        timeout = min(timeout, 10.0)

        # Parse port list
        if ports == "top20":
            port_list = TOP20_PORTS
        elif ports == "top100":
            port_list = TOP100_PORTS
        else:
            try:
                port_list = sorted({int(p.strip()) for p in ports.split(",") if p.strip()})
            except ValueError:
                return {"error": f"Invalid port list: {ports}. Use 'top20', 'top100', or '80,443'"}

        # Resolve hostname
        try:
            ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            return {"error": f"Could not resolve hostname: {hostname}"}

        # Scan ports concurrently
        open_ports = []
        closed_ports = []

        # Limit concurrency to avoid overwhelming the target
        semaphore = asyncio.Semaphore(20)

        async def scan_port(port: int) -> None:
            async with semaphore:
                result = await _check_port(ip, port, timeout)
                if result["open"]:
                    entry = {
                        "port": port,
                        "service": PORT_SERVICE_MAP.get(port, "unknown"),
                        "banner": result.get("banner", ""),
                    }

                    # Check if this port is risky
                    if port in DATABASE_PORTS:
                        entry["severity"] = PORT_FINDINGS["database"]["severity"]
                        entry["finding"] = f"{entry['service']} port ({port}) exposed to internet"
                        entry["remediation"] = PORT_FINDINGS["database"]["remediation"]
                    elif port in ADMIN_PORTS:
                        entry["severity"] = PORT_FINDINGS["admin"]["severity"]
                        entry["finding"] = (
                            f"{entry['service']} admin port ({port}) exposed to internet"
                        )
                        entry["remediation"] = PORT_FINDINGS["admin"]["remediation"]
                    elif port in LEGACY_PORTS:
                        entry["severity"] = PORT_FINDINGS["legacy"]["severity"]
                        entry["finding"] = (
                            f"Legacy protocol {entry['service']} ({port}) still active"
                        )
                        entry["remediation"] = PORT_FINDINGS["legacy"]["remediation"]

                    open_ports.append(entry)
                else:
                    closed_ports.append(port)

        await asyncio.gather(*[scan_port(p) for p in port_list])

        # Sort open ports by port number
        open_ports.sort(key=lambda x: x["port"])

        # Grade input
        open_port_numbers = {p["port"] for p in open_ports}
        grade_input = {
            "no_database_ports_exposed": not bool(open_port_numbers & DATABASE_PORTS),
            "no_admin_ports_exposed": not bool(open_port_numbers & ADMIN_PORTS),
            "no_legacy_ports_exposed": not bool(open_port_numbers & LEGACY_PORTS),
            "only_web_ports": open_port_numbers <= {80, 443, 8080, 8443},
        }

        return {
            "hostname": hostname,
            "ip": ip,
            "ports_scanned": len(port_list),
            "open_ports": open_ports,
            "closed_ports": sorted(closed_ports),
            "grade_input": grade_input,
        }


async def _check_port(ip: str, port: int, timeout: float) -> dict:
    """Check if a single port is open and try to grab a banner."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        # Try banner grab from the same connection
        banner = ""
        try:
            data = await asyncio.wait_for(reader.read(256), timeout=2.0)
            banner = data.decode("utf-8", errors="ignore").strip()
        except Exception:
            pass

        writer.close()
        await writer.wait_closed()
        return {"open": True, "banner": banner}
    except (TimeoutError, ConnectionRefusedError, OSError):
        return {"open": False}
