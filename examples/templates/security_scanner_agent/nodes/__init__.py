"""Node definitions for Security Code Scanner Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
# Collects the target repository path and scope preferences from the user.
intake_node = NodeSpec(
    id="intake",
    name="Security Scan Intake",
    description="Collect target codebase path, language, and scope from the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["target"],
    output_keys=["scan_config"],
    success_criteria=(
        "A scan configuration is produced with: target path or repo URL, "
        "primary language, scan scope (full/focused), and any exclusions."
    ),
    system_prompt="""\
You are a security scan intake specialist. The user wants to scan code for vulnerabilities.

**STEP 1 — Gather info (text only, NO tool calls):**
1. Read the target info provided (path, URL, or description)
2. Ask what language(s) the codebase uses if not obvious
3. Ask about scan scope: full audit or focused on specific areas
   (e.g., authentication, input validation, injection, secrets)
4. Ask if any files/directories should be excluded

Keep it to 1-2 messages. Don't over-ask.

**STEP 2 — After the user confirms, call set_output:**
- set_output("scan_config", "JSON-like description: target, language, scope areas, exclusions")
""",
    tools=[],
)

# Node 2: Static Analysis
# Scans source code for vulnerability patterns without executing it.
static_analysis_node = NodeSpec(
    id="static_analysis",
    name="Static Analysis",
    description="Scan source code for common vulnerability patterns",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["scan_config"],
    output_keys=["static_findings", "file_inventory"],
    success_criteria=(
        "All files matching the scan config have been analyzed. "
        "Findings include file path, line reference, vulnerability type, "
        "severity, and a brief description for each issue found."
    ),
    system_prompt="""\
You are a security static analysis engine. Given a scan configuration,
analyze the codebase for vulnerability patterns.

**CATEGORIES TO CHECK (in order of severity):**

1. **CRITICAL — Remote Code Execution / Injection**
   - Shell command injection (os.system, subprocess with shell=True, eval, exec)
   - SQL injection (string concatenation in queries, unsanitized f-strings)
   - Template injection (user input in Jinja2/Mako without escaping)
   - Deserialization attacks (pickle.loads, yaml.unsafe_load on untrusted data)

2. **HIGH — Authentication & Authorization**
   - Hardcoded credentials, API keys, tokens in source
   - Missing authentication checks on sensitive endpoints
   - Broken access control (IDOR, privilege escalation paths)
   - Weak cryptography (MD5/SHA1 for passwords, ECB mode, small key sizes)

3. **HIGH — Data Exposure**
   - Sensitive data in logs (passwords, tokens, PII)
   - Unencrypted storage of secrets
   - Overly verbose error messages exposing internals
   - Missing input validation on external data

4. **MEDIUM — Configuration & Dependencies**
   - Debug mode enabled in production configs
   - CORS misconfigurations (wildcard origins)
   - Missing security headers
   - Known vulnerable dependency versions

5. **LOW — Code Quality (Security-relevant)**
   - Race conditions in file operations
   - Unbounded resource allocation (no limits on uploads, queries)
   - Missing rate limiting
   - Insufficient logging of security events

**PROCESS:**
1. Use web_search to look up current CVEs for any dependencies found
2. Use save_data to record findings as you go
3. Organize findings by severity

When done, use set_output (one key per turn):
- set_output("static_findings", "JSON array of findings: [{severity, category, file, \
line_ref, title, description, recommendation}]")
- set_output("file_inventory", "Summary: total files scanned, languages found, \
dependency files identified")
""",
    tools=[
        "web_search",
        "save_data",
        "append_data",
        "load_data",
        "list_data_files",
    ],
)

# Node 3: Risk Assessment
# Prioritizes findings and assigns CVSS-like scores.
risk_assessment_node = NodeSpec(
    id="risk_assessment",
    name="Risk Assessment",
    description="Score and prioritize all findings by exploitability and impact",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["static_findings", "file_inventory", "scan_config"],
    output_keys=["risk_report", "remediation_plan"],
    success_criteria=(
        "Each finding has a risk score (Critical/High/Medium/Low) with justification. "
        "A prioritized remediation plan is produced."
    ),
    system_prompt="""\
You are a security risk assessor. Given the static analysis findings,
produce a risk-scored report and remediation plan.

**FOR EACH FINDING, ASSESS:**
1. **Exploitability** (1-10): How easy is this to exploit?
   - 9-10: Publicly known exploit, no authentication required
   - 7-8: Requires basic knowledge, low barrier
   - 4-6: Requires specific conditions or insider access
   - 1-3: Theoretical, very difficult to exploit

2. **Impact** (1-10): What's the damage if exploited?
   - 9-10: Full system compromise, data breach
   - 7-8: Significant data exposure or service disruption
   - 4-6: Limited data exposure or partial service impact
   - 1-3: Minimal impact, information disclosure

3. **Risk Score**: (Exploitability + Impact) / 2
   - 8-10: CRITICAL — Fix immediately
   - 6-7.9: HIGH — Fix within 1 sprint
   - 4-5.9: MEDIUM — Plan for next release
   - 1-3.9: LOW — Track and address when convenient

**PRODUCE:**
1. **Risk Report**: All findings sorted by risk score (highest first)
2. **Remediation Plan**: Prioritized list of fixes with:
   - Specific code change recommendations
   - Estimated effort (trivial / small / medium / large)
   - Dependencies between fixes (what should be fixed first)

Use save_data to store the risk report.

When done, use set_output (one key per turn):
- set_output("risk_report", "Structured risk report with scored findings")
- set_output("remediation_plan", "Prioritized remediation steps with effort estimates")
""",
    tools=["save_data", "append_data", "load_data", "web_search"],
)

# Node 4: Review (client-facing)
# Presents findings to the user for approval before generating the final report.
review_node = NodeSpec(
    id="review",
    name="Review Findings",
    description="Present scored findings to user and collect feedback",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["risk_report", "remediation_plan", "scan_config"],
    output_keys=["approved", "review_feedback"],
    success_criteria=(
        "User has reviewed the findings and either approved the report "
        "or provided feedback for deeper analysis."
    ),
    system_prompt="""\
Present the security scan results to the user clearly and concisely.

**STEP 1 — Present (text only, NO tool calls):**
1. **Executive Summary**: Total findings by severity (Critical/High/Medium/Low)
2. **Top 5 Most Critical Issues**: Brief description of each
3. **Key Recommendations**: Top 3 actions to take first
4. **Coverage**: What was scanned and what wasn't

Ask the user:
- Are they satisfied with the scan depth?
- Do they want to focus deeper on any specific area?
- Should we generate the final report?

**STEP 2 — After the user responds, call set_output:**
- set_output("approved", "true") — if they want the report generated
- set_output("approved", "false") — if they want deeper analysis
- set_output("review_feedback", "What the user wants examined further, or empty string")
""",
    tools=[],
)

# Node 5: Report Generation (client-facing)
# Produces a professional HTML security audit report.
report_node = NodeSpec(
    id="report",
    name="Generate Security Report",
    description="Generate a professional HTML security audit report",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["risk_report", "remediation_plan", "scan_config", "static_findings"],
    output_keys=["delivery_status"],
    success_criteria=(
        "A professional HTML security report has been generated, saved, "
        "and presented to the user with a download link."
    ),
    system_prompt="""\
Generate a professional security audit report as an HTML file.

**CRITICAL: Build the file in multiple append_data calls. NEVER write the entire HTML \
in a single save_data call.**

IMPORTANT: save_data and append_data require TWO separate arguments: filename and data.
Do NOT include data_dir in tool calls — it is auto-injected.

**PROCESS (follow exactly):**

**Step 1 — HTML head + executive summary (save_data):**
save_data(filename="security_report.html", data="<!DOCTYPE html>\\n<html>...")

Include: DOCTYPE, head with professional security-themed CSS, title page with:
- Report title: "Security Audit Report"
- Date, target system, scan scope
- Executive summary with finding counts by severity
- Overall risk rating (Critical/High/Medium/Low)

**CSS to use (security-themed):**
```
body{font-family:'Segoe UI',system-ui,sans-serif;max-width:900px;margin:0 auto;\
padding:40px;line-height:1.7;color:#1a1a2e;background:#f5f5f5}
.report{background:#fff;padding:40px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}
h1{font-size:1.8em;color:#16213e;border-bottom:3px solid #e94560;padding-bottom:10px}
h2{font-size:1.4em;color:#16213e;margin-top:35px;padding-top:15px}
h3{font-size:1.1em;color:#0f3460}
.severity-critical{background:#dc3545;color:#fff;padding:3px 10px;border-radius:4px;\
font-weight:bold;font-size:0.85em}
.severity-high{background:#fd7e14;color:#fff;padding:3px 10px;border-radius:4px;\
font-weight:bold;font-size:0.85em}
.severity-medium{background:#ffc107;color:#000;padding:3px 10px;border-radius:4px;\
font-weight:bold;font-size:0.85em}
.severity-low{background:#28a745;color:#fff;padding:3px 10px;border-radius:4px;\
font-weight:bold;font-size:0.85em}
.finding{border:1px solid #dee2e6;border-radius:8px;padding:20px;margin:15px 0;\
background:#fff}
.finding-header{display:flex;justify-content:space-between;align-items:center;\
margin-bottom:10px}
.recommendation{background:#e8f4f8;padding:15px;border-radius:6px;border-left:4px \
solid #0f3460;margin:10px 0}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:20px 0}
.stat-card{text-align:center;padding:20px;border-radius:8px;font-weight:bold}
.stat-critical{background:#fde8ea}.stat-high{background:#fff3e0}
.stat-medium{background:#fff8e1}.stat-low{background:#e8f5e9}
table{width:100%;border-collapse:collapse;margin:15px 0}
th{background:#16213e;color:#fff;padding:12px;text-align:left}
td{padding:10px;border-bottom:1px solid #dee2e6}
.footer{text-align:center;color:#999;border-top:1px solid #ddd;\
padding-top:20px;margin-top:50px;font-size:0.85em}
```

**Step 2 — Detailed findings (append_data):**
For each finding (grouped by severity), generate:
```
<div class="finding">
  <div class="finding-header">
    <h3>{Finding Title}</h3>
    <span class="severity-{level}">{SEVERITY}</span>
  </div>
  <p><strong>Location:</strong> {file}:{line}</p>
  <p><strong>Risk Score:</strong> {score}/10</p>
  <p>{Description}</p>
  <div class="recommendation"><strong>Fix:</strong> {recommendation}</div>
</div>
```

**Step 3 — Remediation roadmap (append_data):**
Table with prioritized fixes: priority, finding, effort, dependencies.

**Step 4 — Close HTML (append_data):**
Footer with disclaimer and closing tags.

**Step 5 — Serve the file:**
serve_file_to_user(filename="security_report.html", label="Security Audit Report", \
open_in_browser=true)

**Step 6 — Present to user (text only):**
Print the file_path and summarize key findings. Ask if they have questions.

**Step 7 — After user responds:**
- set_output("delivery_status", "completed")
""",
    tools=["save_data", "append_data", "load_data", "serve_file_to_user"],
)

__all__ = [
    "intake_node",
    "static_analysis_node",
    "risk_assessment_node",
    "review_node",
    "report_node",
]
