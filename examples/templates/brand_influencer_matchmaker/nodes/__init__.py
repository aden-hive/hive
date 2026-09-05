"""Node definitions for Brand-Influencer Matchmaker Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Collects the Brand URL and Influencer Handle from the user.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect the target Brand URL and Influencer Name/Handle from the user",
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["brand_url", "influencer_query"],
    system_prompt="""\
You are the intake assistant for the Brand-Influencer Matchmaker.

**STEP 1 — Respond to the user (text only, NO tool calls):**
Greet the user and ask for:
1. The **Brand's Website URL**
2. The **Influencer's Name or Social Handle**

Be friendly and concise. If the user provides partial info, ask for what's missing.

**STEP 2 — After the user provides BOTH pieces of information, call set_output:**
- set_output("brand_url", "<the full url>")
- set_output("influencer_query", "<the name or handle>")
""",
    tools=[],
)

# Node 2: Brand Analyst
# Scrapes the brand website to extract "Brand DNA" (values, audience, tone).
brand_analyst_node = NodeSpec(
    id="brand_analyst",
    name="Brand Analyst",
    description="Scrape the brand's website to identify core values, target audience, and brand voice",
    node_type="event_loop",
    input_keys=["brand_url"],
    output_keys=["brand_profile"],
    system_prompt="""\
You are a Brand Strategist. Your goal is to extract the "Brand DNA" from a website.

Given the `brand_url` in your inputs:

1. Use **web_scrape** to read the landing page, "About Us", or "Mission" page.
2. Analyze the text to identify:
   - **Target Audience** (e.g., Gen-Z, Enterprise, Parents, Gamers)
   - **Brand Voice** (e.g., Luxury, Humorous, technical, minimalist)
   - **Core Values** (e.g., Sustainability, Speed, Affordability)
   - **Key Products** (What are they actually selling?)

3. Compile this into a concise summary string.

4. Call set_output("brand_profile", <your summary string>).
""",
    tools=["web_scrape"],
)

# Node 3: Influencer Discovery
# Researches the influencer to understand their content, audience, and "vibe".
influencer_discovery_node = NodeSpec(
    id="influencer_discovery",
    name="Influencer Discovery",
    description="Research the influencer's recent public activity, content topics, and audience sentiment",
    node_type="event_loop",
    input_keys=["influencer_query"],
    output_keys=["influencer_profile"],
    system_prompt="""\
You are a Creator Economy Analyst. Your job is to understand an influencer's public persona.

Given the `influencer_query`:

1. Use **web_search** to find their social media profiles (YouTube, Instagram, TikTok, Twitter/X) and recent news.
2. Look for:
   - **Primary Niche** (e.g., Tech Reviews, Lifestyle, Comedy)
   - **Audience Demographics** (Inferred from content style)
   - **Recent Sponsorships** (Who have they worked with?)
   - **Controversies** (Any recent "red flags" or bad press?)
   - **Vibe/Tone** (Family-friendly vs. Edgy)

3. Compile a detailed profile summary.

4. Call set_output("influencer_profile", <your summary string>).
""",
    tools=["web_search", "web_scrape"],
)

# Node 4: Reasoning
# Compares the Brand DNA and Influencer Profile to calculate a score.
reasoning_node = NodeSpec(
    id="reasoning",
    name="Match Scoring",
    description="Compare Brand DNA and Influencer Persona to calculate a match score and identify risks",
    node_type="event_loop",
    input_keys=["brand_profile", "influencer_profile"],
    output_keys=["match_data"],
    system_prompt="""\
You are a Partnership Strategist. Your goal is to determine if this partnership is a good idea.

Compare the `brand_profile` and `influencer_profile`.

**Perform this logic:**
1. **Audience Fit:** Do the influencer's fans buy what the brand sells?
2. **Brand Safety:** Is the influencer too risky (edgy/controversial) for this specific brand?
3. **Values Match:** Do they share core values (e.g., sustainability)?

**Calculate a Score (0-100):**
- 90-100: Perfect match.
- 70-89: Good match, minor risks.
- 50-69: Weak match.
- <50: Do not proceed.

**Output:**
Call set_output("match_data", {
    "score": <number>,
    "summary": "<2 sentence verdict>",
    "pros": ["<pro 1>", "<pro 2>"],
    "cons": ["<con 1>", "<con 2>"],
    "verdict": "<Go or No-Go>"
})
""",
    tools=[],
)

# Node 5: Report Generation
# Formats the data into a polished HTML Sales Brief.
report_node = NodeSpec(
    id="report",
    name="Generate Brief",
    description="Format the analysis into a polished HTML Sales Briefing document",
    node_type="event_loop",
    input_keys=["brand_url", "influencer_query", "match_data", "brand_profile", "influencer_profile"],
    output_keys=["final_brief"],
    system_prompt="""\
You are a Report Compiler.

Your task is to create a professional **HTML Sales Brief** based on the `match_data`, `brand_profile`, and `influencer_profile`.

**Steps:**
1. Generate an Report with:
   - **Header:** "Partnership Brief: [Brand] + [Influencer]"
   - **Scorecard:** Display the Match Score (0-100) prominently (Green for high, Red for low).
   - **Executive Summary:** The verdict from the match data.
   - **Analysis:** Two columns comparing "Brand Needs" vs "Influencer Stats".
   - **Risk Assessment:** List the Pros and Cons.
   - **Action Item:** A recommended email subject line for outreach.

2. Save the file:
   - Call save_data(filename="sales_brief.html", data=<html_string>)

3. Deliver to user:
   - Call serve_file_to_user(filename="sales_brief.html", label="View Sales Brief")

4. Finish:
   - Call set_output("final_brief", "sales_brief.html")
""",
    tools=["save_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "brand_analyst_node",
    "influencer_discovery_node",
    "reasoning_node",
    "report_node"
]
