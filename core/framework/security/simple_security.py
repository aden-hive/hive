"""
Simple security utilities for Hive framework without external dependencies.
"""

import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import threading
import asyncio


class SecurityLevel(Enum):
    """Security severity levels."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityViolation(RuntimeError):
    """Exception raised when a security violation is detected."""
    
    def __init__(
        self,
        violation_type: str,
        field_path: str,
        description: str,
        severity: str,
        original_value: Any = None
    ):
        self.violation_type = violation_type
        self.field_path = field_path
        self.description = description
        self.severity = severity
        self.original_value = original_value
        super().__init__(f"{severity.upper()}: {description} (at {field_path})")


class InputSanitizer:
    """Simple input sanitizer without external dependencies."""
    
    def __init__(self):
        self._max_string_length = 10000
        self._max_dict_size = 100
        self._max_list_size = 1000
        
        # Code patterns
        self._code_patterns = [
            r'\bimport\s+\w+',
            r'\bfrom\s+\w+\s+import',
            r'\bdef\s+\w+\s*\(',
            r'\bclass\s+\w+\s*:',
            r'\bexec\s*\(',
            r'\beval\s*\(',
            r'<script[^>]*>',
            r'javascript:',
            r'\bSELECT\s+.*\bFROM\b',
            r'\bINSERT\s+INTO\b',
        ]
        self._compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self._code_patterns]
        
        # XSS patterns
        self._xss_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'<iframe[^>]*>',
        ]
        self._xss_compiled = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in self._xss_patterns]
        
        # Path traversal patterns
        self._path_traversal_patterns = [
            r'\.\./',
            r'%2e%2e%2f',
        ]
        self._path_compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self._path_traversal_patterns]
    
    def sanitize_dict(self, data: Dict[str, Any], field_path: str = "") -> Dict[str, Any]:
        """Sanitize a dictionary."""
        if not isinstance(data, dict):
            raise SecurityViolation(
                violation_type="type_error",
                field_path=field_path,
                description="Expected dict, got {}".format(type(data).__name__),
                severity="critical",
                original_value=data
            )

        if len(data) > self._max_dict_size:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"Dictionary too large: {len(data)} > {self._max_dict_size}",
                severity="high",
                original_value=data
            )

        sanitized = {}
        
        for key, value in data.items():
            current_path = f"{field_path}.{key}" if field_path else key
            sanitized_key = self._sanitize_string(str(key), f"{current_path}.key")
            sanitized_value = self._sanitize_value(value, current_path)
            sanitized[sanitized_key] = sanitized_value
            
        return sanitized
    
    def _sanitize_value(self, value: Any, field_path: str) -> Any:
        """Sanitize a value based on its type."""
        if isinstance(value, str):
            return self._sanitize_string(value, field_path)
        elif isinstance(value, dict):
            return self.sanitize_dict(value, field_path)
        elif isinstance(value, list):
            return self._sanitize_list(value, field_path)
        elif isinstance(value, (int, float, bool)):
            return value
        elif value is None:
            return None
        else:
            return self._sanitize_string(str(value), field_path)
    
    def _sanitize_string(self, value: str, field_path: str) -> str:
        """Sanitize a string value."""
        if len(value) > self._max_string_length:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"String too long: {len(value)} > {self._max_string_length}",
                severity="high",
                original_value=value
            )

        sanitized = value
        
        # Check for code injection
        for pattern in self._compiled_patterns:
            if pattern.search(sanitized):
                sanitized = "[CODE_CONTENT_REMOVED]"
                break

        # Check for XSS
        for pattern in self._xss_compiled:
            sanitized = pattern.sub("[XSS_CONTENT_REMOVED]", sanitized)

        # Check for path traversal
        for pattern in self._path_compiled:
            sanitized = pattern.sub("", sanitized)
        
        return sanitized
    
    def _sanitize_list(self, value: List[Any], field_path: str) -> List[Any]:
        """Sanitize a list value."""
        if len(value) > self._max_list_size:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"List too large: {len(value)} > {self._max_list_size}",
                severity="high",
                original_value=value
            )

        return [self._sanitize_value(item, f"{field_path}[{i}]") for i, item in enumerate(value)]
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize a filename."""
        sanitized = re.sub(r'[\\/]', '_', filename)
        sanitized = re.sub(r'[<>:"|?*]', '_', sanitized)
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
        
        if len(sanitized) > 255:
            sanitized = sanitized[:255]
            
        return sanitized or "unnamed_file"


@dataclass
class SecurityEvent:
    """Represents a security event."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    security_level: str = SecurityLevel.INFO.value
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    execution_id: Optional[str] = None
    entry_point_id: Optional[str] = None
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "security_level": self.security_level,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "entry_point_id": self.entry_point_id,
            "description": self.description,
            "details": self.details,
        }

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class AuditLogger:
    """Simple audit logger without external dependencies."""
    
    def __init__(self, log_file: Optional[Path] = None):
        """Initialize audit logger."""
        self.log_file = log_file
        self._events_logged = 0
        self._start_time = time.time()
        
        # Create audit logger
        self._logger = logging.getLogger("hive.audit")
        self._logger.setLevel(logging.INFO)
        
        # Remove existing handlers to avoid duplicates
        self._logger.handlers.clear()
        
        # Setup file handler if log_file specified
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(self.log_file)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self._logger.addHandler(handler)
        
        # Setup console handler for critical events
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.CRITICAL)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        self._logger.addHandler(console_handler)

    def log_event(self, event: SecurityEvent) -> None:
        """Log a security event."""
        try:
            self._logger.info(event.to_json())
            self._events_logged += 1
        except Exception as e:
            print(f"Failed to log audit event: {e}")

    def log_security_violation(self, violation_type: str, description: str, 
                            field_path: str = "", original_value: Any = None, 
                            severity: str = SecurityLevel.MEDIUM.value, **kwargs) -> None:
        """Log a security violation."""
        event = SecurityEvent(
            event_type="security_violation",
            security_level=severity,
            description=description,
            details={
                "violation_type": violation_type,
                "field_path": field_path,
                "original_value": str(original_value) if original_value else None,
                **kwargs
            }
        )
        self.log_event(event)

    def log_runtime_start(self, stream_count: int, **kwargs) -> None:
        """Log runtime start event."""
        event = SecurityEvent(
            event_type="runtime_start",
            security_level=SecurityLevel.INFO.value,
            description=f"Agent runtime started with {stream_count} streams",
            details={"stream_count": stream_count, **kwargs}
        )
        self.log_event(event)

    def log_execution_trigger(self, entry_point_id: str, execution_id: str, 
                           correlation_id: Optional[str] = None, **kwargs) -> None:
        """Log execution trigger event."""
        event = SecurityEvent(
            event_type="execution_trigger",
            security_level=SecurityLevel.INFO.value,
            description=f"Execution triggered on entry point: {entry_point_id}",
            entry_point_id=entry_point_id,
            execution_id=execution_id,
            details={"correlation_id": correlation_id, **kwargs}
        )
        self.log_event(event)

    def get_stats(self) -> Dict[str, Any]:
        """Get audit logger statistics."""
        uptime = time.time() - self._start_time
        
        return {
            "events_logged": self._events_logged,
            "uptime_seconds": uptime,
            "events_per_second": self._events_logged / uptime if uptime > 0 else 0,
            "log_file": str(self.log_file) if self.log_file else None,
        }


class LRUCache:
    """Simple LRU cache implementation."""
    
    def __init__(self, max_size: int = 1000, ttl: float = 60.0):
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._timestamps: Dict[str, float] = {}
        self._lock = threading.RLock()
        
    def get(self, key: str) -> Any:
        """Get value from cache."""
        with self._lock:
            if key not in self._cache:
                return None
            
            # Check TTL
            if time.time() - self._timestamps[key] > self._ttl:
                del self._cache[key]
                del self._timestamps[key]
                return None
            
            # Move to end (most recently used)
            value = self._cache.pop(key)
            self._cache[key] = value
            return value
            
    def put(self, key: str, value: Any) -> None:
        """Put value in cache."""
        with self._lock:
            # Remove if exists
            if key in self._cache:
                del self._cache[key]
                del self._timestamps[key]
            
            # Add to end
            self._cache[key] = value
            self._timestamps[key] = time.time()
            
            # Evict if over size limit
            while len(self._cache) > self._max_size:
                # Remove oldest (first) item
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                del self._timestamps[oldest_key]
                
    def invalidate(self, key: str) -> None:
        """Invalidate a cache entry."""
        with self._lock:
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)
            
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            current_time = time.time()
            expired_count = sum(
                1 for timestamp in self._timestamps.values()
                if current_time - timestamp > self._ttl
            )
            
            return {
                "total_entries": len(self._cache),
                "expired_entries": expired_count,
                "valid_entries": len(self._cache) - expired_count,
                "max_size": self._max_size,
                "ttl": self._ttl
            }


class ThreadSafeLockManager:
    """Thread-safe lock manager."""
    
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._lock = threading.RLock()
        
    def get_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for the given key."""
        with self._lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]
            
    def remove_lock(self, key: str) -> None:
        """Remove a lock from the manager."""
        with self._lock:
            self._locks.pop(key, None)
            
    def clear_all(self) -> None:
        """Clear all locks."""
        with self._lock:
            self._locks.clear()
            
    def get_stats(self) -> dict:
        """Get lock statistics."""
        with self._lock:
            return {
                "total_locks": len(self._locks),
                "lock_keys": list(self._locks.keys())
            }


# Export main classes
__all__ = [
    "SecurityViolation",
    "SecurityLevel", 
    "InputSanitizer",
    "AuditLogger",
    "SecurityEvent",
    "LRUCache",
    "ThreadSafeLockManager",
]