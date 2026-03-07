"""Node definitions for Job Hunter Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (simple)
# Collect resume and identify strongest role types.
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description="Analyze resume and identify 3-5 strongest role types",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["resume_text"],
    output_keys=["resume_text", "role_analysis"],
    success_criteria=(
        "The user's resume has been analyzed and 3-5 target roles identified "
        "based on their actual experience."
    ),
    system_prompt="""\
You are a career analyst. Your task is to analyze the user's resume and identify the best role fits.

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
    tools=[],
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
You are a career coach creating personalized application materials.

**PROCESS:**
1. Create application_materials.html using save_data and append_data.
2. Generate resume customization list and professional cold email for each selected job.
3. Serve the file to the user.
4. Create Gmail drafts using gmail_create_draft.

**FINISH:**
Call set_output("application_materials", "Completed")
""",
    tools=["save_data", "append_data", "serve_file_to_user", "gmail_create_draft"],
)

__all__ = [
    "intake_node",
    "job_search_node",
    "job_review_node",
    "customize_node",
]
