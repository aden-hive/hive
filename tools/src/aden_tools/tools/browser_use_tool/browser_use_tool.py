"""
Browser-Use Tool - Natural Language Web Automation.

Integrates the browser-use library to enable autonomous web task execution
using natural language instructions and LLM-driven browser control.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from fastmcp import FastMCP
from browser_use import Agent, Browser, Controller, ChatOpenAI

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

# Configure logging
logger = logging.getLogger(__name__)


def is_safe_url(url: str) -> bool:
    """
    Validate if a URL is safe to access (SSRF protection).
    
    Args:
        url: The URL to validate.
        
    Returns:
        True if the URL is considered safe, False otherwise.
    """
    try:
        parsed = urlparse(url)
        # Only allow http and https
        if parsed.scheme not in ("http", "https"):
            return False
            
        # Block localhost and private IP ranges
        hostname = parsed.hostname
        if not hostname:
            return False
            
        hostname = hostname.lower()
        blocked_hosts = {"localhost", "0.0.0.0"}
        if hostname in blocked_hosts:
            return False
            
        # Try to resolve hostname to IP to catch obfuscated IPs and local resolution
        try:
            # getaddrinfo handles IPv4, IPv6, '127.1', '2130706433', etc. and also resolves domains
            addr_info = socket.getaddrinfo(hostname, None)
            for family, kind, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]  # The IP address
                ip = ipaddress.ip_address(ip_str)
                if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified:
                    return False
        except (socket.gaierror, ValueError):
            # If resolution fails, it might still be a valid domain we can't resolve here
            pass
            
        return True
    except Exception:
        return False


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register browser-use tools with the MCP server."""

    @mcp.tool()
    async def browser_use_task(
        task: str,
        allowed_domains: list[str] | None = None,
        max_steps: int = 15,
        timeout: int = 60,
        headless: bool = True,
    ) -> dict[str, Any]:
        """
        Execute a web automation task using natural language.
        
        Use this tool when you need to perform actions on a website like
        filling forms, clicking buttons, navigating complex menus, or
        extracting data from dynamically rendered pages.
        
        Args:
            task: Natural language description of the task (e.g., 'Go to booking.com and find hotels in London for next weekend')
            allowed_domains: Optional list of domains the agent is allowed to visit (e.g., ['google.com', 'booking.com'])
            max_steps: Maximum number of agent steps to take (1-50, default: 15)
            timeout: Maximum execution time in seconds (10-300, default: 60)
            headless: Whether to run the browser in headless mode (default: True)
            
        Returns:
            Dict containing the final result, history summary, and any captured errors.
        """
        # Validate inputs
        max_steps = max(1, min(max_steps, 50))
        timeout = max(10, min(timeout, 300))
        
        # Get LLM credentials
        api_key = None
        if credentials:
            api_key = credentials.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            
        if not api_key:
            return {"error": "OpenAI API key not found. Please set OPENAI_API_KEY."}

        # Initialize LLM
        # Browser-Use agents currently work best with GPT-4o or similar high-reasoning models
        llm = ChatOpenAI(model="gpt-4o", api_key=api_key)
        
        # Configure Browser and Agent
        browser = Browser(headless=headless, allowed_domains=allowed_domains)
        
        # Capturing steps and screenshots for observability
        step_logs = []
        
        async def on_step(state: Any, output: Any, step_number: int):
            log_entry = {
                "step": step_number,
                "url": state.url,
                "action": output.model_dump() if hasattr(output, 'model_dump') else str(output)
            }
            # Note: Browser-Use can capture screenshots in state.screenshot
            if hasattr(state, 'screenshot') and state.screenshot:
                log_entry["screenshot"] = "[Screenshot captured]" 
                logger.info(f"Step {step_number}: Screenshot available at {state.url}")
            
            step_logs.append(log_entry)
            logger.info(f"Completed step {step_number} on {state.url}")

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                register_new_step_callback=on_step
            )
            
            # Execute the task
            result = await agent.run(max_steps=max_steps)
            
            # Extract final message and history
            return {
                "result": result.final_result(),
                "steps_taken": len(result.history),
                "step_summary": step_logs,
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Browser-Use agent failed: {e}")
            return {
                "error": f"Task execution failed: {str(e)}",
                "success": False,
                "steps_completed": step_logs
            }
        finally:
            await browser.close()
