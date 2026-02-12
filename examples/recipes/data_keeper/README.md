# Recipe: Data Keeper

Pull data and reports from multiple data sources.

## Why

You can't steer the ship if you're the one manually copying and pasting numbers from Google Analytics into an Excel sheet. Every hour spent wrangling data is an hour not spent making decisions based on that data. This agent becomes your "Data DJ" — mixing sources, syncing sheets, and serving up the numbers you need when you need them.

## What

- Pull metrics from analytics, ads, CRM, and other platforms
- Consolidate data into unified dashboards and spreadsheets
- Generate daily/weekly/monthly reports automatically
- Track KPIs and flag anomalies or trends
- Keep data sources in sync (no more stale spreadsheets)

## Integrations

| Platform | Purpose |
|----------|---------|
| Google Analytics 4 | Website traffic and conversion data |
| Google Sheets / Excel | Report destination and dashboards |
| Meta Ads / Google Ads | Ad performance metrics |
| Stripe / QuickBooks | Revenue and financial data |
| HubSpot / Salesforce | Sales pipeline and CRM metrics |
| Slack | Report delivery and anomaly alerts |
| BigQuery / Snowflake | Data warehouse queries (if applicable) |

## Escalation Path

| Trigger | Action |
|---------|--------|
| Data source API fails or returns errors | Alert with error details and last successful sync time |
| KPI drops >20% week-over-week | Immediate alert with breakdown by segment |
| Data discrepancy between sources | Flag for investigation — which source is correct? |
| Report generation fails | Notify with error and offer manual trigger |
| Unusual spike in any metric | Alert with context — is this real or a tracking bug? |
| New data source requested | Queue for setup — may need credentials or API access |
