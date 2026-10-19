from __future__ import annotations

from aden_tools.credentials.base import CredentialSpec

SIMILARWEB_CREDENTIALS = {
    "similarweb": CredentialSpec(
        env_var="SIMILARWEB_API_KEY",
        tools=[
            "similarweb_v5_traffic_and_engagement",
            "similarweb_v5_website_rank",
            "similarweb_v5_traffic_sources",
            "similarweb_v5_geography",
            "similarweb_v5_demographics",
            "similarweb_v5_company_info",
            "similarweb_v5_top_sites_by_category",
            "similarweb_v5_referrals",
            "similarweb_v5_ppc_spend",
            "similarweb_v5_geography_details",
            "similarweb_v5_similar_sites",
            "similarweb_v5_ad_networks",
            "similarweb_v5_demographics_traffic",
            "similarweb_v5_deduplicated_audience",
            "similarweb_v5_audience_interests",
            "similarweb_v5_audience_overlap",
            "similarweb_v5_technologies",
            "similarweb_v5_leading_folders",
            "similarweb_v5_popular_pages",
            "similarweb_v5_subdomains",
            "similarweb_v5_keyword_competitors",
            "similarweb_v5_keyword_opportunities",
            "similarweb_v5_serp_features",
            "similarweb_v5_organic_keywords",
            "similarweb_v5_paid_keywords",
            "similarweb_v5_serp_players",
            "similarweb_v5_social_referrals",
            "similarweb_v5_segments_list",
            "similarweb_v5_segment_analysis",
        ],
        required=True,
        help_url="https://developer.similarweb.com/",
        description="API key for SimilarWeb traffic and competitor insights.",
        direct_api_key_supported=True,
        api_key_instructions="""To get a SimilarWeb API key:
1. Go to the SimilarWeb Developer Portal (https://developer.similarweb.com/)
2. Or log into your SimilarWeb Pro account at pro.similarweb.com
3. Navigate to Account Settings > API (or Data Extraction / API section)
4. Click on "Generate API Key"
5. Copy the generated API key and securely store it in your .env file""",
        credential_id="similarweb",
        credential_key="api_key",
        health_check_endpoint="https://api.similarweb.com/v5/website-analysis/websites/traffic-and-engagement/",
    )
}
