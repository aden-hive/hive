"""
Centralized constants for the Aden Hive Framework.

This file aggregates magic numbers, model names, and configuration thresholds
to ensure consistency and testability across the codebase.
"""

# =============================================================================
# LLM MODELS
# =============================================================================
# Default model used for routing, decision making, and standard nodes
DEFAULT_ROUTING_MODEL = "claude-haiku-4-5-20251001"

# Model used for JSON extraction fallback (when regex fails)
DEFAULT_CLEANUP_MODEL = "claude-haiku-4-5-20251001"

# Model used for generating node output summaries
DEFAULT_SUMMARY_MODEL = "claude-haiku-4-5-20251001"


# =============================================================================
# THRESHOLDS & LIMITS
# =============================================================================
# Character limit for detecting if a string contains code (security/validation)
CODE_DETECTION_CHAR_LIMIT = 5000

# Maximum history size for shared state changes
MAX_STATE_HISTORY = 1000

# Maximum number of execution results to retain
MAX_EXECUTION_HISTORY = 1000

# Maximum history size for the event bus
MAX_EVENT_HISTORY = 1000


# =============================================================================
# STORAGE & RUNTIME
# =============================================================================
# Default interval for batch processing in seconds
DEFAULT_BATCH_INTERVAL_SEC = 0.1

# Maximum number of items to process in a single batch
DEFAULT_MAX_BATCH_SIZE = 100

# Default Time-To-Live for cache entries in seconds
DEFAULT_CACHE_TTL_SEC = 60.0


# =============================================================================
# RETRY LOGIC
# =============================================================================
# Default number of retries for fallible operations
DEFAULT_MAX_RETRIES = 3

# Base delay in milliseconds for retries
DEFAULT_RETRY_BASE_MS = 1000
