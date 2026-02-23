# Subdomain Enumerator

Discovers subdomains via Certificate Transparency (CT) logs — fully passive OSINT. Queries [crt.sh](https://crt.sh) to find all certificates ever issued for a domain, then flags subdomains that indicate potentially sensitive environments.

No active DNS brute-forcing or intrusive probing.

## Tools

### `subdomain_enumerate`

Enumerate subdomains for a domain using CT log data.

| Parameter     | Type    | Required | Description                                                            |
| ------------- | ------- | -------- | ---------------------------------------------------------------------- |
| `domain`      | string  | Yes      | Base domain to enumerate (e.g. `"example.com"`). No protocol prefix.  |
| `max_results` | integer | No       | Max subdomains to return (default: `50`, max: `200`)                   |

**Interesting subdomain keywords flagged:**

| Keyword    | Severity | Reason                                         |
| ---------- | -------- | ---------------------------------------------- |
| `admin`    | High     | Admin panel exposed publicly                   |
| `backup`   | High     | Backup infrastructure exposed                  |
| `debug`    | High     | Debug endpoint exposed                         |
| `staging`  | Medium   | Staging environment publicly accessible        |
| `dev`      | Medium   | Development environment publicly accessible    |
| `test`     | Medium   | Test environment publicly accessible           |
| `internal` | Medium   | Internal subdomain with a public certificate   |
| `ftp`      | Medium   | Legacy FTP subdomain                           |
| `vpn`      | Low      | VPN endpoint discoverable via CT logs          |
| `api`      | Low      | API subdomain — potential attack surface       |
| `mail`     | Info     | Mail server — verify SPF/DKIM/DMARC            |

**Returns:** Full list of discovered subdomains, interesting findings with severity and remediation, and a `grade_input` dict compatible with the `risk_score` tool.

**Example:**

```python
subdomain_enumerate(domain="example.com")
subdomain_enumerate(domain="example.com", max_results=100)
```

**Example response (abbreviated):**

```json
{
  "domain": "example.com",
  "source": "crt.sh (Certificate Transparency)",
  "total_found": 12,
  "subdomains": ["api.example.com", "dev.example.com", "staging.example.com", "www.example.com"],
  "interesting": [
    {
      "subdomain": "dev.example.com",
      "reason": "Development environment exposed publicly",
      "severity": "medium",
      "remediation": "Restrict development servers to internal access only."
    },
    {
      "subdomain": "staging.example.com",
      "reason": "Staging environment exposed publicly",
      "severity": "medium",
      "remediation": "Restrict staging to VPN or internal network access."
    }
  ],
  "grade_input": {
    "no_dev_staging_exposed": false,
    "no_admin_exposed": true,
    "reasonable_surface_area": true
  }
}
```

## Credentials

No API key required. Uses the public [crt.sh](https://crt.sh) API.

## Integration with `risk_score`

Pass the full JSON output to the `risk_score` tool as `subdomain_results` to include attack surface analysis in the overall security grade.

## Notes

- This is an async tool — it must be awaited in async contexts.
- Wildcard entries (e.g. `*.example.com`) are filtered out — only concrete subdomain names are returned.
- CT log data is historical; a subdomain appearing here does not necessarily mean it is currently active.
- Results depend on crt.sh availability — the tool will return an error if the service times out (30-second timeout).
