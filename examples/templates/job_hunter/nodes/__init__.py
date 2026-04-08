"""Node definitions for Job Hunter Agent."""

from framework.orchestrator import NodeSpec

# Node 1: Intake (simple)
# Collect resume and identify strongest role types.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Analyze resume and identify 3-5 strongest role types",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[],
    output_keys=["resume_text", "role_analysis"],
    success_criteria=(
        "The user's resume has been analyzed and 3-5 target roles identified "
        "based on their actual experience."
    ),
    system_prompt="""\
You are a career analyst. Your task is to analyze the user's resume and identify the best role fits.

**ACCEPTING THE RESUME:**
The user can provide their resume in two ways:
1. **Paste text** — The user pastes their resume content directly.
2. **PDF file path** — The user provides a path to a PDF file (e.g., "/path/to/resume.pdf"). \
If a file path is provided, call pdf_read(file_path="<path>") to extract the text before analyzing.

**PROCESS:**
1. Identify key skills (technical and soft skills).
2. Summarize years and types of experience.
3. Identify 3-5 specific role types where they're most competitive based on their ACTUAL experience.

**OUTPUT:**
You MUST call set_output to store:
- set_output("resume_text", "<the full resume text from input>")
- set_output("role_analysis", "<JSON with: skills, experience_summary, target_roles (3-5 specific role titles)>")

Do NOT wait for user confirmation. Simply perform the analysis and set the outputs.
""",
    tools=["pdf_read"],
)

# Node 2: Job Search (simple)
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
Use web_scrape to directly scrape job listings from job boards. Build search URLs with the role title:
- LinkedIn Jobs: https://www.linkedin.com/jobs/search/?keywords={role_title}
- Indeed: https://www.indeed.com/jobs?q={role_title}

Gather 10 quality job listings total across the target roles.

**For each job, extract:**
- Job title, Company name, Location, Brief description, URL.

**OUTPUT:** Once you have 10 jobs, call:
set_output("job_listings", "<JSON array of 10 job objects>")
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

**STEP 1 — Present the jobs:**
Display all 10 jobs in a clear, numbered format.
Ask: "Which jobs would you like me to create application materials for? List the numbers or say 'all'."

**STEP 2 — After user responds:**
Confirm their selection and call:
set_output("selected_jobs", "<JSON array of the selected job objects>")
""",
    tools=[],
)

# Node 4: Customize (client-facing, terminal)
# Generate resume customization list and cold email for each selected job.
customize_node = NodeSpec(
    id="customize",
    name="Customize",
    description="For each selected job, generate resume customization list and cold outreach email, create Gmail drafts",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["selected_jobs", "resume_text"],
    output_keys=["application_materials"],
    success_criteria=(
        "Resume customization list and cold outreach email generated "
        "for each selected job, saved as HTML, and Gmail drafts created in user's inbox."
    ),
    system_prompt="""\
You are a career coach creating personalized application materials and Gmail drafts.

**CRITICAL: You MUST create Gmail drafts for each selected job using gmail_create_draft.**

**PROCESS:**
1. Create application_materials.html using save_data and append_data.
2. For each selected job:
   a. Generate a specific resume customization list
   b. Create a professional cold outreach email
   c. **IMMEDIATELY call gmail_create_draft** with:
      - to: hiring manager or recruiter email (if available) or company email
      - subject: "Application for [Job Title] - [Your Name]"
      - html: the professional cold email in HTML format
3. Serve the application_materials.html file to the user.
4. Confirm each Gmail draft was created successfully.

**EMAIL REQUIREMENTS:**
- Professional, personalized cold outreach email
- Reference specific company details and role
- Mention 2-3 relevant qualifications from their resume
- Include clear call-to-action
- Professional email signature
- Format as HTML with proper structure

**Gmail Draft Creation:**
For each job, you MUST call gmail_create_draft(to="[email]", subject="[subject]", html="[email_html]")
- Extract company email from job listing if available
- Use generic format like "careers@[company].com" if no specific email
- Subject format: "Application for [Job Title] - [Applicant Name]"
- HTML email body with proper formatting

**FINISH:**
Only call set_output("application_materials", "Completed") AFTER creating ALL Gmail drafts.
""",
    tools=["save_data", "append_data", "serve_file_to_user", "gmail_create_draft"],
)

__all__ = [
    "intake_node",
    "job_search_node",
    "job_review_node",
    "customize_node",
]
