# Google Analytics Tool

Query GA4 website traffic and marketing performance data via the Data API v1.

## Description

Provides read-only access to Google Analytics 4 (GA4) properties. Use these tools to pull website traffic data, monitor real-time activity, and analyze marketing performance.

Supports:
- **Custom reports** with any combination of GA4 dimensions and metrics
- **Real-time data** for current website activity
- **Convenience wrappers** for common queries (top pages, traffic sources)

## Tools

### `ga_run_report`

Run a custom GA4 report with flexible dimensions, metrics, and date ranges.

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `property_id` | str | Yes | - | GA4 property ID (e.g., `"properties/123456"`) |
| `metrics` | list[str] | Yes | - | Metrics to retrieve (e.g., `["sessions", "totalUsers"]`) |
| `dimensions` | list[str] | No | `None` | Dimensions to group by (e.g., `["pagePath", "sessionSource"]`) |
| `start_date` | str | No | `"28daysAgo"` | Start date (e.g., `"2024-01-01"` or `"7daysAgo"`) |
| `end_date` | str | No | `"today"` | End date |
| `limit` | int | No | `100` | Max rows to return (1-10000) |

### `ga_get_realtime`

Get real-time analytics data (active users, current pages).

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `property_id` | str | Yes | - | GA4 property ID |
| `metrics` | list[str] | No | `["activeUsers"]` | Metrics to retrieve |

### `ga_get_top_pages`

Get top pages by views and engagement (convenience wrapper).

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `property_id` | str | Yes | - | GA4 property ID |
| `start_date` | str | No | `"28daysAgo"` | Start date |
| `end_date` | str | No | `"today"` | End date |
| `limit` | int | No | `10` | Max pages to return (1-10000) |

Returns: `pagePath`, `pageTitle`, `screenPageViews`, `averageSessionDuration`, `bounceRate`

### `ga_get_traffic_sources`

Get traffic breakdown by source/medium (convenience wrapper).

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `property_id` | str | Yes | - | GA4 property ID |
| `start_date` | str | No | `"28daysAgo"` | Start date |
| `end_date` | str | No | `"today"` | End date |
| `limit` | int | No | `10` | Max sources to return (1-10000) |

Returns: `sessionSource`, `sessionMedium`, `sessions`, `totalUsers`, `conversions`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Path to Google Cloud service account JSON key file |

## Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) > IAM & Admin > Service Accounts
2. Create a service account (e.g., "hive-analytics-reader")
3. Download the JSON key file
4. Enable the **Google Analytics Data API** in your Google Cloud project
5. In Google Analytics, go to Admin > Property > Property Access Management
6. Add the service account email with **Viewer** role
7. Set the environment variable:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
   ```

## Common GA4 Metrics

`sessions`, `totalUsers`, `newUsers`, `screenPageViews`, `conversions`, `bounceRate`, `averageSessionDuration`, `engagedSessions`

## Common GA4 Dimensions

`pagePath`, `pageTitle`, `sessionSource`, `sessionMedium`, `country`, `deviceCategory`, `date`

## Example Usage

```python
# Custom report: sessions by page over the last 7 days
result = ga_run_report(
    property_id="properties/123456",
    metrics=["sessions", "screenPageViews"],
    dimensions=["pagePath"],
    start_date="7daysAgo",
)

# Real-time active users
result = ga_get_realtime(property_id="properties/123456")

# Top 10 pages this month
result = ga_get_top_pages(
    property_id="properties/123456",
    start_date="2024-01-01",
    end_date="2024-01-31",
)

# Traffic sources breakdown
result = ga_get_traffic_sources(property_id="properties/123456")
```

## Error Handling

Returns error dicts for common issues:
- `Google Analytics credentials not configured` - No credentials set
- `property_id must start with 'properties/'` - Invalid property ID format
- `metrics list must not be empty` - No metrics provided
- `limit must be between 1 and 10000` - Limit out of bounds
- `Failed to initialize Google Analytics client` - Bad credentials file
- `Google Analytics API error: ...` - API-level errors (permissions, quota, etc.)
