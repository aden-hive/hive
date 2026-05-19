"""
Web Scrape Tool - Extract content from web pages.

Uses Playwright with stealth for headless browser scraping,
enabling JavaScript-rendered content and bot detection evasion.
Uses BeautifulSoup for HTML parsing and content extraction.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse
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
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

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
