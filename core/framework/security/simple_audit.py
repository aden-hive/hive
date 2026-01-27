"""
Simple working audit logger for testing without external dependencies.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SecurityLevel(Enum):
    """Security severity levels."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityEvent:
    """Represents a security event."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    security_level: str = SecurityLevel.INFO.value
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "security_level": self.security_level,
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
        
        # Create audit logger
        self._logger = logging.getLogger("hive.audit")
        self._logger.setLevel(logging.INFO)
        
        # Remove existing handlers
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

    def log_runtime_stop(self, **kwargs) -> None:
        """Log runtime stop event."""
        event = SecurityEvent(
            event_type="runtime_stop",
            security_level=SecurityLevel.INFO.value,
            description="Agent runtime stopped",
            details=kwargs
        )
        self.log_event(event)

    def log_execution_trigger(self, entry_point_id: str, execution_id: str, 
                           correlation_id: Optional[str] = None, **kwargs) -> None:
        """Log execution trigger event."""
        event = SecurityEvent(
            event_type="execution_trigger",
            security_level=SecurityLevel.INFO.value,
            description=f"Execution triggered on entry point: {entry_point_id}",
            details={
                "entry_point_id": entry_point_id,
                "execution_id": execution_id,
                "correlation_id": correlation_id,
                **kwargs
            }
        )
        self.log_event(event)

    def log_execution_complete(self, entry_point_id: str, execution_id: str, 
                           success: bool, duration_ms: int, **kwargs) -> None:
        """Log execution completion."""
        event = SecurityEvent(
            event_type="execution_complete" if success else "execution_failed",
            security_level=SecurityLevel.INFO.value,
            description=f"Execution {'completed' if success else 'failed'} for {entry_point_id}",
            details={
                "entry_point_id": entry_point_id,
                "execution_id": execution_id,
                "success": success,
                "duration_ms": duration_ms,
                **kwargs
            }
        )
        self.log_event(event)

    def log_entry_point_registration(self, entry_point_id: str, entry_node: str, **kwargs) -> None:
        """Log entry point registration."""
        event = SecurityEvent(
            event_type="entry_point_registered",
            security_level=SecurityLevel.INFO.value,
            description=f"Entry point registered: {entry_point_id} -> {entry_node}",
            details={"entry_point_id": entry_point_id, "entry_node": entry_node, **kwargs}
        )
        self.log_event(event)

    def log_entry_point_unregistration(self, entry_point_id: str, **kwargs) -> None:
        """Log entry point unregistration."""
        event = SecurityEvent(
            event_type="entry_point_unregistered",
            security_level=SecurityLevel.INFO.value,
            description=f"Entry point unregistered: {entry_point_id}",
            details={"entry_point_id": entry_point_id, **kwargs}
        )
        self.log_event(event)

    def log_resource_exceeded(self, resource_type: str, current_value: float, 
                           limit: float, **kwargs) -> None:
        """Log resource limit exceeded."""
        event = SecurityEvent(
            event_type="resource_exceeded",
            security_level=SecurityLevel.HIGH.value,
            description=f"{resource_type} limit exceeded: {current_value} > {limit}",
            details={
                "resource_type": resource_type,
                "current_value": current_value,
                "limit": limit,
                **kwargs
            }
        )
        self.log_event(event)

    def get_stats(self) -> Dict[str, Any]:
        """Get audit logger statistics."""
        return {
            "events_logged": self._events_logged,
            "log_file": str(self.log_file) if self.log_file else None,
        }

    def cleanup(self) -> None:
        """Cleanup resources."""
        # Close handlers
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)