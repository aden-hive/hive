# Vibe Prospecting Tool

B2B prospecting and data enrichment via the Vibe Prospecting (Explorium) API.

## Tools

| Tool | Description |
|------|-------------|
| `vibeprospecting_search_companies` | Search companies with filters (industry, size, location, tech stack) |
| `vibeprospecting_enrich_company` | Enrich a company by business_id, domain, or name |
| `vibeprospecting_search_prospects` | Search prospects with filters (job title, level, department) |
| `vibeprospecting_enrich_prospect` | Enrich a prospect by prospect_id, email, LinkedIn URL, or name |
| `vibeprospecting_match_company` | Match a company to get accurate business_id |
| `vibeprospecting_match_prospect` | Match a prospect to get accurate prospect_id |
| `vibeprospecting_company_statistics` | Get market statistics for companies matching filters |
| `vibeprospecting_autocomplete_company` | Autocomplete company search |

## Authentication

Requires a Vibe Prospecting API key passed via `VIBEPROSPECTING_API_KEY` environment variable or the credential store.

**How to get an API key:**

1. Sign up at https://www.vibeprospecting.ai/
2. Navigate to your account settings or API section
3. Generate an API key
4. Set environment variable:
   ```bash
   export VIBEPROSPECTING_API_KEY=your-api-key
   ```

## Pricing

| Plan | Price | Credits | Validity |
|------|-------|---------|----------|
| Free Trial | $0 | 400 | 90 days |
| Plus | $19.99 | 600 | 365 days |
| Boost | $69.99 | 2,500 | 365 days |
| Ultra | $149.99 | 6,000 | 365 days |
| Custom | Custom | Volume discount | Custom |

**Credit Usage:**
- Discovery: Finding companies/prospects
- Email Reveal: Access verified email addresses
- Phone Reveal: Access phone numbers
- Enrichment: Additional business and prospect signals

## Rate Limits

- **200 queries per minute (QPM)**
- Automatically enforced with clear error messages
- Use pagination and batching for large datasets

## Usage Examples

### Search for Companies

```python
# Search for mid-sized US software companies
result = vibeprospecting_search_companies(
    filters_json='''{
        "country_code": {"type": "includes", "values": ["us"]},
        "company_size": {"type": "includes", "values": ["51-200", "201-500"]},
        "industry": {"type": "includes", "values": ["software", "technology"]}
    }''',
    page_size=25,
    mode="full"
)
```

### Enrich a Company

```python
# Enrich by domain
result = vibeprospecting_enrich_company(domain="openai.com")

# Or by business_id (most accurate)
result = vibeprospecting_enrich_company(business_id="abc123xyz")
```

### Search for Prospects

```python
# Find VP-level sales prospects at specific companies
result = vibeprospecting_search_prospects(
    filters_json='''{
        "business_id": {"values": ["company_id_here"]},
        "job_level": {"values": ["vp", "director"]},
        "job_department": {"values": ["sales", "business development"]},
        "has_email": {"value": true}
    }''',
    page_size=50
)
```

### Enrich a Prospect

```python
# Enrich by email
result = vibeprospecting_enrich_prospect(email="john@acme.com")

# Or by LinkedIn URL
result = vibeprospecting_enrich_prospect(
    linkedin_url="linkedin.com/in/johndoe"
)
```

### Match Company Before Enrichment

```python
# Match to get accurate business_id
match_result = vibeprospecting_match_company(domain="tesla.com")
business_id = match_result.get("business_id")

# Then enrich with the matched ID
enrich_result = vibeprospecting_enrich_company(business_id=business_id)
```

### Get Market Statistics

```python
# Check market size before fetching full dataset
stats = vibeprospecting_company_statistics(
    filters_json='''{
        "country_code": {"type": "includes", "values": ["us"]},
        "company_size": {"type": "includes", "values": ["11-50"]},
        "industry": {"type": "includes", "values": ["software"]}
    }'''
)
# Returns: total count, distributions, etc.
```

### Autocomplete

```python
# Autocomplete company search
suggestions = vibeprospecting_autocomplete_company(
    query="tesla",
    limit=10
)
```

## Common Filters

### Company Filters

- `country_code`: Country codes (e.g., "us", "ca", "gb")
- `company_size`: Employee ranges (e.g., "1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+")
- `industry`: Industry categories (e.g., "software", "technology", "finance", "healthcare")
- `technologies`: Tech stack (e.g., "salesforce", "aws", "kubernetes", "hubspot")
- `annual_revenue_range`: Revenue ranges (e.g., "1M-10M", "10M-50M", "50M-100M", "100M-500M")
- `has_funding`: Boolean for funded companies
- `city`: City names
- `region_name`: State/province names

### Prospect Filters

- `business_id`: Target specific companies
- `job_title`: Exact job titles
- `job_level`: Seniority levels (e.g., "entry", "mid-level", "senior", "manager", "director", "vp", "c-level", "owner")
- `job_department`: Departments (e.g., "sales", "marketing", "engineering", "operations", "finance", "hr")
- `seniority`: Broader seniority categories
- `has_email`: Boolean for email availability
- `has_phone`: Boolean for phone availability
- `country_code`: Location filters
- `total_experience_months`: Experience range (e.g., {"gte": 36, "lte": 120})

## Filter Format

Filters use a consistent JSON structure:

```json
{
  "field_name": {
    "type": "includes",  // or "excludes"
    "values": ["value1", "value2"]
  }
}
```

For boolean filters:
```json
{
  "has_email": {
    "value": true
  }
}
```

For range filters:
```json
{
  "total_experience_months": {
    "gte": 36,
    "lte": 120
  }
}
```

## Best Practices

1. **Use Statistics First**: Check market size with `company_statistics` before fetching large datasets
2. **Match Before Enrichment**: Use match endpoints for accurate entity resolution
3. **Paginate Large Results**: Use `page` and `page_size` parameters
4. **Filter Strategically**: Combine multiple filters for precise targeting
5. **Monitor Rate Limits**: Stay within 200 QPM to avoid throttling
6. **Choose Mode Wisely**: Use `mode="basic"` when you don't need full enrichment data

## Workflow Example

```python
# 1. Check market size
stats = vibeprospecting_company_statistics(
    filters_json='{"country_code": {"type": "includes", "values": ["us"]}, "company_size": {"type": "includes", "values": ["51-200"]}}'
)
print(f"Found {stats['total_count']} companies")

# 2. Search companies
companies = vibeprospecting_search_companies(
    filters_json='{"country_code": {"type": "includes", "values": ["us"]}, "company_size": {"type": "includes", "values": ["51-200"]}}',
    page_size=100
)

# 3. Extract business_ids
business_ids = [c['business_id'] for c in companies['data']]

# 4. Search prospects at those companies
prospects = vibeprospecting_search_prospects(
    filters_json=f'{{"business_id": {{"values": {business_ids}}}, "job_level": {{"values": ["vp", "director"]}}, "has_email": {{"value": true}}}}',
    page_size=100
)

# 5. Enrich specific prospects
for prospect in prospects['data']:
    enriched = vibeprospecting_enrich_prospect(
        prospect_id=prospect['prospect_id']
    )
```

## Error Handling

The API returns clear error messages for common failure modes:

- `401` - Invalid API key
- `403` - Insufficient credits or permissions
- `404` - Resource not found
- `422` - Invalid parameters or filters
- `429` - Rate limit exceeded (200 QPM)

All errors are returned in a consistent format:
```python
{
    "error": "Error message",
    "help": "Additional guidance"
}
```

## Support

- **Documentation**: https://developers.explorium.ai/reference/introduction
- **Support Email**: support@vibeprospecting.ai
- **Pricing**: https://www.vibeprospecting.ai/pricing

## API Reference

- Base URL: `https://api.explorium.ai/v1`
- Authentication: API key in `API_KEY` header
- Rate Limit: 200 queries per minute
- Max page size: 100 records