# Recipe: News Jacking

Automated personalized outreach triggered by real-time company news.

## Why

Cold outreach gets ignored. But when you reference something that *just* happened to someone — a funding round, a podcast appearance, a new hire announcement — suddenly you're not a stranger, you're someone who pays attention. The problem is manually monitoring hundreds of leads for these moments is impossible. This agent does the watching so you can do the reaching.

## What

- Monitor news sources for lead companies (LinkedIn, Google News, TechCrunch, press releases)
- Detect trigger events: funding announcements, executive hires, podcast appearances, product launches, awards
- Draft hyper-personalized outreach referencing the specific event
- Queue emails for human review or auto-send based on confidence score
- Track response rates by trigger type to optimize over time

## Integrations

| Platform | Purpose |
|----------|---------|
| Google News API / NewsAPI | Monitor company mentions |
| LinkedIn Sales Navigator | Track company updates and job changes |
| Apollo / Clearbit | Enrich lead data and find contact info |
| Gmail / Outlook | Send personalized outreach |
| CRM (HubSpot, Salesforce) | Log outreach and track responses |
| Slack | Notify when high-value triggers detected |

## Escalation Path

| Trigger | Action |
|---------|--------|
| High-value lead (enterprise, known target account) | Queue for human review before sending |
| Confidence score < 80% on event details | Flag for verification — do NOT auto-send |
| Unable to verify news source | Skip outreach, log for manual review |
| Lead responds | Alert immediately, pause automation for this lead |
| Bounce or unsubscribe | Remove from automation, update CRM |
| Same lead triggered multiple times in 30 days | Consolidate into single touchpoint |

## Guardrails

This agent has high "spam potential" if not configured carefully:

| Risk | Mitigation |
|------|------------|
| Hallucinated event details | Always include source URL, verify against multiple sources |
| Tone-deaf timing (layoffs, bad news) | Filter out negative events, require human review for ambiguous |
| Over-automation feels robotic | Randomize send times, vary templates, cap frequency per lead |
| Referencing wrong person/company | Double-check entity resolution before drafting |

## Example Flow

```
1. Agent detects: "[Lead's Company] raises $5M Series A" on TechCrunch
2. Enriches: Finds CEO email via Apollo, confirms company match
3. Drafts: "Hey [Name], congrats on the Series A! Saw the TechCrunch piece
   this morning. Scaling the team post-raise is always a ride — we help
   [Company Type] with [Value Prop]..."
4. Scores: 92% confidence (verified source, exact name match)
5. Routes: Auto-queue for send at 9:15 AM recipient's timezone
6. Logs: Records in CRM with trigger type "funding_announcement"
```
