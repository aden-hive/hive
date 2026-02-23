# Tech Stack Detector

Fingerprints a website's technology stack through passive HTTP analysis. Identifies web server, backend language, framework, CMS, JavaScript libraries, CDN, analytics tools, and security configuration — all from a small number of HTTP requests.

## Tools

### `tech_stack_detect`

Detect the technology stack of a website.

| Parameter | Type   | Required | Description                                                              |
| --------- | ------ | -------- | ------------------------------------------------------------------------ |
| `url`     | string | Yes      | URL to analyze (e.g. `"https://example.com"`). `https://` is added automatically if omitted. |

**What it detects:**

| Category              | Detection method                                      | Examples                                           |
| --------------------- | ----------------------------------------------------- | -------------------------------------------------- |
| **Web server**        | `Server` response header                              | nginx, Apache, Caddy, IIS                          |
| **CDN**               | CDN-specific response headers                         | Cloudflare, AWS CloudFront, Fastly, Vercel, Netlify, Fly.io |
| **Framework**         | `X-Powered-By` header, HTML patterns                  | Django, Laravel, Ruby on Rails                     |
| **Backend language**  | `X-Powered-By` header, session cookies                | PHP, Node.js, Java, ASP.NET                        |
| **CMS**               | HTML source patterns, meta generator tag, path probing | WordPress, Drupal, Joomla, Shopify, Ghost, Wix     |
| **JavaScript libraries** | HTML source patterns                               | React, Angular, Vue.js, Next.js, Nuxt.js, jQuery, Bootstrap, Tailwind CSS, Svelte |
| **Analytics**         | HTML source patterns                                  | Google Analytics, Facebook Pixel, Hotjar, Mixpanel, Segment |
| **Cookie security**   | `Set-Cookie` response headers                         | `Secure`, `HttpOnly`, `SameSite` flags             |
| **security.txt**      | Probes `/.well-known/security.txt`                    | Present / absent                                   |
| **robots.txt**        | Probes `/robots.txt`                                  | Present / absent                                   |

**Returns:** Detected technologies per category, cookie security analysis, interesting accessible paths, and a `grade_input` dict compatible with the `risk_score` tool.

**Example:**

```python
tech_stack_detect(url="https://example.com")
```

**Example response (abbreviated):**

```json
{
  "url": "https://example.com",
  "server": { "name": "nginx", "version": null, "raw": "nginx" },
  "framework": "Django",
  "language": "Python",
  "cms": null,
  "javascript_libraries": ["React", "Next.js"],
  "cdn": "Cloudflare",
  "analytics": ["Google Analytics"],
  "security_txt": true,
  "robots_txt": true,
  "interesting_paths": ["/api/"],
  "cookies": [
    { "name": "sessionid", "secure": true, "httponly": true, "samesite": "Lax" }
  ],
  "grade_input": {
    "server_version_hidden": true,
    "framework_version_hidden": true,
    "security_txt_present": true,
    "cookies_secure": true,
    "cookies_httponly": true
  }
}
```

## Credentials

No API key required.

## Integration with `risk_score`

Pass the full JSON output to the `risk_score` tool as `tech_results` to include technology disclosure findings in the overall security grade.

## Notes

- Request timeout is 15 seconds.
- CMS and framework detection from path probing does not follow redirects to avoid false positives.
- A `403 Forbidden` response to `/wp-admin/` still counts as WordPress detection (the path exists).
- Cookie analysis reads raw `Set-Cookie` headers directly rather than the parsed cookie jar, ensuring `HttpOnly` flags are not lost.
- Only use against sites you own or have explicit written authorisation to test.
