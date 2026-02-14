# Brand-Influencer Matchmaker

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: 2026-02-14

## Overview

Analyze brand websites and influencer content to calculate a compatibility score and generate a strategic sales briefing document to aid partnership decisions.

## Architecture

### Execution Flow

```
intake → brand_analyst → influencer_discovery → reasoning → report
```

### Nodes (5 total)

1. **intake** (event_loop)
   - Collect the target Brand URL and the Influencer's name or social handle from the user.
   - Writes: `brand_url`, `influencer_query`
   - Client-facing: Yes (blocks for user input)
2. **brand_analyst** (event_loop)
   - Scrape the brand's website to identify core values, target audience, and brand voice.
   - Reads: `brand_url`
   - Writes: `brand_profile`
   - Tools: `web_scrape`
3. **influencer_discovery** (event_loop)
   - Research the influencer's recent public activity, content topics, and audience sentiment.
   - Reads: `influencer_query`
   - Writes: `influencer_profile`
   - Tools: `web_search, web_scrape`
4. **reasoning** (event_loop)
   - Compare Brand DNA and Influencer Persona to calculate a match score and identify risks.
   - Reads: `brand_profile`, `influencer_profile`
   - Writes: `match_data`
   - Tools: None (Pure reasoning)
5. **report** (event_loop)
   - Format the analysis into a polished HTML Sales Briefing document and deliver it to the user.
   - Reads: `match_data`, `brand_profile`, `influencer_profile`
   - Writes: `final_brief`
   - Tools: `save_data, serve_file_to_user`

### Edges (4 total)

- `intake` → `brand_analyst` (condition: on_success, priority=1)
- `brand_analyst` → `influencer_discovery` (condition: on_success, priority=1)
- `influencer_discovery` → `reasoning` (condition: on_success, priority=1)
- `reasoning` → `report` (condition: on_success, priority=1)


## Goal Criteria

### Success Criteria

**Successfully identified Brand DNA and target audience** (weight 0.2)
- Metric: Brand profile completeness
- Target: 100%
**Extracted influencer sentiment and content topics** (weight 0.2)
- Metric: Influencer profile completeness
- Target: 100%
**Calculated a logical compatibility score (0-100)** (weight 0.3)
- Metric: Score generated
- Target: true
**Generated and delivered the HTML sales brief** (weight 0.3)
- Metric: File delivered
- Target: true

### Constraints

**Never invent 'Red Flags' or controversies that do not exist** (hard)
- Category: quality
**Must cite the Brand URL in the report** (hard)
- Category: compliance

## Required Tools

- `save_data`
- `serve_file_to_user`
- `web_scrape`
- `web_search`

## Usage

### Basic Usage

```python
from framework.runner import AgentRunner

# Load the agent
runner = AgentRunner.load("examples/templates/brand_influencer_matchmaker")

# Run with input
# Note: The agent uses an interactive 'intake' node, so initial input can be empty
result = await runner.run({})

# Access results
print(result.output)
print(result.status)
```

### Input Schema

The agent's entry node `intake` is interactive and will prompt for:
- `brand_url` (string)
- `influencer_query` (string)

### Output Schema

Terminal nodes: `report`
- `final_brief`: Path to the generated HTML file.

## Version History

- **1.0.0** (2026-02-14): Initial release
  - 5 nodes, 4 edges
  - Goal: Brand-Influencer Matchmaker
```
