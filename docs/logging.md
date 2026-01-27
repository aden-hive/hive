# Logging Configuration

The Aden Agent Framework includes a comprehensive logging configuration module that makes it easy to set up proper logging for your agents and applications.

## Quick Start

```python
from framework import setup_logging, get_logger

# Configure logging for your application
setup_logging(level="INFO")

# Get a logger for your module
logger = get_logger(__name__)

# Use the logger
logger.info("Agent started")
logger.warning("Low memory warning")
logger.error("Failed to connect to API")
```

## Features

### Basic Setup

The `setup_logging()` function configures logging for the entire framework:

```python
from framework import setup_logging

# Set log level
setup_logging(level="DEBUG")  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### File Logging

Write logs to a file in addition to console output:

```python
from pathlib import Path
from framework import setup_logging

setup_logging(
    level="INFO",
    log_file=Path("logs/agent.log")
)
```

You can also pass a string path:

```python
from framework import setup_logging

setup_logging(
    level="INFO",
    log_file="logs/agent.log"  # String paths are also supported
)
```

### Custom Format

Customize the log message format:

```python
from framework import setup_logging

setup_logging(
    level="INFO",
    format_string="%(levelname)s - %(name)s - %(message)s",
    include_timestamp=False
)
```

### Framework-Specific Logging

Control logging for framework modules separately:

```python
from framework import set_framework_log_level

# Set all framework loggers to DEBUG
set_framework_log_level("DEBUG")
```

### Disable Framework Logging

Useful for testing or when you only want application logs:

```python
from framework import disable_framework_logging

disable_framework_logging()
```

## Integration with AgentRunner

The logging configuration integrates seamlessly with the AgentRunner:

```python
from pathlib import Path
from framework import setup_logging, AgentRunner

# Configure logging before running agents
setup_logging(level="INFO", log_file=Path("agent_run.log"))

# Load and run your agent
runner = AgentRunner.load("exports/my_agent")
result = await runner.run({"input": "data"})
```

## Best Practices

### Development

During development, use DEBUG level for detailed information:

```python
setup_logging(level="DEBUG")
```

### Production

In production, use INFO or WARNING level and log to files:

```python
from pathlib import Path
from framework import setup_logging

setup_logging(
    level="INFO",
    log_file=Path("/var/log/agent/production.log")
)
```

### Testing

Disable framework logging during tests to reduce noise:

```python
from framework import disable_framework_logging

def test_my_agent():
    disable_framework_logging()
    # Your test code here
```

## Module-Level Loggers

Each module should create its own logger:

```python
from framework import get_logger

logger = get_logger(__name__)

def my_function():
    logger.debug("Entering my_function")
    logger.info("Processing data")
    logger.warning("Unusual condition detected")
```

## Log Levels

Choose the appropriate log level for your messages:

- **DEBUG**: Detailed diagnostic information for debugging
- **INFO**: General informational messages about normal operation
- **WARNING**: Warning messages for unusual but handled situations
- **ERROR**: Error messages for serious problems
- **CRITICAL**: Critical messages for severe errors that may cause shutdown

## Error Handling

The logging module validates log levels and raises `ValueError` for invalid levels:

```python
from framework import setup_logging

try:
    setup_logging(level="INVALID")  # Raises ValueError
except ValueError as e:
    print(f"Configuration error: {e}")
    # Output: Invalid log level 'INVALID'. Valid levels are: CRITICAL, DEBUG, ERROR, INFO, WARNING
```

When creating log directories, the module will raise `PermissionError` or `OSError` if unable to create the directory:

```python
from pathlib import Path
from framework import setup_logging

try:
    setup_logging(level="INFO", log_file=Path("/restricted/path/agent.log"))
except PermissionError:
    print("Cannot create log directory - permission denied")
```

## Environment Variables

You can also control logging via environment variables:

```bash
# Set log level
export ADEN_LOG_LEVEL=DEBUG

# Set log file
export ADEN_LOG_FILE=/var/log/agent.log
```

Then in your code:

```python
import os
from pathlib import Path
from framework import setup_logging

# Get environment variables with proper type handling
log_file_env = os.getenv("ADEN_LOG_FILE")

setup_logging(
    level=os.getenv("ADEN_LOG_LEVEL", "INFO"),
    log_file=Path(log_file_env) if log_file_env else None
)
```

## API Reference

### `setup_logging(level, log_file, format_string, include_timestamp)`

Configure logging for the framework.

**Parameters:**
- `level` (str): Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `log_file` (Path | str, optional): File path to write logs to (accepts Path or string)
- `format_string` (str, optional): Custom format string for log messages
- `include_timestamp` (bool): Whether to include timestamps (default: True)

**Raises:**
- `ValueError`: If an invalid log level is provided
- `PermissionError`: If unable to create log file directory
- `OSError`: If unable to create log file directory

### `get_logger(name)`

Get a logger instance for a module.

**Parameters:**
- `name` (str): Logger name (typically `__name__`)

**Returns:**
- `logging.Logger`: Logger instance

### `set_framework_log_level(level)`

Set log level for all framework loggers.

**Parameters:**
- `level` (str): Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

**Raises:**
- `ValueError`: If an invalid log level is provided

### `disable_framework_logging()`

Disable all framework logging (useful for testing).

## Migration Guide

If you have existing code using `print()` statements, here's how to migrate:

### Before

```python
print("Starting agent...")
print(f"Error: {error_message}")
```

### After

```python
from framework import get_logger

logger = get_logger(__name__)

logger.info("Starting agent...")
logger.error(f"Error: {error_message}")
```

## Examples

### Example 1: Simple Agent with Logging

```python
from framework import setup_logging, get_logger, AgentRunner

# Configure logging
setup_logging(level="INFO")
logger = get_logger(__name__)

async def main():
    logger.info("Loading agent...")
    runner = AgentRunner.load("exports/my_agent")
    
    logger.info("Running agent with input data")
    result = await runner.run({"query": "What is AI?"})
    
    if result.success:
        logger.info("Agent completed successfully")
    else:
        logger.error(f"Agent failed: {result.error}")
```

### Example 2: Production Deployment

```python
from pathlib import Path
from framework import setup_logging, get_logger

# Production logging configuration
setup_logging(
    level="WARNING",  # Only warnings and errors
    log_file=Path("/var/log/aden/agent.log"),
    format_string="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = get_logger(__name__)
logger.info("Agent service started")
```

### Example 3: Development with Debug Logging

```python
from framework import setup_logging, set_framework_log_level

# Enable debug logging for development
setup_logging(level="DEBUG")
set_framework_log_level("DEBUG")

# Now all framework operations will be logged in detail
```
