"""Node definitions for Twitter Outreach Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Collect the target Twitter handle, outreach purpose, and recipient email.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect the target Twitter handle, outreach purpose, and recipient email from the user",
    node_type="event_loop",
    client_facing=True,
    input_keys=[],
    output_keys=["twitter_handle", "outreach_context", "recipient_email"],
    system_prompt="""\
You are the intake assistant for a personalized Twitter outreach agent.

**STEP 1 — Respond to the user (text only, NO tool calls):**
Greet the user and ask them to provide:
1. The Twitter/X handle of the person they want to reach out to
2. The purpose/context of the outreach (e.g., partnership opportunity, hiring, collaboration, introduction)
3. The recipient's email address

Be friendly and concise. If the user provides partial info, ask for what's missing.

**STEP 2 — After the user provides ALL three pieces of information, call set_output:**
- set_output("twitter_handle", "<the Twitter handle, including @>")
- set_output("outreach_context", "<the outreach purpose/context>")
- set_output("recipient_email", "<the email address>")
""",
    tools=[],
)

# Node 2: Research
# Searches the web and scrapes the target's Twitter/X profile to build a comprehensive summary.
research_node = NodeSpec(
    id="research",
    name="Research",
    description="Research the target's Twitter/X profile — bio, recent tweets, interests, and topics they engage with",
    node_type="event_loop",
    input_keys=["twitter_handle"],
    output_keys=["profile_summary"],
    system_prompt="""\
You are a Twitter/X profile researcher. Your job is to thoroughly research a person's public Twitter/X presence.

Given the Twitter handle provided in your inputs, do the following:

1. Use web_search to find their Twitter/X profile and any relevant public information about them.
2. Use web_scrape to read their Twitter/X profile page (try https://x.com/{handle} or https://twitter.com/{handle}).
3. Extract and analyze:
   - Their bio and self-description
   - Recent tweets and topics they post about
   - Professional interests, projects, or accomplishments
   - Any recurring themes or passions
   - Specific tweets worth referencing in outreach
4. Look for additional context (personal website, blog, other social profiles mentioned in bio).

Compile a comprehensive profile summary that would help someone write a highly personalized outreach email.

Use set_output("profile_summary", <your detailed summary as a string>) to store your findings.

Do NOT return raw JSON. Use the set_output tool to produce outputs.
""",
    tools=["web_search", "web_scrape"],
)

# Node 3: Draft & Review (client-facing)
# Drafts a personalized email, presents to user, iterates until approved.
draft_review_node = NodeSpec(
    id="draft-review",
    name="Draft & Review",
    description="Draft a personalized outreach email using profile research, present to user for review, and iterate until approved",
    node_type="event_loop",
    client_facing=True,
    input_keys=["outreach_context", "recipient_email", "profile_summary"],
    output_keys=["approved_email"],
    system_prompt="""\
You are an expert email copywriter specializing in personalized outreach.

You have been given:
- A profile summary of the target person (from their Twitter/X)
- The outreach context/purpose
- The recipient's email address

**STEP 1 — Draft and present the email (text only, NO tool calls):**

Using the profile research, draft a personalized outreach email that:
- References at least 2 specific details from their Twitter profile (tweets, interests, projects)
- Clearly connects to the outreach purpose
- Includes a specific, relevant call to action
- Is professional but conversational and authentic — NOT spammy, robotic, or overly formal
- Is concise (under 300 words)

Present the complete email draft to the user, formatted clearly with Subject line and Body.
Then ask: "Would you like any changes, or shall I send this?"

If the user requests changes, revise the email and present the updated version. Keep iterating until the user is satisfied.

**STEP 2 — After the user explicitly approves the email, call set_output:**
- set_output("approved_email", "<the final approved email text including subject line>")
""",
    tools=[],
)

# Node 4: Send
# Sends the approved email using the send_email tool.
send_node = NodeSpec(
    id="send",
    name="Send",
    description="Send the approved outreach email to the recipient",
    node_type="event_loop",
    input_keys=["approved_email", "recipient_email"],
    output_keys=["delivery_status"],
    system_prompt="""\
You are responsible for sending the approved outreach email.

You have the approved email text and the recipient's email address in your inputs.

Parse the subject line and body from the approved_email, then use the send_email tool to send it to the recipient_email address.

After sending successfully, call:
- set_output("delivery_status", "sent")

If there is an error sending, call:
- set_output("delivery_status", "failed: <error details>")

Do NOT return raw JSON. Use the set_output tool to produce outputs.
""",
    tools=["send_email"],
)

__all__ = [
    "intake_node",
    "research_node",
    "draft_review_node",
    "send_node",
]
