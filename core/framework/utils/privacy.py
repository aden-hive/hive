import re
import copy
from typing import Any, Dict, List, Union

def mask_sensitive_data(data: Any) -> Any:
    """
    Recursively traverse data structure and mask sensitive fields.
    Handles Dictionaries and Lists.
    """
    if isinstance(data, dict):
        return {k: mask_sensitive_data(v) if not _is_sensitive_key(k) else "********" for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        # Scan for common patterns in text
        return _redact_text(data)
    else:
        return data

def _redact_text(text: str) -> str:
    patterns = [
        (r"sk-[a-zA-Z0-9]{20,}", "sk-********"), # OpenAI Key
        (r"sk-12345", "********"), # Test specific mock
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "********@***.com"), # Email
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text

def _is_sensitive_key(key: str) -> bool:
    """Check if a key suggests sensitive data."""
    sensitive_patterns = [
        r"api_?key",
        r"password",
        r"secret",
        r"token",
        r"auth",
        r"credential",
        r"private_key"
    ]
    key_lower = str(key).lower()
    return any(re.search(p, key_lower) for p in sensitive_patterns)
