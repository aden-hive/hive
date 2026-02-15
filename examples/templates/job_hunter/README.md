# Job Hunter

**Version**: 1.0.0
**Type**: Multi-node agent
**Created**: 2026-02-13

## Overview

Analyze a user's resume to identify their strongest role fits, find 10 matching job opportunities, let the user select which to pursue, then generate a resume customization list and cold outreach email for each selected job.

## Architecture

### Execution Flow

```
intake → job-search → job-review → customize
```

### Nodes (4 total)

1. **intake** (event_loop)
   - Collect resume from user, analyze skills and experience, identify 2-3 strongest role types
   - Writes: `resume_text, role_analysis`
   - Client-facing: Yes (blocks for user input)
2. **job-review** (event_loop)
   - Present all 10 jobs to the user, let them select which to pursue
   - Reads: `job_listings, resume_text`
   - Writes: `selected_jobs`
   - Client-facing: Yes (blocks for user input)
3. **customize** (event_loop)
   - For each selected job, generate resume customization list and cold outreach email
   - Reads: `selected_jobs, resume_text`
   - Writes: `application_materials`
   - Tools: `save_data`
   - Client-facing: Yes (blocks for user input)
4. **job-search** (event_loop)
   - Search for 10 jobs matching identified roles and scrape job posting details
   - Reads: `role_analysis`
   - Writes: `job_listings`
   - Tools: `web_search, web_scrape`

### Edges (3 total)

- `intake` → `job-search` (condition: on_success, priority=1)
- `job-search` → `job-review` (condition: on_success, priority=1)
- `job-review` → `customize` (condition: on_success, priority=1)


## Goal Criteria

### Success Criteria

**Identifies 2-3 role types that genuinely match the user's experience** (weight 0.2)
- Metric: role_match_accuracy
- Target: >=0.8
**Found jobs align with identified roles and user's background** (weight 0.2)
- Metric: job_relevance_score
- Target: >=0.8
**Resume changes are specific, actionable, and tailored to each job posting** (weight 0.25)
- Metric: customization_specificity
- Target: >=0.85
**Cold emails are personalized, professional, and reference specific company/role details** (weight 0.2)
- Metric: email_personalization_score
- Target: >=0.85
**User approves outputs without major revisions needed** (weight 0.15)
- Metric: approval_rate
- Target: >=0.9

### Constraints

**Only suggest roles the user is realistically qualified for - no aspirational stretch roles** (quality)
- Category: accuracy
**Resume customizations must be truthful - enhance presentation, never fabricate experience** (ethical)
- Category: integrity
**Cold emails must be professional and not spammy** (quality)
- Category: tone
**Only customize for jobs the user explicitly selects** (behavioral)
- Category: user_control

## Required Tools

- `save_data`
- `web_scrape`
- `web_search`

## MCP Tool Sources

### hive-tools (stdio)
Hive tools MCP server

**Configuration:**
- Command: `uv`
- Args: `['run', 'python', 'mcp_server.py', '--stdio']`
- Working Directory: `tools`

Tools from these MCP servers are automatically loaded when the agent runs.

## Usage

### Basic Usage

```python
from framework.runner import AgentRunner

# Load the agent
runner = AgentRunner.load("exports/job_hunter")

# Run with input
result = await runner.run({"input_key": "value"})

# Access results
print(result.output)
print(result.status)
```

### Input Schema

The agent's entry node `intake` requires:


### Output Schema

Terminal nodes: `customize`

## Version History

- **1.0.0** (2026-02-13): Initial release
  - 4 nodes, 3 edges
  - Goal: Job Hunter
