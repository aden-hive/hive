# Port Scanner Tool

Scan common ports and detect exposed services using non-intrusive TCP connect probes.

## Features

- **port_scan** - Scan a host for open ports, grab service banners, and flag risky exposures

## How It Works

Performs TCP connect scans using Python's asyncio. The scanner:
1. Attempts to establish a TCP connection to each port
2. Grabs service banners where available
3. Identifies the service type (HTTP, SSH, MySQL, etc.)
4. Flags security risks (exposed databases, admin interfaces, legacy protocols)

**No credentials required** - Uses only standard network connections.

## Usage Examples

### Scan Top 20 Common Ports
```python
port_scan(
    hostname="example.com",
    ports="top20"
)
```

### Scan Top 100 Ports
```python
port_scan(
    hostname="example.com",
    ports="top100",
    timeout=5.0
)
```

### Scan Specific Ports
```python
port_scan(
    hostname="example.com",
    ports="80,443,8080,3306,5432"
)
```

## API Reference

### port_scan

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| hostname | str | Yes | - | Domain or IP to scan (e.g., "example.com") |
| ports | str | No | "top20" | Ports to scan: "top20", "top100", or comma-separated list |
| timeout | float | No | 3.0 | Connection timeout per port in seconds (max 10.0) |

### Response
```json
{
  "hostname": "example.com",
  "ip": "93.184.216.34",
  "ports_scanned": 20,
  "open_ports": [
    {
      "port": 80,
      "service": "HTTP",
      "banner": "nginx/1.18.0"
    },
    {
      "port": 443,
      "service": "HTTPS",
      "banner": ""
    },
    {
      "port": 3306,
      "service": "MySQL",
      "banner": "",
      "severity": "high",
      "finding": "MySQL port (3306) exposed to internet",
      "remediation": "Restrict database ports to localhost or VPN only."
    }
  ],
  "closed_ports": [21, 22, 23, ...],
  "grade_input": {
    "no_database_ports_exposed": false,
    "no_admin_ports_exposed": true,
    "no_legacy_ports_exposed": true,
    "only_web_ports": false
  }
}
```

## Security Findings

The scanner flags three categories of risky ports:

| Category | Ports | Severity |
|----------|-------|----------|
| Database | 1433 (MSSQL), 3306 (MySQL), 5432 (PostgreSQL), 6379 (Redis), 27017 (MongoDB) | High |
| Admin/Remote | 3389 (RDP), 5900 (VNC), 2082-2087 (cPanel) | High |
| Legacy | 21 (FTP), 23 (Telnet), 110 (POP3), 143 (IMAP), 445 (SMB) | Medium |

## Ethical Use

⚠️ **Important**: Only scan systems you own or have explicit permission to test.

- This tool performs active network connections
- Unauthorized port scanning may violate laws and terms of service
- Use responsibly for security assessments of your own infrastructure

## Error Handling
```python
{"error": "Could not resolve hostname: invalid.domain"}
{"error": "Invalid port list: abc. Use 'top20', 'top100', or '80,443'"}
```

## Integration with Risk Scorer

The `grade_input` field can be passed to the `risk_score` tool for weighted security grading.
