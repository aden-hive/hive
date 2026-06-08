"""
Web Scrape Tool - Extract content from web pages.

Uses Playwright with stealth for headless browser scraping,
enabling JavaScript-rendered content and bot detection evasion.
Uses BeautifulSoup for HTML parsing and content extraction.
Validates URLs against internal network ranges to prevent SSRF attacks.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup, NavigableString
from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)
from playwright_stealth import Stealth

# Browser-like User-Agent for actual page requests
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _is_internal_address(raw_ip: str) -> bool:
    """Check whether an IP address targets non-public infrastructure."""
    ip_str = raw_ip.split("%")[0] if "%" in raw_ip else raw_ip
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Unparseable — fail closed
    return not addr.is_global or addr.is_multicast


def _check_url_target(url: str) -> str | None:
    """Resolve a URL's hostname and reject it if any address is non-public.

    Returns an error message if blocked, None if safe.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return "Invalid URL: missing hostname"

    # Fast-path for raw IP literals
    try:
        ipaddress.ip_address(hostname)
        if _is_internal_address(hostname):
            return f"Blocked: direct request to internal address ({hostname})"
    except ValueError:
        pass  # Not an IP literal, resolve below

    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"DNS resolution failed for host: {hostname}"

    if not results:
        return f"No DNS records found for host: {hostname}"

    for entry in results:
        resolved_ip = str(entry[4][0])
        if _is_internal_address(resolved_ip):
            return f"Blocked: {hostname} resolves to internal address"

    return None


def register_tools(mcp: FastMCP) -> None:
    """Register web scrape tools with the MCP server."""

    @mcp.tool()
    async def web_scrape(
        url: str,
        selector: str | None = None,
        include_links: bool = False,
        max_length: int = 50000,
        offset: int = 0,
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
            include_links: When True, links are inlined as `[text](url)` in
                content and also returned as a `links` list
            max_length: Maximum length of extracted text returned in this call (1000-500000)
            offset: Character offset into the extracted text. Use with
                `next_offset` from a prior truncated result to paginate.
            respect_robots_txt: Whether to respect robots.txt rules (default True)

        Returns:
            Dict with: url, final_url, title, description, page_type
            (article|listing|page), content, length, offset, total_length,
            truncated, next_offset, headings, structured_data (json_ld + open_graph),
            and optionally links. On error, returns {"error": str, ...} with a hint when applicable.
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Validate max_length
            max_length = max(1000, min(max_length, 500000))

            # SSRF check: validate URL before making any request (must run
            # before robots.txt fetch, which also makes a network request)
            block_reason = _check_url_target(url)
            if block_reason is not None:
                return {"error": block_reason, "blocked_by_ssrf_protection": True, "url": url}

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
                            "hint": ("Pass respect_robots_txt=False if you have authorization to scrape this site."),
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

                    # Intercept navigation requests to block SSRF via redirects.
                    # Only check "document" requests (navigations), not
                    # sub-resources (CSS/JS/images) to avoid false positives
                    # and unnecessary DNS lookups.
                    ssrf_blocked: dict[str, Any] | None = None

                    async def _ssrf_route_handler(route):
                        nonlocal ssrf_blocked
                        req_url = route.request.url

                        # Skip non-network schemes (data:, blob:, etc.)
                        if urlparse(req_url).scheme not in {"http", "https"}:
                            await route.continue_()
                            return

                        block = _check_url_target(req_url)
                        if block is not None:
                            ssrf_blocked = {
                                "error": block,
                                "blocked_by_ssrf_protection": True,
                                "url": req_url,
                            }
                            await route.abort("blockedbyclient")
                        else:
                            await route.continue_()

                    await page.route("**/*", _ssrf_route_handler)

                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                    # Check if a redirect was blocked by SSRF protection
                    if ssrf_blocked is not None:
                        return ssrf_blocked

                    # Validate response before waiting for JS render
                    if response is None:
                        return {"error": "Navigation failed: no response received"}

                    if response.status != 200:
                        hint = (
                            "Site likely requires auth, blocks bots, or is rate-limiting."
                            if response.status in (401, 403, 429)
                            else "Resource may not exist or server may be down."
                        )
                        return {
                            "error": f"HTTP {response.status}: Failed to fetch URL",
                            "url": url,
                            "status": response.status,
                            "hint": hint,
                        }

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
            base_url = str(response.url)  # Final URL after redirects

            # Extract structured data BEFORE noise removal — JSON-LD lives
            # in <script>, which gets decomposed below. JSON-LD is often the
            # cleanest source of structured info on listing pages.
            json_ld: list[Any] = []
            for script in soup.find_all("script", type="application/ld+json"):
                raw = script.string or script.get_text() or ""
                if raw.strip():
                    try:
                        json_ld.append(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        pass

            open_graph: dict[str, str] = {}
            for meta in soup.find_all("meta"):
                prop = (meta.get("property") or "").strip()
                if prop.startswith("og:"):
                    val = (meta.get("content") or "").strip()
                    if val:
                        open_graph[prop[3:]] = val

            # Remove noise elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
                tag.decompose()

            # Get title and description (fall back to OG description)
            title = soup.title.get_text(strip=True) if soup.title else ""
            description = ""
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                description = meta_desc.get("content", "") or ""
            if not description:
                description = open_graph.get("description", "")

            # Headings outline (capped) — lets the agent drill in via selector
            headings: list[dict[str, Any]] = []
            for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                h_text = h.get_text(strip=True)
                if h_text:
                    headings.append({"level": int(h.name[1]), "text": h_text})
                if len(headings) >= 100:
                    break

            # Page-type heuristic: many <article> blocks → listing page
            article_count = len(soup.find_all("article"))
            if article_count >= 3:
                page_type = "listing"
            elif article_count == 1 or soup.find("main"):
                page_type = "article"
            else:
                page_type = "page"

            # Locate target subtree
            if selector:
                content_elem = soup.select_one(selector)
                if not content_elem:
                    return {
                        "error": f"No elements found matching selector: {selector}",
                        "url": url,
                        "hint": "Try a broader selector or omit selector to use auto-detection.",
                    }
            else:
                # Prefer <main> over the first <article> — on listing pages
                # the latter would drop every article after the first.
                content_elem = (
                    soup.find("main")
                    or soup.find(attrs={"role": "main"})
                    or soup.find("article")
                    or soup.find(class_=["content", "post", "entry", "article-body"])
                    or soup.find("body")
                )

            # Collect link metadata BEFORE rewriting anchors (rewriting
            # replaces <a> elements with NavigableStrings, so find_all('a')
            # would miss them after).
            links: list[dict[str, str]] = []
            if content_elem and include_links:
                for a in content_elem.find_all("a", href=True)[:50]:
                    link_text = a.get_text(strip=True)
                    href = urljoin(base_url, a["href"])
                    if link_text and href:
                        links.append({"text": link_text, "href": href})

            text = ""
            if content_elem:
                # Inline anchors as [text](url) so links survive text
                # extraction (otherwise the agent has to correlate `links`
                # against the text blob).
                if include_links:
                    for a in content_elem.find_all("a", href=True):
                        link_text = a.get_text(strip=True)
                        if link_text:
                            href = urljoin(base_url, a["href"])
                            a.replace_with(NavigableString(f"[{link_text}]({href})"))

                # Convert <br> and block elements into newlines so the output
                # preserves paragraph/list/heading structure rather than
                # collapsing into one giant whitespace-joined string.
                for br in content_elem.find_all("br"):
                    br.replace_with(NavigableString("\n"))
                block_tags = (
                    "p",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "li",
                    "tr",
                    "div",
                    "section",
                    "article",
                    "blockquote",
                )
                for block in content_elem.find_all(block_tags):
                    block.insert_before(NavigableString("\n"))
                    block.append(NavigableString("\n"))

                raw_text = content_elem.get_text(separator=" ")

                # Normalize: squash spaces within each line, collapse runs of
                # blank lines to a single blank, trim.
                cleaned: list[str] = []
                blank = True  # swallow leading blanks
                for line in raw_text.split("\n"):
                    line = re.sub(r"[ \t]+", " ", line).strip()
                    if line:
                        cleaned.append(line)
                        blank = False
                    elif not blank:
                        cleaned.append("")
                        blank = True
                text = "\n".join(cleaned).strip()

            # Apply offset/truncation with continuation metadata. Reserve 3
            # chars for the ellipsis so the returned string stays within
            # max_length (back-compat with existing test expectations).
            total_length = len(text)
            offset = max(0, min(offset, total_length))
            end = offset + max_length
            truncated = end < total_length
            sliced = text[offset:end]
            if truncated and len(sliced) >= 3:
                sliced = sliced[:-3] + "..."

            structured_data: dict[str, Any] = {}
            if json_ld:
                structured_data["json_ld"] = json_ld
            if open_graph:
                structured_data["open_graph"] = open_graph

            result: dict[str, Any] = {
                "url": url,
                "final_url": base_url,
                "title": title,
                "description": description,
                "page_type": page_type,
                "content": sliced,
                "length": len(sliced),
                "offset": offset,
                "total_length": total_length,
                "truncated": truncated,
                "next_offset": end if truncated else None,
                "headings": headings,
            }
            if structured_data:
                result["structured_data"] = structured_data
            if include_links:
                result["links"] = links

            return result

        except PlaywrightTimeout:
            return {"error": "Request timed out"}
        except PlaywrightError as e:
            return {"error": f"Browser error: {e!s}"}
        except Exception as e:
            return {"error": f"Scraping failed: {e!s}"}
