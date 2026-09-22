"""Node definitions for Procurement Approval Agent."""

from framework.graph import NodeSpec

# Node 0: First-run setup wizard
setup_wizard_node = NodeSpec(
    id="setup-wizard",
    name="Setup Wizard",
    description="First-run onboarding for QuickBooks integration preference",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=[],
    output_keys=["setup_completed", "preferred_sync_method"],
    system_prompt="""\
You are the onboarding setup wizard for Procurement Approval Agent.

Only run this during first execution.

Ask the user:
"Do you have QuickBooks API credentials configured? (yes/no)"

If yes:
- explain API sync mode and that credentials should be configured
- set_output("preferred_sync_method", "api")

If no:
- explain CSV fallback workflow for manual import
- set_output("preferred_sync_method", "csv")

Then always:
- set_output("setup_completed", true)
""",
    tools=[],
)

# Node 1: Intake - Receives purchase request
pre_execution_check_node = NodeSpec(
    id="pre-execution-check",
    name="Execution Confirmation",
    description="Confirm whether to process this request now",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["item", "cost", "department", "requester"],
    output_keys=["process_request"],
    system_prompt="""\
You are an execution gate for procurement processing.

Ask:
"Do you want to process this purchase request now? (yes/no)"

If yes:
- set_output("process_request", true)
If no:
- set_output("process_request", false)
""",
    tools=[],
)

request_cancelled_node = NodeSpec(
    id="request-cancelled",
    name="Request Cancelled",
    description="Terminal node when user chooses not to process request",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["item", "requester"],
    output_keys=["request_cancelled"],
    system_prompt="""\
You are a cancellation handler.

The user chose not to process this request now.
Call:
- set_output("request_cancelled", true)
""",
    tools=[],
)


intake_node = NodeSpec(
    id="intake",
    name="Request Intake",
    description="Validate and parse purchase request",
    node_type="event_loop",
    client_facing=False,
    input_keys=["item", "cost", "justification", "requester", "department", "vendor"],
    output_keys=["validated_request"],
    system_prompt="""\
You are a purchase request validator.

Your task:
1. Check all required fields are present: item, cost, justification, requester, department.
2. Validate cost is a positive number.
3. Ensure justification is at least 10 words.
4. Normalize vendor to "Unknown" when not provided.

If validation passes:
- call set_output("validated_request", {...}) with item, cost, justification, requester, department, vendor

If validation fails:
- explain what failed in plain language
- do not set outputs
""",
    tools=[],
)

# Node 2: Budget Check
budget_check_node = NodeSpec(
    id="budget-check",
    name="Budget Validation",
    description="Check if request fits within department budget",
    node_type="event_loop",
    client_facing=False,
    input_keys=["validated_request"],
    output_keys=["budget_status", "remaining_budget"],
    system_prompt="""\
You are a budget validator.

Task:
1. Use load_data to read `data/budget_tracking.db`.
2. Compute remaining_budget = allocated - spent for the request department.
3. Determine budget_status:
   - cost <= remaining_budget * 0.9  => auto_approved
   - cost <= remaining_budget        => needs_approval
   - cost > remaining_budget         => denied

Then call:
- set_output("budget_status", "auto_approved" | "needs_approval" | "denied")
- set_output("remaining_budget", <number>)

If department is missing in budget data:
- set_output("budget_status", "denied")
- set_output("remaining_budget", 0)
""",
    tools=["load_data"],
)

# Node 3: Manager Approval - client-facing node
approval_node = NodeSpec(
    id="manager-approval",
    name="Manager Approval",
    description="Get manager approval for purchase request",
    node_type="event_loop",
    client_facing=True,
    input_keys=["validated_request", "budget_status", "remaining_budget"],
    output_keys=["approval_decision", "approver_name"],
    nullable_output_keys=["approver_name"],
    max_node_visits=1,
    system_prompt="""\
You are a procurement approval interface.

STEP 1 - Present the request details clearly to the manager and ask:
"Do you approve this request? (yes/no)"

Include:
- Item
- Cost
- Department
- Requester
- Justification
- Budget impact (cost vs remaining budget)

STEP 2 - After manager response, set outputs:
- approved => set_output("approval_decision", "approved") and set_output("approver_name", "Manager")
- rejected => set_output("approval_decision", "rejected")
""",
    tools=[],
)

# Node 4: Vendor Check
vendor_check_node = NodeSpec(
    id="vendor-check",
    name="Vendor Validation",
    description="Check whether vendor is on approved list",
    node_type="event_loop",
    client_facing=False,
    input_keys=["validated_request"],
    output_keys=["vendor_approved"],
    system_prompt="""\
Check whether validated_request.vendor appears in `data/approved_vendors.csv`.

Use load_data to read the CSV and set:
- set_output("vendor_approved", true/false)

Comparison should be case-insensitive.
""",
    tools=["load_data"],
)

# Node 5: Generate PO
po_generator_node = NodeSpec(
    id="po-generator",
    name="PO Generator",
    description="Generate purchase order documents",
    node_type="event_loop",
    client_facing=False,
    input_keys=["validated_request"],
    output_keys=["po_number", "po_data", "po_files_created"],
    system_prompt="""\
Generate a Purchase Order for the approved request.

1. Build PO number in format: PO-YYYYMMDD-XXX.
2. Create structured PO JSON.
3. Create human-readable text summary.
4. Create a QuickBooks-compatible CSV.

Use save_data to create files under data/po/:
- <po_number>.json
- <po_number>.txt
- <po_number>_qb_import.csv

Then call:
- set_output("po_number", <po_number>)
- set_output("po_data", <po_json_dict>)
- set_output("po_files_created", [<json>, <txt>, <csv>])
""",
    tools=["save_data"],
)

# Node 6: Integration Check
integration_setup_check_node = NodeSpec(
    id="integration-setup-check",
    name="Integration Setup Check",
    description="Ask whether API credentials are available for this request",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["po_number"],
    output_keys=["declared_qb_api_available", "declared_sync_preference"],
    system_prompt="""\
You are an integration setup checkpoint.

Ask:
"Do you have QuickBooks API credentials configured for this run? (yes/no)"

If yes:
- set_output("declared_qb_api_available", true)
- set_output("declared_sync_preference", "api")
If no:
- set_output("declared_qb_api_available", false)
- set_output("declared_sync_preference", "csv")
""",
    tools=[],
)


integration_check_node = NodeSpec(
    id="integration-check",
    name="Integration Capability Check",
    description="Detect whether QuickBooks API credentials are available",
    node_type="event_loop",
    client_facing=False,
    input_keys=["po_number", "po_data"],
    output_keys=["has_qb_api", "sync_method"],
    system_prompt="""\
Determine whether QuickBooks API credentials are available.

Set:
- has_qb_api: true/false
- sync_method: "api" if credentials exist, otherwise "csv"

Always call:
- set_output("has_qb_api", <true_or_false>)
- set_output("sync_method", "api" | "csv")
""",
    tools=[],
)

pre_sync_confirmation_node = NodeSpec(
    id="pre-sync-confirmation",
    name="Pre-Sync Confirmation",
    description="Final yes/no confirmation before sync/export",
    node_type="event_loop",
    client_facing=True,
    max_node_visits=1,
    input_keys=["sync_method", "po_number"],
    output_keys=["sync_confirmed"],
    system_prompt="""\
You are a final sync gate.

Ask:
"Proceed with {{sync_method}} step for purchase order {{po_number}}? (yes/no)"

If yes:
- set_output("sync_confirmed", true)
If no:
- set_output("sync_confirmed", false)
""",
    tools=[],
)

sync_cancelled_node = NodeSpec(
    id="sync-cancelled",
    name="Sync Cancelled",
    description="Terminal node when user declines final sync/export",
    node_type="event_loop",
    client_facing=False,
    max_node_visits=1,
    input_keys=["po_number", "sync_method"],
    output_keys=["sync_cancelled"],
    system_prompt="""\
You are a sync cancellation handler.

The user declined the final sync/export step.
Call:
- set_output("sync_cancelled", true)
""",
    tools=[],
)

# Node 7: QuickBooks Sync
quickbooks_sync_node = NodeSpec(
    id="quickbooks-sync",
    name="QuickBooks Sync",
    description="Sync generated PO to QuickBooks API",
    node_type="event_loop",
    client_facing=False,
    input_keys=["po_number", "po_data"],
    output_keys=["qb_po_id", "sync_status"],
    system_prompt="""\
Sync the PO to QuickBooks.

Inputs:
- po_number
- po_data

For mock testing mode, simulate the API call and return:
- qb_po_id (fake QuickBooks PO ID)
- sync_status = "mock_synced"

For real mode (future):
- use QuickBooks credentials and API endpoints
- return actual qb_po_id and status

Always call:
- set_output("qb_po_id", <id>)
- set_output("sync_status", <status>)
""",
    tools=[],
)

# Node 8: CSV Export (fallback path)
csv_export_node = NodeSpec(
    id="csv-export",
    name="QuickBooks CSV Export",
    description="Generate CSV + instructions when API sync is unavailable",
    node_type="event_loop",
    client_facing=False,
    input_keys=["po_number", "po_data"],
    output_keys=["csv_file_path", "import_instructions"],
    system_prompt="""\
Generate fallback QuickBooks import artifacts for manual upload.

Create:
1. A QuickBooks-compatible CSV file
2. A markdown instructions file describing import steps

Then call:
- set_output("csv_file_path", <path_to_csv>)
- set_output("import_instructions", <path_to_markdown_instructions>)
""",
    tools=["save_data"],
)

# Node 9: Notification Generator
notification_node = NodeSpec(
    id="notifications",
    name="Generate Notifications",
    description="Create notification files for stakeholders",
    node_type="event_loop",
    client_facing=False,
    input_keys=["validated_request", "po_number", "po_files_created", "sync_method"],
    output_keys=["notifications_created"],
    system_prompt="""\
Create notification markdown files under data/notifications/:
1. notification_requester_<po_number>.md
2. notification_finance_<po_number>.md
3. notification_manager_<po_number>.md

Use save_data to write these files and then:
- set_output("notifications_created", [file1, file2, file3])
""",
    tools=["save_data"],
)

__all__ = [
    "setup_wizard_node",
    "pre_execution_check_node",
    "request_cancelled_node",
    "intake_node",
    "budget_check_node",
    "approval_node",
    "vendor_check_node",
    "po_generator_node",
    "integration_setup_check_node",
    "integration_check_node",
    "pre_sync_confirmation_node",
    "sync_cancelled_node",
    "quickbooks_sync_node",
    "csv_export_node",
    "notification_node",
]
