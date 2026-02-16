"""Node definitions for Job Hunter Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Collect resume and identify strongest role types.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Collect resume from user, analyze skills and experience, identify 3-5 strongest role types",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[],
    output_keys=["resume_text", "role_analysis"],
    success_criteria=(
        "The user's resume has been analyzed and 3-5 target roles identified "
        "based on their actual experience, with user confirmation."
    ),
    system_prompt="""\
You are a career analyst helping a job seeker find their best opportunities.

**STEP 1 — Greet and collect resume (text only, NO tool calls):**

Ask the user to paste their resume. Be friendly and concise:
"Please paste your resume below. I'll analyze your experience and identify the roles where you have the strongest chance of success."

**STEP 2 — After the user provides their resume:**

Analyze the resume thoroughly:
1. Identify key skills (technical and soft skills)
2. Summarize years and types of experience
3. Identify 3-5 specific role types where they're most competitive based on their ACTUAL experience

Present your analysis to the user and ask if they agree with the role types identified.

**STEP 3 — After user confirms, call set_output IMMEDIATELY:**

IMPORTANT: When the user says any of these, treat it as CONFIRMATION and call set_output immediately:
- "yes", "sure", "looks good", "that works", "go ahead", "find jobs", "start searching", etc.

DO NOT ask follow-up questions after the user confirms. DO NOT ask which roles to focus on.
The job search will use ALL the roles you identified.

Use set_output to store:
- set_output("resume_text", "<the full resume text>")
- set_output("role_analysis", "<JSON with: skills, experience_summary, target_roles (3-5 specific role titles)>")

NEVER ask the user to pick between roles. Your job is to identify the right roles, not make them choose.
""",
    tools=[],
)

# Node 2: Job Search
# Search for 10 jobs matching the identified roles.
job_search_node = NodeSpec(
    id="job-search",
    name="Job Search",
    description="Search for 10 jobs matching identified roles by scraping job board sites directly",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["role_analysis"],
    output_keys=["job_listings"],
    success_criteria=(
        "10 relevant job listings have been found with complete details "
        "including title, company, location, description, and URL."
    ),
    system_prompt="""\
You are a job search specialist. Your task is to find 10 relevant job openings.

**INPUT:** You have access to role_analysis containing target roles and skills.

**PROCESS:**
Use web_scrape to directly scrape job listings from these job boards. Build search URLs with the role title:

**Recommended Job Sites (scrape these directly):**
1. **LinkedIn Jobs:** https://www.linkedin.com/jobs/search/?keywords={role_title}
2. **Indeed:** https://www.indeed.com/jobs?q={role_title}
3. **Glassdoor:** https://www.glassdoor.com/Job/jobs.htm?sc.keyword={role_title}
4. **Wellfound (Startups):** https://wellfound.com/jobs?q={role_title}
5. **RemoteOK:** https://remoteok.com/remote-{role_title}-jobs

**Strategy:**
- For each target role in role_analysis, scrape 1-2 job board search result pages
- Extract job listings from the scraped HTML
- If a job looks promising, scrape its detail page for more info
- Gather 10 quality job listings total across the target roles

**For each job, extract:**
- Job title
- Company name
- Location (or "Remote" if applicable)
- Brief job description/requirements summary
- URL to the job posting
- Any info about the hiring manager or company contact if visible

**OUTPUT:** Once you have 10 jobs, call:
set_output("job_listings", "<JSON array of 10 job objects with title, company, location, description, url, contact_info>")

Focus on finding REAL, current job postings with actual URLs the user can visit.
""",
    tools=["web_scrape"],
)

# Node 3: Job Review (client-facing)
# Present jobs and let user select which to pursue.
job_review_node = NodeSpec(
    id="job-review",
    name="Job Review",
    description="Present all 10 jobs to the user, let them select which to pursue",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["job_listings", "resume_text"],
    output_keys=["selected_jobs"],
    success_criteria=(
        "User has reviewed all job listings and explicitly selected "
        "which jobs they want to apply to."
    ),
    system_prompt="""\
You are helping a job seeker choose which positions to apply to.

**STEP 1 — Present the jobs (text only, NO tool calls):**

Display all 10 jobs in a clear, numbered format:

```
**Job Opportunities Found:**

1. **[Job Title]** at [Company]
   Location: [Location]
   [Brief description - 2-3 lines]
   URL: [link]

2. **[Job Title]** at [Company]
   ...
```

After listing all jobs, ask:
"Which jobs would you like me to create application materials for? Please list the numbers (e.g., '1, 3, 5') or say 'all' for all of them."

**STEP 2 — After the user responds:**

Confirm their selection and call set_output:
- set_output("selected_jobs", "<JSON array of the selected job objects>")

Only include the jobs the user explicitly selected.
""",
    tools=[],
)

# Node 4: Customize (client-facing, terminal)
# Generate resume customization list and cold email for each selected job.
customize_node = NodeSpec(
    id="customize",
    name="Customize",
    description="For each selected job, generate resume customization list and cold outreach email as HTML",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["selected_jobs", "resume_text"],
    output_keys=["application_materials"],
    success_criteria=(
        "Resume customization list and cold outreach email generated "
        "for each selected job, saved as a single HTML file and opened for the user."
    ),
    system_prompt="""\
You are a career coach creating personalized application materials.

**INPUT:** You have the user's resume and their selected jobs.

**OUTPUT FORMAT: Single HTML Report**
Generate ONE polished HTML report containing materials for ALL selected jobs.

**HTML Structure:**
```html
<!DOCTYPE html>
<html>
<head>
  <title>Job Application Materials</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 40px; line-height: 1.6; }
    h1 { color: #1a1a1a; border-bottom: 2px solid #0066cc; padding-bottom: 10px; }
    h2 { color: #0066cc; margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; }
    h3 { color: #333; margin-top: 20px; }
    .job-section { margin-bottom: 60px; }
    .email-card { background: #f8f9fa; border-left: 4px solid #0066cc; padding: 20px; margin: 20px 0; white-space: pre-wrap; }
    .customization-list { background: #fff; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px; }
    ul { line-height: 1.8; }
    .toc { background: #f0f4f8; padding: 20px; border-radius: 8px; margin-bottom: 40px; }
    .toc a { color: #0066cc; text-decoration: none; }
    .toc a:hover { text-decoration: underline; }
    .job-url { color: #666; font-size: 0.9em; }
  </style>
</head>
<body>
  <h1>Job Application Materials</h1>
  <div class="toc">
    <strong>Table of Contents:</strong>
    <ol>
      <li><a href="#job-1">Job Title at Company</a></li>
      <!-- ... more jobs ... -->
    </ol>
  </div>

  <!-- For each job: -->
  <div class="job-section" id="job-1">
    <h2>Job Title at Company</h2>
    <p class="job-url">URL: <a href="...">link</a></p>

    <h3>Resume Customization List</h3>
    <div class="customization-list">
      <h4>Priority Changes</h4>
      <ul>
        <li>...</li>
      </ul>
      <h4>Keywords to Incorporate</h4>
      <ul>...</ul>
      <h4>Experiences to Emphasize</h4>
      <ul>...</ul>
      <h4>Suggested Rewrites</h4>
      <ul>...</ul>
    </div>

    <h3>Cold Outreach Email</h3>
    <div class="email-card">
Subject: ...

Dear Hiring Manager,

...

Best regards,
[Your Name]
    </div>
  </div>
</body>
</html>
```

**PROCESS:**
1. Generate the complete HTML report for ALL selected jobs
2. Save it using: save_data(filename="application_materials.html", data="<the HTML content>")
3. Get the clickable file path using: serve_file_to_user(filename="application_materials.html", open_in_browser=true)
4. **CRITICAL: Print the file path in your response so the user can click it:**
   "Your application materials have been saved and opened in your browser.

   **File location:** [print the file_path from serve_file_to_user result]"
5. Call set_output("application_materials", "Created application_materials.html with materials for {N} jobs")

**IMPORTANT:**
- Only suggest truthful resume changes — enhance presentation, never fabricate
- Cold emails must be professional, personalized, and under 150 words
- ALWAYS print the full file path so users can easily access the file later
""",
    tools=["save_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "job_search_node",
    "job_review_node",
    "customize_node",
]
