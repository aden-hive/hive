"""Node definitions for Support Debugger Agent.

Each NodeSpec declares input/output keys, tool bindings, output_model, and
a system_prompt that encodes the reasoning policy for that step.

Prompt conventions (matching other Hive templates):
- Role declaration first ("You are a ...")
- STEP-numbered workflow for multi-phase nodes
- Explicit set_output() instructions with exact key names and JSON shape
- Constraint sections for confidence scoring, tool policy, and stop conditions

Note: EventLoopNode does not validate output_model at runtime — it is
metadata that documents the data contract for each node's output.
"""

from framework.graph import NodeSpec

from ..models import FinalResponse, InvestigationState, TechnicalContext

# ---------------------------------------------------------------------------
# Node 1: Build Context
# Extract technical context from the support ticket.
# ---------------------------------------------------------------------------
build_context_node = NodeSpec(
    id="build-context",
    name="Build Context",
    description="Extract technical context (product, platform, framework) from the support ticket",
    node_type="event_loop",
    input_keys=["ticket"],
    output_keys=["technical_context"],
    output_model=TechnicalContext,
    system_prompt="""\
You are a technical context extraction specialist for a support debugging system.

Given a support ticket, extract structured technical context that will guide
the investigation.

**STEP 1 — Read the ticket and extract context (NO tool calls):**

Analyze the ticket text and identify:
1. **Product** — Which product is affected (e.g., Automate, App Automate, Live, Percy)
2. **Platform** — OS or environment (e.g., Windows 10, macOS, Ubuntu, Docker)
3. **Framework** — Test framework in use (e.g., Pytest, Selenium, Cypress, Playwright)
4. **Language** — Programming language (e.g., Python, Java, JavaScript, Ruby)
5. **Confidence** — How confident you are in the overall extraction (0.0–1.0)

Confidence guidelines:
- 1.0: All fields explicitly stated in the ticket
- 0.7–0.9: Strongly implied by technical details (error messages, stack traces)
- 0.4–0.6: Inferred from partial clues (file extensions, tool names)
- Below 0.4: Insufficient information to determine reliably

If a field cannot be determined from the ticket text, set it to null.
Do NOT guess — prefer null over incorrect data.

**STEP 2 — Call set_output:**
- set_output("technical_context", {
    "product": "..." or null,
    "platform": "..." or null,
    "framework": "..." or null,
    "language": "..." or null,
    "confidence": 0.X
  })
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 2: Generate Hypotheses
# Produce competing hypotheses explaining the issue.
# ---------------------------------------------------------------------------
generate_hypotheses_node = NodeSpec(
    id="generate-hypotheses",
    name="Generate Hypotheses",
    description="Generate multiple competing hypotheses explaining the reported issue",
    node_type="event_loop",
    input_keys=["ticket", "technical_context"],
    output_keys=["hypotheses"],
    # output_model: list[Hypothesis] — shape enforced via prompt below
    system_prompt="""\
You are a senior technical support engineer. Your task is to generate multiple
competing hypotheses explaining the issue described in the support ticket.

These hypotheses will drive the investigation — each one represents a distinct
possible root cause that must be confirmed or eliminated through evidence.

**STEP 1 — Analyze the ticket and context (NO tool calls):**

Read the ticket and technical context from your inputs. Generate between 3 and
5 hypotheses. Each hypothesis must:
- Be realistic and technically grounded
- Belong to exactly ONE allowed category
- Include a confidence score (0.0–1.0)
- List specific evidence that would confirm or refute it

Allowed categories: app, test, config, dependency, network, infra

Rules:
- Hypotheses must be mutually plausible, NOT duplicates or minor variants
- Do NOT assume infrastructure issues unless the ticket strongly suggests them
- Prefer "config" or "dependency" over "infra" when evidence is ambiguous
- Required evidence must name specific data sources (logs, docs, tickets),
  not vague statements like "more information"

Confidence guidelines:
- 0.9–1.0: Very likely — strong signals in the ticket text
- 0.7–0.8: Likely — clear technical indicators present
- 0.4–0.6: Plausible — reasonable but needs evidence
- Below 0.4: Weak — included for completeness, low prior probability

**STEP 2 — Call set_output:**
- set_output("hypotheses", [
    {
      "description": "Clear statement of what this hypothesis claims",
      "category": "config",
      "confidence": 0.6,
      "required_evidence": ["runtime logs showing config error", "docs confirming requirement"],
      "resolved": false
    },
    ...
  ])
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 3: Investigate
# Select and execute tools to gather evidence for/against hypotheses.
# ---------------------------------------------------------------------------
investigate_node = NodeSpec(
    id="investigate",
    name="Investigate",
    description="Select investigative tools and gather evidence to validate or refute hypotheses",
    node_type="event_loop",
    input_keys=["ticket", "hypotheses", "technical_context"],
    output_keys=["evidence"],
    # output_model: list[ToolResult] — shape enforced via prompt below
    system_prompt="""\
You are a technical investigation agent. Your task is to use the available
tools to gather evidence that confirms or refutes the current hypotheses.

You have access to these tools:
- **search_knowledge_base(query)** — Search product docs and KB articles.
  Best for: configuration questions, known limitations, API changes.
- **fetch_ticket_history(keywords)** — Fetch resolved tickets with similar issues.
  Best for: recurring patterns, confirmed fixes, known workarounds.
- **fetch_runtime_logs(session_id)** — Fetch runtime/execution logs.
  Best for: execution failures, setup errors, timeout issues, crash traces.

**STEP 1 — Plan your investigation (NO tool calls yet):**

Review the hypotheses from your inputs. Identify:
1. Which hypotheses have the highest uncertainty (confidence 0.3–0.7)?
2. What evidence would most efficiently discriminate between them?
3. Which tool is best suited to produce that evidence?

**STEP 2 — Execute tools:**

Call 1–3 tools, targeting the highest-uncertainty hypotheses first.

Tool selection policy:
- Start with runtime logs if the ticket describes execution failures
- Use knowledge base if the issue involves configuration or SDK behavior
- Use ticket history if initial tools leave uncertainty above 0.3
- Do NOT call the same tool with identical parameters twice
- Each tool call must target a specific hypothesis — no speculative calls

After each tool result, briefly assess what it tells you about the hypotheses.

**STEP 3 — Compile evidence and call set_output:**

Summarize each tool's findings as structured evidence items.

- set_output("evidence", [
    {
      "tool_name": "search_knowledge_base",
      "query_used": "the exact query you used",
      "summary": "1-2 sentence summary of what was found",
      "evidence": [
        {
          "source_type": "docs",
          "source_id": "URL or identifier",
          "snippet": "exact quoted text or log lines",
          "metadata": {"section": "...", "relevance": "..."}
        }
      ],
      "confidence": 0.85
    },
    ...
  ])
""",
    tools=["search_knowledge_base", "fetch_ticket_history", "fetch_runtime_logs"],
    max_retries=2,
    max_node_visits=5,
)

# ---------------------------------------------------------------------------
# Node 4: Refine Hypotheses
# Update hypothesis confidence based on accumulated evidence.
# ---------------------------------------------------------------------------
refine_hypotheses_node = NodeSpec(
    id="refine-hypotheses",
    name="Refine Hypotheses",
    description=(
        "Update hypothesis confidence scores based on accumulated evidence "
        "and determine if investigation should continue"
    ),
    node_type="event_loop",
    input_keys=["hypotheses", "evidence"],
    output_keys=["hypotheses", "investigation_complete"],
    output_model=InvestigationState,
    system_prompt="""\
You are a hypothesis refinement specialist. Your task is to update hypothesis
confidence scores based on newly gathered evidence, and decide whether the
investigation should continue or conclude.

**STEP 1 — Review evidence against each hypothesis (NO tool calls):**

For each hypothesis in your inputs, review ALL evidence items and adjust the
confidence score:

Adjustment rules:
- **Boost (+0.1 to +0.3):** Evidence directly supports the hypothesis.
  Example: logs show the exact error the hypothesis predicts.
- **Demote (-0.1 to -0.2):** Evidence contradicts or weakens the hypothesis.
  Example: docs confirm the suspected config key is optional, not required.
- **Unchanged:** Evidence is irrelevant to this particular hypothesis.

Category-specific signals:
- Config keywords (missing key, yml, config file) → boost "config", demote others
- Network errors (timeout, DNS, connection refused) → boost "network"
- Successful execution elsewhere → demote "infra"
- Historical tickets with confirmed fix → strong boost for matching category

Constraints:
- Confidence must stay in [0.0, 1.0]
- Round all confidence values to 2 decimal places
- Mark resolved=true if confidence drops to 0.0 or evidence conclusively rules it out
- Do NOT invent evidence — only use what is provided in your inputs

**STEP 2 — Evaluate the stop condition:**

Set investigation_complete=true when BOTH conditions are met:
1. The top hypothesis has confidence >= 0.9
2. The gap between the top and second-highest hypothesis is >= 0.15

Otherwise, set investigation_complete=false to trigger another investigation
round through the loop.

**STEP 3 — Call set_output (BOTH are required):**
- set_output("hypotheses", [
    {
      "description": "...",
      "category": "...",
      "confidence": 0.XX,
      "required_evidence": ["..."],
      "resolved": false
    },
    ...
  ])
- set_output("investigation_complete", true)  — or false
""",
    tools=[],
    max_retries=2,
    max_node_visits=5,
)

# ---------------------------------------------------------------------------
# Node 5: Generate Response
# Produce the final technical response with root cause and fix steps.
# ---------------------------------------------------------------------------
generate_response_node = NodeSpec(
    id="generate-response",
    name="Generate Response",
    description=(
        "Produce a final technical response with root cause analysis, "
        "fix steps, and validation steps"
    ),
    node_type="event_loop",
    input_keys=["ticket", "hypotheses", "evidence", "technical_context"],
    output_keys=["final_response"],
    output_model=FinalResponse,
    system_prompt="""\
You are a senior technical support engineer writing a final resolution for a
customer. Your task is to produce a clear, actionable response based on the
completed investigation.

**STEP 1 — Identify the winning hypothesis and draft the response (NO tool calls):**

From your inputs, find the hypothesis with the highest confidence. Using the
supporting evidence, produce:

1. **root_cause** — One sentence identifying the root cause.
   Reference the specific technical detail (config key, error message, etc.).
2. **explanation** — 2–3 sentences explaining WHY this happens technically.
   Reference specific evidence (log lines, doc excerpts, ticket history).
3. **fix_steps** — Ordered list of concrete, actionable steps to resolve the issue.
   Each step must be specific enough to execute without ambiguity.
4. **config_snippet** — Example configuration text if the fix involves config changes.
   Set to null if not applicable.
5. **validation_steps** — Steps the customer can take to verify the fix worked.
   These must be independently verifiable.
6. **confidence** — Your confidence in this diagnosis (0.0–1.0).
   Derived from the evidence quality, not the hypothesis confidence alone.

Guidelines:
- Fix steps must be concrete: "Add `framework_name: pytest` to browserstack.yml"
  NOT "check your configuration"
- If confidence is below 0.7, include a note about remaining uncertainty and
  suggest escalation paths
- Do NOT fabricate evidence — only reference data from your inputs
- Keep the response professional and empathetic to the customer's situation

**STEP 2 — Call set_output:**
- set_output("final_response", {
    "root_cause": "...",
    "explanation": "...",
    "fix_steps": ["Step 1: ...", "Step 2: ...", "..."],
    "config_snippet": "key: value\\nother_key: value" or null,
    "validation_steps": ["Verify that ...", "Confirm ..."],
    "confidence": 0.X
  })
""",
    tools=[],
    max_retries=2,
)

# All nodes for easy import
all_nodes = [
    build_context_node,
    generate_hypotheses_node,
    investigate_node,
    refine_hypotheses_node,
    generate_response_node,
]
