"""
Web Scrape Tool - Extract content from web pages.

Uses Playwright with stealth for headless browser scraping,
enabling JavaScript-rendered content and bot detection evasion.
Uses BeautifulSoup for HTML parsing and content extraction.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse
import ipaddress
import socket
from typing import Any, List
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import httpcore
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)
from playwright_stealth import Stealth

# Browser-like User-Agent for actual page requests
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _get_robots_parser(base_url: str, timeout: float = 10.0) -> RobotFileParser | None:
    """
    Fetch and parse robots.txt for a domain.

    Args:
        base_url: Base URL of the domain (e.g., 'https://example.com')
        timeout: Timeout for fetching robots.txt

    Returns:
        RobotFileParser if robots.txt exists and was parsed, None otherwise
    """
    if base_url in _robots_cache:
        return _robots_cache[base_url]

    robots_url = f"{base_url}/robots.txt"
    parser = RobotFileParser()

    try:
        transport = httpx.HTTPTransport(network_backend=SSRFProtectedBackend())
        with httpx.Client(transport=transport, follow_redirects=True, timeout=timeout) as client:
            response = client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
                _robots_cache[base_url] = parser
                return parser
            else:
                _robots_cache[base_url] = None
                return None
    except (httpx.TimeoutException, httpx.RequestError):
        return None


def _is_allowed_by_robots(url: str) -> tuple[bool, str]:
    """
    Check if URL is allowed by robots.txt.

    Args:
        url: Full URL to check

    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"

    parser = _get_robots_parser(base_url)

    if parser is None:
        # No robots.txt found or couldn't fetch - all paths allowed
        return True, "No robots.txt found or not accessible"

    # Check both our bot user-agent and wildcard
    if parser.can_fetch(USER_AGENT, path) and parser.can_fetch("*", path):
        return True, "Allowed by robots.txt"
    else:
        return False, f"Blocked by robots.txt for path: {path}"


def _check_ip_safety(ip_str: str) -> tuple[bool, str]:
    """
    Helper to check if an IP address is safe.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback:
            return True, f"loopback address ({ip_str})"
        if ip.is_private:
            return True, f"private network address ({ip_str})"
        if ip.is_link_local:
            return True, f"link-local address ({ip_str})"
        if ip.is_reserved:
            return True, f"reserved address ({ip_str})"
        return False, "safe"
    except ValueError:
        return True, f"invalid IP address ({ip_str})"


class SSRFProtectedBackend(httpcore.SyncBackend):
    """
    Custom httpcore backend that prevents SSRF by validating IP addresses
    at the time of connection, preventing DNS rebinding.
    """
    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        try:
            # Resolve to IPs and validate all of them
            addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            if not addr_info:
                raise httpcore.ConnectError(f"DNS resolution failed for {host}")

            for info in addr_info:
                ip_str = info[4][0]
                is_unsafe, reason = _check_ip_safety(ip_str)
                if is_unsafe:
                    raise httpcore.ConnectError(f"SSRF Protection: {reason}")

            # Use the first safe IP to prevent a second DNS lookup
            safe_ip = addr_info[0][4][0]
            return super().connect_tcp(
                host=safe_ip,
                port=port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )
        except socket.gaierror as e:
            raise httpcore.ConnectError(f"DNS resolution failed for {host}: {str(e)}")


def _is_unsafe_url(url: str) -> tuple[bool, str]:
    """
    Check if a URL points to an unsafe destination (initial fast-fail SSRF check).
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            return True, "Invalid URL: no hostname found"

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for info in addr_info:
                ip_str = info[4][0]
                is_unsafe, reason = _check_ip_safety(ip_str)
                if is_unsafe:
                    return True, f"Blocked: {reason}"
        except socket.gaierror:
            return False, "DNS resolution failed, allowing request to proceed to transport"

        return False, "URL is safe"

    except Exception as e:
        return True, f"URL validation error: {str(e)}"


def register_tools(mcp: FastMCP) -> None:
    """Register web scrape tools with the MCP server."""

    @mcp.tool()
    async def web_scrape(
        url: str,
        selector: str | None = None,
        include_links: bool = False,
        max_length: int = 50000,
        respect_robots_txt: bool = True,
    ) -> dict:
        """
        Scrape and extract text content from a webpage.

        Uses a headless browser to render JavaScript and bypass bot detection.
        Use when you need to read the content of a specific URL,
        extract data from a website, or read articles/documentation.

        Args:
            url: URL of the webpage to scrape
            selector: CSS selector to target specific content (e.g., 'article', '.main-content')
            include_links: Include extracted links in the response
            max_length: Maximum length of extracted text (1000-500000)
            respect_robots_txt: Whether to respect robots.txt rules (default True)

        Returns:
            Dict with scraped content (url, title, description, content, length) or error dict
        """
        try:
            # Validate URL scheme
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Block internal/private networks (SSRF protection)
            is_unsafe, safety_reason = _is_unsafe_url(url)
            if is_unsafe:
                return {
                    "error": f"SSRF Protection: {safety_reason}",
                    "blocked_by_ssrf_protection": True,
                    "url": url,
                }

            # Check robots.txt if enabled
            if respect_robots_txt:
                allowed, reason = _is_allowed_by_robots(url)
                if not allowed:
                    return {
                        "error": f"Scraping blocked: {reason}",
                        "blocked_by_robots_txt": True,
                        "url": url,
                    }

            # Validate max_length
            max_length = max(1000, min(max_length, 500000))

            # Make request with SSRF protection at transport layer
            transport = httpx.HTTPTransport(network_backend=SSRFProtectedBackend())
            with httpx.Client(transport=transport, follow_redirects=True, timeout=30.0) as client:
                response = client.get(
                    url,
                    headers={
                        "User-Agent": BROWSER_USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                    },
                )

                if response.status_code != 200:
                    return {"error": f"HTTP {response.status_code}: Failed to fetch URL"}

            # Check content type
            content_type = response.headers.get("content-type", "").lower()
            if not any(t in content_type for t in ["text/html", "application/xhtml+xml"]):
                return {
                    "error": f"Skipping non-HTML content (Content-Type: {content_type})",
                    "url": url,
                    "skipped": True,
                }

            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")
            # Validate max_length
            max_length = max(1000, min(max_length, 500000))

            # Check robots.txt before launching browser
            if respect_robots_txt:
                try:
                    parsed = urlparse(url)
                    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
                    rp = RobotFileParser()
                    rp.set_url(robots_url)
                    rp.read()
                    if not rp.can_fetch(BROWSER_USER_AGENT, url):
                        return {
                            "error": f"Blocked by robots.txt: {url}",
                            "url": url,
                            "skipped": True,
                        }
                except Exception:
                    pass  # If robots.txt can't be fetched, proceed anyway

            # Launch headless browser with stealth
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=BROWSER_USER_AGENT,
                        locale="en-US",
                    )
                    page = await context.new_page()
                    await Stealth().apply_stealth_async(page)

                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                    # Validate response before waiting for JS render
                    if response is None:
                        return {"error": "Navigation failed: no response received"}

                    if response.status != 200:
                        return {"error": f"HTTP {response.status}: Failed to fetch URL"}

                    content_type = response.headers.get("content-type", "").lower()
                    if not any(t in content_type for t in ["text/html", "application/xhtml+xml"]):
                        return {
                            "error": (f"Skipping non-HTML content (Content-Type: {content_type})"),
                            "url": url,
                            "skipped": True,
                        }

                    # Wait for JS to finish rendering dynamic content
                    try:
                        await page.wait_for_load_state("networkidle", timeout=3000)
                    except PlaywrightTimeout:
                        pass  # Proceed with whatever has loaded

                    # Get fully rendered HTML
                    html_content = await page.content()
                finally:
                    await browser.close()

            # Parse rendered HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove noise elements
            for tag in soup(
                ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]
            ):
                tag.decompose()

            # Get title and description
            title = soup.title.get_text(strip=True) if soup.title else ""

            description = ""
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                description = meta_desc.get("content", "")

            # Target content
            if selector:
                content_elem = soup.select_one(selector)
                if not content_elem:
                    return {"error": f"No elements found matching selector: {selector}"}
                text = content_elem.get_text(separator=" ", strip=True)
            else:
                # Auto-detect main content
                main_content = (
                    soup.find("article")
                    or soup.find("main")
                    or soup.find(attrs={"role": "main"})
                    or soup.find(class_=["content", "post", "entry", "article-body"])
                    or soup.find("body")
                )
                text = main_content.get_text(separator=" ", strip=True) if main_content else ""

            # Clean up whitespace
            text = " ".join(text.split())

            # Truncate if needed
            if len(text) > max_length:
                text = text[:max_length] + "..."

            result: dict[str, Any] = {
                "url": url,
                "title": title,
                "description": description,
                "content": text,
                "length": len(text),
            }

            # Extract links if requested
            if include_links:
                links: list[dict[str, str]] = []
                base_url = str(response.url)  # Use final URL after redirects
                for a in soup.find_all("a", href=True)[:50]:
                    href = a["href"]
                    # Convert relative URLs to absolute URLs
                    absolute_href = urljoin(base_url, href)
                    link_text = a.get_text(strip=True)
                    if link_text and absolute_href:
                        links.append({"text": link_text, "href": absolute_href})
                result["links"] = links

            return result

        except PlaywrightTimeout:
            return {"error": "Request timed out"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Scraping failed: {e!s}"}
