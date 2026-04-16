# SimilarWeb Tool

Integration with SimilarWeb for deep website analytics, competitor intelligence, market research data, traffic sources, e-commerce conversion, and audience demographics.

## Overview

This tool enables Hive agents to interact with SimilarWeb's data intelligence infrastructure for:

- Website traffic analysis and engagement metrics
- Competitor research and benchmarking
- SEO and keyword analysis
- Advertising strategy and PPC spend insights
- Mobile app performance and retention
- Audience demographics and geographic distribution
- Conversion rate optimization
- Technical profile and company insights

## Available Tools

This integration provides over 80 MCP tools for comprehensive market intelligence operations:

**Website Overview & Traffic**

- `similarweb_get_website_overview` - Get total traffic, bounce rate, global/country ranking for a domain
- `similarweb_get_pages_per_visit` - Get average pages per visit
- `similarweb_get_average_visit_duration` - Get average visit duration
- `similarweb_get_bounce_rate` - Get bounce rate metrics
- `similarweb_get_page_views` - Get total page views
- `similarweb_get_desktop_vs_mobile` - Get desktop vs mobile traffic split
- `similarweb_get_global_rank` - Get the global rank for a website
- `similarweb_get_country_rank` - Get the country rank for a website
- `similarweb_get_industry_rank` - Get the industry rank for a website
- `similarweb_get_geography` - Get traffic distribution by geography
- `similarweb_get_subdomain_traffic` - Get traffic breakdown by subdomain
- `similarweb_get_top_pages` - Get the most popular pages on a website
- `similarweb_get_popular_pages` - Get popular pages metrics
- `similarweb_get_website_description` - Get domain description and details
- `similarweb_get_folders` - Get traffic metrics by folder structure
- `similarweb_get_api_lite` - Get lite website metrics via the API

**Competitor Intelligence**

- `similarweb_get_similar_competitors` - Find a list of similar websites or competitors
- `similarweb_get_top_similar_rank` - Get top similar sites by ranking
- `similarweb_get_category_leaders` - Find leaders within a specific category
- `similarweb_get_top_sites_total` - Discover top sites overall
- `similarweb_get_top_sites_desktop` - Discover top sites on desktop
- `similarweb_get_top_sites_mobile` - Discover top sites on mobile

**Marketing Channels & Traffic Sources**

- `similarweb_get_traffic_sources` - Break down direct, social, organic, and paid traffic
- `similarweb_get_social_media_traffic` - Analyze social media traffic sources
- `similarweb_get_referring_websites` - Get top referring websites
- `similarweb_get_top_outgoing_links` - Extract top outgoing links
- `similarweb_get_display_ads_publishers` - Find display ad publishers
- `similarweb_get_ad_creatives` - Review top ad creatives
- `similarweb_get_paid_search_competitors` - Identify and analyze paid search competitors
- `similarweb_get_cross_browsing_behavior` - Analyze cross-browsing behavior
- `similarweb_get_all_traffic_ppc_spend` - Get total PPC spend across channels

**Keywords & Search**

- `similarweb_get_top_keywords` - Identify top search keywords driving traffic
- `similarweb_get_keyword_analysis` - Get keyword metrics like Search Volume, CPC, and Keyword Difficulty
- `similarweb_get_keyword_competitors` - Find domains dominating a specific keyword in organic and paid search
- `similarweb_get_rank_tracking_campaigns` - Access rank tracking campaign data
- `similarweb_get_rank_tracking_position_trend` - View rank tracking position trends
- `similarweb_get_rank_tracking_snapshot` - Get a rank tracking snapshot
- `similarweb_get_rank_tracker_describe` - Describe rank tracker details

**Audience & Demographics**

- `similarweb_get_audience_geography` - Get traffic distribution by country
- `similarweb_get_deduplicated_audience` - Get deduplicated audience metrics
- `similarweb_get_audience_interests` - Analyze general audience interests
- `similarweb_get_audience_demographics_groups` - View audience demographic groups
- `similarweb_get_audience_demographics_age` - Get audience age distribution
- `similarweb_get_audience_demographics_gender` - Get audience gender distribution
- `similarweb_get_audience_interests_all` - Get complete audience interests
- `similarweb_get_audience_interests_desktop` - Get audience desktop interests
- `similarweb_get_audience_interests_mobile` - Get audience mobile interests
- `similarweb_get_audience_overlap_desktop` - Analyze desktop audience overlap
- `similarweb_get_audience_new_vs_returning` - Compare new vs returning audience

**Segments & Conversion**

- `similarweb_get_conversion_rate` - Get e-commerce conversion rate
- `similarweb_get_conversion_segments` - Get segment conversion analysis
- `similarweb_get_conversion_analysis_desktop` - Get desktop conversion metrics
- `similarweb_get_custom_segments` - Analyze custom traffic segments
- `similarweb_get_predefined_segments` - Analyze predefined traffic segments
- `similarweb_get_segment_traffic_total` - View total segment traffic
- `similarweb_get_segment_traffic_desktop` - View desktop segment traffic
- `similarweb_get_segment_marketing_channels_desktop` - Segment channels on desktop
- `similarweb_get_segment_marketing_channels_all` - Segment marketing channels

**App Intelligence**

- `similarweb_get_app_overview` - View general app overview metrics
- `similarweb_get_app_ranking` - View app store category ranking
- `similarweb_get_app_engagement` - View app engagement numbers
- `similarweb_get_app_dau_mau` - Get Daily/Monthly Active Users
- `similarweb_get_app_retention` - Get app retention rate metrics
- `similarweb_get_app_session_details` - Get app usage time and session details

**Company Intel & Technologies**

- `similarweb_get_company_info` - Access company firmographics
- `similarweb_get_list_companies` - List companies in analysis
- `similarweb_get_company_analysis_total` - Total analysis for a company
- `similarweb_get_company_analysis_desktop` - Desktop company analysis
- `similarweb_get_company_analysis_mobile` - Mobile company analysis
- `similarweb_get_technologies` - See tracking & tech stack usage
- `similarweb_get_website_technologies` - Get website technology metrics

**Desktop Metrics**

- `similarweb_get_desktop_visits`
- `similarweb_get_desktop_pages_per_visit`
- `similarweb_get_desktop_average_visit_duration`
- `similarweb_get_desktop_bounce_rate`
- `similarweb_get_desktop_pageviews`
- `similarweb_get_desktop_unique_visitors`
- `similarweb_get_desktop_geography`
- `similarweb_get_desktop_visits_by_channel`
- `similarweb_get_desktop_pages_per_visit_by_channel`
- `similarweb_get_desktop_average_visit_duration_by_channel`
- `similarweb_get_desktop_bounce_rate_by_channel`
- `similarweb_get_desktop_referrals`
- `similarweb_get_desktop_social_referrals`
- `similarweb_get_desktop_ad_networks`
- `similarweb_get_desktop_display_publishers`
- `similarweb_get_desktop_publishers_per_ad_network`
- `similarweb_get_desktop_organic_keyword_competitors`
- `similarweb_get_desktop_paid_keyword_competitors`
- `similarweb_get_desktop_organic_outgoing_links`
- `similarweb_get_desktop_outgoing_ads_networks`
- `similarweb_get_desktop_outgoing_ads_advertisers`
- `similarweb_get_desktop_traffic_sources_by_channel`
- `similarweb_get_desktop_ppc_spend`
- `similarweb_get_subdomains_desktop`

**Mobile Web Metrics**

- `similarweb_get_mobile_traffic_sources_by_channel`
- `similarweb_get_mobile_referrals`
- `similarweb_get_mobile_outgoing_referrals`
- `similarweb_get_mobile_organic_keyword_competitors`
- `similarweb_get_mobile_paid_keyword_competitors`
- `similarweb_get_subdomains_mobile`

**Account & Utilities**

- `similarweb_get_device_split` - Check traffic divided by device
- `similarweb_get_batch_describe_tables` - Describe Data Tables structure
- `similarweb_get_test_webhooks` - Trigger webhook testing
- `similarweb_get_remaining_credits` - View remaining API credits globally
- `similarweb_get_remaining_user_credits` - View remaining user credits

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

Here are usage examples for all available MCP tools:

### Website Overview & Traffic

```python
similarweb_get_website_overview(domain="example.com", country="us", start_date="2023-01", end_date="2023-12")
similarweb_get_pages_per_visit(domain="example.com")
similarweb_get_average_visit_duration(domain="example.com")
similarweb_get_bounce_rate(domain="example.com")
similarweb_get_page_views(domain="example.com")
similarweb_get_desktop_vs_mobile(domain="example.com")
similarweb_get_global_rank(domain="example.com")
similarweb_get_country_rank(domain="example.com", country="us")
similarweb_get_industry_rank(domain="example.com")
similarweb_get_geography(domain="example.com")
similarweb_get_subdomain_traffic(domain="example.com")
similarweb_get_top_pages(domain="example.com")
similarweb_get_popular_pages(domain="example.com")
similarweb_get_website_description(domain="example.com")
similarweb_get_folders(domain="example.com")
similarweb_get_api_lite(domain="example.com")
```

### Competitor Intelligence

```python
similarweb_get_similar_competitors(domain="example.com", limit=5)
similarweb_get_top_similar_rank(domain="example.com")
similarweb_get_category_leaders(category="Arts_and_Entertainment")
similarweb_get_top_sites_total()
similarweb_get_top_sites_desktop()
similarweb_get_top_sites_mobile()
```

### Marketing Channels & Traffic Sources

```python
similarweb_get_traffic_sources(domain="example.com")
similarweb_get_social_media_traffic(domain="example.com")
similarweb_get_referring_websites(domain="example.com")
similarweb_get_top_outgoing_links(domain="example.com")
similarweb_get_display_ads_publishers(domain="example.com")
similarweb_get_ad_creatives(domain="example.com")
similarweb_get_paid_search_competitors(domain="example.com")
similarweb_get_cross_browsing_behavior(domain="example.com", competitors="competitor.com")
similarweb_get_all_traffic_ppc_spend(domain="example.com")
```

### Keywords & Search

```python
similarweb_get_top_keywords(domain="example.com")
similarweb_get_keyword_analysis(keyword="buy shoes", country="us")
similarweb_get_keyword_competitors(keyword="buy shoes", limit=10)
similarweb_get_rank_tracking_campaigns()
similarweb_get_rank_tracking_position_trend(campaign_id="12345")
similarweb_get_rank_tracking_snapshot(campaign_id="12345")
similarweb_get_rank_tracker_describe()
```

### Audience & Demographics

```python
similarweb_get_audience_geography(domain="example.com")
similarweb_get_deduplicated_audience(domain="example.com")
similarweb_get_audience_interests(domain="example.com")
similarweb_get_audience_demographics_groups(domain="example.com")
similarweb_get_audience_demographics_age(domain="example.com")
similarweb_get_audience_demographics_gender(domain="example.com")
similarweb_get_audience_interests_all(domain="example.com")
similarweb_get_audience_interests_desktop(domain="example.com")
similarweb_get_audience_interests_mobile(domain="example.com")
similarweb_get_audience_overlap_desktop(domain="example.com", competitors=["competitor.com"])
similarweb_get_audience_new_vs_returning(domain="example.com")
```

### Segments & Conversion

```python
similarweb_get_conversion_rate(domain="example.com")
similarweb_get_conversion_segments(domain="example.com")
similarweb_get_conversion_analysis_desktop(domain="example.com")
similarweb_get_custom_segments()
similarweb_get_predefined_segments()
similarweb_get_segment_traffic_total(segment_id="123")
similarweb_get_segment_traffic_desktop(segment_id="123")
similarweb_get_segment_marketing_channels_desktop(segment_id="123")
similarweb_get_segment_marketing_channels_all(segment_id="123")
```

### App Intelligence

```python
similarweb_get_app_overview(app_id="com.whatsapp", store="google")
similarweb_get_app_ranking(app_id="com.whatsapp", store="google", category="Communication")
similarweb_get_app_engagement(app_id="com.whatsapp", store="google")
similarweb_get_app_dau_mau(app_id="com.whatsapp", store="google")
similarweb_get_app_retention(app_id="com.whatsapp", store="google")
similarweb_get_app_session_details(app_id="com.whatsapp", store="google")
```

### Company Intel & Technologies

```python
similarweb_get_company_info(domain="example.com")
similarweb_get_list_companies()
similarweb_get_company_analysis_total(company_id="123")
similarweb_get_company_analysis_desktop(company_id="123")
similarweb_get_company_analysis_mobile(company_id="123")
similarweb_get_technologies(domain="example.com")
similarweb_get_website_technologies(domain="example.com")
```

### Desktop Metrics Deep Dive

```python
similarweb_get_desktop_visits(domain="example.com")
similarweb_get_desktop_pages_per_visit(domain="example.com")
similarweb_get_desktop_average_visit_duration(domain="example.com")
similarweb_get_desktop_bounce_rate(domain="example.com")
similarweb_get_desktop_pageviews(domain="example.com")
similarweb_get_desktop_unique_visitors(domain="example.com")
similarweb_get_desktop_geography(domain="example.com")
similarweb_get_desktop_visits_by_channel(domain="example.com")
similarweb_get_desktop_pages_per_visit_by_channel(domain="example.com")
similarweb_get_desktop_average_visit_duration_by_channel(domain="example.com")
similarweb_get_desktop_bounce_rate_by_channel(domain="example.com")
similarweb_get_desktop_referrals(domain="example.com")
similarweb_get_desktop_social_referrals(domain="example.com")
similarweb_get_desktop_ad_networks(domain="example.com")
similarweb_get_desktop_display_publishers(domain="example.com")
similarweb_get_desktop_publishers_per_ad_network(domain="example.com")
similarweb_get_desktop_organic_keyword_competitors(domain="example.com")
similarweb_get_desktop_paid_keyword_competitors(domain="example.com")
similarweb_get_desktop_organic_outgoing_links(domain="example.com")
similarweb_get_desktop_outgoing_ads_networks(domain="example.com")
similarweb_get_desktop_outgoing_ads_advertisers(domain="example.com")
similarweb_get_desktop_traffic_sources_by_channel(domain="example.com")
similarweb_get_desktop_ppc_spend(domain="example.com")
similarweb_get_subdomains_desktop(domain="example.com")
```

### Mobile Web Metrics

```python
similarweb_get_mobile_traffic_sources_by_channel(domain="example.com")
similarweb_get_mobile_referrals(domain="example.com")
similarweb_get_mobile_outgoing_referrals(domain="example.com")
similarweb_get_mobile_organic_keyword_competitors(domain="example.com")
similarweb_get_mobile_paid_keyword_competitors(domain="example.com")
similarweb_get_subdomains_mobile(domain="example.com")
```

### Account Details & Utilities

```python
similarweb_get_device_split(domain="example.com")
similarweb_get_batch_describe_tables()
similarweb_get_test_webhooks()
similarweb_get_remaining_credits()
similarweb_get_remaining_user_credits()
```

## Authentication

The tool passes your `SIMILARWEB_API_KEY` to the API calls as a query parameter (or header) during communication with the endpoints hosted under `https://api.similarweb.com`. The framework's credential adapter intercepts the secret parameter injected into your workspace securely.

## Error Handling

The API responses gracefully return API errors inside regular Python exceptions and dictionaries with a detailed message. In instance of incorrect authentication, `api_key is invalid` responses are raised and can be dealt with smoothly via MCP format outputs.
