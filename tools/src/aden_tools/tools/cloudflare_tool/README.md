# Cloudflare DNS/Zone Management Tool

Provides comprehensive Cloudflare DNS/Zone management tools for agents to inspect domains, DNS records, manage infrastructure, and diagnose DNS configuration issues.

## Features

- **Zone Management**: List zones, get details, and manage 30+ settings (SSL, IPv6, WebSockets, etc.).
- **DNS Management**: Create, Update, Delete, and List DNS records (A, CNAME, TXT, MX, etc.).
- **Security & Firewall**: Manage firewall rules, WAF rulesets, Bot management, and Zero Trust Access policies.
- **Analytics & Metrics**: Get traffic (bandwidth), security (threats), cache, and performance analytics.
- **Performance & Cache**: Purge everything or specific files from cache, manage speed settings (Minify, Brotli).
- **Eco-system Support**: List R2 Buckets, Pages Projects, and manage Workers routing.
- **Diagnostics**: Specialized DNS health diagnosis for domains with structured troubleshooting output.

## Authentication

Requires a Cloudflare API token with the following permissions:

### Recommended Permissions

- `Zone:Read`, `Zone:Edit` — zone information and settings
- `DNS:Read`, `DNS:Edit` — DNS records management
- `Account:Read`, `Account:Edit` — (Optional) account members and R2/Pages listing
- `Analytics:Read` — Analytics dashboards

### Setup

1. Navigate to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Create/Configure an API token with appropriate permissions.
3. Set the environment variable:
   ```bash
   export CLOUDFLARE_API_TOKEN="your_api_token_here"
   ```
   _Note: Can also be configured via the Aden Credential Store._

## Key Tools Summary

### Infrastructure & Zones

- `cloudflare_list_zones`: List zones in the account.
- `cloudflare_get_zone_settings`: Read 30+ common zone settings.
- `cloudflare_update_zone_setting`: Update specific settings (IPv6, settings IDs, etc.).
- `cloudflare_set_ssl_mode`: Quick toggle for SSL modes (Strict, Flexible, etc.).

### DNS Operations

- `cloudflare_list_dns_records`: List and filter DNS records.
- `cloudflare_create_dns_record`: Add new A, CNAME, TXT, etc. records.
- `cloudflare_update_dns_record`: Modify existing records.
- `cloudflare_delete_dns_record`: Remove records permanently.

### Analytics & Health

- `cloudflare_get_zone_analytics`: Get last 24h traffic/threat stats.
- `cloudflare_check_domain_dns_health`: Deep diagnostic check for domain misconfigurations.
- `cloudflare_get_http_analytics_report`: Detailed status code and content type distribution.

### Security

- `cloudflare_create_firewall_rule`: Create custom blocking/allow rules.
- `cloudflare_list_waf_rulesets`: View modern WAF configuration.
- `cloudflare_create_access_policy`: Set Zero Trust Access policies.

### Cache & Performance

- `cloudflare_purge_cache_all`: Clear the entire zone cache.
- `cloudflare_purge_cache_files`: Clear specific URLs from cache.
- `cloudflare_get_speed_settings`: Check Minify, Brotli, and Rocket Loader status.

### Account & Advanced

- `cloudflare_list_accounts`: List all accessible accounts.
- `cloudflare_invite_account_member`: Manage team access.
- `cloudflare_list_r2_buckets`: Overview of R2 storage.
- `cloudflare_create_worker_route`: Bind Worker scripts to URL patterns.

---

_Generated for the Model Context Protocol (MCP) as part of the Aden Tools suite._

### `cloudflare_get_zone`

Get details for a specific zone.

**Parameters:**

- `zone_id` (str, required): Zone ID (32-character hex string)

**Returns:**

```json
{
  "id": "023e105f4ecef8ad9ca31a8372d0c353",
  "name": "example.com",
  "status": "active",
  "name_servers": ["ns1.cloudflare.com", "ns2.cloudflare.com"],
  "created_on": "2014-01-01T23:27:06.000Z",
  "modified_on": "2014-07-10T05:35:15.000Z",
  "plan": "pro",
  "type": "full"
}
```

### `cloudflare_list_dns_records`

List DNS records for a zone.

**Parameters:**

- `zone_id` (str, required): Zone ID
- `name` (str, optional): Filter by DNS record name
- `type` (str, optional): Filter by record type (A, AAAA, CNAME, MX, TXT, etc.)
- `page` (int, default=1): Page number for pagination
- `per_page` (int, default=20): Results per page (max 100)

**Returns:**

```json
{
  "records": [
    {
      "id": "372e67954025e0ba6aaa6d586b9e0b59",
      "type": "A",
      "name": "example.com",
      "content": "192.0.2.1",
      "ttl": 3600,
      "proxied": true,
      "priority": null
    }
  ],
  "zone_id": "023e105f4ecef8ad9ca31a8372d0c353",
  "page": 1,
  "per_page": 20,
  "total": 1
}
```

### `cloudflare_get_dns_record`

Get a specific DNS record by ID.

**Parameters:**

- `zone_id` (str, required): Zone ID
- `record_id` (str, required): DNS record ID

**Returns:**

```json
{
  "id": "372e67954025e0ba6aaa6d586b9e0b59",
  "type": "A",
  "name": "example.com",
  "content": "192.0.2.1",
  "ttl": 3600,
  "proxied": true,
  "priority": null,
  "created_on": "2014-01-01T23:28:48.000Z",
  "modified_on": "2014-07-10T05:35:15.000Z"
}
```

### `cloudflare_check_domain_dns_health`

Perform a comprehensive DNS health check for a domain, identifying common configuration issues.

**Parameters:**

- `domain` (str, required): Domain name (e.g., "example.com")

**Returns:**

```json
{
  "domain": "example.com",
  "zone_found": true,
  "zone_id": "023e105f4ecef8ad9ca31a8372d0c353",
  "zone_status": "active",
  "root_records": [
    {
      "id": "372e67954025e0ba6aaa6d586b9e0b59",
      "type": "A",
      "name": "example.com",
      "content": "192.0.2.1",
      "ttl": 3600,
      "proxied": false
    }
  ],
  "www_records": [
    {
      "id": "372e67954025e0ba6aaa6d586b9e0b60",
      "type": "A",
      "name": "www.example.com",
      "content": "192.0.2.1",
      "ttl": 3600,
      "proxied": false
    }
  ],
  "mx_records": [],
  "ns_records": [],
  "total_records": 2,
  "issues": [
    {
      "code": "MX_MISSING",
      "message": "No MX records configured for example.com"
    }
  ],
  "summary": "Zone is active. Found 2 DNS records. Issues detected: MX_MISSING."
}
```

## Common Issue Codes

- `ZONE_NOT_FOUND` — Zone not found for the domain in Cloudflare
- `ZONE_INACTIVE` — Zone status is not "active"
- `ROOT_MISSING` — No A/AAAA records for root domain
- `WWW_MISSING` — No www subdomain DNS record
- `MX_MISSING` — No MX records configured
- `PROXY_INVALID` — Proxied record has no valid target

## Usage Examples

```python
# List all zones
zones = mcp.tools["cloudflare_list_zones"](page=1, per_page=20)

# Get zone details
zone = mcp.tools["cloudflare_get_zone"](zone_id="023e105f4ecef8ad9ca31a8372d0c353")

# List DNS records for a zone
records = mcp.tools["cloudflare_list_dns_records"](
    zone_id="023e105f4ecef8ad9ca31a8372d0c353",
    type="A"
)

# Check DNS health for a domain
health = mcp.tools["cloudflare_check_domain_dns_health"](domain="example.com")
```

## Error Handling

All tools return structured error dictionaries on failure:

```json
{
  "error": "Unauthorized - invalid or missing CLOUDFLARE_API_TOKEN",
  "status_code": 401
}
```

Common error codes:

- `401` — Invalid or missing credentials
- `403` — Insufficient permissions
- `404` — Resource not found
- `429` — Rate limited (check `retry_after` header)

## Implementation Notes

- Tools encompass both resource query (GET) and update/create (POST/PATCH/DELETE) operations
- Credentials are retrieved from the `CLOUDFLARE_API_TOKEN` environment variable
- Requests are validated and sanitized for security
- Responses are normalized into compact, agent-friendly objects
- Pagination defaults to 20 results, maximum 100 per page
- API timeout is 30 seconds

## Files

- `cloudflare_tool.py` — Main tool implementation
- `__init__.py` — Package export
- `README.md` — This documentation
