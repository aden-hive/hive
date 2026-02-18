# Job Hunter

**Version**: 2.0.0
**Type**: Multi-node autonomous agent
**Upgraded**: 2026-02-18
**Previous Version**: 1.0.0 (2026-02-13)

---

## Overview

Parse and ATS-score a user's resume, identify errors and improvement areas, research live market demand for their skills, find 10 matching job opportunities, let the user select which to pursue, then generate ATS-optimized resume customizations and cold outreach emails for each selected job — with an automated critique-and-revision loop before delivery.

---

## Architecture

### Execution Flow

```
resume_uploader
       |
       v
resume_parser
       |
       v
preference_intake
       |
       v
market_analyst
       |
       v
job_selector
       |
       v
jd_parser
       |
       v
ats_analyzer
       |
       v
chief_strategist
       |
       v
senior_copywriter
       |
       v
critic
       |
       v
revision_router
       |
       v
publisher
```

---

### Nodes (12 total)

1. **resume_uploader** (event_loop)
   - Collects the resume from the user via PDF upload, DOCX upload, or text paste
   - Writes: `raw_resume_content`, `resume_file_type`
   - Tools: `pdf_read`, `web_scrape`
   - Client-facing: Yes

2. **resume_parser** (event_loop)
   - Parses the raw resume into structured JSON covering all sections, skills, experience, education, and format errors
   - Reads: `raw_resume_content`
   - Writes: `parsed_resume`
   - Client-facing: No

3. **preference_intake** (event_loop)
   - Shows the resume analysis and detected errors to the user, confirms role fits, and collects job search preferences
   - Reads: `parsed_resume`
   - Writes: `user_preferences`, `confirmed_roles`
   - Client-facing: Yes

4. **market_analyst** (event_loop)
   - Scrapes live job boards and salary sites to validate demand, open role counts, top hirers, and salary ranges per role
   - Reads: `confirmed_roles`, `user_preferences`, `parsed_resume`
   - Writes: `market_intelligence`
   - Tools: `web_scrape`
   - Client-facing: No

5. **job_selector** (event_loop)
   - Presents the market intelligence report, searches for 10 real live job listings, and lets the user select which to pursue
   - Reads: `market_intelligence`, `confirmed_roles`, `user_preferences`, `parsed_resume`
   - Writes: `job_listings`, `selected_jobs`
   - Tools: `web_scrape`
   - Client-facing: Yes

6. **jd_parser** (event_loop)
   - Scrapes and parses the full job description for each selected job, extracting ATS keywords, required skills, and seniority signals
   - Reads: `selected_jobs`
   - Writes: `parsed_job_descriptions`
   - Tools: `web_scrape`
   - Client-facing: No

7. **ats_analyzer** (event_loop)
   - Mathematically scores the resume against each job description (0-100) across keyword match, skills match, experience match, and format quality
   - Reads: `parsed_resume`, `parsed_job_descriptions`
   - Writes: `ats_reports`
   - Client-facing: No

8. **chief_strategist** (event_loop)
   - Produces a per-job strategy brief defining what to write, what to emphasize, and what angle to take — does not write a single line of copy
   - Reads: `parsed_resume`, `parsed_job_descriptions`, `ats_reports`, `market_intelligence`
   - Writes: `strategy_briefs`
   - Client-facing: No

9. **senior_copywriter** (event_loop)
   - Follows the strategy brief to write the resume customization list and cold outreach email for each selected job
   - Reads: `strategy_briefs`, `parsed_resume`, `parsed_job_descriptions`, `ats_reports`
   - Writes: `draft_materials`
   - Client-facing: No

10. **critic** (event_loop)
    - Reviews every draft against quality standards, counts email words, checks for fabrications and generic phrases, and issues a pass/fail with revision instructions
    - Reads: `draft_materials`, `strategy_briefs`, `ats_reports`
    - Writes: `critique_report`
    - Client-facing: No

11. **revision_router** (event_loop)
    - Applies the critic's revision instructions to failing drafts and passes approved drafts through unchanged
    - Reads: `draft_materials`, `critique_report`, `strategy_briefs`
    - Writes: `final_materials`
    - Client-facing: No

12. **publisher** (event_loop)
    - Builds the HTML application materials report incrementally, serves it to the user, and creates Gmail drafts for each cold email
    - Reads: `final_materials`, `ats_reports`, `parsed_resume`
    - Writes: `application_materials`
    - Tools: `save_data`, `append_data`, `serve_file_to_user`, `gmail_create_draft`
    - Client-facing: Yes

---

### Edges (11 total)

- `resume_uploader` → `resume_parser` (condition: on_success, priority=1)
- `resume_parser` → `preference_intake` (condition: on_success, priority=1)
- `preference_intake` → `market_analyst` (condition: on_success, priority=1)
- `market_analyst` → `job_selector` (condition: on_success, priority=1)
- `job_selector` → `jd_parser` (condition: on_success, priority=1)
- `jd_parser` → `ats_analyzer` (condition: on_success, priority=1)
- `ats_analyzer` → `chief_strategist` (condition: on_success, priority=1)
- `chief_strategist` → `senior_copywriter` (condition: on_success, priority=1)
- `senior_copywriter` → `critic` (condition: on_success, priority=1)
- `critic` → `revision_router` (condition: on_success, priority=1)
- `revision_router` → `publisher` (condition: on_success, priority=1)

---

## Goal Criteria

### Success Criteria

**Resume parsed with all sections, skills, and errors identified** (weight: 0.10)
- Metric: parse_completeness
- Target: >=0.95

**ATS scores accurately reflect keyword match rate and format quality** (weight: 0.15)
- Metric: ats_score_validity
- Target: >=0.85

**Identifies 3-5 role types that genuinely match the user's actual experience** (weight: 0.15)
- Metric: role_match_accuracy
- Target: >=0.8

**Found jobs align with identified roles and user's background** (weight: 0.15)
- Metric: job_relevance_score
- Target: >=0.8

**Resume changes are specific, actionable, and tailored to each job posting** (weight: 0.20)
- Metric: customization_specificity
- Target: >=0.85

**Cold emails are personalized, professional, and reference specific company details** (weight: 0.15)
- Metric: email_personalization_score
- Target: >=0.85

**User approves outputs without major revisions needed** (weight: 0.10)
- Metric: approval_rate
- Target: >=0.9

### Constraints

**Only suggest roles the user is realistically qualified for — no aspirational stretch roles** (quality)
- Category: accuracy

**Resume customizations must be truthful — enhance presentation, never fabricate experience** (ethical)
- Category: integrity

**Cold emails must be professional, specific, and not spammy** (quality)
- Category: tone

**Only generate materials for jobs the user explicitly selects** (behavioral)
- Category: user_control

**Keyword injections and bullet rewrites must never introduce experience the candidate does not have** (ethical)
- Category: integrity

---

## Required Tools

- `pdf_read`
- `web_scrape`
- `save_data`
- `append_data`
- `serve_file_to_user`
- `gmail_create_draft`

---

## MCP Tool Sources

### hive-tools (stdio)
Hive tools MCP server

**Configuration:**
- Command: `uv`
- Args: `['run', 'python', 'mcp_server.py', '--stdio']`
- Working Directory: `tools`

Tools from this MCP server are automatically loaded when the agent runs.

---

## How to Upload Your Resume

You do not need a button or file picker. The agent reads your resume directly from a file path you paste into the chat.

**Step 1:** Right-click your resume file (PDF or Word document).

**Step 2:** Copy the file path.
- Windows: Select "Copy as path"
- Mac: Hold Option and right-click, then select "Copy ... as Pathname"

**Step 3:** Paste the path directly into the Agent TUI chat box and press Enter.

Example:
```
C:\Users\Rahul\Documents\MyResume.pdf
```

The agent will read the file automatically. If the file cannot be read (scanned PDF, permissions issue), it will ask you to paste the resume text directly instead.

---

## Usage

### Basic Usage

```python
from framework.runner import AgentRunner

# Load the agent
runner = AgentRunner.load("exports/job_hunter")

# Run with input
result = await runner.run({})

# Access results
print(result.output)
print(result.status)
```

### Input Schema

The agent's entry node `resume_uploader` requires no input keys. The user provides the resume interactively at runtime via upload or text paste.

### Output Schema

Terminal node: `publisher`
- `application_materials` — path to the generated HTML report and count of jobs covered

---

## V1 to V2 Comparison

| Feature | V1 (1.0.0) | V2 (2.0.0) |
|---|---|---|
| Pipeline type | Linear chain | Sequential with critique loop |
| Node count | 4 | 12 |
| Edge count | 3 | 11 |
| Resume input | Text paste only | PDF, DOCX, or text paste with OCR fallback |
| Resume analysis | None | Full structural parse with error detection |
| ATS scoring | None | Mathematical per-job score (0-100) |
| Data source | User input only | Live job board and salary scraping |
| Strategy | Writer decides on the fly | Dedicated strategist node, writer follows brief |
| Quality control | None | Critic node with pass/fail and revision loop |
| Output | HTML report + Gmail drafts | HTML report with ATS scores + Gmail drafts |
| Time saved per application | ~10 minutes | ~45 minutes |

---

## Version History

- **2.0.0** (2026-02-18): Major upgrade
  - 12 nodes, 11 edges
  - Added: resume_parser, preference_intake, market_analyst, job_selector, jd_parser, ats_analyzer, chief_strategist, senior_copywriter, critic, revision_router, publisher
  - Replaced: intake, job-search, job-review, customize
  - New capabilities: PDF/DOCX upload with OCR, ATS scoring enginea, live market research, strategy briefs, editorial critique loop

- **1.0.0** (2026-02-13): Initial release
  - 4 nodes, 3 edges
  - Goal: Job Hunter