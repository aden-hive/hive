"""
Web Scrape Tool - Extract content from web pages.

Uses Playwright with stealth for headless browser scraping,
enabling JavaScript-rendered content and bot detection evasion.
Uses BeautifulSoup for HTML parsing and content extraction.
Validates URLs against internal network ranges to prevent SSRF attacks.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, NavigableString
from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)
from playwright_stealth import Stealth

# Browser-like User-Agent for actual page requests
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _resolve_scrape_artifact_dir() -> Path:
    """Return the directory where extracted scrape text is written.

    Prefers ``<HIVE_STORAGE_PATH>/data`` (same folder the agent uses for
    spillover, injected per-agent into MCP subprocess env by the
    framework's tool_registry).  Falls back to the shared
    ``<HIVE_HOME>/tool-artifacts`` directory — same folder the browser
    inspection tools use.  HIVE_HOME respects the desktop shell's
    override (e.g. macOS userData dir); defaults to ``~/.hive`` for the
    OSS install.
    """
    storage = os.environ.get("HIVE_STORAGE_PATH")
    if storage:
        return Path(storage) / "data"
    hive_home = os.environ.get("HIVE_HOME")
    base = Path(hive_home).expanduser() if hive_home else Path.home() / ".hive"
    return base / "tool-artifacts"


def _write_scrape_artifact(host: str, raw_text: str) -> Path:
    """Persist extracted scrape text as raw UTF-8 (no JSON wrapping) and
    return the absolute path.  Filename: ``web_scrape_<unix_ms>_<host>.txt``.
    Host is sanitized to a filesystem-safe slug (~60 chars).
    """
    out_dir = _resolve_scrape_artifact_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    safe_host = re.sub(r"[^a-zA-Z0-9._-]", "_", host or "unknown")[:60]
    path = out_dir / f"web_scrape_{ts_ms}_{safe_host}.txt"
    path.write_text(raw_text, encoding="utf-8")
    return path.resolve()


def _is_internal_address(raw_ip: str) -> bool:
    """Check whether an IP address targets non-public infrastructure."""
    ip_str = raw_ip.split("%")[0] if "%" in raw_ip else raw_ip
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Unparseable — fail closed
    return not addr.is_global or addr.is_multicast


async def _check_url_target(url: str) -> str | None:
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

    # Cap DNS resolution at 5s so a hung resolver can't burn the tool budget.
    loop = asyncio.get_running_loop()
    try:
        results = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
            timeout=5.0,
        )
    except (TimeoutError, socket.gaierror):
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
        respect_robots_txt: bool = False,
    ) -> dict:
        """
        Scrape and extract text content from a webpage.

        Uses a headless browser to render JavaScript and bypass bot detection.
        Use when you need to read the content of a specific URL,
        extract data from a website, or read articles/documentation.

        The extracted text body is **written to a file on disk** rather
        than returned inline — JSON-wrapping multi-KB page text escapes
        every newline and quote, which poisons the agent's context. The
        response carries only metadata (title, description, headings,
        structured data, links) plus ``saved_to`` pointing at the raw
        text file. Use ``terminal_exec("cat <saved_to>")`` (page large
        output via ``terminal_output_get``) or ``terminal_rg`` on
        ``saved_to`` to inspect the body. Length is reported via
        ``total_length``.

        Args:
            url: URL of the webpage to scrape
            selector: CSS selector to target specific content (e.g., 'article', '.main-content')
            include_links: When True, links are inlined as `[text](url)` in
                the saved body and also returned as a `links` list
            respect_robots_txt: Whether to respect robots.txt rules (default False —
                operator has authorization for these one-off, low-volume fetches;
                pass True to re-enable the check for a given call)

        Returns:
            Dict with: url, final_url, title, description, page_type
            (article|listing|page), total_length, saved_to, headings,
            structured_data (json_ld + open_graph), and optionally links.
            On error, returns {"error": str, ...} with a hint when applicable.
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # SSRF check: validate URL before making any request (must run
            # before robots.txt fetch, which also makes a network request)
            block_reason = await _check_url_target(url)
            if block_reason is not None:
                return {"error": block_reason, "blocked_by_ssrf_protection": True, "url": url}

            # Check robots.txt before launching browser. RobotFileParser.read()
            # has no timeout — fetch via httpx with a 5s cap so a slow host
            # can't burn the tool budget here.
            if respect_robots_txt:
                try:
                    parsed = urlparse(url)
                    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                        resp = await client.get(robots_url, headers={"User-Agent": BROWSER_USER_AGENT})
                    if resp.status_code < 400:
                        rp = RobotFileParser()
                        rp.parse(resp.text.splitlines())
                        if not rp.can_fetch(BROWSER_USER_AGENT, url):
                            return {
                                "error": f"Blocked by robots.txt: {url}",
                                "url": url,
                                "skipped": True,
                                "hint": ("Pass respect_robots_txt=False if you have authorization to scrape this site."),
                            }
                except (httpx.HTTPError, ValueError):
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

                        block = await _check_url_target(req_url)
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

                    # Cap goto at 30s so its own PlaywrightTimeout fires
                    # inside the 60s agent-loop budget — letting the outer
                    # timeout win leaks the browser subprocess.
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=30000,
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

            # Persist the extracted body to disk rather than embedding
            # it in the JSON response. A JSON-wrapped multi-KB page text
            # escapes every newline and quote, which is noisy and
            # token-hostile for the agent. The response carries only
            # metadata + the file path; the agent reads/greps the file
            # on demand.
            total_length = len(text)
            saved_to: str | None = None
            if total_length > 0:
                try:
                    host = urlparse(base_url).hostname or urlparse(url).hostname or "unknown"
                    saved_to = str(_write_scrape_artifact(host, text))
                except OSError as write_err:
                    return {
                        "error": f"Failed to write scrape artifact: {write_err}",
                        "url": url,
                    }

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
                "total_length": total_length,
                "saved_to": saved_to,
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
