# Tech Stack Detector Tool

Fingerprint web technologies through passive HTTP analysis.

## Features

- **tech_stack_detect** - Identify web server, framework, CMS, JavaScript libraries, CDN, and security configuration

## How It Works

Performs non-intrusive HTTP requests to identify technologies:
1. Analyzes response headers (Server, X-Powered-By)
2. Parses HTML for JS libraries, frameworks, and CMS signatures
3. Inspects cookies for backend technology hints
4. Probes common paths (wp-admin, security.txt, etc.)
5. Detects CDN and analytics services

**No credentials required** - Uses only standard HTTP requests.

## Usage Examples

### Basic Detection
```python
tech_stack_detect(url="https://example.com")
```

## API Reference

### tech_stack_detect

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| url | str | Yes | URL to analyze (auto-prefixes https://) |

### Response
```json
{
  "url": "https://example.com/",
  "server": {
    "name": "nginx",
    "version": "1.18.0",
    "raw": "nginx/1.18.0"
  },
  "framework": "Express",
  "language": "Node.js",
  "cms": "WordPress",
  "javascript_libraries": ["React", "jQuery 3.6.0"],
  "cdn": "Cloudflare",
  "analytics": ["Google Analytics"],
  "security_txt": true,
  "robots_txt": true,
  "interesting_paths": ["/api/", "/admin/"],
  "cookies": [
    {
      "name": "session",
      "secure": true,
      "httponly": true,
      "samesite": "Strict"
    }
  ],
  "grade_input": {
    "server_version_hidden": false,
    "framework_version_hidden": true,
    "security_txt_present": true,
    "cookies_secure": true,
    "cookies_httponly": true
  }
}
```

## Technologies Detected

### Web Servers
nginx, Apache, IIS, LiteSpeed, etc.

### Frameworks & Languages
- **PHP**: Laravel, WordPress, Drupal
- **Python**: Django, Flask
- **JavaScript**: Express, Next.js, Nuxt.js
- **Ruby**: Rails
- **Java**: Spring
- **.NET**: ASP.NET

### JavaScript Libraries
React, Angular, Vue.js, jQuery, Bootstrap, Tailwind CSS, Svelte

### CMS Platforms
WordPress, Drupal, Joomla, Shopify, Squarespace, Wix, Ghost

### CDN Providers
Cloudflare, AWS CloudFront, Fastly, Akamai, Vercel, Netlify

### Analytics
Google Analytics, Facebook Pixel, Hotjar, Mixpanel, Segment

## Security Checks

| Check | Risk |
|-------|------|
| Server version disclosed | Enables targeted exploits |
| Framework version disclosed | Enables targeted exploits |
| No security.txt | No vulnerability reporting channel |
| Cookies missing Secure flag | Transmitted over HTTP |
| Cookies missing HttpOnly flag | Accessible to JavaScript (XSS risk) |

## Ethical Use

⚠️ **Important**: Only scan systems you own or have explicit permission to test.

- This tool sends multiple HTTP requests
- Path probing may be logged by the target

## Error Handling
```python
{"error": "Connection failed: [details]"}
{"error": "Request to https://example.com timed out"}
{"error": "Detection failed: [details]"}
```

## Integration with Risk Scorer

The `grade_input` field can be passed to the `risk_score` tool for weighted security grading.
