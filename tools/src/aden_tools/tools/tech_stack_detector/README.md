# Tech Stack Detector

Fingerprint web technologies through passive HTTP analysis.

## Features

- **Web server detection** — identifies server software and version from headers
- **Framework detection** — recognizes frameworks via headers (X-Powered-By), HTML patterns, and cookies
- **CMS identification** — detects WordPress, Drupal, Joomla, Shopify, Squarespace, Wix, Ghost, and others
- **JavaScript library detection** — identifies React, Angular, Vue.js, jQuery, Bootstrap, Tailwind CSS, Svelte, Next.js, Nuxt.js
- **CDN detection** — recognizes Cloudflare, AWS CloudFront, Fastly, Akamai, Vercel, Netlify, Fly.io
- **Analytics detection** — identifies Google Analytics, Facebook Pixel, Hotjar, Mixpanel, Segment
- **Cookie security analysis** — checks Secure, HttpOnly, and SameSite flags
- **Common path probing** — tests for security.txt, robots.txt, admin panels, and CMS-specific paths
- **Grade input** output for the `risk_scorer` tool

## Usage

```python
result = await tech_stack_detect("https://example.com")
```

### Scan Options

```python
# Auto-prefixes https:// if omitted
result = await tech_stack_detect("example.com")
```

## API Reference

| Parameter | Type  | Default  | Description                                          |
|-----------|-------|----------|------------------------------------------------------|
| `url`     | `str` | required | URL to analyze. Auto-prefixes `https://` if needed.  |

### Return Value

| Field                  | Type         | Description                                        |
|------------------------|--------------|----------------------------------------------------|
| `url`                  | `str`        | Final URL after redirects                          |
| `server`               | `dict\|None` | Server name, version, and raw header               |
| `framework`            | `str\|None`  | Detected framework (e.g., `"Django"`, `"Express"`) |
| `language`             | `str\|None`  | Detected language (e.g., `"PHP"`, `"Node.js"`)     |
| `cms`                  | `str\|None`  | Detected CMS (e.g., `"WordPress"`)                 |
| `javascript_libraries` | `list[str]`  | Detected JS libraries with versions when available |
| `cdn`                  | `str\|None`  | Detected CDN provider                              |
| `analytics`            | `list[str]`  | Detected analytics and tracking services           |
| `security_txt`         | `bool`       | Whether `/.well-known/security.txt` exists         |
| `robots_txt`           | `bool`       | Whether `/robots.txt` exists                       |
| `interesting_paths`    | `list[str]`  | Other discovered paths (admin, API, etc.)          |
| `cookies`              | `list[dict]` | Cookie security flag analysis                      |
| `grade_input`          | `dict`       | Scoring data for the `risk_scorer` tool            |

### Detection Methods

| Detection Target     | Method                                       |
|----------------------|----------------------------------------------|
| Web server           | `Server` response header                     |
| Framework            | `X-Powered-By` header, HTML patterns, cookies|
| Language             | Headers, cookie names (e.g., `PHPSESSID`)    |
| CMS                  | HTML content, meta generator tag, probe paths|
| JavaScript libraries | Regex patterns in HTML source                |
| CDN                  | CDN-specific response headers                |
| Analytics            | Regex patterns in HTML source                |

## Dependencies

- Python 3.11+
- [httpx](https://www.python-httpx.org/)

## Error Handling

| Error                       | Cause                    |
|-----------------------------|--------------------------|
| `"Connection failed: ..."`    | Host unreachable         |
| `"Request to ... timed out"`  | 15-second timeout exceeded|
| `"Detection failed: ..."`     | Other HTTP error         |

## Responsible Use

This tool performs **passive fingerprinting** through standard HTTP requests and public HTML analysis. It does not exploit vulnerabilities or inject payloads.

- Only scan websites you own or have explicit authorization to test
- Path probing sends standard HTTP requests — each returns normal 200/301/403/404 responses
- Technology information is used for security assessment, not exploitation
- Respect robots.txt directives when performing broader assessments
- Do not use detected technology versions to target known vulnerabilities without authorization
