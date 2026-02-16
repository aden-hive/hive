"""Node definitions for RSS-to-Twitter Agent."""

from framework.graph import NodeSpec

# Node 1: Fetch
# Fetches and parses RSS feeds, extracts article metadata.
fetch_node = NodeSpec(
    id="fetch",
    name="Fetch RSS",
    description="Fetch and parse RSS feeds, extract article titles, links, and summaries",
    node_type="event_loop",
    client_facing=False,
    input_keys=[],
    output_keys=["articles_json"],
    system_prompt="""\
You are an RSS feed fetcher. Your job is to retrieve and parse articles from RSS feeds.

**At the very start of every run, before calling any tools:** Output a short introduction (plain text) that:
1. Explains what this agent does: it repurposes content from RSS feeds into Twitter/X threads.
2. Lists the RSS feeds you are currently monitoring, with their URLs (see the list below).

Then proceed to fetch and parse those feeds.

Fetch articles from these RSS feeds:
1. https://news.ycombinator.com/rss
2. https://techcrunch.com/feed/

For each feed:
1. Use web_scrape to fetch the RSS feed URL.
2. Extract up to 5 articles per feed, capturing:
   - title
   - link
   - summary (first 200 characters if available)
   - source (the feed's title)

Compile all articles into a JSON array and call:
- set_output("articles_json", <JSON string of articles array>)

Each article object should have keys: "title", "link", "summary", "source".

Do NOT return raw text. Use the set_output tool to produce outputs.
""",
    tools=["web_scrape"],
)

# Node 2: Process
# Extracts key points from fetched articles for thread generation.
process_node = NodeSpec(
    id="process",
    name="Process Content",
    description="Extract key points and metadata from fetched articles for thread generation",
    node_type="event_loop",
    client_facing=False,
    input_keys=["articles_json"],
    output_keys=["processed_json"],
    system_prompt="""\
You are a content processor. Your job is to analyze articles and extract key points for Twitter threads.

You will receive a JSON array of articles in your inputs. For each article, extract:
1. The article title
2. The article URL
3. The source name
4. 2-3 key points summarizing the most interesting or notable aspects

Produce a JSON array of processed articles, where each object has:
- "title": the article title
- "url": the article link
- "source": the source name
- "key_points": array of key point strings

Limit output to at most 3 processed articles (the most interesting ones).

Call set_output("processed_json", <JSON string of processed articles array>).

Do NOT return raw text. Use the set_output tool to produce outputs.
""",
    tools=[],
)

# Node 3: Generate (client-facing)
# Generates Twitter threads from processed content and presents to user.
generate_node = NodeSpec(
    id="generate",
    name="Generate Threads",
    description="Generate engaging Twitter threads from processed articles and present to user for review",
    node_type="event_loop",
    client_facing=True,
    input_keys=["processed_json"],
    output_keys=["threads_json"],
    system_prompt="""\
You are a Twitter thread generator. Your job is to create engaging Twitter threads from processed articles.

You will receive a JSON array of processed articles in your inputs. For each article, generate a Twitter thread:

1. **Hook tweet**: Start with 🚀 and the article title, ending with "Thread 🧵👇"
2. **Key point tweets**: Number each key point (1/, 2/, etc.)
3. **CTA tweet**: End with 🔗 the article URL and "Follow for more!"

Use a professional tone. Keep each tweet concise and engaging.

**STEP 1 — Present the generated threads to the user (text only, NO tool calls):**
Format each thread clearly with the article title as a header, then show all tweets in the thread.
Ask: "Would you like any changes to these threads, or shall I finalize them?"

If the user requests changes, revise and present again.

**STEP 2 — After user approves, call set_output then post_to_twitter:**
- set_output("threads_json", <JSON string of threads array>)
- Call post_to_twitter(threads_json=<the same JSON string>). In live mode the tool posts to Twitter/X; in draft mode it simply confirms. The tool handles missing credentials by falling back to draft and notifying the user.

Each thread object should have: "article_title", "source", "thread" (array of tweet strings), "tweet_count".
""",
    tools=["post_to_twitter"],
)

__all__ = [
    "fetch_node",
    "process_node",
    "generate_node",
]
