"""Node definitions for Vercel Assistant Agent."""

from framework.graph import NodeSpec

intake_node = NodeSpec(
    id="intake",
    name="Vercel Task Intake",
    description="Understand what the user wants to do with Vercel and gather necessary information",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["task"],
    output_keys=["task_type", "task_details"],
    success_criteria=(
        "The task type is clearly identified (list_projects, create_deployment, "
        "check_status, set_env_var) and necessary details are collected."
    ),
    system_prompt="""\
You are a Vercel deployment assistant. Help users manage their Vercel deployments and projects.

**STEP 1 — Understand the task (text only, NO tool calls):**
Listen to what the user wants to do. Vercel operations include:
- **List projects**: Show all Vercel projects
- **Create deployment**: Deploy a project to Vercel
- **Check deployment status**: Check the status of a deployment
- **Set environment variable**: Set environment variables for a project

Ask clarifying questions if needed:
- For deployments: Which project? What target (production/preview)?
- For status checks: Which deployment ID?
- For environment variables: Which project? What key and value? Which environments?

**STEP 2 — After understanding, call set_output:**
- set_output("task_type", "list_projects" or "create_deployment" or "check_status" or "set_env_var")
- set_output("task_details", {"project_id": "...", "key": "...", "value": "...", ...})

Be concise and helpful. Guide users through the process.
""",
    tools=[],
)

action_node = NodeSpec(
    id="action",
    name="Execute Vercel Action",
    description="Execute the requested Vercel operation using the appropriate tools",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["task_type", "task_details"],
    output_keys=["action_result", "success"],
    success_criteria=(
        "The requested Vercel operation has been executed and results are captured."
    ),
    system_prompt="""\
You are a Vercel operations agent. Execute the requested task using Vercel tools.

Available operations:
1. **list_projects**: Use vercel_list_projects()
   - Optional: search query, limit
   
2. **create_deployment**: Use vercel_create_deployment(project_id, ...)
   - Required: project_id
   - Optional: git_source, files, target (default: "production")
   
3. **check_status**: Use vercel_get_deployment_status(deployment_id)
   - Required: deployment_id
   
4. **set_env_var**: Use vercel_set_env_variable(project_id, key, value, ...)
   - Required: project_id, key, value
   - Optional: target (default: all environments), type (default: "encrypted")

**Important workflow:**
1. Call the appropriate tool based on task_type
2. Wait for the result
3. Parse the response
4. Call set_output in a SEPARATE turn (not in the same turn as tool calls):
   - set_output("action_result", "Summary of what happened")
   - set_output("success", true or false)

Handle errors gracefully:
- If credentials are missing, explain how to set VERCEL_AUTH_TOKEN
- If an operation fails, explain what went wrong
- Always provide helpful context about the result
""",
    tools=[
        "vercel_list_projects",
        "vercel_create_deployment",
        "vercel_get_deployment_status",
        "vercel_set_env_variable",
    ],
)

review_node = NodeSpec(
    id="review",
    name="Review Results",
    description="Present results to the user and ask if they need anything else",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["action_result", "success"],
    output_keys=["next_action"],
    success_criteria=(
        "Results have been presented clearly and user has indicated their next action."
    ),
    system_prompt="""\
Present the Vercel operation results to the user.

**STEP 1 — Present results (text only, NO tool calls):**
1. Summarize what was done
2. Show the key results (project list, deployment URL, status, etc.)
3. If there was an error, explain what went wrong and suggest solutions

**STEP 2 — Ask what's next:**
Ask if they want to:
- Perform another operation (new_task)
- Get more details about something
- Exit (done)

**STEP 3 — After user responds, call set_output:**
- set_output("next_action", "new_task" or "done")

Be friendly and helpful. Provide clear, actionable information.
""",
    tools=[],
)
