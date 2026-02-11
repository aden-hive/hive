# Recipe: Ad Campaign Monitoring

Checking daily spends on Meta/Google ads and flagging if the Cost Per Acquisition (CPA) spikes.

## Why

Ad platforms are designed to spend your money. Without daily oversight, a $50/day campaign can quietly become a $500 disaster. This agent watches your campaigns like a hawk, catching anomalies before they drain your budget and surfacing optimization opportunities you'd otherwise miss.

## What

- Monitor daily spend across all active campaigns
- Track CPA, ROAS, CTR, and conversion metrics
- Compare performance against historical benchmarks
- Identify underperforming ads and audiences
- Generate daily/weekly performance summaries

## Integrations

| Platform | Purpose |
|----------|---------|
| Meta Ads API | Facebook/Instagram campaign data |
| Google Ads API | Search/Display/YouTube campaign data |
| Google Analytics 4 | Conversion tracking and attribution |
| Google Sheets | Performance dashboards and reporting |
| Slack | Alerts and daily summaries |

## Escalation Path

| Trigger | Action |
|---------|--------|
| CPA spikes >30% above target | Alert with breakdown by ad set and pause recommendation |
| Daily budget exhausted before noon | Immediate alert — possible click fraud or viral ad |
| ROAS drops below profitability threshold | Pause campaign and notify with optimization suggestions |
| Ad rejected by platform | Alert with rejection reason and suggested fix |
| Competitor running aggressive campaign | Flag if detected through auction insights |
| Budget pacing off by >20% | Alert with projected monthly spend |
