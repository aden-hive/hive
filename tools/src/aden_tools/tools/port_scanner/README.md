# Port Scanner

Scans a host for open TCP ports using async connect probes. Identifies exposed services, grabs service banners, and flags risky exposures such as publicly accessible databases, remote admin interfaces, and legacy protocols. Uses Python stdlib only — no external tools required.

## Tools

### `port_scan`

Scan a host for open ports.

| Parameter  | Type   | Required | Description                                                                 |
| ---------- | ------ | -------- | --------------------------------------------------------------------------- |
| `hostname` | string | Yes      | Domain or IP to scan (e.g. `"example.com"`). Protocol prefix is stripped automatically. |
| `ports`    | string | No       | Port set to scan: `"top20"` (default), `"top100"`, or comma-separated like `"80,443,8080"`. |
| `timeout`  | float  | No       | Connection timeout per port in seconds (default: `3.0`, max: `10.0`).      |

**Port sets:**

| Value    | Ports scanned |
| -------- | ------------- |
| `top20`  | 20 well-known ports: FTP, SSH, Telnet, SMTP, DNS, HTTP, HTTPS, SMB, databases, RDP, VNC, etc. |
| `top100` | Top 20 + ~80 additional common ports including alt-HTTP, IRC, LDAP, VoIP, NoSQL, admin panels |
| Custom   | Any comma-separated list, e.g. `"22,80,443,3306"` |

**Risk classification for open ports:**

| Category  | Ports                                             | Severity |
| --------- | ------------------------------------------------- | -------- |
| Database  | MySQL, PostgreSQL, MSSQL, Redis, MongoDB, Elasticsearch, CouchDB, Memcached | High |
| Admin     | RDP, VNC, cPanel, Webmin                          | High     |
| Legacy    | FTP, Telnet, POP3, IMAP, SMB                      | Medium   |

**Returns:** List of open ports with service name and banner, list of closed ports, security findings with remediation advice, and a `grade_input` dict compatible with the `risk_score` tool.

**Example:**

```python
port_scan(hostname="example.com", ports="top20")
port_scan(hostname="192.168.1.1", ports="top100", timeout=5.0)
port_scan(hostname="example.com", ports="22,80,443,3306,5432")
```

**Example response (abbreviated):**

```json
{
  "hostname": "example.com",
  "ip": "93.184.216.34",
  "ports_scanned": 20,
  "open_ports": [
    { "port": 80, "service": "HTTP", "banner": "" },
    { "port": 443, "service": "HTTPS", "banner": "" },
    {
      "port": 3306,
      "service": "MySQL",
      "severity": "high",
      "finding": "MySQL port (3306) exposed to internet",
      "remediation": "Restrict database ports to localhost or VPN only..."
    }
  ],
  "closed_ports": [21, 22, 23, 25],
  "grade_input": {
    "no_database_ports_exposed": false,
    "no_admin_ports_exposed": true,
    "no_legacy_ports_exposed": true,
    "only_web_ports": false
  }
}
```

## Credentials

No API key required. Uses Python's `asyncio` and `socket` stdlib.

## Integration with `risk_score`

Pass the full JSON output (or just the `grade_input` field) to the `risk_score` tool as `ports_results` to include network exposure in the overall security grade.

## Notes

- Concurrency is capped at 20 simultaneous connections to avoid overwhelming the target.
- Banner grabbing reads up to 256 bytes from the open connection with a 2-second timeout.
- Only use against hosts you own or have explicit written authorisation to scan.
