"""
System Tool - Get system information and resources.
"""
import platform
import os
import sys
from typing import Dict, Any
from fastmcp import FastMCP

def register_tools(mcp: FastMCP, credentials=None) -> None:
    """Register system tools."""

    @mcp.tool()
    def get_system_info() -> Dict[str, Any]:
        """Get information about the operating system and resources."""
        info = {
            "os": os.name,
            "platform": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "python_version": sys.version,
            "cpu_count": os.cpu_count(),
        }
        
        # Try to get memory info if psutil is available
        try:
            import psutil
            vm = psutil.virtual_memory()
            info["memory_total_gb"] = round(vm.total / (1024**3), 2)
            info["memory_available_gb"] = round(vm.available / (1024**3), 2)
            info["memory_percent"] = vm.percent
            
            disk = psutil.disk_usage('/')
            info["disk_total_gb"] = round(disk.total / (1024**3), 2)
            info["disk_free_gb"] = round(disk.free / (1024**3), 2)
        except ImportError:
            info["note"] = "Install 'psutil' for detailed memory/disk stats"
            
        return info

    @mcp.tool()
    def list_processes(top_n: int = 10, sort_by: str = "memory") -> Dict[str, Any]:
        """
        List top resource-consuming processes.
        
        Args:
            top_n: Number of processes to list
            sort_by: 'memory' or 'cpu'
        """
        try:
            import psutil
        except ImportError:
            return {"error": "psutil module is required for this tool. Please install it."}
            
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'memory_percent', 'cpu_percent']):
            try:
                pinfo = proc.info
                processes.append(pinfo)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # Sort
        if sort_by == "cpu":
            processes.sort(key=lambda p: p['cpu_percent'] or 0, reverse=True)
        else:
            processes.sort(key=lambda p: p['memory_percent'] or 0, reverse=True)
            
        return {
            "count": len(processes),
            "top_processes": processes[:top_n]
        }
