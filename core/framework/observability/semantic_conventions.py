"""Semantic conventions for Hive agent observability.

Follows OpenTelemetry GenAI semantic conventions where applicable,
with Hive-specific extensions prefixed ``hive.``.

See: https://opentelemetry.io/docs/specs/semconv/gen-ai/
"""

# -- Span names --
SPAN_AGENT_RUN = "agent.run"
SPAN_NODE_EXECUTE = "node.execute"
SPAN_TOOL_CALL = "tool.call"

# -- Resource attributes --
ATTR_FRAMEWORK_NAME = "agent.framework.name"
ATTR_FRAMEWORK_VERSION = "agent.framework.version"
FRAMEWORK_NAME = "hive"

# -- Run attributes --
ATTR_RUN_ID = "hive.run.id"
ATTR_GOAL_ID = "hive.goal.id"
ATTR_RUN_STATUS = "hive.run.status"
ATTR_RUN_DURATION_MS = "hive.run.duration_ms"

# -- Node attributes --
ATTR_NODE_ID = "hive.node.id"
ATTR_NODE_NAME = "hive.node.name"
ATTR_NODE_TYPE = "hive.node.type"
ATTR_NODE_LATENCY_MS = "hive.node.latency_ms"
ATTR_NODE_SUCCESS = "hive.node.success"

# -- LLM / token attributes (aligned with OTel GenAI semconv) --
ATTR_LLM_TOKENS_INPUT = "gen_ai.usage.input_tokens"
ATTR_LLM_TOKENS_OUTPUT = "gen_ai.usage.output_tokens"
ATTR_LLM_TOKENS_TOTAL = "gen_ai.usage.total_tokens"

# -- Decision attributes --
ATTR_DECISION_ID = "hive.decision.id"
ATTR_DECISION_INTENT = "hive.decision.intent"
ATTR_DECISION_CHOSEN = "hive.decision.chosen"
ATTR_DECISION_OPTIONS_COUNT = "hive.decision.options_count"

# -- Tool attributes --
ATTR_TOOL_NAME = "hive.tool.name"
ATTR_TOOL_IS_ERROR = "hive.tool.is_error"
ATTR_TOOL_LATENCY_MS = "hive.tool.latency_ms"

# -- Metric names --
METRIC_RUNS_TOTAL = "hive.agent.runs.total"
METRIC_NODE_DURATION = "hive.node.duration"
METRIC_TOKENS_USED = "hive.llm.tokens.used"
METRIC_DECISIONS_TOTAL = "hive.decisions.total"
METRIC_TOOL_CALLS_TOTAL = "hive.tool.calls.total"
METRIC_NODE_ERRORS_TOTAL = "hive.node.errors.total"
