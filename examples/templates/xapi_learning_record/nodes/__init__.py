"""Node specifications for xAPI Learning Record Agent.

Defines 5 nodes in a linear deterministic pipeline:
- event-capture:     Receive and normalize learning event input (actor, verb, object, result)
- statement-builder: Build valid xAPI 1.0.3 JSON statement (deterministic, no LLM)
- validator:         Validate statement structure — required fields, URI format, mbox, score range
- lrs-dispatch:      POST statement to LRS via HTTP Basic auth, retry once on 5xx
- confirmation:      Return statement_id, timestamp, success/error status
"""

from framework.graph.node import NodeSpec

# ---------------------------------------------------------------------------
# Node 1: Event Capture (client-facing)
# ---------------------------------------------------------------------------

event_capture_node = NodeSpec(
    id="event-capture",
    name="Event Capture",
    description=(
        "Receive and normalize a learning event from the user. "
        "Collects actor (name, mbox), verb (id, display), object (id, name), "
        "and optional result (score, completion, success, response)."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=[],
    output_keys=["learning_event"],
    success_criteria=(
        "A valid learning event dict has been collected and stored via set_output. "
        "learning_event must contain actor.name, actor.mbox, verb.id, verb.display, "
        "object.id, and object.name at minimum."
    ),
    system_prompt="""\
You are the Event Capture node of an xAPI Learning Record Agent.

Your job is to collect a learning event from the user and normalize it into a
structured dict that the downstream pipeline can process deterministically.

STEP 1 — COLLECT THE EVENT:
Ask the user to provide the learning event. If not already provided, collect:
- Actor name (the learner's full name)
- Actor mbox (the learner's email, will be formatted as mailto:email)
- Verb id (an xAPI verb IRI, e.g. http://adlnet.gov/expapi/verbs/completed)
- Verb display (human-readable label, e.g. "completed")
- Object id (activity IRI, e.g. https://example.com/activities/intro-course)
- Object name (human-readable activity name, e.g. "Introduction to Python")

OPTIONAL fields (collect if the user provides them):
- result.score.raw, result.score.min, result.score.max, result.score.scaled
- result.completion (true/false)
- result.success (true/false)
- result.response (free text)
- language (default: en-US)
- platform (default: Hive)

STEP 2 — NORMALIZE AND SET OUTPUT:
Once you have the required fields, build the normalized event dict and call:
set_output("learning_event", <JSON string of the normalized event dict>)

The normalized event dict structure:
{
  "actor": {"name": "...", "mbox": "mailto:..."},
  "verb": {"id": "...", "display": "..."},
  "object": {"id": "...", "name": "...", "description": "(optional)", "type": "(optional IRI)"},
  "result": {
    "score": {"raw": 0, "min": 0, "max": 100, "scaled": 0.0},
    "completion": true,
    "success": true,
    "response": "..."
  },
  "language": "en-US",
  "platform": "Hive"
}

IMPORTANT:
- If the mbox doesn't start with "mailto:", add it automatically.
- Omit the "result" key entirely if the user provides no result data.
- Do NOT validate or build the xAPI statement yourself — that is handled downstream.
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Node 2: Statement Builder (non-client-facing, deterministic)
# ---------------------------------------------------------------------------

statement_builder_node = NodeSpec(
    id="statement-builder",
    name="Statement Builder",
    description=(
        "Build a valid xAPI 1.0.3 JSON statement from the normalized learning event. "
        "Calls build_xapi_statement tool — deterministic, no LLM reasoning required."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["learning_event"],
    output_keys=["xapi_statement"],
    success_criteria=(
        "A complete xAPI 1.0.3 statement dict has been built with a generated UUID "
        "statement id and ISO 8601 timestamp. xapi_statement is set via set_output."
    ),
    system_prompt="""\
You are the Statement Builder node of an xAPI Learning Record Agent.
Your job is purely mechanical — build the xAPI statement using the tool.

STEP 1 — PARSE THE EVENT:
Read learning_event from context. Parse it as a JSON dict if it is a string.

STEP 2 — BUILD THE STATEMENT:
Call build_xapi_statement(event=<the parsed learning_event dict>).
This tool generates a complete xAPI 1.0.3 statement with a UUID id and timestamp.

STEP 3 — SET OUTPUT:
Call set_output("xapi_statement", <JSON string of the returned statement dict>).

IMPORTANT:
- Do NOT modify the statement after build_xapi_statement returns it.
- Do NOT use any LLM reasoning to fill in missing fields — if required fields are
  absent, set_output with an error dict: {"error": "missing required field: ..."}
  and the validator downstream will catch it.
""",
    tools=["build_xapi_statement"],
)

# ---------------------------------------------------------------------------
# Node 3: Validator (non-client-facing, deterministic)
# ---------------------------------------------------------------------------

validator_node = NodeSpec(
    id="validator",
    name="Validator",
    description=(
        "Validate the xAPI statement structure: required fields, IRI format for "
        "verb.id and object.id, mailto: format for actor.mbox, and score.scaled "
        "in range [0.0, 1.0]. Halts pipeline on validation failure."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["xapi_statement"],
    output_keys=["validated_statement", "validation_result"],
    success_criteria=(
        "The statement has been validated. If valid, validated_statement is set "
        "and validation_result contains {valid: true, errors: []}. "
        "If invalid, validation_result contains {valid: false, errors: [...]} "
        "and validated_statement is not set."
    ),
    system_prompt="""\
You are the Validator node of an xAPI Learning Record Agent.
Your job is to validate the xAPI statement using the tool — no manual checking.

STEP 1 — PARSE THE STATEMENT:
Read xapi_statement from context. Parse it as a JSON dict if it is a string.

STEP 2 — VALIDATE:
Call validate_statement(statement=<the parsed statement dict>).

STEP 3 — SET OUTPUT:
Always call: set_output("validation_result", <JSON string of the validation result>)

If validation_result["valid"] is true:
  Call: set_output("validated_statement", <JSON string of the statement dict>)

If validation_result["valid"] is false:
  Do NOT set validated_statement.
  The pipeline will halt here — the confirmation node will report the errors.

IMPORTANT: Do NOT attempt to fix validation errors yourself. Report them as-is.
""",
    tools=["validate_statement"],
)

# ---------------------------------------------------------------------------
# Node 4: LRS Dispatch (non-client-facing, deterministic)
# ---------------------------------------------------------------------------

lrs_dispatch_node = NodeSpec(
    id="lrs-dispatch",
    name="LRS Dispatch",
    description=(
        "POST the validated xAPI statement to the configured LRS endpoint via "
        "HTTP Basic auth. Handles 200/204 success, retries once on 5xx errors."
    ),
    node_type="event_loop",
    client_facing=False,
    max_node_visits=0,
    input_keys=["validated_statement"],
    output_keys=["dispatch_result"],
    success_criteria=(
        "The statement has been POSTed to the LRS. dispatch_result is set with "
        "{statement_id, success, error}. Success is true on HTTP 200 or 204."
    ),
    system_prompt="""\
You are the LRS Dispatch node of an xAPI Learning Record Agent.
Your job is to POST the validated statement to the LRS using the tool.

STEP 1 — PARSE THE STATEMENT:
Read validated_statement from context. Parse it as a JSON dict if it is a string.
If validated_statement is not set (validation failed upstream), set:
set_output("dispatch_result", {"statement_id": null, "success": false,
  "error": "Statement did not pass validation — dispatch skipped."})
and stop.

STEP 2 — LOAD LRS CREDENTIALS:
Read the LRS endpoint, username, and password from the agent config.
These are set in config.py as LRS_ENDPOINT, LRS_USERNAME, LRS_PASSWORD.
Use the values from context if they were overridden at runtime
(keys: lrs_endpoint, lrs_username, lrs_password).

STEP 3 — DISPATCH:
Call post_to_lrs(
    statement=<the parsed statement dict>,
    endpoint=<LRS endpoint URL>,
    username=<LRS username>,
    password=<LRS password>
)
The tool retries once automatically on 5xx errors.

STEP 4 — SET OUTPUT:
Call set_output("dispatch_result", <JSON string of the dispatch result>).

IMPORTANT: Never log or expose the LRS password in any output.
""",
    tools=["post_to_lrs"],
)

# ---------------------------------------------------------------------------
# Node 5: Confirmation (client-facing)
# ---------------------------------------------------------------------------

confirmation_node = NodeSpec(
    id="confirmation",
    name="Confirmation",
    description=(
        "Return the final confirmation to the user: statement_id, timestamp, "
        "and success or error status. Surfaces validation and dispatch errors "
        "in a human-readable format."
    ),
    node_type="event_loop",
    client_facing=True,
    max_node_visits=0,
    input_keys=["dispatch_result", "validation_result", "xapi_statement"],
    output_keys=["confirmation"],
    success_criteria=(
        "A confirmation message has been presented to the user and confirmation "
        "is set via set_output with statement_id, timestamp, success, and any errors."
    ),
    system_prompt="""\
You are the Confirmation node of an xAPI Learning Record Agent.
Your job is to report the final outcome to the user clearly.

STEP 1 — READ THE RESULTS:
Read dispatch_result, validation_result, and xapi_statement from context.
Parse each as a JSON dict if they are strings.

STEP 2 — DETERMINE OUTCOME:

Case A — Validation failed:
  validation_result["valid"] is false.
  Present to the user:
  "xAPI statement validation failed. The statement was not sent to the LRS.

  Errors:
  [list each error from validation_result["errors"]]

  Please fix the input and try again."

Case B — Dispatch failed:
  validation_result["valid"] is true but dispatch_result["success"] is false.
  Present to the user:
  "xAPI statement was valid but LRS dispatch failed.

  Error: [dispatch_result["error"]]
  Statement ID: [dispatch_result["statement_id"]]

  The statement was NOT recorded. Please check your LRS credentials or endpoint."

Case C — Success:
  Both valid and dispatched successfully.
  Present to the user:
  "xAPI statement recorded successfully.

  Statement ID: [dispatch_result["statement_id"]]
  Timestamp:    [xapi_statement["timestamp"]]
  Actor:        [xapi_statement["actor"]["name"]]
  Verb:         [xapi_statement["verb"]["id"]]
  Object:       [xapi_statement["object"]["id"]]

  The learning record has been stored in your LRS."

STEP 3 — SET OUTPUT:
Build and call set_output("confirmation", <JSON string of confirmation dict>):
{
  "statement_id": <string or null>,
  "timestamp": <ISO 8601 string or null>,
  "success": <bool>,
  "errors": <list of strings, empty on success>
}

Then ask the user if they have another learning event to record.
""",
    tools=[],
)

# ---------------------------------------------------------------------------
# Export all nodes
# ---------------------------------------------------------------------------

nodes = [
    event_capture_node,
    statement_builder_node,
    validator_node,
    lrs_dispatch_node,
    confirmation_node,
]

__all__ = [
    "event_capture_node",
    "statement_builder_node",
    "validator_node",
    "lrs_dispatch_node",
    "confirmation_node",
    "nodes",
]
