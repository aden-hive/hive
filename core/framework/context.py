
from contextvars import ContextVar

# Track execution depth to prevent infinite recursion
# This is incremented each time AgentRunner.run() is called in the same context
execution_depth: ContextVar[int] = ContextVar("execution_depth", default=0)

MAX_RECURSION_DEPTH = 5
