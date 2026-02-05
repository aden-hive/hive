## Apollo.io Integration in Hive

# Overview
Apollo.io integration enables Hive agents to enrich B2B contacts and companies with real-world data such as job titles, company size, industry, and contact information.
This integration is mainly used for sales, SDR, and business research workflows where agents need accurate prospect and company intelligence.

Apollo is used as a replacement for Clearbit, which discontinued its free tier.

## Why Apollo is Used in Hive
# Hive agents often work on business workflows like:
1.Lead generation
2.Meeting preparation
3.Sales prospecting
4.Account research
# For these workflows, agents need identity and data enrichment, such as:
Who is the decision maker?
What is the company size and industry?
Is this lead relevant or not?

Apollo provides reliable B2B data through APIs, which makes it a good fit for Hive’s autonomous agents.

## Requirements & Setup
# Prerequisites
Python 3.x
An active Apollo.io account
Apollo API key
# Environment Variable
Set the API key as an environment variable:
export APOLLO_API_KEY=your_apollo_api_key
⚠️ Security Note:
The API key should never be hardcoded in the codebase or printed in logs.

## Available Apollo Tools
Hive exposes the following Apollo tools for agents:
# 1. Enrich a Person
Used to fetch detailed contact information using email or LinkedIn URL.
apollo_enrich_person(email="john@company.com")

Returns:
Full name
Job title
Email & phone
Company details
LinkedIn profile
# 2. Enrich a Company
Used to fetch firmographic details using a company domain.
apollo_enrich_company(domain="company.com")

Returns:
Company name
Industry
Employee size
Funding details
Tech stack
Headquarters location
# 3. Search People
Used to find contacts based on job titles and filters.
apollo_search_people(
    titles=["VP Sales"],
    limit=5
)
Optional filters:
Seniority
Location
Company size
Industry
Returns:
List of matching contacts with email and company info
# 4. Search Companies
Used to find companies matching specific criteria.
apollo_search_companies(
    industries=["SaaS"],
    limit=5
)
Returns:
List of companies with firmographic data
# Credit Usage & Caching
Each Apollo API request consumes 1 export credit
Credits reset monthly and do not roll over
# Why Caching Matters
To avoid wasting credits:
Cache responses for repeated requests
Reuse existing enrichment data when possible
This improves performance and reduces API costs.
# Error Handling
The integration handles Apollo-specific errors gracefully:
 401 – Invalid API key
 403 – Insufficient credits
 422 – Invalid parameters
 429 – Rate limit exceeded
Agents should handle these responses without failing the entire workflow.

# Example End-to-End Workflow (Demo Agent)
# Sales Research Agent Flow
Search decision makers at a target company
Enrich the selected contact
Enrich the company profile
Use the enriched data for outreach or meeting preparation
Example flow:
people = apollo_search_people(titles=["Head of Sales"], limit=3)
person = apollo_enrich_person(email=people[0]["email"])
company = apollo_enrich_company(domain=person["company_domain"])
This allows the agent to work with real, enriched business data.