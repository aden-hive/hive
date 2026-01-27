"""
System Monitor Tool - Check host resource usage.
"""
from __future__ import annotations
import psutil
import platform
from fastmcp import FastMCP

def register_tools(mcp: FastMCP) -> None:
    """Register system monitor tools with the MCP server."""

    @mcp.tool()
    def system_monitor(
        metric: str = "all"
    ) -> str:
        """
        Check the current system health (CPU, RAM, Disk).
        Use this tool when you need to check if the machine is overloaded.

        Args:
            metric: The specific metric to check. Options: "cpu", "memory", "disk", or "all".
                   Defaults to "all".

        Returns:
            A string summary of the requested system resources.
        """
        try:
            output = []
            
            # CPU Check
            if metric in ["all", "cpu"]:
                cpu_pct = psutil.cpu_percent(interval=0.1)
                cpu_count = psutil.cpu_count()
                output.append(f"CPU: {cpu_pct}% usage ({cpu_count} cores)")

            # Memory Check
            if metric in ["all", "memory"]:
                mem = psutil.virtual_memory()
                mem_used = round(mem.percent, 1)
                mem_avail = round(mem.available / (1024 * 1024), 2)
                output.append(f"RAM: {mem_used}% used ({mem_avail} MB available)")

            # Disk Check
            if metric in ["all", "disk"]:
                disk = psutil.disk_usage('/')
                disk_free = round(disk.free / (1024**3), 2)
                output.append(f"Disk: {disk_free} GB free")

            if not output:
                return "Error: Invalid metric requested. Use 'cpu', 'memory', 'disk', or 'all'."

            return " | ".join(output)

        except Exception as e:
            return f"Error reading system stats: {str(e)}"