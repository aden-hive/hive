"""Node definitions for Hacker News Briefing Agent."""

from framework.graph import NodeSpec


intake_preferences_node = NodeSpec(
    id="intake-preferences",
    name="Intake Preferences",
    description=(
        "Gather runtime preferences for briefing scope, item count, delivery channels, "
        "and timezone/time."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[],
    output_keys=["briefing_config"],
    system_prompt="""\
You are collecting user preferences for a Hacker News briefing.

**STEP 1 — Respond to the user (text only, NO tool calls):**
Ask for:
1) Story count
2) Topic bias (all vs specific themes)
3) Delivery channel preference (markdown/email/slack/all)
4) Timezone and preferred daily send time

If the user already provided any values, confirm and ask only for missing fields.

**STEP 2 — After the user responds, call set_output:**
- set_output("briefing_config", "JSON string with keys: story_count, topic_bias, channels, timezone, send_time")
""",
    tools=["get_current_time"],
)


collect_hn_candidates_node = NodeSpec(
    id="collect-hn-candidates",
    name="Collect HN Candidates",
    description=(
        "Collect top Hacker News stories by scraping listing pages and extracting "
        "candidate links and metadata."
    ),
    node_type="event_loop",
    max_node_visits=1,
    input_keys=["briefing_config"],
    output_keys=["candidate_stories", "source_notes"],
    system_prompt="""\
Collect Hacker News candidates and linked context.

Use web_scrape to fetch:
- https://news.ycombinator.com/
- https://news.ycombinator.com/newest
- optional "best" style index pages if available

Then extract candidate stories with: title, url, hn_link, points/comments if present.
Create source_notes describing scraping coverage and any failures.

Use set_output in separate turns:
- set_output("candidate_stories", "JSON array of story objects")
- set_output("source_notes", "Text summary of source coverage and fetch issues")
""",
    tools=["web_scrape"],
)


rank_and_summarize_node = NodeSpec(
    id="rank-and-summarize",
    name="Rank And Summarize",
    description=(
        "Rank candidate stories and draft concise briefing with why-it-matters notes "
        "and source links."
    ),
    node_type="event_loop",
    max_node_visits=5,
    input_keys=["candidate_stories", "source_notes", "briefing_config", "review_feedback"],
    output_keys=["briefing_draft"],
    nullable_output_keys=["review_feedback"],
    system_prompt="""\
Create the briefing draft from candidate stories.

Rules:
- Respect story_count and topic_bias from briefing_config.
- Every item must include at least one source URL.
- If review_feedback exists, revise the draft to address it.
- Keep concise: short headline + why-it-matters + links.

Call:
- set_output("briefing_draft", "Markdown briefing text with numbered items and citations")
""",
    tools=[],
)


review_briefing_node = NodeSpec(
    id="review-briefing",
    name="Review Briefing",
    description="Present draft briefing to user for approval or revision feedback.",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=5,
    input_keys=["briefing_draft"],
    output_keys=["approved_briefing", "review_feedback"],
    nullable_output_keys=["approved_briefing", "review_feedback"],
    system_prompt="""\
Show the current briefing draft to the user.

**STEP 1 — Respond to user (text only, NO tool calls):**
Present the draft clearly and ask for one of:
- approve
- revision feedback

**STEP 2 — After user responds, call set_output:**
- If approved: set_output("approved_briefing", "<final markdown>"), set_output("review_feedback", "")
- If changes requested: set_output("review_feedback", "<requested changes>"), set_output("approved_briefing", "")
""",
    tools=[],
)


deliver_briefing_node = NodeSpec(
    id="deliver-briefing",
    name="Deliver Briefing",
    description=(
        "Write approved briefing to markdown output and return delivery report. "
        "Channel preferences remain in config for later adapters."
    ),
    node_type="event_loop",
    max_node_visits=1,
    input_keys=["approved_briefing", "briefing_config"],
    output_keys=["delivery_report"],
    system_prompt="""\
Persist the approved briefing to disk using write_to_file.

Write to a deterministic path, for example:
- exports/hacker_news_briefing/output/hn_briefing_<YYYY-MM-DD>.md

Then call:
- set_output("delivery_report", "JSON string with file_path, status, and notes")
""",
    tools=["write_to_file"],
)


__all__ = [
    "intake_preferences_node",
    "collect_hn_candidates_node",
    "rank_and_summarize_node",
    "review_briefing_node",
    "deliver_briefing_node",
]
