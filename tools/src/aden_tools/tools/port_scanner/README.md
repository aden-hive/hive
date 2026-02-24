# Port Scanner

Scan common ports and detect exposed services through non-intrusive TCP connect probes.

## Features

- **TCP connect scanning** on top 20, top 100, or custom port lists
- **Service identification** via well-known port mapping (SSH, HTTP, MySQL, Redis, etc.)
- **Banner grabbing** to capture service version information from open ports
- **Risk categorization** — flags database ports, admin interfaces, and legacy protocols
- **Concurrent scanning** with configurable concurrency limits and timeouts
- **Grade input** output for the `risk_scorer` tool

## Usage

```python
result = await port_scan("example.com")
```

### Scan Options

```python
# Quick scan — top 20 common ports
result = await port_scan("example.com", ports="top20")

# Extended scan — top 100 ports
result = await port_scan("example.com", ports="top100")

# Custom ports
result = await port_scan("example.com", ports="80,443,8080,3306")

# Adjust timeout (default 3s, max 10s)
result = await port_scan("example.com", ports="top20", timeout=5.0)
```

## API Reference

| Parameter  | Type    | Default   | Description                                                                 |
|------------|---------|-----------|-----------------------------------------------------------------------------|
| `hostname` | `str`   | required  | Domain or IP to scan (e.g., `"example.com"`). Protocol prefixes are stripped. |
| `ports`    | `str`   | `"top20"` | Port selection: `"top20"`, `"top100"`, or comma-separated list like `"80,443"`. |
| `timeout`  | `float` | `3.0`     | Connection timeout per port in seconds. Capped at 10.0.                     |

### Return Value

| Field           | Type         | Description                                         |
|-----------------|--------------|-----------------------------------------------------|
| `hostname`      | `str`        | Resolved hostname                                   |
| `ip`            | `str`        | Resolved IP address                                 |
| `ports_scanned` | `int`        | Total number of ports probed                        |
| `open_ports`    | `list[dict]` | Open ports with service name, banner, and risk info |
| `closed_ports`  | `list[int]`  | List of closed port numbers                         |
| `grade_input`   | `dict`       | Scoring data for the `risk_scorer` tool             |

### Risk Severities

| Category  | Ports                              | Severity |
|-----------|------------------------------------|----------|
| Database  | 1433, 3306, 5432, 6379, 27017, ... | High     |
| Admin     | 3389 (RDP), 5900 (VNC), ...        | High     |
| Legacy    | 21 (FTP), 23 (Telnet), 445 (SMB)   | Medium   |

## Dependencies

- Python 3.11+
- Python stdlib only (`asyncio`, `socket`)

## Error Handling

| Error                        | Cause                         |
|------------------------------|-------------------------------|
| `"Could not resolve hostname"` | DNS resolution failure        |
| `"Invalid port list"`         | Malformed `ports` parameter   |

## Responsible Use

This tool performs **non-intrusive TCP connect scans** using Python's standard library. It does not exploit vulnerabilities.

- Only scan hosts you own or have explicit authorization to test
- Respect rate limits and do not scan production systems during peak hours
- Unauthorized port scanning may violate laws and terms of service
- Use results for defensive security assessment only
