"""Node definitions for Automated HR Screener."""

import os

from framework.graph import NodeSpec


def _build_intake_prompt():
    """Build intake prompt with pre-filled data from env vars."""
    jd = os.environ.get("HR_JOB_DESCRIPTION", "")
    rf = os.environ.get("HR_RESUME_FILES", "")
    nc = os.environ.get("HR_NOTIFY_CANDIDATES", "no")
    if jd and rf:
        return f"""You are the intake processor. Data has been pre-collected.

Call set_output 3 times with this exact data:
1. set_output(key="job_description", value="{jd}")
2. set_output(key="resume_files", value="{rf}")
3. set_output(key="notify_candidates", value="{nc}")

Do NOT modify the values. Do NOT ask questions. Do NOT output text."""
    return """You are the intake processor. Ask the user for:
1. Job description
2. Resume PDF path
3. Email notification preference (yes/no)
Then call set_output for each."""


# Node 1: Intake
intake_node = NodeSpec(
    id="intake",
    name="Intake",
    description=(
        "Collect job description, resume file paths, "
        "and email notification preference from the user."
    ),
    node_type="event_loop",
    client_facing=False,
    input_keys=[],
    output_keys=["job_description", "resume_files", "notify_candidates"],
    system_prompt=_build_intake_prompt(),
    tools=[],
)

# Node 2: Scan Resumes
# Reads each PDF using pdf_read and collects extracted text.
scan_resumes_node = NodeSpec(
    id="scan-resumes",
    name="Scan Resumes",
    description="Read each PDF resume using pdf_read and collect text data.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["job_description", "resume_files"],
    output_keys=["resume_data"],
    system_prompt="""\
You are a Senior Technical Recruiter specializing in parsing and analyzing engineering resumes.

The "resume_files" context contains comma-separated PDF file paths.

For EACH file path in the list:
1. Call pdf_read(file_path="<path>")
2. Remember the result

After reading ALL files, use the `set_output` tool with key "resume_data" to save a JSON string:
{"candidates": [{"file_name": "name.pdf", "text": "<extracted text>"}, ...], "total_resumes": N}

RULES:
- Call pdf_read for EACH file. Do NOT skip any.
- Include the REAL text from pdf_read. NEVER fabricate content.
- If a pdf_read fails, include: {"file_name": "x.pdf", "text": "", "error": "reason"}
- Only use the set_output tool AFTER reading ALL files.
""",
    tools=["list_dir", "pdf_read"],
)

# Node 3: Rank Candidates
rank_candidates_node = NodeSpec(
    id="rank-candidates",
    name="Rank Candidates",
    description="Score and rank all candidates against the job description.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["job_description", "resume_data"],
    output_keys=["rankings"],
    system_prompt="""\
You are a Senior Principal Engineer responsible for rigorously evaluating and ranking engineering candidates based on technical merit.

CHECK FIRST: If resume_data has no candidates or all have empty text:
- Use the `set_output` tool with key "rankings" to save: '{"error": "No data", "rankings": [], "total_candidates": 0}'
- STOP. Do NOT fabricate candidates.

For each candidate, read their ACTUAL text and score (0-100):
- Skills Match (40%): skills vs job requirements
- Experience (25%): relevant experience level
- Education (15%): relevant degrees/certs
- Communication (10%): resume quality
- Bonus (10%): projects, publications, etc.

Use the `set_output` tool with key "rankings" to save a JSON string:
{"rankings": [{"rank": 1, "file_name": "x.pdf", "candidate_name": "Name", \
"overall_score": 85, "scores": {"skills_match": 90, "experience": 80, \
"education": 75, "communication": 85, "bonus_factors": 70}, \
"summary": "2 sentences", "top_skills": ["a","b"], "email": "x@y.com or null"}], \
"total_candidates": N}

RULES:
- NEVER fabricate. ALL data from actual resume text only.
- For the `email` field, extract the EXACT email address as it appears in the text using strict pattern matching. Do not misspell it or fabricate it.
- Score ALL candidates, sort by score descending.
""",
    tools=[],
)

# Node 4: Generate Report
generate_report_node = NodeSpec(
    id="generate-report",
    name="Generate Report",
    description="Build a plain text screening report of ranked candidates.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["rankings"],
    output_keys=["report_file"],
    system_prompt="""\
You are a report generator. Write a plain text screening report.

Do EXACTLY these 2 steps:

Step 1: Call save_data with filename="hr_screening_report.txt" and data = a structured plain text report. Format:

HR SCREENING REPORT
===================
Date: <today>
Total Candidates: <N>

RANKINGS:
1. <Name> | Score: <X>/100 | Email: <email>
   Strengths: <1-2 sentences from summary>
   Top Skills: <comma list>

2. <next candidate>
...

RECOMMENDATION: <top candidate name> is the strongest fit.

Step 2: Call set_output with key="report_file" and value="hr_screening_report.txt"

ONLY 2 tool calls. No HTML. No append_data. No serve_file_to_user. STOP after set_output.
""",
    tools=["save_data"],
)

# Node 5: Notify Candidates (client-facing)
notify_candidates_node = NodeSpec(
    id="notify-candidates",
    name="Notify Candidates",
    description="Send response emails to candidates after user approval.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["rankings", "notify_candidates"],
    output_keys=["emails_sent"],
    system_prompt="""\
You are the email notification assistant.

If notify_candidates is "no":
  Call set_output(key="emails_sent", value="skipped") and STOP.

If "yes":
1. Show the user a summary of candidates with real emails from rankings.
   Ask: "Type YES to send emails."
2. If user confirms, for EACH candidate with a real email:
   Call send_email(provider="resend", from_email="onboarding@resend.dev",
   to=<candidate email>, subject="Your Application Update",
   html="<p>Dear <Name>,</p><p>Thank you for applying.</p><p>Best regards,<br>Recruitment Team</p>")
3. Call set_output(key="emails_sent", value="Sent to: <list of emails>")

RULES:
- ONLY use real emails from rankings. NEVER use example.com or placeholder emails.
- Call set_output EXACTLY ONCE at the end.
- If user declines, call set_output(key="emails_sent", value="cancelled").
""",
    tools=["send_email"],
)

__all__ = [
    "intake_node",
    "scan_resumes_node",
    "rank_candidates_node",
    "generate_report_node",
    "notify_candidates_node",
]
