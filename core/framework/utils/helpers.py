import logging
import os
import re
import time
from functools import wraps
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two dictionaries.

    Values from override take precedence. Nested dicts are merged recursively.
    Lists are replaced, not merged.
    """
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """Decorator for retry logic with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay on each retry
        exceptions: Tuple of exceptions to catch and retry
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.debug(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            delay,
                            e,
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.warning(
                            "All %d retries exhausted for %s: %s",
                            max_retries,
                            func.__name__,
                            e,
                        )
            raise last_exception

        return wrapper

    return decorator


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Sanitize a string to be a safe filename.

    Replaces characters that are invalid in filenames with replacement.
    Strips leading/trailing whitespace and dots.
    """
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    sanitized = re.sub(invalid_chars, replacement, name)
    sanitized = sanitized.strip(". ")
    if not sanitized:
        return "unnamed"
    return sanitized


def parse_json_safely(
    text: str, default: Any = None
) -> dict[str, Any] | list[Any] | None:
    """Parse JSON text with error handling.

    Args:
        text: JSON string to parse
        default: Value to return if parsing fails (default: None)

    Returns:
        Parsed JSON object, or default if parsing fails
    """
    import json

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug("Failed to parse JSON: %s", e)
        return default


def ensure_dir(path: str | os.PathLike) -> str:
    """Ensure a directory exists, creating it if necessary.

    Returns the path as a string.
    """
    path_str = os.path.abspath(os.fspath(path))
    os.makedirs(path_str, exist_ok=True)
    return path_str


def is_valid_url(url: str) -> bool:
    """Check if a string is a valid URL."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False
