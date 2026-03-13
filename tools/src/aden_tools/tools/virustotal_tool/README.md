# VirusTotal Tool

Threat intelligence and security scanning via the [VirusTotal API](https://docs.virustotal.com/reference/overview).

## Tools

| Tool | Description |
|------|-------------|
| `vt_scan_ip` | Scan an IP address for malicious activity reports |
| `vt_scan_domain` | Check domain reputation and threat categorization |
| `vt_scan_hash` | Look up a file hash (MD5/SHA-1/SHA-256) against 70+ AV engines |

## Setup

1. Create a free account at https://www.virustotal.com/gui/join-us
2. Go to your profile → API Key
3. Add the key to Hive:

```bash
hive credentials set virustotal --key api_key --value YOUR_API_KEY
```

Or set the environment variable:

```bash
export VIRUSTOTAL_API_KEY=your_api_key_here
```

## Rate Limits

Free tier: 500 requests/day, 4 requests/minute.

## Example Usage

```python
# In an agent graph node:
result = await call_tool("vt_scan_ip", {"ip": "8.8.8.8"})
# Returns: {"ip": "8.8.8.8", "as_owner": "GOOGLE", "analysis_stats": {...}}

result = await call_tool("vt_scan_domain", {"domain": "example.com"})
# Returns: {"domain": "example.com", "reputation": 0, "analysis_stats": {...}}

result = await call_tool("vt_scan_hash", {"file_hash": "d41d8cd98f00b204e9800998ecf8427e"})
# Returns: {"hash": "...", "file_type": "Text", "analysis_stats": {...}}
```
