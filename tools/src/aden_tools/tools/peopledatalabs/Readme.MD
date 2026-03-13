# People Data Labs Tool

B2B person and company data enrichment with access to 3 billion+ person profiles and comprehensive company data.

## Tools

| Tool | Description |
|------|-------------|
| `pdl_enrich_person` | Enrich person by email, phone, LinkedIn, or name + company/location |
| `pdl_search_people` | Search 3B+ person profiles with advanced Elasticsearch queries |
| `pdl_identify_person` | Get multiple possible matches for a person with confidence scores |
| `pdl_bulk_enrich_people` | Bulk enrich up to 100 people in a single request |
| `pdl_enrich_company` | Enrich company by domain, name, or LinkedIn profile |
| `pdl_search_companies` | Search companies with advanced queries |
| `pdl_autocomplete` | Autocomplete suggestions for company, school, title, skill, location |
| `pdl_clean_company` | Clean and normalize company names |
| `pdl_clean_location` | Parse and normalize location strings |
| `pdl_clean_school` | Clean and normalize school names |

## Authentication

Requires a People Data Labs API key passed via `PDL_API_KEY` environment variable or the credential store.

**How to get an API key:**

1. Sign up at https://dashboard.peopledatalabs.com/signup
2. Get your API key from the dashboard (automatically generated)
3. Free tier includes:
   - **1,000 free API credits**
   - Access to 3 billion+ person profiles
   - 100 requests per minute
4. Set environment variable:
   ```bash
   export PDL_API_KEY=your-api-key
   ```

## Pricing

| Plan | Price | Monthly Credits | Cost per 1K Credits | Rate Limit |
|------|-------|----------------|---------------------|------------|
| **Free** | $0 | 1,000 (one-time) | Free | 100 req/min |
| **Starter** | $249/mo | 10,000 | $24.90 | 1,000 req/min |
| **Growth** | $999/mo | 50,000 | $19.98 | 1,000 req/min |
| **Premium** | Custom | Custom | $10-15 | Custom |

**Credit Usage:**
- **Enrichment**: 1 credit per successful match (200 response)
- **Search**: 1 credit per record returned
- **Identify**: 1 credit per request (regardless of matches)
- **Bulk**: 1 credit per successful match in batch
- **Cleaners & Autocomplete**: FREE (no credits)

**Note**: Failed matches (404 responses) are FREE - no credits charged!

## Rate Limits

- **Free tier**: 100 requests per minute
- **Paid tier**: 1,000 requests per minute
- **Bulk enrichment**: Counts as 1 request (not 100)

## Dataset Coverage

### Person Dataset (3+ Billion Profiles)
- **Emails**: 1.5B+ work emails, 500M+ personal emails
- **Phone Numbers**: 600M+ mobile, 200M+ landline
- **Job History**: Current + historical employment
- **Education**: Schools, degrees, fields of study
- **Skills**: 50K+ normalized skills
- **Social Profiles**: LinkedIn, Twitter, Facebook, GitHub
- **Demographics**: Age, gender, location

### Company Dataset
- **20M+ companies** globally
- Industries, employee counts, revenue estimates
- Technologies used, funding information
- Social profiles and contact info

## Usage Examples

### 1. Enrich Person by Email

```python
result = pdl_enrich_person(email="[email protected]")

# Returns:
{
    "status": 200,
    "likelihood": 10,
    "data": {
        "id": "qEnOZ5Oh0poWnQ1luFBfVw_0000",
        "full_name": "sean thorne",
        "first_name": "sean",
        "last_name": "thorne",
        "emails": [
            {"address": "[email protected]", "type": "professional"}
        ],
        "phone_numbers": ["+14155551234"],
        "job_title": "software engineer",
        "job_company_name": "people data labs",
        "job_company_website": "peopledatalabs.com",
        "job_start_date": "2019-01",
        "experience": [...],
        "education": [...],
        "skills": ["python", "machine learning", "data science"],
        "linkedin_url": "linkedin.com/in/seanthorne",
        "github_url": "github.com/seanthorne",
        "location": {
            "name": "san francisco, california, united states",
            "locality": "san francisco",
            "region": "california",
            "country": "united states"
        }
    }
}
```

### 2. Enrich Person by Name + Company

```python
# When you don't have email, use name + context
result = pdl_enrich_person(
    first_name="John",
    last_name="Smith",
    company="Google",
    locality="Mountain View"
)
```

### 3. Search People with Advanced Queries

```python
# Find VP-level sales people at tech companies in California
result = pdl_search_people(
    query_json='''{
        "bool": {
            "must": [
                {"term": {"job_title_role": "sales"}},
                {"term": {"job_title_levels": "vp"}},
                {"term": {"job_company_industry": "computer software"}},
                {"term": {"location_region": "california"}},
                {"exists": {"field": "emails"}}
            ]
        }
    }''',
    size=50
)

# Returns:
{
    "status": 200,
    "total": 15234,
    "data": [
        {
            "id": "...",
            "full_name": "jane doe",
            "job_title": "vp of sales",
            "job_company_name": "salesforce",
            "emails": ["[email protected]"],
            ...
        },
        ...
    ],
    "scroll_token": "..." # Use for pagination
}
```

### 4. Identify Person (Multiple Matches)

```python
# When you have partial info and want ALL possible matches
result = pdl_identify_person(
    name="John Smith",
    company="Google"
)

# Returns multiple candidates with likelihood scores:
{
    "status": 200,
    "total": 3,
    "matches": [
        {
            "data": {...},
            "likelihood": 8  # 0-10 scale, 10 = most confident
        },
        {
            "data": {...},
            "likelihood": 6
        },
        {
            "data": {...},
            "likelihood": 4
        }
    ]
}
```

### 5. Bulk Enrich People

```python
# Enrich up to 100 people in one request (much faster!)
result = pdl_bulk_enrich_people(
    requests_json='''[
        {"params": {"email": "[email protected]"}},
        {"params": {"email": "[email protected]"}},
        {"params": {"first_name": "Jane", "last_name": "Doe", "company": "Acme"}}
    ]'''
)

# Returns array of results, one per input:
{
    "status": 200,
    [
        {"status": 200, "data": {...}},  # Match found
        {"status": 404},                  # No match (FREE)
        {"status": 200, "data": {...}}
    ]
}
```

### 6. Enrich Company

```python
result = pdl_enrich_company(website="peopledatalabs.com")

# Returns:
{
    "status": 200,
    "likelihood": 10,
    "data": {
        "id": "...",
        "name": "people data labs",
        "website": "peopledatalabs.com",
        "linkedin_url": "linkedin.com/company/people-data-labs",
        "industry": "computer software",
        "size": "51-200",
        "founded": 2015,
        "location": {
            "name": "san francisco, california, united states"
        },
        "description": "...",
        "tags": ["data", "api", "b2b"],
        "technologies": ["python", "aws", "react"]
    }
}
```

### 7. Search Companies

```python
# Find mid-sized SaaS companies in the Bay Area
result = pdl_search_companies(
    query_json='''{
        "bool": {
            "must": [
                {"term": {"industry": "computer software"}},
                {"range": {"size": {"gte": 50, "lte": 500}}},
                {"term": {"location.region": "california"}},
                {"match": {"tags": "saas"}}
            ]
        }
    }''',
    size=25
)
```

### 8. Clean Data Before Enrichment

```python
# Clean company name
clean = pdl_clean_company(name="Google, Inc.")
# Returns: {"name": "google"}

# Clean location
clean = pdl_clean_location(location="NYC, NY")
# Returns: {
#     "name": "new york, new york, united states",
#     "locality": "new york",
#     "region": "new york",
#     "country": "united states",
#     "continent": "north america"
# }

# Clean school
clean = pdl_clean_school(name="MIT")
# Returns: {"name": "massachusetts institute of technology"}
```

### 9. Autocomplete

```python
# Get school suggestions
result = pdl_autocomplete(
    field="school",
    text="stanf",
    size=5
)

# Returns:
{
    "status": 200,
    "data": [
        {"name": "stanford university", "count": 123456},
        {"name": "stanford graduate school of business", "count": 45678}
    ]
}
```

## Advanced Search Query Examples

### Person Search Queries

```python
# Software engineers at FAANG companies
{
    "bool": {
        "must": [
            {"term": {"job_title_role": "engineering"}},
            {"terms": {"job_company_name": ["google", "facebook", "amazon", "apple", "netflix"]}}
        ]
    }
}

# Marketing managers with MBA
{
    "bool": {
        "must": [
            {"term": {"job_title_role": "marketing"}},
            {"term": {"job_title_levels": "manager"}},
            {"term": {"education_degrees": "mba"}}
        ]
    }
}

# People with specific skills
{
    "bool": {
        "must": [
            {"term": {"skills": "machine learning"}},
            {"term": {"skills": "python"}},
            {"range": {"experience.company": {"gte": 5}}}
        ]
    }
}

# Recent job changers (started current job in last 6 months)
{
    "range": {
        "job_start_date": {
            "gte": "2024-09-01"
        }
    }
}
```

### Company Search Queries

```python
# Tech companies with 100-1000 employees
{
    "bool": {
        "must": [
            {"term": {"industry": "computer software"}},
            {"range": {"size": {"gte": 100, "lte": 1000}}}
        ]
    }
}

# Companies using specific technologies
{
    "bool": {
        "must": [
            {"term": {"tags": "saas"}},
            {"terms": {"technologies": ["kubernetes", "aws", "react"]}}
        ]
    }
}
```

## Common Query Fields

### Person Fields
- **Job**: `job_title`, `job_title_role`, `job_title_sub_role`, `job_title_levels`, `job_company_name`, `job_company_website`, `job_company_industry`, `job_start_date`
- **Location**: `location_country`, `location_region`, `location_locality`, `location_metro`
- **Education**: `education_school_name`, `education_degrees`, `education_majors`
- **Skills**: `skills`, `languages`, `interests`, `certifications`
- **Experience**: `experience.company` (years at companies), `experience.title` (years in titles)
- **Demographics**: `age`, `gender`, `birth_year`
- **Contact**: `emails`, `phone_numbers`, `linkedin_url`, `twitter_url`

### Company Fields
- **Basic**: `name`, `website`, `industry`, `tags`, `description`
- **Size**: `size` (employee count range), `founded` (year)
- **Location**: `location.country`, `location.region`, `location.locality`
- **Social**: `linkedin_url`, `twitter_url`, `facebook_url`
- **Tech**: `technologies` (tech stack)

## Elasticsearch Query Operators

- **`term`**: Exact match - `{"term": {"field": "value"}}`
- **`terms`**: Match any of multiple values - `{"terms": {"field": ["val1", "val2"]}}`
- **`match`**: Text search - `{"match": {"field": "search text"}}`
- **`range`**: Numeric/date ranges - `{"range": {"field": {"gte": 100, "lte": 500}}}`
- **`exists`**: Field has a value - `{"exists": {"field": "emails"}}`
- **`bool`**: Combine queries
  - `must`: All conditions required (AND)
  - `should`: Any condition (OR)
  - `must_not`: Exclude (NOT)

## Waterfall Enrichment Pattern

People Data Labs is perfect for waterfall enrichment - try multiple match strategies:

```python
# 1. Try email first (most accurate)
result = pdl_enrich_person(email="[email protected]")

if result.get("status") == 404:
    # 2. Try LinkedIn profile
    result = pdl_enrich_person(profile="linkedin.com/in/johndoe")

if result.get("status") == 404:
    # 3. Try name + company
    result = pdl_enrich_person(
        first_name="John",
        last_name="Doe",
        company="Acme Corp"
    )

if result.get("status") == 404:
    # 4. Use identify for multiple candidates
    result = pdl_identify_person(
        name="John Doe",
        company="Acme"
    )
```

## Best Practices

### 1. Use Bulk for Volume
- Bulk enrichment is **100x more efficient** than individual requests
- Rate limit: 1 bulk request = 1 request (not 100!)
- Use for processing large lists

### 2. Clean Before Enrichment
- Always use cleaner APIs before enrichment
- Improves match rates significantly
- Free to use (no credits)

### 3. Start Specific, Then Broaden
```python
# Good waterfall:
email → phone → LinkedIn → name+company → name only (with identify)
```

### 4. Use Search for Discovery, Enrich for Detail
- **Search**: Find people matching criteria (1 credit per result)
- **Enrich**: Get full details on known person (1 credit if match)
- Don't search if you already have identifiers

### 5. Leverage Free 404s
- No match = no credit charged
- Safe to try multiple match strategies
- Only pay for successful enrichments

### 6. Optimize Rate Limits
- Free: 100/min → Max 6,000 enrichments/hour
- Paid: 1,000/min → Max 60,000 enrichments/hour  
- Bulk: Effectively 10,000/min (10 bulk * 100 each * 1000 QPM)

## Error Handling

The API returns clear error messages:

- `200` - Success, match found (1 credit)
- `404` - No match found (FREE, 0 credits)
- `400` - Invalid parameters
- `401` - Invalid API key
- `403` - Insufficient credits
- `429` - Rate limit exceeded

All errors returned in consistent format:
```python
{
    "error": "Error message",
    "help": "Additional guidance"
}
```

## Integration with Other Tools

### With Apollo/Vibe Prospecting
```python
# 1. Find prospects with Vibe/Apollo
prospects = apollo_search_people(...)

# 2. Enrich with PDL for additional data
for prospect in prospects:
    pdl_data = pdl_enrich_person(email=prospect['email'])
    # Merge data sources
```

### With Airtable
```python
# 1. Get contacts from Airtable
records = airtable_list_records(base_id="...", table_name="Leads")

# 2. Bulk enrich with PDL
requests = [{"params": {"email": r["fields"]["Email"]}} for r in records["records"]]
enriched = pdl_bulk_enrich_people(requests_json=json.dumps(requests))

# 3. Write back to Airtable
for i, result in enumerate(enriched):
    if result.get("status") == 200:
        airtable_update_record(
            base_id="...",
            table_name="Leads",
            record_id=records["records"][i]["id"],
            fields={"LinkedIn": result["data"]["linkedin_url"], ...}
        )
```

## Support

- **Documentation**: https://docs.peopledatalabs.com/
- **Dashboard**: https://dashboard.peopledatalabs.com/
- **Support Email**: [email protected]
- **API Status**: https://status.peopledatalabs.com/

## API Reference

- **Base URL**: `https://api.peopledatalabs.com/v5`
- **Authentication**: X-Api-Key header
- **Rate Limits**: 100/min (free), 1,000/min (paid)
- **Max bulk size**: 100 records
- **Response format**: JSON