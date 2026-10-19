# SimilarWeb Tool

Integration with SimilarWeb for deep website analytics, competitor intelligence, market research data, traffic sources, and audience demographics.

## Overview

This tool enables Hive agents to interact with SimilarWeb's data intelligence infrastructure for:

- Website traffic analysis and engagement metrics
- Competitor research and benchmarking
- SEO and keyword analysis
- Advertising strategy and PPC spend insights
- Audience demographics and geographic distribution
- Technical profile and company insights

## Available Tools

This integration provides the following MCP tools for comprehensive market intelligence operations:

**Website Overview & Traffic**

- `similarweb_v5_traffic_and_engagement` - Get traffic and engagement metrics (visits, duration, pages per visit, bounce rate)
- `similarweb_v5_traffic_sources` - Get marketing channels (traffic sources) breakdown
- `similarweb_v5_geography` - Get traffic distribution by geography
- `similarweb_v5_geography_details` - Get detailed traffic distribution by country
- `similarweb_v5_website_rank` - Get global, country, and category ranks for a website

**Competitor Intelligence**

- `similarweb_v5_similar_sites` - Get a list of websites similar to the given domain
- `similarweb_v5_top_sites_by_category` - Get top sites in a specific category (e.g., 'Games', 'Lifestyle')
- `similarweb_v5_company_info` - Get company information (HQ, industry, etc.) for a website domain
- `similarweb_v5_technologies` - Get technologies used on the website (CMS, Ads, Analytics, etc.)

**Marketing Channels & Referrals**

- `similarweb_v5_referrals` - Get detailed referral traffic sources for a domain
- `similarweb_v5_social_referrals` - Get traffic distribution from social networks
- `similarweb_v5_ppc_spend` - Get estimated PPC spend for a website domain
- `similarweb_v5_ad_networks` - Get performance data across different ad networks

**Keywords & Search**

- `similarweb_v5_keyword_competitors` - Get organic and paid keyword competitors
- `similarweb_v5_keyword_opportunities` - Get keyword gap analysis and opportunities
- `similarweb_v5_organic_keywords` - Get detailed organic keyword performance
- `similarweb_v5_paid_keywords` - Get detailed paid keyword performance
- `similarweb_v5_serp_features` - Get SERP features analysis
- `similarweb_v5_serp_players` - Get top websites driving search traffic for keywords

**Website Content & Structure**

- `similarweb_v5_leading_folders` - Get top sub-folders by traffic
- `similarweb_v5_popular_pages` - Get most visited pages
- `similarweb_v5_subdomains` - Get traffic breakdown by subdomain

**Audience & Segments**

- `similarweb_v5_demographics` - Get audience demographics (age and gender)
- `similarweb_v5_demographics_traffic` - Get traffic breakdown by audience demographic segments
- `similarweb_v5_deduplicated_audience` - Get unique visitor count across multiple domains
- `similarweb_v5_audience_interests` - Get interests and categories relevant to the website's audience
- `similarweb_v5_audience_overlap` - Get shared audience between the main domain and a comparison domain
- `similarweb_v5_segments_list` - List custom segments available for the domain
- `similarweb_v5_segment_analysis` - Get traffic and engagement for a specific segment ID

## Setup

### 1. Get SimilarWeb API Credentials

1. Go to the [SimilarWeb Developer Portal](https://developer.similarweb.com/)
2. Log into your SimilarWeb Pro account at `pro.similarweb.com`
3. Navigate to **Account Settings** -> **API** (or Data Extraction / API section)
4. Click on **Generate API Key**
5. Copy the generated API key.

### 2. Configure Environment Variables

```bash
export SIMILARWEB_API_KEY="your_api_key_here"
```

## Usage

Here are usage examples for the available MCP tools:

### Website Overview & Traffic

```python
similarweb_v5_traffic_and_engagement(domain="example.com", country="world", granularity="monthly")
similarweb_v5_traffic_sources(domain="example.com", country="world")
similarweb_v5_geography(domain="example.com")
similarweb_v5_geography_details(domain="example.com")
similarweb_v5_website_rank(domain="example.com")
```

### Competitor Intelligence

```python
similarweb_v5_similar_sites(domain="example.com")
similarweb_v5_top_sites_by_category(category="Games", country="world")
similarweb_v5_company_info(domain="example.com")
similarweb_v5_technologies(domain="example.com")
```

### Marketing Channels & Referrals

```python
similarweb_v5_referrals(domain="example.com", country="world")
similarweb_v5_social_referrals(domain="example.com", country="world")
similarweb_v5_ppc_spend(domain="example.com", country="world")
similarweb_v5_ad_networks(domain="example.com", country="world")
```

### Keywords & Search

```python
similarweb_v5_keyword_competitors(domain="example.com")
similarweb_v5_keyword_opportunities(domain="example.com")
similarweb_v5_organic_keywords(domain="example.com", country="world")
similarweb_v5_paid_keywords(domain="example.com", country="world")
similarweb_v5_serp_features(domain="example.com")
similarweb_v5_serp_players(domain="example.com")
```

### Website Content & Structure

```python
similarweb_v5_leading_folders(domain="example.com", country="world")
similarweb_v5_popular_pages(domain="example.com", country="world")
similarweb_v5_subdomains(domain="example.com", country="world")
```

### Audience & Segments

```python
similarweb_v5_demographics(domain="example.com")
similarweb_v5_demographics_traffic(domain="example.com")
similarweb_v5_deduplicated_audience(domains="example.com,competitor.com", country="world")
similarweb_v5_audience_interests(domain="example.com")
similarweb_v5_audience_overlap(domain="example.com", compare_to="competitor.com")
similarweb_v5_segments_list(domain="example.com")
similarweb_v5_segment_analysis(segment_id="12345", country="world")
```

## Authentication

The tool passes your `SIMILARWEB_API_KEY` to the API calls via the `api-key` HTTP header during communication with the endpoints hosted under `https://api.similarweb.com`. The framework's credential adapter intercepts the secret parameter injected into your workspace securely.

## Error Handling

The API responses gracefully return API errors inside regular Python dictionaries with a detailed message (e.g. `{"error": "HTTP error 403: ..."}`).
