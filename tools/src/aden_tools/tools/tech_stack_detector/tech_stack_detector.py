"""
Tech Stack Detector - Fingerprint web technologies via passive analysis.

Performs non-intrusive HTTP requests to identify web server, framework, CMS,
JavaScript libraries, CDN, and security configuration through response headers,
HTML analysis, cookies, and common path probing.
"""

from __future__ import annotations

import re

import httpx
from fastmcp import FastMCP

# Patterns to detect JS frameworks/libraries in HTML source
JS_PATTERNS = {
    "React": [
        re.compile(r"react(?:\.min)?\.js", re.I),
        re.compile(r"data-reactroot", re.I),
        re.compile(r"__NEXT_DATA__", re.I),
    ],
    "Angular": [
        re.compile(r"angular(?:\.min)?\.js", re.I),
        re.compile(r"ng-app", re.I),
        re.compile(r"ng-version", re.I),
    ],
    "Vue.js": [
        re.compile(r"vue(?:\.min)?\.js", re.I),
        re.compile(r"data-v-[a-f0-9]", re.I),
        re.compile(r"__vue__", re.I),
    ],
    "jQuery": [
        re.compile(r"jquery[.-](\d+\.\d+(?:\.\d+)?)", re.I),
        re.compile(r"jquery(?:\.min)?\.js", re.I),
    ],
    "Bootstrap": [
        re.compile(r"bootstrap[.-](\d+\.\d+(?:\.\d+)?)", re.I),
        re.compile(r"bootstrap(?:\.min)?\.(?:js|css)", re.I),
    ],
    "Tailwind CSS": [
        re.compile(r"tailwind", re.I),
    ],
    "Svelte": [
        re.compile(r"svelte", re.I),
        re.compile(r"__svelte", re.I),
    ],
    "Next.js": [
        re.compile(r"_next/static", re.I),
        re.compile(r"__NEXT_DATA__", re.I),
    ],
    "Nuxt.js": [
        re.compile(r"__nuxt", re.I),
        re.compile(r"_nuxt/", re.I),
    ],
}

# Cookie names that reveal backend technology
COOKIE_TECH_MAP = {
    "PHPSESSID": "PHP",
    "JSESSIONID": "Java",
    "ASP.NET_SessionId": "ASP.NET",
    "csrftoken": "Django",
    "laravel_session": "Laravel",
    "rack.session": "Ruby/Rails",
    "connect.sid": "Node.js/Express",
    "_rails_session": "Ruby on Rails",
}

# Analytics and tracking patterns
ANALYTICS_PATTERNS = {
    "Google Analytics": [
        re.compile(r"google-analytics\.com/analytics\.js", re.I),
        re.compile(r"googletagmanager\.com", re.I),
        re.compile(r"gtag\(", re.I),
    ],
    "Facebook Pixel": [re.compile(r"connect\.facebook\.net", re.I)],
    "Hotjar": [re.compile(r"static\.hotjar\.com", re.I)],
    "Mixpanel": [re.compile(r"cdn\.mxpnl\.com", re.I)],
    "Segment": [re.compile(r"cdn\.segment\.com", re.I)],
}

# CDN detection via response headers
CDN_HEADERS = {
    "cf-ray": "Cloudflare",
    "x-cdn": None,  # Value is the CDN name
    "x-served-by": "Fastly",
    "x-amz-cf-id": "AWS CloudFront",
    "x-cache": None,  # Generic, check value
    "via": None,  # Often contains CDN info
    "x-vercel-id": "Vercel",
    "x-netlify-request-id": "Netlify",
    "fly-request-id": "Fly.io",
}

# Paths to probe for CMS / framework detection
PROBE_PATHS = {
    "/wp-admin/": "WordPress",
    "/wp-json/wp/v2/": "WordPress",
    "/wp-login.php": "WordPress",
    "/administrator/": "Joomla",
    "/user/login": "Drupal",
    "/admin/": None,  # Generic admin panel
    "/api/": None,  # API endpoint
    "/.well-known/security.txt": None,
    "/robots.txt": None,
    "/sitemap.xml": None,
}


def register_tools(mcp: FastMCP) -> None:
    """Register tech stack detection tools with the MCP server."""

    @mcp.tool()
    async def tech_stack_detect(url: str) -> dict:
        """
        Detect the technology stack of a website through passive analysis.

        Identifies web server, framework, CMS, JavaScript libraries, CDN,
        analytics, and security configuration by analyzing HTTP responses,
        HTML content, cookies, and common paths. Non-intrusive.

        Args:
            url: URL to analyze (e.g., "https://example.com"). Auto-prefixes https://.

        Returns:
            Dict with detected technologies, security configuration,
            and grade_input for the risk_scorer tool.
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        # Ensure trailing slash for base URL
        base_url = url.rstrip("/")

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15,
                verify=True,
            ) as client:
                # Main page request
                response = await client.get(base_url)
                html = response.text
                headers = response.headers

                # Detect server
                server = _detect_server(headers)

                # Detect CDN
                cdn = _detect_cdn(headers)

                # Detect framework from headers
                framework = _detect_framework_from_headers(headers)

                # Detect language from headers/cookies
                language = _detect_language(headers, response.cookies)

                # Detect JS libraries from HTML
                js_libs = _detect_js_libraries(html)

                # Detect analytics
                analytics = _detect_analytics(html)

                # Detect CMS from HTML meta tags
                cms = _detect_cms_from_html(html)

                # Analyze cookies from raw Set-Cookie headers
                cookies = _analyze_cookies(response.headers)

                # If we detected language from cookies, update
                for cookie_name in response.cookies:
                    if cookie_name in COOKIE_TECH_MAP and not language:
                        language = COOKIE_TECH_MAP[cookie_name]

                # Probe common paths
                security_txt = False
                robots_txt = False
                interesting_paths = []
                cms_from_paths = None

                for path, tech in PROBE_PATHS.items():
                    try:
                        probe_resp = await client.get(
                            f"{base_url}{path}",
                            follow_redirects=False,
                        )
                        if probe_resp.status_code in (200, 301, 302, 403):
                            if path == "/.well-known/security.txt":
                                security_txt = probe_resp.status_code == 200
                            elif path == "/robots.txt":
                                robots_txt = probe_resp.status_code == 200
                            elif tech and probe_resp.status_code in (200, 301, 302):
                                cms_from_paths = tech
                            elif probe_resp.status_code in (200, 301, 302):
                                interesting_paths.append(path)
                    except httpx.HTTPError:
                        continue

                # Use CMS from paths if not detected from HTML
                if not cms and cms_from_paths:
                    cms = cms_from_paths

                # Detect framework from HTML if not from headers
                if not framework:
                    framework = _detect_framework_from_html(html)

        except httpx.ConnectError as e:
            return {"error": f"Connection failed: {e}"}
        except httpx.TimeoutException:
            return {"error": f"Request to {url} timed out"}
        except Exception as e:
            return {"error": f"Detection failed: {e}"}

        # Grade input
        server_version_hidden = True
        if server and server.get("version"):
            server_version_hidden = False

        grade_input = {
            "server_version_hidden": server_version_hidden,
            "framework_version_hidden": framework is None or not _has_version(framework),
            "security_txt_present": security_txt,
            "cookies_secure": all(c.get("secure", False) for c in cookies) if cookies else True,
            "cookies_httponly": (
                all(c.get("httponly", False) for c in cookies) if cookies else True
            ),
        }

        return {
            "url": str(response.url),
            "server": server,
            "framework": framework,
            "language": language,
            "cms": cms,
            "javascript_libraries": js_libs,
            "cdn": cdn,
            "analytics": analytics,
            "security_txt": security_txt,
            "robots_txt": robots_txt,
            "interesting_paths": interesting_paths,
            "cookies": cookies,
            "grade_input": grade_input,
        }


def _detect_server(headers: httpx.Headers) -> dict | None:
    """Detect web server from headers."""
    server_header = headers.get("server")
    if not server_header:
        return None

    # Try to parse name and version
    match = re.match(r"^([\w.-]+)(?:/(\S+))?", server_header)
    if match:
        return {"name": match.group(1), "version": match.group(2), "raw": server_header}
    return {"name": server_header, "version": None, "raw": server_header}


def _detect_cdn(headers: httpx.Headers) -> str | None:
    """Detect CDN from response headers."""
    for header_name, cdn_name in CDN_HEADERS.items():
        value = headers.get(header_name)
        if value:
            if cdn_name:
                return cdn_name
            # Try to infer from value
            value_lower = value.lower()
            if "cloudflare" in value_lower:
                return "Cloudflare"
            if "cloudfront" in value_lower:
                return "AWS CloudFront"
            if "fastly" in value_lower:
                return "Fastly"
            if "akamai" in value_lower:
                return "Akamai"
            if "varnish" in value_lower:
                return "Varnish"
    return None


def _detect_framework_from_headers(headers: httpx.Headers) -> str | None:
    """Detect framework from HTTP headers."""
    powered_by = headers.get("x-powered-by")
    if powered_by:
        return powered_by
    return None


def _detect_framework_from_html(html: str) -> str | None:
    """Detect framework from HTML content."""
    # Django
    if "csrfmiddlewaretoken" in html:
        return "Django"
    # Rails
    if "csrf-token" in html and "data-turbo" in html:
        return "Ruby on Rails"
    # Laravel
    if "laravel" in html.lower():
        return "Laravel"
    return None


def _detect_language(headers: httpx.Headers, cookies: httpx.Cookies) -> str | None:
    """Detect programming language."""
    powered_by = headers.get("x-powered-by", "").lower()
    if "php" in powered_by:
        return "PHP"
    if "asp.net" in powered_by:
        return "ASP.NET"
    if "express" in powered_by:
        return "Node.js"

    # Check cookies
    for cookie_name in cookies:
        if cookie_name in COOKIE_TECH_MAP:
            tech = COOKIE_TECH_MAP[cookie_name]
            if tech in ("PHP", "Java", "ASP.NET", "Node.js/Express"):
                return tech
    return None


def _detect_js_libraries(html: str) -> list[str]:
    """Detect JavaScript libraries from HTML source."""
    found = []
    for lib_name, patterns in JS_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(html)
            if match:
                # Try to extract version
                version_match = re.search(
                    rf"{lib_name.lower().replace('.', r'.')}[/-](\d+\.\d+(?:\.\d+)?)",
                    html,
                    re.I,
                )
                if version_match:
                    found.append(f"{lib_name} {version_match.group(1)}")
                else:
                    found.append(lib_name)
                break
    return found


def _detect_analytics(html: str) -> list[str]:
    """Detect analytics/tracking from HTML source."""
    found = []
    for name, patterns in ANALYTICS_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(html):
                found.append(name)
                break
    return found


def _detect_cms_from_html(html: str) -> str | None:
    """Detect CMS from HTML meta tags and content."""
    # WordPress
    if "wp-content" in html or "wp-includes" in html:
        return "WordPress"
    # Drupal
    if "Drupal" in html or "drupal.js" in html:
        return "Drupal"
    # Joomla
    if "/media/jui/" in html or "Joomla" in html:
        return "Joomla"
    # Shopify
    if "cdn.shopify.com" in html:
        return "Shopify"
    # Squarespace
    if "squarespace" in html.lower():
        return "Squarespace"
    # Wix
    if "wix.com" in html:
        return "Wix"
    # Ghost
    if "ghost-" in html or "ghost/" in html:
        return "Ghost"

    # Check meta generator tag
    gen_match = re.search(
        r'<meta[^>]+name=["\']generator["\'][^>]+content=["\'](.*?)["\']',
        html,
        re.I,
    )
    if not gen_match:
        gen_match = re.search(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']generator["\']',
            html,
            re.I,
        )
    if gen_match:
        return gen_match.group(1)

    return None


def _analyze_cookies(headers: httpx.Headers) -> list[dict]:
    """Analyze cookies for security flags by parsing raw Set-Cookie headers."""
    result = []
    for raw in headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0].strip()
        parts = [p.strip().lower() for p in raw.split(";")]
        result.append(
            {
                "name": name,
                "secure": "secure" in parts,
                "httponly": "httponly" in parts,
                "samesite": _extract_samesite(raw.lower()),
            }
        )
    return result


def _extract_samesite(raw_lower: str) -> str | None:
    """Extract SameSite value from a lowercased Set-Cookie string."""
    for part in raw_lower.split(";"):
        part = part.strip()
        if part.startswith("samesite="):
            return part.split("=", 1)[1].strip().capitalize()
    return None


def _has_version(value: str) -> bool:
    """Check if a string contains a version number."""
    return bool(re.search(r"\d+\.\d+", value))
