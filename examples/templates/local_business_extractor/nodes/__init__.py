"""Node definitions for Local Business Extractor."""

from framework.graph import NodeSpec

# GCU Subagent for Google Maps
map_search_gcu = NodeSpec(
    id="map-search-worker",
    name="Maps Browser Worker",
    description="Browser subagent that searches Google Maps and extracts business links.",
    node_type="gcu",
    client_facing=False,
    max_node_visits=1,
    input_keys=["query"],
    output_keys=["business_list"],
    tools=[],  # Auto-populated with browser tools
    system_prompt="""\
You are a browser agent. Your job: Search Google Maps for the provided query and extract business names and website URLs.

## Workflow
1. browser_start
2. browser_open(url="https://www.google.com/maps")
3. Use browser_type or browser_click to search for the "query" in memory.
4. browser_wait(seconds=3)
5. browser_snapshot to find the list of results.
6. For each relevant result, extract:
   - Name of the business
   - Website URL (look for the website icon/link)
7. set_output("business_list", [{"name": "...", "website": "..."}, ...])

## Constraints
- Extract at least 5-10 businesses if possible.
- If you see a "Website" button, extract that URL specifically.
""",
)

# Processing Node: Scrape & Prepare
extract_contacts_node = NodeSpec(
    id="extract-contacts",
    name="Extract Business Details",
    description="Scrapes business websites and Maps for comprehensive business details.",
    node_type="event_loop",
    sub_agents=["map-search-worker"],
    input_keys=["user_request"],
    output_keys=["business_data"],
    success_criteria="Comprehensive business details (reviews, hours, contacts) extracted.",
    system_prompt="""\
1. Call delegate_to_sub_agent(agent_id="map-search-worker", task=user_request)
2. Receive "business_list" from memory.
3. For each business in the list:
   - Use exa_get_contents or exa_search to find:
     - Contact emails and phone numbers.
     - Business hours.
     - Customer reviews or ratings summary.
     - Physical address.
4. Format the data into a comprehensive report for each business.
5. set_output("business_data", enriched_business_list)
""",
    tools=["exa_get_contents", "exa_search"],
)

# Google Sheets Sync Node
sheets_sync_node = NodeSpec(
    id="sheets-sync",
    name="Google Sheets Sync",
    description="Appends the extracted business data to a Google Sheets spreadsheet.",
    node_type="event_loop",
    input_keys=["business_data"],
    output_keys=["spreadsheet_id"],
    success_criteria="Data successfully synced to Google Sheets.",
    system_prompt="""\
1. Check memory for "spreadsheet_id". If not set, create a new spreadsheet:
   - Use google_sheets_create_spreadsheet(title="Comprehensive Business Leads")
   - Save the spreadsheet ID with set_output("spreadsheet_id", id)
2. If the spreadsheet is new, write header row:
   - Use google_sheets_update_values(spreadsheet_id=id, range_name="Sheet1!A1:G1", values=[["Name", "Website", "Email", "Phone", "Address", "Hours", "Reviews"]])
3. For each business in "business_data", append a row:
   - Use google_sheets_append_values(spreadsheet_id=id, range_name="Sheet1!A:G", values=[[name, website, email, phone, address, hours, reviews]])
4. set_output("spreadsheet_id", id)
""",
    tools=[
        "google_sheets_create_spreadsheet",
        "google_sheets_update_values",
        "google_sheets_append_values",
        "google_sheets_get_values",
    ],
)
