"""Node definitions for Twitter News Digest."""

from framework.orchestrator import NodeSpec

# Node 1: Browser subagent (GCU) to fetch tweets
fetch_node = NodeSpec(
    id="fetch-tweets",
    name="Fetch Tech Tweets",
    description="Browser subagent to navigate to tech news Twitter profiles and extract latest tweets.",
    node_type="gcu",
    client_facing=False,
    max_node_visits=1,
    input_keys=["twitter_handles"],
    output_keys=["raw_tweets"],
    tools=[],  # Auto-populated with browser tools
    system_prompt="""\
You are a specialized tech news researcher.
Your task is to navigate to the provided tech Twitter profiles and extract the latest 10 tweets from each.

## Target Content
Focus on:
- Major software/AI releases
- Tech company earnings/acquisitions
- Hardware/Silicon breakthroughs

## Instructions
1. browser_start
2. For each handle:
   a. browser_open(url=f"https://x.com/{handle}")
   b. browser_wait(seconds=5)
   c. browser_snapshot
   d. Parse relevant tech news text
3. set_output("raw_tweets", consolidated_json)
""",
)

# Node 2: Process and summarize (autonomous)
process_node = NodeSpec(
    id="process-news",
    name="Process Tech News",
    description="Analyze and summarize the raw tweets into a daily tech digest.",
    node_type="event_loop",
    sub_agents=["fetch-tweets"],
    input_keys=["user_request", "feedback", "raw_tweets"],
    output_keys=["daily_digest"],
    nullable_output_keys=["feedback", "raw_tweets"],
    success_criteria="A high-quality, tech-focused news summary.",
    system_prompt="""\
You are a senior technology editor.
If "raw_tweets" is missing, call delegate_to_sub_agent(agent_id="fetch-tweets", task="Fetch tech news from @TechCrunch, @verge, @WIRED, @CNET, @engadget, @Gizmodo, @TheRegister, @ArsTechnica, @ZDNet, @venturebeat, @AndrewYNg, @ylecun, @geoffreyhinton, @goodfellow_ian, @drfeifei, @hardmaru, @tegmark, @GaryMarcus, @schmidhuberAI, @fastdotai").

Once tech tweets are available:
1. Synthesize a "Daily Tech Report" highlighting major breakthroughs.
2. Save the report using save_data(filename="daily_tech_report.txt", data=summary).
3. set_output("daily_digest", summary)
""",
    tools=["save_data", "load_data"],
)

# Node 3: Review (client-facing)
review_node = NodeSpec(
    id="review-digest",
    name="Review Digest",
    description="Present the news digest for user review and approval.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["daily_digest"],
    output_keys=["status", "feedback"],
    nullable_output_keys=["feedback"],
    success_criteria="User has reviewed the digest and provided feedback or approval.",
    system_prompt="""\
Present the daily news digest to the user.

**STEP 1 — Present (text only, NO tool calls):**
Display the summary and ask:
1. Is this summary helpful?
2. Are there specific handles or topics you'd like to focus on for tomorrow?

**STEP 2 — After user responds, call set_output:**
- set_output("status", "approved") if satisfied.
- set_output("status", "revise") and set_output("feedback", "...") if changes are needed.
""",
    tools=[],
)

__all__ = ["fetch_node", "process_node", "review_node"]
