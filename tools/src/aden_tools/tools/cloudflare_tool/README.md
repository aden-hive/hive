# Cloudflare Tool

Manage DNS records, zones, and cache via the Cloudflare API v4.

## Setup

You need a Cloudflare API Token with the appropriate permissions.

### Getting a Cloudflare API Token

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click "Create Token"
3. Use the "Edit zone DNS" template (or create a custom token)
4. Select permissions:
   - **Zone → Zone → Read** (for listing and viewing zones)
   - **Zone → DNS → Edit** (for managing DNS records)
   - **Zone → Cache Purge → Purge** (for cache management)
5. Select zone resources (all zones or specific ones)
6. Click "Continue to summary" → "Create Token"
7. Copy the token

**Note:** Use scoped API Tokens (not the legacy Global API Key) for security.

### Configuration

```bash
export CLOUDFLARE_API_TOKEN=your_api_token_here
```

Or configure via the credential store (recommended for production).

## All Tools (7 Total)

### Zones (2)

| Tool | Description |
|------|-------------|
| `cloudflare_list_zones` | List domains on the account with optional filtering |
| `cloudflare_get_zone` | Get zone details (status, nameservers, plan) |

### DNS Records (4)

| Tool | Description |
|------|-------------|
| `cloudflare_list_dns_records` | List DNS records for a zone with type/name filtering |
| `cloudflare_create_dns_record` | Create A, AAAA, CNAME, MX, TXT, and other records |
| `cloudflare_update_dns_record` | Update an existing DNS record |
| `cloudflare_delete_dns_record` | Delete a DNS record |

### Cache (1)

| Tool | Description |
|------|-------------|
| `cloudflare_purge_cache` | Purge all cached content or specific URLs/tags |

## Supported Record Types

| Type | Example Content | Proxied | Priority |
|------|----------------|---------|----------|
| A | `192.0.2.1` | Yes | No |
| AAAA | `2001:db8::1` | Yes | No |
| CNAME | `example.netlify.app` | Yes | No |
| MX | `mail.example.com` | No | Required |
| TXT | `v=spf1 include:_spf.google.com ~all` | No | No |
| NS | `ns1.example.com` | No | No |
| SRV | `0 5 5060 sip.example.com` | No | No |
| CAA | `0 issue "letsencrypt.org"` | No | No |

## Use Cases

- *"List all DNS records for my domain and check the MX records"*
- *"Add a CNAME record pointing blog.example.com to my hosting provider"*
- *"After deployment, purge the Cloudflare cache for my site"*
- *"Check if my domain is active on Cloudflare and show the nameservers"*
- *"Create a TXT record for domain verification"*
