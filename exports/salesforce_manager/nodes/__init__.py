"""Node definitions for Salesforce Manager Agent."""

from framework.graph import NodeSpec

# Node 1: Intake (client-facing)
intake_node = NodeSpec(
    id="intake",
    name="Salesforce Intake",
    description="Identify the Salesforce task the user wants to perform",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["user_query"],
    output_keys=["salesforce_brief"],
    system_prompt="""
You are a Salesforce CRM assistant. The user wants to perform an action in Salesforce.
Actions can include:
- Searching for leads, contacts, or opportunities
- Creating or updating records
- Running SOQL queries
- Describing object schemas

Discuss with the user to clarify exactly what they want to do.
1. If the request is clear, summarize it and ask for confirmation.
2. If it's vague, ask clarifying questions.

When the task is clear and confirmed, use set_output:
- set_output("salesforce_brief", "A clear description of the Salesforce task, including any specific filters, record names, or SOQL queries.")
""",
    tools=[],
)

# Node 2: Salesforce Manager
salesforce_manager_node = NodeSpec(
    id="salesforce_manager",
    name="Salesforce Manager",
    description="Execute Salesforce CLI tools and manage records",
    node_type="event_loop",
    max_node_visits=0,
    input_keys=["salesforce_brief"],
    output_keys=["salesforce_result"],
    system_prompt="""
You are a Salesforce operations specialist. Your goal is to execute the task described in the salesforce_brief.

You have access to a variety of Salesforce tools:
- salesforce_query: For custom SOQL queries
- salesforce_create_record / salesforce_update_record: For record management
- salesforce_search_leads / salesforce_search_contacts / salesforce_search_opportunities: For quick searches
- salesforce_describe_object: To understand field names and types

Instructions:
1. Select the appropriate tool for the brief.
2. Execute the tool(s) and analyze the results.
3. If more steps are needed (e.g., getting a record ID before updating), perform them.
4. Once the task is complete, summarize the results.

When done, use set_output:
- set_output("salesforce_result", "A detailed summary of the actions taken and the data retrieved or modified.")
""",
    tools=[
        "salesforce_query",
        "salesforce_create_record",
        "salesforce_update_record",
        "salesforce_get_record",
        "salesforce_describe_object",
        "salesforce_search_leads",
        "salesforce_search_contacts",
        "salesforce_search_opportunities",
    ],
)

# Node 3: Output (client-facing)
output_node = NodeSpec(
    id="output",
    name="Salesforce Output",
    description="Present the final results to the user",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["salesforce_result"],
    output_keys=["next_action"],
    system_prompt="""
Present the results of the Salesforce operation to the user in a professional and clear format.

1. Summarize the successful actions.
2. Display the relevant data (leads found, record ID created, etc.).
3. Ask the user if they have any follow-up tasks or if they are finished.

When the user responds, if they want to do something new, use set_output:
- set_output("next_action", "new_task")
Otherwise, if they are done:
- set_output("next_action", "exit")
""",
    tools=[],
)

__all__ = [
    "intake_node",
    "salesforce_manager_node",
    "output_node",
]
