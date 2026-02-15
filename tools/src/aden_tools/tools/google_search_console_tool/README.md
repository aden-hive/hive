# Google Search Console Tool

SEO Performance, Search Queries & Indexing. Completes the marketing analytics picture by providing organic search insights.

## Features
- **Search Analytics**: Detailed performance metrics (clicks, impressions, CTR, position) with dimensions like `query`, `page`, `country`, `device`, and `date`.
- **Keyword Monitoring**: Easily retrieve top search queries driving traffic.
- **Page Analysis**: Identify your highest-performing landing pages in search.
- **Indexing Health**: (via future scope) Monitor crawl and index status.
- **Service Account Support**: Built-in support for Google Cloud service accounts.

## Configuration

Set the following environment variable or configure via the Hive Credential Store:

- `GOOGLE_APPLICATION_CREDENTIALS`: Path to your Google Cloud service account JSON key.

### Permissions Required
The service account needs **Search Console read-only access** for the properties you want to monitor.
1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a Service Account.
2. Download the JSON key.
3. Go to [Google Search Console](https://search.google.com/search-console/users) for each site.
4. Add the service account email as a **User** with **Full** or **Restricted** (read-only) permission.

## Available Tools

### `gsc_search_analytics`
Query search performance data with flexible filtering.
- `site_url` (str): Site URL (e.g., `https://example.com` or `sc-domain:example.com`).
- `start_date` (str, default="28daysAgo"): Start date.
- `end_date` (str, default="today"): End date.
- `dimensions` (list[str], optional): Dimensions to group by.
- `query_filter` (str, optional): Substring match for queries.
- `page_filter` (str, optional): Substring match for page URLs.

### `gsc_get_top_queries`
Convenience wrapper to get top 10 keywords.
- `site_url` (str): Site URL.

### `gsc_get_top_pages`
Convenience wrapper to get top 10 pages.
- `site_url` (str): Site URL.

### `gsc_list_sites`
List all Search Console properties accessible by the credentials.

## Example Workflow

### Automated SEO Report
An agent pulls top keywords and landing pages, identifies opportunities, and sends a summary via email.
```python
sites = gsc_list_sites()
for site in sites['siteEntry']:
    url = site['siteUrl']
    perf = gsc_get_top_queries(site_url=url)
    # Analyze and report...
```

### Content Gap Analysis
Identify queries with high impressions but low CTR to suggest title/meta description improvements.
```python
results = gsc_search_analytics(
    site_url="https://example.com",
    dimensions=["query"],
    limit=100
)
for row in results.get('rows', []):
    if row['impressions'] > 1000 and row['ctr'] < 0.01:
        # Suggest optimization...
```
