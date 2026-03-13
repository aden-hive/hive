# VirusTotal Tool

Threat intelligence and security scanning via the [VirusTotal API v3](https://docs.virustotal.com/reference/overview).

## Tools

| Tool | Description |
|------|-------------|
| `vt_scan_ip` | Scan an IPv4 address for reputation and threat data |
| `vt_scan_domain` | Analyze a domain for security threats and DNS records |
| `vt_scan_hash` | Look up a file hash (MD5/SHA1/SHA256) for malware detection |

## Setup

1. Create a free VirusTotal account at https://www.virustotal.com/gui/join-us
2. Verify your email and log in
3. Click your profile icon → "API Key"
4. Copy the API key

```bash
export VIRUSTOTAL_API_KEY=your_api_key_here
```

## Rate Limits

Free tier: 4 requests/minute, 500 requests/day.

## Example Usage

```python
# Scan an IP address
vt_scan_ip(ip="8.8.8.8")

# Analyze a domain
vt_scan_domain(domain="example.com")

# Look up a file hash
vt_scan_hash(file_hash="d41d8cd98f00b204e9800998ecf8427e")
```
