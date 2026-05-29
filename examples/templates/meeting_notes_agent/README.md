# Meeting Notes Agent

An intelligent agent that parses meeting transcripts to extract structured information: summaries, decisions, action items, blockers, and follow-ups. Optionally delivers results to Slack.

## What It Does

Given a meeting transcript, the agent:
1. **Extracts structured data**:
   - Executive summary (2-3 sentences)
   - List of attendees with roles
   - Key decisions made
   - Action items with owners, due dates, and priority levels
   - Blockers preventing progress
   - Follow-up items for future attention

2. **Reviews with you**: Presents the extracted data for your confirmation

3. **Delivers results**:
   - Saves formatted meeting notes as a markdown file
   - Optionally posts a summary to Slack

## How to Use

### Via Hive UI

1. Start the Hive server: `hive serve`
2. Open http://127.0.0.1:8787
3. Select "Meeting Notes Agent" from the sample agents
4. Click "Run" and provide your meeting transcript

### Via CLI

```bash
# Run the agent
hive run examples.templates.meeting_notes_agent

# Or with Python
python -m examples.templates.meeting_notes_agent
```

## Example Input

```
Meeting: Product Planning Q1 2024
Date: 2024-01-15

Transcript:
Sarah (PM): Let's review our Q1 priorities. We need to ship the new dashboard by end of January.
Mike (Eng): I can lead that. We're blocked on the API design though.
Sarah: OK, let's schedule an API review this week. Mike, can you draft the spec by Friday?
Mike: Yes, I'll have it ready.
Lisa (Design): I'll finalize the mockups by Wednesday to unblock Mike.
Sarah: Great. Decision: Dashboard is our top priority for Q1.
```

## Example Output

```markdown
# Product Planning Q1 2024
Date: 2024-01-15

## Executive Summary
The team reviewed Q1 priorities and decided to prioritize the new dashboard launch by end of January. Key action items were assigned to unblock development.

## Attendees
- Sarah (PM)
- Mike (Eng)
- Lisa (Design)

## Key Decisions
1. Dashboard is the top priority for Q1

## Action Items
| Task | Owner | Due | Priority |
|------|-------|-----|----------|
| Draft API spec | Mike | Friday | high |
| Finalize mockups | Lisa | Wednesday | high |
| Schedule API review | Sarah | This week | medium |

## Blockers
1. API design is blocking dashboard development

## Follow-ups
- None
```

## Features

- **Accurate extraction**: Only extracts information explicitly stated in the transcript
- **Priority assignment**: Automatically assigns priority based on urgency cues
- **User review**: Presents extracted data for confirmation before delivery
- **Slack integration**: Optionally posts results to a Slack channel
- **Markdown export**: Saves formatted notes as a downloadable file

## Configuration

The agent uses the following optional inputs:
- `meeting_name`: Title of the meeting (default: "Meeting")
- `meeting_date`: Date in any format (default: empty)
- `slack_channel`: Slack channel ID or name to post results (default: none)

## Requirements

- **Tools**: `save_data`, `serve_file_to_user`, `slack_post_message` (optional)
- **LLM**: Works with any configured LLM provider (Claude, Gemini, etc.)

## Graph Structure

```
intake → extract → review → deliver
```

1. **Intake**: Receives transcript and metadata
2. **Extract**: Parses transcript and extracts structured data
3. **Review**: Presents data to user for confirmation
4. **Deliver**: Saves notes and optionally posts to Slack

## Tips

- Provide clear, complete transcripts for best results
- Include speaker names and roles when possible
- Use urgency keywords (urgent, ASAP, critical) for high-priority items
- Specify due dates explicitly (e.g., "by Friday", "next week")

## Limitations

- Only extracts information explicitly stated in the transcript
- Cannot infer unstated action items or decisions
- Requires speaker names to be mentioned for action item assignment
- Slack posting requires Slack credentials to be configured
